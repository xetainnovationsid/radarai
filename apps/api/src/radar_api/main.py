import logging
import tempfile
from io import BytesIO
from math import isclose, isfinite
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image
from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from radar_api.contracts import (
    CreateReportDraftRequest,
    CreateStudyRequest,
    FindingCorrectionRequest,
    FindingReviewEvent,
    FindingReviewRequest,
    InferenceJob,
    ReportDraft,
    Study,
    StudyAnalysisResponse,
    StudyLocalizations,
    StudyModelScores,
    StudySliceScore,
)
from radar_api.database import SessionLocal, get_session
from radar_api.dicom_upload import UploadLimits, UploadTooLarge, stage_upload
from radar_api.dicom_validation import DicomValidationError, validate_ct_slice
from radar_api.inference_jobs import run_inference_job
from radar_api.models import (
    FindingEvidenceRecord,
    ImageAssetRecord,
    InferenceJobRecord,
    InferenceScoreRecord,
    ModelVersionRecord,
    PersistedFindingRecord,
    ReportDraftRecord,
    ReviewEventRecord,
    StudyAnalysisRecord,
    StudyLocalizationRecord,
    StudyRecord,
    StudySliceRecord,
)
from radar_api.report_service import (
    REPORT_PROMPT_VERSION,
    ReportModelUnavailable,
    ReportOutputError,
    generate_report_content,
)
from radar_api.security import (
    Principal,
    SecurityAndRateLimitMiddleware,
    allowed_web_origins,
    is_auth_required,
    require_authenticated_principal,
)
from radar_api.storage import PrivateImageStore
from radar_api.worker_bridge import (
    WorkerClaimRequest,
    WorkerScores,
    claim_next_job,
    fail_worker_job,
    get_job_slice,
    heartbeat_worker_job,
    persist_worker_scores,
    require_worker_token,
    worker_mode_enabled,
)

load_dotenv()
logger = logging.getLogger("radar_api")

# Guard against Pillow decompression bombs on malformed images.
Image.MAX_IMAGE_PIXELS = 16_777_216

app = FastAPI(
    title="RADAR AI API",
    description="Research prototype API for brain CT review assistance. Not for clinical use.",
    version="0.1.0",
)

app.add_middleware(SecurityAndRateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_web_origins(),
    allow_credentials=False,
    allow_methods=["DELETE", "GET", "POST", "PUT", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Request-ID",
        "X-Requested-With",
    ],
    expose_headers=[
        "X-Request-ID",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "Retry-After",
    ],
)


def require_owned_study(
    study_id: UUID,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_authenticated_principal),
) -> Principal:
    """Hide studies belonging to another researcher behind the same 404 response."""
    owned_id = session.scalar(
        select(StudyRecord.study_id).where(
            StudyRecord.study_id == study_id,
            StudyRecord.owner_id == principal.subject[:64],
        )
    )
    if owned_id is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return principal


