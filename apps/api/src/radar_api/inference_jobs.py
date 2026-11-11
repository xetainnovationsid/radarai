"""Persisted background execution for local research checkpoint inference."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from radar_api.database import SessionLocal
from radar_api.inference_service import (
    ModelUnavailableError,
    StudyScoringError,
    score_local_checkpoint,
)
from radar_api.models import (
    FindingEvidenceRecord,
    ImageAssetRecord,
    InferenceJobRecord,
    InferenceScoreRecord,
    ModelVersionRecord,
    PersistedFindingRecord,
    StudyAnalysisRecord,
    StudyRecord,
    StudySliceRecord,
)
from radar_api.storage import PrivateImageStore

logger = logging.getLogger("radar_api.inference")
PREPROCESSING_VERSION = "densenet121-ct-preprocessing/v2"


def _materialize_dicom_slices(session, study: StudyRecord, directory: Path) -> list[Path]:
    """Write stored database blobs to private temporary paths for the path-based model runner."""
    slices_by_asset = {item.image_asset_id: item for item in study.slices}
    statement = (
        select(
            ImageAssetRecord.image_asset_id,
            ImageAssetRecord.storage_key,
            ImageAssetRecord.dicom_data,
        )
        .where(ImageAssetRecord.image_asset_id.in_(slices_by_asset))
        .execution_options(yield_per=16)
    )
    paths_by_asset: dict[UUID, Path] = {}
    store = PrivateImageStore()

    for asset_id, storage_key, payload in session.execute(statement):
        if payload is None:
            try:
                payload = store.path_for(storage_key).read_bytes()
            except OSError as error:
                raise StudyScoringError("Stored CT slice is unavailable") from error
        if not payload:
            raise StudyScoringError("Stored CT slice is empty")

        path = directory / f"{asset_id.hex}.dcm"
        path.write_bytes(payload)
        if os.name != "nt":
            path.chmod(0o600)
        paths_by_asset[asset_id] = path

    if len(paths_by_asset) != len(study.slices):
        raise StudyScoringError("Stored CT series is incomplete")
    return [paths_by_asset[item.image_asset_id] for item in study.slices]


def run_inference_job(job_id: UUID) -> None:
    """Run one queued job and persist either a traceable result or safe error state."""
    with SessionLocal() as session:
        job = session.get(InferenceJobRecord, job_id)
        if job is None or job.status != "queued":
            return
        study = session.scalar(
            select(StudyRecord)
            .where(StudyRecord.study_id == job.study_id)
            .options(selectinload(StudyRecord.slices))
        )
        if study is None or not study.slices:
            _finish_failed(session, job, study, "study_has_no_slices")
            return

        job.status = "processing"
        job.started_at = datetime.now(UTC)
        session.commit()
        try:
            with tempfile.TemporaryDirectory(prefix="radar-inference-") as temporary_directory:
                paths = _materialize_dicom_slices(
                    session, study, Path(temporary_directory)
                )
                result = score_local_checkpoint(paths)
        except ModelUnavailableError:
            _finish_failed(session, job, study, "model_unavailable")
            return
        except StudyScoringError:
            _finish_failed(session, job, study, "inference_failed")
            return
        except Exception as error:  # keep private paths and upstream details out of API state/logs
            logger.error("Inference job %s failed with %s", job.job_id, type(error).__name__)
            _finish_failed(session, job, study, "inference_internal_error")
            return

        try:
            score_rows = result["slices"]
            if len(score_rows) != len(study.slices):
                raise ValueError("model returned an incomplete slice set")
            threshold = float(os.getenv("RADAR_ICH_SCORE_THRESHOLD", "0.5"))
            if not 0.0 < threshold < 1.0:
                threshold = 0.5
            model_version = ModelVersionRecord(
                model_version_id=uuid4(),
                provider="local_checkpoint",
                model_id=str(result["model_id"])[:160],
                prompt_version="ct-inference-v1",
                preprocessing_version=PREPROCESSING_VERSION,
                artifact_sha256=str(result["checkpoint_sha256"]),
                device=str(result["device"])[:16],
            )
            session.add(model_version)
            session.flush()
            analysis = StudyAnalysisRecord(
                analysis_id=uuid4(),
                study_id=study.study_id,
                model_version_id=model_version.model_version_id,
            )
            session.add(analysis)
            session.flush()
            positive_slices: list[tuple[StudySliceRecord, float]] = []
            for image_slice, output in zip(study.slices, score_rows, strict=True):
                scores = output.get("scores")
                if not isinstance(scores, dict) or "0" not in scores or "1" not in scores:
                    raise ValueError("model returned an unsupported output contract")
                class_0 = float(scores["0"])
                class_1 = float(scores["1"])
                if not 0 <= class_0 <= 1 or not 0 <= class_1 <= 1:
                    raise ValueError("model returned an out-of-range score")
                session.add_all(
                    [
                        InferenceScoreRecord(
                            analysis_id=analysis.analysis_id,
                            study_id=study.study_id,
                            slice_id=image_slice.slice_id,
                            model_version_id=model_version.model_version_id,
                            subtype="hemorrhage_absent",
                            score=class_0,
                        ),
                        InferenceScoreRecord(
                            analysis_id=analysis.analysis_id,
                            study_id=study.study_id,
                            slice_id=image_slice.slice_id,
                            model_version_id=model_version.model_version_id,
                            subtype="hemorrhage_present",
                            score=class_1,
                        ),
                    ]
                )
                if class_1 >= threshold:
                    positive_slices.append((image_slice, class_1))
            for image_slice, confidence in positive_slices:
                finding_id = uuid4()
                finding = PersistedFindingRecord(
                    finding_id=finding_id,
                    study_id=study.study_id,
                    category="suspected_intracranial_hemorrhage",
                    confidence=confidence,
                    review_status="pending",
                    model_version_id=model_version.model_version_id,
                )
                finding.evidence.append(
                    FindingEvidenceRecord(finding_id=finding_id, slice_id=image_slice.slice_id)
                )
                session.add(finding)
            study.status = "ready"
            job.status = "completed"
            job.error_code = None
            job.finished_at = datetime.now(UTC)
            session.commit()
        except Exception as error:
            session.rollback()
            logger.error(
                "Inference job %s persistence failed with %s", job.job_id, type(error).__name__
            )
            job = session.get(InferenceJobRecord, job_id)
            study = session.get(StudyRecord, job.study_id) if job else None
            if job is not None:
                _finish_failed(session, job, study, "inference_persistence_failed")


def _finish_failed(
    session,
    job: InferenceJobRecord,
    study: StudyRecord | None,
    error_code: str,
) -> None:
    if study is not None:
        study.status = "failed"
    job.status = "failed"
    job.error_code = error_code
    job.finished_at = datetime.now(UTC)
    session.commit()
