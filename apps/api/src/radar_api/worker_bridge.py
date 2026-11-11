"""Authenticated pull-worker bridge for inference on the researcher's laptop."""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from radar_api.contracts import Box2D
from radar_api.models import (
    FindingEvidenceRecord,
    ImageAssetRecord,
    InferenceJobRecord,
    InferenceScoreRecord,
    ModelVersionRecord,
    PersistedFindingRecord,
    StudyAnalysisRecord,
    StudyLocalizationRecord,
    StudyRecord,
    StudySliceRecord,
)


class WorkerLocalizationSlice(BaseModel):
    slice_id: UUID
    index: int = Field(ge=0)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    box: Box2D | None = None
    mask_pixels: int = Field(ge=0)


class WorkerLocalization(BaseModel):
    model_id: str = Field(min_length=1, max_length=160)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    device: str = Field(min_length=1, max_length=16)
    threshold: float = Field(gt=0, lt=1)
    slices: list[WorkerLocalizationSlice] = Field(min_length=1, max_length=10000)


class WorkerClaimRequest(BaseModel):
    study_id: UUID | None = None


class WorkerScores(BaseModel):
    model_id: str = Field(min_length=1, max_length=160)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    device: str = Field(min_length=1, max_length=16)
    slices: list[dict[str, object]] = Field(min_length=1, max_length=10000)
    localization: WorkerLocalization | None = None


def worker_mode_enabled() -> bool:
    return os.getenv("RADAR_INFERENCE_MODE", "local").strip().lower() == "laptop_worker"


def require_worker_token(request: Request) -> None:
    expected = os.getenv("RADAR_WORKER_TOKEN", "").strip()
    supplied = request.headers.get("authorization", "")
    if len(expected) < 32 or not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker authentication failed")
    if not worker_mode_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Laptop worker mode is disabled")


