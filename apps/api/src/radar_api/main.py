import logging
from io import BytesIO
from math import isclose
from uuid import UUID, uuid4

import numpy as np
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile, status
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
from radar_api.localization_service import (
    LocalizationInputError,
    LocalizationUnavailableError,
    localize_dicom_series,
)
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
    """Remove only an empty study record created by an upload that did not complete."""

    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices))
    )
    if study is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if study.slices:
        raise HTTPException(
            status_code=409,
            detail="A study with uploaded slices cannot be deleted",
        )
    session.delete(study)
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
            "generation_mode": "meta_model_api" if record.model_version_id else "manual_fallback",
            "model_id": (
                session.get(ModelVersionRecord, record.model_version_id).model_id
                if record.model_version_id
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
                    "Meta report generation is unavailable. Use manual_content to save a cited "
                    "research draft, or configure MODEL_API_KEY on the API server."
                ),
            ) from error
        except ReportOutputError as error:
            raise HTTPException(
                status_code=502, detail="Meta returned an invalid report draft"
            ) from error
        model_version = ModelVersionRecord(
            provider="meta_model_api",
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
        "generation_mode": "manual_fallback" if manual else "meta_model_api",
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
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    if not study.slices:
        raise HTTPException(
            status_code=409, detail="Upload a CT series before requesting inference"
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
    """Return real bounding boxes derived from the configured pretrained ICH mask model."""
    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices).selectinload(StudySliceRecord.image_asset))
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    if not study.slices:
        raise HTTPException(status_code=409, detail="Upload a CT series before localization")

    store = PrivateImageStore()
    paths = tuple(str(store.path_for(item.image_asset.storage_key)) for item in study.slices)
    try:
        result = localize_dicom_series(paths)
    except LocalizationUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Pretrained lesion localization is unavailable. Configure the local SAMIHS "
                "model package and checkpoint, then restart the API."
            ),
        ) from error
    except LocalizationInputError as error:
        raise HTTPException(
            status_code=422,
            detail="Stored CT series does not meet the localizer input requirements.",
        ) from error

    localized_slices = []
    for image_slice, localization in zip(study.slices, result["slices"], strict=True):
        localized_slices.append(
            {
                "slice_id": image_slice.slice_id,
                "index": image_slice.index,
                "image_width": localization["image_width"],
                "image_height": localization["image_height"],
                "box": localization["box"],
                "mask_pixels": localization["mask_pixels"],
            }
        )
    return {
        "schema_version": "1.0.0",
        "study_id": study.study_id,
        "model_id": result["model_id"],
        "checkpoint_sha256": result["checkpoint_sha256"],
        "device": result["device"],
        "threshold": result["threshold"],
        "score_semantics": "SAMIHS binary ICH segmentation mask; research localization only",
        "slices": localized_slices,
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
        .options(selectinload(StudySliceRecord.image_asset))
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Study slice not found")

    path = PrivateImageStore().path_for(record.image_asset.storage_key)
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise HTTPException(status_code=422, detail="Stored DICOM slice cannot be read") from error

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
        .options(selectinload(StudySliceRecord.image_asset))
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Study slice not found")

    path = PrivateImageStore().path_for(record.image_asset.storage_key)
    try:
        dataset = dcmread(path, force=False)
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
        if width <= 0:
            raise ValueError("Invalid window width")
        low, high = level - width / 2, level + width / 2
        pixels = np.clip((pixels - low) / (high - low), 0, 1)
        if str(getattr(dataset, "PhotometricInterpretation", "")) == "MONOCHROME1":
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
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> StudyRecord:
    """Validate and privately store one anonymized, single-frame CT series."""

    limits = UploadLimits.from_environment()
    if not files:
        raise HTTPException(status_code=422, detail="At least one DICOM image is required")
    if len(files) > limits.max_files:
        raise HTTPException(status_code=413, detail="DICOM series contains too many files")

    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices))
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.slices:
        raise HTTPException(status_code=409, detail="Study already has an uploaded DICOM series")

    store = PrivateImageStore()
    staged = []
    published_keys: list[str] = []
    try:
        total_size = 0
        for upload in files:
            item = await stage_upload(
                upload,
                store,
                limits,
                already_staged_bytes=total_size,
            )
            staged.append(item)
            total_size += item.size_bytes

        validated = [validate_ct_slice(item.path, max_pixels=limits.max_pixels) for item in staged]
        for attribute, message in (
            ("study_instance_uid", "DICOM files do not belong to the same study"),
            ("series_instance_uid", "DICOM files do not belong to the same CT series"),
        ):
            identifiers = {getattr(item, attribute) for item in validated} - {None}
            if len(identifiers) > 1:
                raise DicomValidationError(message)
        if len({(item.rows, item.columns) for item in validated}) != 1:
            raise DicomValidationError("DICOM series image dimensions do not match")
        if len({item.sha256 for item in staged}) != len(staged):
            raise DicomValidationError("DICOM series contains duplicate image files")
        sop_identifiers = [item.sop_instance_uid for item in validated if item.sop_instance_uid]
        if len(set(sop_identifiers)) != len(sop_identifiers):
            raise DicomValidationError("DICOM series contains duplicate image instances")

        has_geometry = [item.slice_position is not None for item in validated]
        if len(staged) > 1 and any(has_geometry) and not all(has_geometry):
            raise DicomValidationError(
                "DICOM series has incomplete slice geometry; include geometry for every slice"
            )
        if len(staged) > 1 and not any(has_geometry):
            instance_numbers = [item.instance_number for item in validated]
            if any(number is None for number in instance_numbers) or len(
                set(instance_numbers)
            ) != len(instance_numbers):
                raise DicomValidationError(
                    "Multiple slices need complete position metadata, or a unique "
                    "DICOM Instance Number on every slice so they can be ordered."
                )
        if all(has_geometry):
            orientations = [item.orientation for item in validated]
            if any(orientation is None for orientation in orientations):
                raise DicomValidationError("DICOM series image geometry is incomplete")
            reference_orientation = orientations[0]
            if any(
                any(
                    not isclose(left, right, abs_tol=1e-4)
                    for left, right in zip(orientation, reference_orientation, strict=True)
                )
                for orientation in orientations[1:]
            ):
                raise DicomValidationError("DICOM series image orientations do not match")
        ordered = sorted(
            zip(staged, validated, strict=True),
            key=lambda item: (
                item[1].slice_position
                if item[1].slice_position is not None
                else float(item[1].instance_number or 0),
                item[1].sop_instance_uid or item[0].sha256,
            ),
        )
        for index, (upload, metadata) in enumerate(ordered):
            asset_id = uuid4()
            storage_key = store.storage_key(study_id, asset_id)
            store.publish(upload.path, storage_key)
            published_keys.append(storage_key)
            session.add(
                ImageAssetRecord(
                    image_asset_id=asset_id,
                    storage_key=storage_key,
                    sha256=upload.sha256,
                    size_bytes=upload.size_bytes,
                )
            )
            study.slices.append(
                StudySliceRecord(
                    slice_id=uuid4(),
                    index=index,
                    image_asset_id=asset_id,
                    z_position_mm=metadata.z_position_mm,
                )
            )

        if validated and all(item.is_synthetic_fixture for item in validated):
            fixture_model = session.scalar(
                select(ModelVersionRecord).where(
                    ModelVersionRecord.provider == "demo_fixture",
                    ModelVersionRecord.model_id == "synthetic-fixture",
                    ModelVersionRecord.prompt_version == "demo-fixture-v1",
                )
            )
            if fixture_model is None:
                fixture_model = ModelVersionRecord(
                    model_version_id=uuid4(),
                    provider="demo_fixture",
                    model_id="synthetic-fixture",
                    prompt_version="demo-fixture-v1",
                )
                session.add(fixture_model)
                session.flush()

            session.add(
                StudyAnalysisRecord(
                    analysis_id=uuid4(),
                    study_id=study_id,
                    model_version_id=fixture_model.model_version_id,
                )
            )
            evidence_slices = [
                item
                for item in study.slices
                if item.z_position_mm is not None and 0.0 < item.z_position_mm < 10.0
            ]

            if evidence_slices:
                finding_id = uuid4()
                finding = PersistedFindingRecord(
                    finding_id=finding_id,
                    study_id=study_id,
                    category="suspected_intracranial_hemorrhage",
                    confidence=0.84,
                    review_status="pending",
                    model_version_id=fixture_model.model_version_id,
                )
                for slice_record in evidence_slices:
                    finding.evidence.append(
                        FindingEvidenceRecord(
                            finding_id=finding_id,
                            slice_id=slice_record.slice_id,
                        )
                    )
                session.add(finding)

        study.status = "ready"
        session.commit()
        return study
    except UploadTooLarge as error:
        session.rollback()
        for key in published_keys:
            store.delete(key)
        raise HTTPException(status_code=413, detail=str(error)) from error
    except DicomValidationError as error:
        session.rollback()
        for key in published_keys:
            store.delete(key)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        session.rollback()
        for key in published_keys:
            store.delete(key)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BaseException:
        session.rollback()
        for key in published_keys:
            store.delete(key)
        raise
    finally:
        for item in staged:
            item.path.unlink(missing_ok=True)
        for upload in files:
            await upload.close()