@app.get("/health", tags=["operations"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": "research-prototype"}


@app.get("/health/ready", tags=["operations"])
def readiness_check() -> dict[str, str]:
    """Check that the API process can reach its configured relational database."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as error:
        logger.error("Readiness check failed with %s", type(error).__name__)
        raise HTTPException(status_code=503, detail="Database is unavailable") from error
    return {"status": "ready", "database": "ok"}


@app.get("/internal/worker/health", tags=["operations"])
def laptop_worker_health(request: Request) -> dict[str, str]:
    """Private authenticated health check for the laptop inference worker."""
    require_worker_token(request)
    return {"status": "ready", "mode": "laptop_worker"}


@app.post("/internal/worker/claim", tags=["operations"])
def laptop_worker_claim(
    request: Request,
    payload: WorkerClaimRequest | None = None,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Lease a queued inference job to one authenticated laptop worker."""
    require_worker_token(request)
    job = claim_next_job(session, payload.study_id if payload else None)
    if job is None:
        return {"job": None}
    slices = list(
        session.scalars(
            select(StudySliceRecord)
            .where(StudySliceRecord.study_id == UUID(str(job["study_id"])))
            .order_by(StudySliceRecord.index)
        ).all()
    )
    return {
        "job": job,
        "slices": [{"slice_id": str(item.slice_id), "index": item.index} for item in slices],
    }


@app.get("/internal/worker/jobs/{job_id}/slices/{slice_id}", tags=["operations"])
def laptop_worker_download_slice(
    job_id: UUID,
    slice_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    """Send one DICOM object to the authenticated worker without base64 expansion."""
    require_worker_token(request)
    lease_token = _worker_lease_token(request)
    content, digest, index = get_job_slice(session, job_id, slice_id, lease_token)
    return Response(
        content=content,
        media_type="application/dicom",
        headers={"X-DICOM-SHA256": digest, "X-DICOM-Index": str(index)},
    )


@app.post("/internal/worker/jobs/{job_id}/complete", tags=["operations"])
def laptop_worker_complete(
    job_id: UUID,
    result: WorkerScores,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Validate and persist local model output returned by the laptop worker."""
    require_worker_token(request)
    persist_worker_scores(session, job_id, _worker_lease_token(request), result)
    return {"status": "completed"}


@app.post("/internal/worker/jobs/{job_id}/fail", tags=["operations"])
def laptop_worker_fail(
    job_id: UUID,
    payload: dict[str, str],
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Persist a safe error code if a local inference job cannot finish."""
    require_worker_token(request)
    allowed = {"model_unavailable", "inference_failed", "worker_internal_error"}
    error_code = payload.get("error_code", "worker_internal_error")
    if error_code not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported worker error code")
    fail_worker_job(session, job_id, _worker_lease_token(request), error_code)
    return {"status": "failed"}


def _worker_lease_token(request: Request) -> UUID:
    raw_token = request.headers.get("x-radar-worker-lease", "").strip()
    try:
        return UUID(raw_token)
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Worker lease authentication failed") from error


@app.post("/internal/worker/jobs/{job_id}/heartbeat", tags=["operations"])
def laptop_worker_heartbeat(
    job_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Extend the current worker lease while a long local inference is running."""
    require_worker_token(request)
    heartbeat_worker_job(session, job_id, _worker_lease_token(request))
    return {"status": "active"}


@app.get("/v1/auth/me", tags=["security"])
def current_principal(
    principal: Principal = Depends(require_authenticated_principal),
) -> dict[str, object]:
    """Return the authenticated caller identity and active security enforcement mode."""

    return {
        "authenticated": principal.auth_method != "local_dev",
        "auth_required": is_auth_required(),
        "auth_method": principal.auth_method,
        "subject": principal.subject,
        "reviewer_id": principal.reviewer_id,
        "email": principal.email,
    }


@app.get("/v1/contracts/study-analysis", tags=["contracts"])
def study_analysis_contract() -> dict[str, object]:
    """Expose the versioned JSON Schema used by API and frontend workstreams."""

    return StudyAnalysisResponse.model_json_schema()


@app.post(
    "/v1/studies", response_model=Study, status_code=status.HTTP_201_CREATED, tags=["studies"]
)
def create_study(
    request: CreateStudyRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_authenticated_principal),
) -> StudyRecord:
    """Create an empty CT study record; DICOM upload is handled by a separate workstream."""

    study = StudyRecord(
        modality=request.modality, status="uploaded", owner_id=principal.subject[:64]
    )
    session.add(study)
    session.commit()
    session.refresh(study)
    return study


@app.get("/v1/studies", response_model=list[Study], tags=["studies"])
def list_studies(
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
) -> list[StudyRecord]:
    """List study metadata without exposing patient identifiers or image contents."""

    statement = (
        select(StudyRecord)
        .where(StudyRecord.owner_id == _principal.subject[:64])
        .options(selectinload(StudyRecord.slices))
        .order_by(StudyRecord.created_at.desc(), StudyRecord.study_id)
    )
    return list(session.scalars(statement).all())


@app.get("/v1/studies/{study_id}", response_model=Study, tags=["studies"])
def get_study(
    study_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> StudyRecord:
    """Fetch one study and its ordered slice metadata."""

    statement = (
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices))
    )
    study = session.scalar(statement)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return study


@app.delete("/v1/studies/{study_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["studies"])
def delete_empty_study(
    study_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> Response:
    """Remove an unfinalized study record created by an upload that did not complete."""

    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices))
        .with_for_update()
    )
    if study is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if study.status == "ready":
        raise HTTPException(
            status_code=409,
            detail="A finalized study with uploaded slices cannot be deleted",
        )
    asset_ids = [item.image_asset_id for item in study.slices]
    session.delete(study)
    session.flush()
    if asset_ids:
        for asset in session.scalars(
            select(ImageAssetRecord).where(ImageAssetRecord.image_asset_id.in_(asset_ids))
        ):
            session.delete(asset)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/v1/studies/{study_id}/analysis",
    response_model=StudyAnalysisResponse,
    tags=["analysis"],
)
def get_study_analysis(
    study_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> dict:
    """Return persisted findings only; this endpoint never fabricates inference output."""

    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices))
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    analysis = session.scalar(
        select(StudyAnalysisRecord)
        .where(StudyAnalysisRecord.study_id == study_id)
        .options(selectinload(StudyAnalysisRecord.model_version))
        .order_by(StudyAnalysisRecord.created_at.desc(), StudyAnalysisRecord.analysis_id.desc())
        .limit(1)
    )
    if analysis is None:
        raise HTTPException(status_code=404, detail="No completed model analysis is available")
    findings = list(
        session.scalars(
            select(PersistedFindingRecord)
            .where(
                PersistedFindingRecord.study_id == study_id,
                PersistedFindingRecord.model_version_id == analysis.model_version_id,
            )
            .options(
                selectinload(PersistedFindingRecord.evidence),
                selectinload(PersistedFindingRecord.model_version),
            )
            .order_by(PersistedFindingRecord.finding_id)
        ).all()
    )
    model_version = analysis.model_version
    if any(not item.evidence for item in findings):
        raise HTTPException(
            status_code=409, detail="A finding is missing its required evidence slices"
        )
    study_slice_ids = {item.slice_id for item in study.slices}
    if any(
        link.slice_id not in study_slice_ids for finding in findings for link in finding.evidence
    ):
        raise HTTPException(
            status_code=409, detail="A finding references a slice outside its study"
        )
    return {
        "schema_version": "1.0.0",
        "study": study,
        "findings": [
            {
                "finding_id": item.finding_id,
                "category": item.category,
                "evidence_slice_ids": [link.slice_id for link in item.evidence],
                "confidence": item.confidence,
                "review_status": item.review_status,
                "model_version_id": item.model_version_id,
                "revision": item.revision,
            }
            for item in findings
        ],
        "model_version": model_version,
    }


@app.get(
    "/v1/studies/{study_id}/reports/drafts",
    response_model=list[ReportDraft],
    tags=["reports"],
)
def list_report_drafts(
    study_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> list[dict[str, object]]:
    records = list(
        session.scalars(
            select(ReportDraftRecord)
            .where(ReportDraftRecord.study_id == study_id)
            .options(selectinload(ReportDraftRecord.model_version))
            .order_by(ReportDraftRecord.version.desc())
        ).all()
    )
    return [
        {
            "report_id": record.report_id,
            "study_id": record.study_id,
            "version": record.version,
            "status": record.status,
            "source_finding_ids": record.source_finding_ids,
            "content": record.content,
            "created_by": record.created_by,
            "created_at": record.created_at,
            "generation_mode": "deepseek_api" if record.model_version_id else "manual_fallback",
            "model_id": (
                record.model_version.model_id
                if record.model_version is not None
                else None
            ),
        }
        for record in records
    ]


@app.post(
    "/v1/studies/{study_id}/reports/drafts",
    response_model=ReportDraft,
    status_code=status.HTTP_201_CREATED,
    tags=["reports"],
)
def create_report_draft(
    study_id: UUID,
    request: CreateReportDraftRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> dict[str, object]:
    """Create a cited report draft from persisted findings or accept manual fallback content."""
    analysis = session.scalar(
        select(StudyAnalysisRecord)
        .where(StudyAnalysisRecord.study_id == study_id)
        .options(selectinload(StudyAnalysisRecord.model_version))
        .order_by(StudyAnalysisRecord.created_at.desc(), StudyAnalysisRecord.analysis_id.desc())
        .limit(1)
    )
    if analysis is None:
        raise HTTPException(
            status_code=409, detail="A completed analysis is required for a report draft"
        )
    findings = list(
        session.scalars(
            select(PersistedFindingRecord)
            .where(
                PersistedFindingRecord.study_id == study_id,
                PersistedFindingRecord.model_version_id == analysis.model_version_id,
            )
            .options(selectinload(PersistedFindingRecord.evidence))
            .order_by(PersistedFindingRecord.finding_id)
        ).all()
    )
    if not findings:
        raise HTTPException(
            status_code=409, detail="No saved findings are available for a report draft"
        )
    finding_ids = {item.finding_id for item in findings}
    manual = request.manual_content is not None
    model_version = None
    model_id = None
    if manual:
        content = request.manual_content
    else:
        source = [
            {
                "finding_id": str(item.finding_id),
                "category": item.category,
                "confidence": item.confidence,
                "review_status": item.review_status,
                "evidence_slice_ids": [str(link.slice_id) for link in item.evidence],
            }
            for item in findings
        ]
        try:
            content, model_id = generate_report_content(source)
        except ReportModelUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail=(
                    "DeepSeek report generation is unavailable. Use manual_content to save a cited "
                    "research draft, or configure DEEPSEEK_API_KEY on the API server."
                ),
            ) from error
        except ReportOutputError as error:
            raise HTTPException(
                status_code=502, detail="DeepSeek returned an invalid report draft"
            ) from error
        model_version = ModelVersionRecord(
            provider="deepseek_api",
            model_id=model_id,
            prompt_version=REPORT_PROMPT_VERSION,
        )
        session.add(model_version)
        session.flush()

    assert content is not None
    statements = [*content.findings, content.impression]
    if any(not set(statement.finding_ids).issubset(finding_ids) for statement in statements):
        raise HTTPException(
            status_code=422,
            detail="Report contains a citation that is not part of the current saved analysis",
        )
    latest_version = session.scalar(
        select(ReportDraftRecord.version)
        .where(ReportDraftRecord.study_id == study_id)
        .order_by(ReportDraftRecord.version.desc())
        .limit(1)
    )
    record = ReportDraftRecord(
        report_id=uuid4(),
        study_id=study_id,
        model_version_id=model_version.model_version_id if model_version else None,
        version=(latest_version or 0) + 1,
        status="draft",
        source_finding_ids=sorted(str(item) for item in finding_ids),
        content=content.model_dump(mode="json"),
        created_by=principal.reviewer_id,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return {
        "report_id": record.report_id,
        "study_id": record.study_id,
        "version": record.version,
        "status": record.status,
        "source_finding_ids": record.source_finding_ids,
        "content": record.content,
        "created_by": record.created_by,
        "created_at": record.created_at,
        "generation_mode": "manual_fallback" if manual else "deepseek_api",
        "model_id": model_id,
    }


@app.get(
    "/v1/studies/{study_id}/scores",
    response_model=StudyModelScores,
    tags=["analysis"],
)
def get_study_model_scores(
    study_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> dict[str, object]:
    """Return the latest persisted local scores; inference is started through a job endpoint."""

    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices).selectinload(StudySliceRecord.image_asset))
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    analysis = session.scalar(
        select(StudyAnalysisRecord)
        .where(StudyAnalysisRecord.study_id == study_id)
        .options(selectinload(StudyAnalysisRecord.model_version))
        .order_by(StudyAnalysisRecord.created_at.desc(), StudyAnalysisRecord.analysis_id.desc())
        .limit(1)
    )
    if analysis is None or analysis.model_version.provider != "local_checkpoint":
        raise HTTPException(
            status_code=404,
            detail="No completed local inference is available; submit an inference job first.",
        )
    persisted = list(
        session.scalars(
            select(InferenceScoreRecord)
            .where(InferenceScoreRecord.analysis_id == analysis.analysis_id)
            .order_by(InferenceScoreRecord.slice_id, InferenceScoreRecord.subtype)
        ).all()
    )
    by_slice: dict[UUID, dict[str, float]] = {}
    for row in persisted:
        by_slice.setdefault(row.slice_id, {})[row.subtype] = row.score
    if any(
        not {"hemorrhage_absent", "hemorrhage_present"}.issubset(by_slice.get(item.slice_id, {}))
        for item in study.slices
    ):
        raise HTTPException(status_code=409, detail="Persisted inference scores are incomplete")
    model = analysis.model_version
    slice_scores = [
        StudySliceScore(
            slice_id=image_slice.slice_id,
            index=image_slice.index,
            class_0_score=by_slice[image_slice.slice_id]["hemorrhage_absent"],
            class_1_score=by_slice[image_slice.slice_id]["hemorrhage_present"],
        )
        for image_slice in study.slices
    ]
    return {
        "schema_version": "1.0.0",
        "study_id": study.study_id,
        "model_id": model.model_id,
        "checkpoint_sha256": model.artifact_sha256,
        "device": model.device or "unknown",
        "score_semantics": "Uncalibrated RSNA ICH slice-label scores; not a diagnosis",
        "class_1_label_semantics": (
            "RSNA ICH slice label 1 means hemorrhage annotated present; research score only"
        ),
        "slices": slice_scores,
    }


@app.post(
    "/v1/studies/{study_id}/inference-jobs",
    response_model=InferenceJob,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["analysis"],
)
def create_inference_job(
    study_id: UUID,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> InferenceJobRecord:
    """Queue local checkpoint inference and return immediately with a pollable job ID."""
    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices))
        .with_for_update()
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    if not study.slices:
        raise HTTPException(
            status_code=409, detail="Upload a CT series before requesting inference"
        )
    if study.upload_expected_slices is not None:
        expected_indexes = set(range(study.upload_expected_slices))
        actual_indexes = {item.index for item in study.slices}
        if (
            study.status == "uploaded"
            or len(study.slices) != study.upload_expected_slices
            or actual_indexes != expected_indexes
        ):
            raise HTTPException(
                status_code=409,
                detail="Finish and finalize the CT series upload before requesting inference",
            )
    active_job = session.scalar(
        select(InferenceJobRecord)
        .where(
            InferenceJobRecord.study_id == study_id,
            InferenceJobRecord.status.in_(("queued", "processing")),
        )
        .order_by(InferenceJobRecord.created_at.desc())
        .limit(1)
    )
    if active_job is not None:
        return active_job
    last_job = session.scalar(
        select(InferenceJobRecord)
        .where(InferenceJobRecord.study_id == study_id)
        .order_by(InferenceJobRecord.created_at.desc())
        .limit(1)
    )
    if last_job is not None and last_job.status == "completed":
        return last_job
    job = InferenceJobRecord(
        job_id=uuid4(),
        study_id=study_id,
        requested_by=principal.subject[:64],
        status="queued",
    )
    study.status = "processing"
    session.add(job)
    session.commit()
    session.refresh(job)
    if not worker_mode_enabled():
        background_tasks.add_task(run_inference_job, job.job_id)
    return job


@app.get(
    "/v1/studies/{study_id}/inference-jobs/{job_id}",
    response_model=InferenceJob,
    tags=["analysis"],
)
def get_inference_job(
    study_id: UUID,
    job_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> InferenceJobRecord:
    job = session.scalar(
        select(InferenceJobRecord).where(
            InferenceJobRecord.job_id == job_id,
            InferenceJobRecord.study_id == study_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Inference job not found")
    return job


@app.get(
    "/v1/studies/{study_id}/localizations",
    response_model=StudyLocalizations,
    tags=["analysis"],
)
def get_study_localizations(
    study_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> dict[str, object]:
    """Return the latest persisted SAMIHS result produced by the laptop worker."""
    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices).selectinload(StudySliceRecord.image_asset))
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    if not study.slices:
        raise HTTPException(status_code=409, detail="Upload a CT series before localization")

    record = session.scalar(
        select(StudyLocalizationRecord)
        .where(StudyLocalizationRecord.study_id == study_id)
        .options(selectinload(StudyLocalizationRecord.model_version))
        .order_by(
            StudyLocalizationRecord.created_at.desc(),
            StudyLocalizationRecord.localization_id.desc(),
        )
        .limit(1)
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="SAMIHS results are unavailable until localization completes.",
        )
    if len(record.slices) != len(study.slices):
        raise HTTPException(status_code=409, detail="Persisted SAMIHS localization is incomplete")
    model = record.model_version
    return {
        "schema_version": "1.0.0",
        "study_id": study.study_id,
        "model_id": model.model_id if model is not None else "samihs-v1",
        "checkpoint_sha256": model.artifact_sha256 if model is not None else "",
        "device": (model.device if model is not None else None) or "unknown",
        "threshold": record.threshold,
        "score_semantics": "SAMIHS binary ICH segmentation mask; research localization only",
        "slices": record.slices,
    }


@app.post(
    "/v1/studies/{study_id}/findings/{finding_id}/review",
    response_model=FindingReviewEvent,
    status_code=status.HTTP_201_CREATED,
    tags=["review"],
)
def review_finding(
    study_id: UUID,
    finding_id: UUID,
    request: FindingReviewRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> ReviewEventRecord:
    """Record one reviewer decision and preserve each decision in the audit log."""

    finding = session.scalar(
        select(PersistedFindingRecord)
        .where(
            PersistedFindingRecord.finding_id == finding_id,
            PersistedFindingRecord.study_id == study_id,
        )
        .options(selectinload(PersistedFindingRecord.evidence))
        .with_for_update()
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    previous_snapshot = _finding_snapshot(finding)
    finding.revision += 1
    event = ReviewEventRecord(
        finding_id=finding_id,
        previous_review_status=finding.review_status,
        review_status=request.review_status,
        action="review",
        version=finding.revision,
        previous_snapshot=previous_snapshot,
        current_snapshot=_finding_snapshot(finding, status=request.review_status),
        reviewer=principal.reviewer_id,
    )
    finding.review_status = request.review_status
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _finding_snapshot(
    finding: PersistedFindingRecord, *, status: str | None = None
) -> dict[str, object]:
    return {
        "category": finding.category,
        "confidence": finding.confidence,
        "evidence_slice_ids": [str(item.slice_id) for item in finding.evidence],
        "review_status": status or finding.review_status,
        "revision": finding.revision,
    }


@app.put(
    "/v1/studies/{study_id}/findings/{finding_id}",
    response_model=FindingReviewEvent,
    status_code=status.HTTP_201_CREATED,
    tags=["review"],
)
def correct_finding(
    study_id: UUID,
    finding_id: UUID,
    request: FindingCorrectionRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> ReviewEventRecord:
    """Apply an explicit human correction and preserve before/after values in the audit log."""
    if request.confidence is None and request.evidence_slice_ids is None:
        raise HTTPException(
            status_code=422, detail="Provide confidence or evidence_slice_ids to edit"
        )
    finding = session.scalar(
        select(PersistedFindingRecord)
        .where(
            PersistedFindingRecord.finding_id == finding_id,
            PersistedFindingRecord.study_id == study_id,
        )
        .options(selectinload(PersistedFindingRecord.evidence))
        .with_for_update()
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    previous_snapshot = _finding_snapshot(finding)
    previous_status = finding.review_status
    if request.evidence_slice_ids is not None:
        study_slice_ids = set(
            session.scalars(
                select(StudySliceRecord.slice_id).where(StudySliceRecord.study_id == study_id)
            ).all()
        )
        if not set(request.evidence_slice_ids).issubset(study_slice_ids):
            raise HTTPException(
                status_code=422, detail="Evidence slice must belong to the same study"
            )
        current_evidence = {item.slice_id: item for item in finding.evidence}
        finding.evidence = [
            current_evidence[slice_id]
            for slice_id in request.evidence_slice_ids
            if slice_id in current_evidence
        ]
        finding.evidence.extend(
            FindingEvidenceRecord(finding_id=finding_id, slice_id=slice_id)
            for slice_id in request.evidence_slice_ids
            if slice_id not in current_evidence
        )
    if request.confidence is not None:
        finding.confidence = request.confidence
    finding.review_status = "uncertain"
    finding.revision += 1
    event = ReviewEventRecord(
        finding_id=finding_id,
        previous_review_status=previous_status,
        review_status="uncertain",
        action="edit",
        version=finding.revision,
        previous_snapshot=previous_snapshot,
        current_snapshot=_finding_snapshot(finding),
        reviewer=principal.reviewer_id,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@app.get(
    "/v1/studies/{study_id}/findings/{finding_id}/reviews",
    response_model=list[FindingReviewEvent],
    tags=["review"],
)
def list_finding_reviews(
    study_id: UUID,
    finding_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> list[ReviewEventRecord]:
    finding = session.scalar(
        select(PersistedFindingRecord).where(
            PersistedFindingRecord.finding_id == finding_id,
            PersistedFindingRecord.study_id == study_id,
        )
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return list(
        session.scalars(
            select(ReviewEventRecord)
            .where(ReviewEventRecord.finding_id == finding_id)
            .order_by(ReviewEventRecord.created_at, ReviewEventRecord.review_event_id)
        ).all()
    )


@app.get("/v1/studies/{study_id}/slices/{slice_id}/dicom", tags=["studies"])
def get_slice_dicom(
    study_id: UUID,
    slice_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> Response:
    """Stream one validated private CT slice as a non-cacheable Part 10 DICOM object."""

    record = session.scalar(
        select(StudySliceRecord)
        .where(
            StudySliceRecord.study_id == study_id,
            StudySliceRecord.slice_id == slice_id,
        )
        .options(selectinload(StudySliceRecord.image_asset).undefer(ImageAssetRecord.dicom_data))
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Study slice not found")

    payload = record.image_asset.dicom_data
    if payload is None:
        path = PrivateImageStore().path_for(record.image_asset.storage_key)
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise HTTPException(
                status_code=422, detail="Stored DICOM slice cannot be read"
            ) from error

    return Response(
        content=payload,
        media_type="application/dicom",
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/v1/studies/{study_id}/slices/{slice_id}/image", tags=["studies"])
def get_slice_preview(
    study_id: UUID,
    slice_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> Response:
    """Render one validated private CT slice as a non-cacheable PNG preview."""

    record = session.scalar(
        select(StudySliceRecord)
        .where(
            StudySliceRecord.study_id == study_id,
            StudySliceRecord.slice_id == slice_id,
        )
        .options(selectinload(StudySliceRecord.image_asset).undefer(ImageAssetRecord.dicom_data))
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Study slice not found")

    try:
        payload = record.image_asset.dicom_data
        if payload is None:
            payload = PrivateImageStore().path_for(record.image_asset.storage_key).read_bytes()
        dataset = dcmread(BytesIO(payload), force=False)
        pixels = dataset.pixel_array.astype(np.float32)
        pixels = pixels * float(getattr(dataset, "RescaleSlope", 1)) + float(
            getattr(dataset, "RescaleIntercept", 0)
        )
        window_width = getattr(dataset, "WindowWidth", 80)
        window_center = getattr(dataset, "WindowCenter", 40)
        if not isinstance(window_width, (str, int, float)):
            window_width = window_width[0]
        if not isinstance(window_center, (str, int, float)):
            window_center = window_center[0]
        width = float(window_width)
        level = float(window_center)
        if width < 1.0 or not isfinite(width):
            raise ValueError("Invalid window width")
        low, high = level - width / 2, level + width / 2
        pixels = np.clip((pixels - low) / (high - low), 0, 1)
        if str(getattr(dataset, "PhotometricInterpretation", "")).strip() == "MONOCHROME1":
            pixels = 1 - pixels
        image = Image.fromarray((pixels * 255).astype(np.uint8), mode="L")
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    except (
        InvalidDicomError,
        OSError,
        AttributeError,
        IndexError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as error:
        raise HTTPException(
            status_code=422, detail="Stored CT slice could not be rendered"
        ) from error
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post(
    "/v1/studies/{study_id}/dicom",
    response_model=Study,
    status_code=status.HTTP_201_CREATED,
    tags=["studies"],
)
async def upload_dicom_series(
    study_id: UUID,
    files: list[UploadFile] = File(...),
    slice_index: int = Form(..., alias="index"),
    total_files: int = Form(...),
    finalize: bool = Form(False),
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> StudyRecord:
    """Validate and persist one anonymized CT slice per request.

    One-slice requests stay below Vercel's function request-body limit. The DICOM
    bytes are stored in Supabase Postgres so they survive function restarts.
    """

    limits = UploadLimits.from_environment()
    if len(files) != 1:
        raise HTTPException(status_code=422, detail="Upload exactly one DICOM slice per request")
    if total_files < 1 or total_files > limits.max_files:
        raise HTTPException(status_code=413, detail="DICOM series contains too many files")
    if slice_index < 0 or slice_index >= total_files:
        raise HTTPException(status_code=422, detail="DICOM slice index is outside the series")

    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices).selectinload(StudySliceRecord.image_asset))
        .with_for_update()
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.upload_expected_slices not in (None, total_files):
        raise HTTPException(status_code=409, detail="Upload series size changed during transfer")
    if study.status == "ready" and study.upload_expected_slices != total_files:
        raise HTTPException(status_code=409, detail="Study already has a finalized DICOM series")

    staging_store = PrivateImageStore(root=Path(tempfile.gettempdir()) / "radar-dicom-staging")
    staged_path: Path | None = None
    try:
        staged = await stage_upload(files[0], staging_store, limits, already_staged_bytes=0)
        staged_path = staged.path
        validated = validate_ct_slice(staged.path, max_pixels=limits.max_pixels)
        existing = next((item for item in study.slices if item.index == slice_index), None)
        if existing is not None:
            if existing.image_asset.sha256 != staged.sha256:
                raise HTTPException(
                    status_code=409, detail="A different slice already uses this index"
                )
            if study.status == "ready":
                return study
        else:
            if study.status == "ready":
                raise HTTPException(
                    status_code=409, detail="Study already has a finalized DICOM series"
                )
            if study.upload_expected_slices is None:
                study.upload_expected_slices = total_files
            already_stored_bytes = sum(item.image_asset.size_bytes for item in study.slices)
            if already_stored_bytes + staged.size_bytes > limits.max_series_bytes:
                raise UploadTooLarge("DICOM series exceeds the total size limit")
            if any(item.image_asset.sha256 == staged.sha256 for item in study.slices):
                raise DicomValidationError("DICOM series contains duplicate image files")
            metadata = {
                "study_instance_uid": validated.study_instance_uid,
                "series_instance_uid": validated.series_instance_uid,
                "sop_instance_uid": validated.sop_instance_uid,
                "slice_position": validated.slice_position,
                "instance_number": validated.instance_number,
                "rows": validated.rows,
                "columns": validated.columns,
                "orientation": list(validated.orientation) if validated.orientation else None,
                "is_synthetic_fixture": validated.is_synthetic_fixture,
            }
            if study.slices:
                reference = study.slices[0].dicom_metadata
                for key, message in (
                    ("study_instance_uid", "DICOM files do not belong to the same study"),
                    ("series_instance_uid", "DICOM files do not belong to the same CT series"),
                    ("rows", "DICOM series image dimensions do not match"),
                    ("columns", "DICOM series image dimensions do not match"),
                ):
                    if reference.get(key) != metadata.get(key):
                        raise DicomValidationError(message)
                previous_orientation = reference.get("orientation")
                next_orientation = metadata.get("orientation")
                if (previous_orientation is None) != (next_orientation is None) or (
                    previous_orientation is not None
                    and next_orientation is not None
                    and (
                        len(previous_orientation) != len(next_orientation)
                        or any(
                            not isclose(left, right, abs_tol=1e-4)
                            for left, right in zip(
                                previous_orientation, next_orientation, strict=True
                            )
                        )
                    )
                ):
                    raise DicomValidationError("DICOM series image orientations do not match")
            asset_id = uuid4()
            session.add(
                ImageAssetRecord(
                    image_asset_id=asset_id,
                    storage_key=f"supabase-db://{study_id.hex}/{asset_id.hex}",
                    sha256=staged.sha256,
                    size_bytes=staged.size_bytes,
                    dicom_data=staged.path.read_bytes(),
                )
            )
            study.slices.append(
                StudySliceRecord(
                    slice_id=uuid4(),
                    index=slice_index,
                    image_asset_id=asset_id,
                    z_position_mm=validated.z_position_mm,
                    dicom_metadata=metadata,
                )
            )
        session.flush()

        if finalize:
            if len(study.slices) != total_files or {item.index for item in study.slices} != set(
                range(total_files)
            ):
                raise DicomValidationError("Upload is incomplete; some DICOM slices are missing")
            stored = [item.dicom_metadata for item in study.slices]
            has_geometry = [item.get("slice_position") is not None for item in stored]
            if len(stored) > 1 and any(has_geometry) and not all(has_geometry):
                raise DicomValidationError(
                    "DICOM series has incomplete slice geometry; include geometry for every slice"
                )
            if len(stored) > 1 and not any(has_geometry):
                numbers = [item.get("instance_number") for item in stored]
                if any(number is None for number in numbers) or len(set(numbers)) != len(numbers):
                    raise DicomValidationError(
                        "Multiple slices need complete position metadata or unique Instance Numbers"
                    )
            sop_uids = [
                item.get("sop_instance_uid") for item in stored if item.get("sop_instance_uid")
            ]
            if len(set(sop_uids)) != len(sop_uids):
                raise DicomValidationError("DICOM series contains duplicate image instances")
            ordered = sorted(
                study.slices,
                key=lambda item: (
                    round(item.dicom_metadata.get("slice_position"), 3)
                    if item.dicom_metadata.get("slice_position") is not None
                    else float(item.dicom_metadata.get("instance_number") or 0),
                    item.dicom_metadata.get("instance_number")
                    if item.dicom_metadata.get("instance_number") is not None
                    else 0,
                    item.dicom_metadata.get("sop_instance_uid") or item.image_asset.sha256,
                ),
            )
            for offset, item in enumerate(study.slices):
                item.index = total_files + offset + 1
            session.flush()
            for ordered_index, item in enumerate(ordered):
                item.index = ordered_index
            study.slices.sort(key=lambda item: item.index)
            study.status = "ready"
        else:
            study.status = "uploaded"
        session.commit()
        session.refresh(study)
        return study
    except UploadTooLarge as error:
        session.rollback()
        raise HTTPException(status_code=413, detail=str(error)) from error
    except DicomValidationError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BaseException:
        session.rollback()
        raise
    finally:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        for upload in files:
            await upload.close()