def claim_next_job(
    session: Session, allowed_study_id: UUID | None = None
) -> dict[str, object] | None:
    """Atomically lease one job and reclaim work whose lease expired."""
    now = datetime.now(UTC)
    conditions = [
        (InferenceJobRecord.status == "queued")
        | (
            (InferenceJobRecord.status == "processing")
            & (
                InferenceJobRecord.lease_expires_at.is_(None)
                | (InferenceJobRecord.lease_expires_at < now)
            )
        )
    ]
    if allowed_study_id is not None:
        conditions.append(InferenceJobRecord.study_id == allowed_study_id)
    statement = (
        select(InferenceJobRecord)
        .where(*conditions)
        .order_by(InferenceJobRecord.created_at, InferenceJobRecord.job_id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalar(statement)
    if job is None:
        return None
    study = session.get(StudyRecord, job.study_id)
    if study is None:
        job.status = "failed"
        job.error_code = "study_not_found"
        job.finished_at = datetime.now(UTC)
        job.lease_token = None
        job.lease_expires_at = None
        session.commit()
        return None
    lease_token = uuid4()
    job.status = "processing"
    job.started_at = job.started_at or now
    job.lease_token = lease_token
    job.lease_expires_at = now + timedelta(minutes=10)
    job.attempt_count = (job.attempt_count or 0) + 1
    job.error_code = None
    study.status = "processing"
    session.commit()
    return {
        "job_id": str(job.job_id),
        "study_id": str(job.study_id),
        "lease_token": str(lease_token),
    }


def _require_active_lease(
    session: Session, job_id: UUID, lease_token: UUID
) -> InferenceJobRecord:
    job = session.scalar(
        select(InferenceJobRecord)
        .where(InferenceJobRecord.job_id == job_id)
        .with_for_update()
    )
    now = datetime.now(UTC)
    lease_expires_at = job.lease_expires_at if job is not None else None
    if lease_expires_at is not None and lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    if (
        job is None
        or job.status != "processing"
        or job.lease_token is None
        or lease_expires_at is None
        or lease_expires_at <= now
        or not hmac.compare_digest(str(job.lease_token), str(lease_token))
    ):
        raise HTTPException(status_code=409, detail="Inference job lease is no longer active")
    return job


def heartbeat_worker_job(session: Session, job_id: UUID, lease_token: UUID) -> None:
    job = _require_active_lease(session, job_id, lease_token)
    job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    session.commit()


def get_job_slice(
    session: Session, job_id: UUID, slice_id: UUID, lease_token: UUID
) -> tuple[bytes, str, int]:
    job = _require_active_lease(session, job_id, lease_token)
    item = session.scalar(
        select(StudySliceRecord)
        .where(StudySliceRecord.study_id == job.study_id, StudySliceRecord.slice_id == slice_id)
        .options(selectinload(StudySliceRecord.image_asset).undefer(ImageAssetRecord.dicom_data))
    )
    if item is None or item.image_asset.dicom_data is None:
        raise HTTPException(status_code=404, detail="DICOM slice not found")
    return item.image_asset.dicom_data, item.image_asset.sha256, item.index


def persist_worker_scores(
    session: Session, job_id: UUID, lease_token: UUID, result: WorkerScores
) -> None:
    if not result.device.lower().startswith("cuda"):
        raise HTTPException(status_code=422, detail="Laptop worker must report GPU inference")
    job = _require_active_lease(session, job_id, lease_token)
    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == job.study_id)
        .options(selectinload(StudyRecord.slices))
    )
    if study is None or len(result.slices) != len(study.slices):
        raise HTTPException(status_code=422, detail="Worker returned an incomplete slice set")

    parsed: list[tuple[StudySliceRecord, float, float]] = []
    by_id = {str(row.slice_id): row for row in study.slices}
    for output in result.slices:
        slice_id = str(output.get("slice_id", ""))
        image_slice = by_id.get(slice_id)
        scores = output.get("scores")
        if image_slice is None or not isinstance(scores, dict) or set(scores) != {"0", "1"}:
            raise HTTPException(status_code=422, detail="Worker returned invalid slice scores")
        try:
            class_0, class_1 = float(scores["0"]), float(scores["1"])
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Worker returned invalid scores") from error
        if not (0 <= class_0 <= 1 and 0 <= class_1 <= 1):
            raise HTTPException(status_code=422, detail="Worker scores are outside the valid range")
        parsed.append((image_slice, class_0, class_1))
    if len({row.slice_id for row, _, _ in parsed}) != len(study.slices):
        raise HTTPException(status_code=422, detail="Worker returned duplicate slice scores")

    localization_slices: list[WorkerLocalizationSlice] | None = None
    if result.localization is not None:
        localization = result.localization
        if not localization.device.lower().startswith("cuda"):
            raise HTTPException(status_code=422, detail="SAMIHS must report GPU inference")
        localization_by_id = {str(row.slice_id): row for row in study.slices}
        if len(localization.slices) != len(study.slices):
            raise HTTPException(status_code=422, detail="SAMIHS returned an incomplete slice set")
        for output in localization.slices:
            image_slice = localization_by_id.get(str(output.slice_id))
            if image_slice is None or output.index != image_slice.index:
                raise HTTPException(status_code=422, detail="SAMIHS returned invalid slice evidence")
        if len({row.slice_id for row in localization.slices}) != len(study.slices):
            raise HTTPException(status_code=422, detail="SAMIHS returned duplicate slice evidence")
        localization_slices = localization.slices

    model = ModelVersionRecord(
        model_version_id=uuid4(),
        provider="local_checkpoint",
        model_id=result.model_id,
        prompt_version="ct-inference-v1",
        preprocessing_version="densenet121-ct-preprocessing/v2",
        artifact_sha256=result.checkpoint_sha256,
        device=result.device,
    )
    session.add(model)
    session.flush()
    analysis = StudyAnalysisRecord(
        analysis_id=uuid4(), study_id=study.study_id, model_version_id=model.model_version_id
    )
    session.add(analysis)
    session.flush()
    if result.localization is not None and localization_slices is not None:
        localization = result.localization
        localization_model = ModelVersionRecord(
            model_version_id=uuid4(),
            provider="local_checkpoint",
            model_id=localization.model_id,
            prompt_version="samihs-fixed-center-prompt/v1",
            preprocessing_version="samihs-ct-hu-preprocessing/v1",
            artifact_sha256=localization.checkpoint_sha256,
            device=localization.device,
        )
        session.add(localization_model)
        session.flush()
        session.add(
            StudyLocalizationRecord(
                localization_id=uuid4(),
                study_id=study.study_id,
                model_version_id=localization_model.model_version_id,
                threshold=localization.threshold,
                slices=[row.model_dump(mode="json") for row in localization_slices],
            )
        )
    threshold = float(os.getenv("RADAR_ICH_SCORE_THRESHOLD", "0.5"))
    if not 0 < threshold < 1:
        threshold = 0.5
    positive: list[tuple[StudySliceRecord, float]] = []
    for image_slice, class_0, class_1 in parsed:
        session.add_all(
            [
                InferenceScoreRecord(
                    analysis_id=analysis.analysis_id,
                    study_id=study.study_id,
                    slice_id=image_slice.slice_id,
                    model_version_id=model.model_version_id,
                    subtype="hemorrhage_absent",
                    score=class_0,
                ),
                InferenceScoreRecord(
                    analysis_id=analysis.analysis_id,
                    study_id=study.study_id,
                    slice_id=image_slice.slice_id,
                    model_version_id=model.model_version_id,
                    subtype="hemorrhage_present",
                    score=class_1,
                ),
            ]
        )
        if class_1 >= threshold:
            positive.append((image_slice, class_1))
    for image_slice, confidence in positive:
        finding_id = uuid4()
        finding = PersistedFindingRecord(
            finding_id=finding_id,
            study_id=study.study_id,
            category="suspected_intracranial_hemorrhage",
            confidence=confidence,
            review_status="pending",
            model_version_id=model.model_version_id,
        )
        finding.evidence.append(
            FindingEvidenceRecord(finding_id=finding_id, slice_id=image_slice.slice_id)
        )
        session.add(finding)
    study.status = "ready"
    job.status = "completed"
    job.error_code = None
    job.finished_at = datetime.now(UTC)
    job.lease_token = None
    job.lease_expires_at = None
    session.commit()


def fail_worker_job(
    session: Session, job_id: UUID, lease_token: UUID, error_code: str
) -> None:
    job = _require_active_lease(session, job_id, lease_token)
    study = session.get(StudyRecord, job.study_id)
    if study is not None:
        study.status = "failed"
    job.status = "failed"
    job.error_code = error_code[:48]
    job.finished_at = datetime.now(UTC)
    job.lease_token = None
    job.lease_expires_at = None
    session.commit()
