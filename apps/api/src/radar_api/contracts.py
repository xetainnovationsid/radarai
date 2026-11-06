"""Versioned API contracts shared with the web client."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Reject unknown fields so API drift is visible during development."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class StudyStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class FindingReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class StudySlice(ContractModel):
    slice_id: UUID
    index: int = Field(ge=0)
    image_asset_id: UUID
    z_position_mm: float | None = None


class Study(ContractModel):
    study_id: UUID
    modality: Literal["CT"]
    status: StudyStatus
    slices: list[StudySlice]


class CreateStudyRequest(ContractModel):
    """Create metadata for a study before image upload is handled by its workstream."""

    modality: Literal["CT"] = "CT"


class ModelVersion(ContractModel):
    model_version_id: UUID
    provider: Literal["meta_model_api", "local_checkpoint", "approved_alternate", "demo_fixture"]
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    preprocessing_version: str | None = None
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    device: str | None = None


class Finding(ContractModel):
    finding_id: UUID
    category: Literal["suspected_intracranial_hemorrhage"]
    evidence_slice_ids: list[UUID] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    review_status: FindingReviewStatus = FindingReviewStatus.PENDING
    model_version_id: UUID
    revision: int = Field(default=1, ge=1)


class StudyAnalysisResponse(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    study: Study
    findings: list[Finding]
    model_version: ModelVersion


class StudySliceScore(ContractModel):
    slice_id: UUID
    index: int = Field(ge=0)
    class_0_score: float = Field(ge=0, le=1)
    class_1_score: float = Field(ge=0, le=1)


class StudyModelScores(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    study_id: UUID
    model_id: str = Field(min_length=1)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    device: str = Field(min_length=1)
    score_semantics: Literal["Uncalibrated RSNA ICH slice-label scores; not a diagnosis"]
    class_1_label_semantics: Literal[
        "RSNA ICH slice label 1 means hemorrhage annotated present; research score only"
    ]
    slices: list[StudySliceScore] = Field(min_length=1)


class InferenceJob(ContractModel):
    job_id: UUID
    study_id: UUID
    status: Literal["queued", "processing", "completed", "failed"]
    error_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ReportStatement(ContractModel):
    text: str = Field(min_length=1, max_length=2000)
    finding_ids: list[UUID] = Field(min_length=1)


class ReportContent(ContractModel):
    findings: list[ReportStatement] = Field(min_length=1, max_length=20)
    impression: ReportStatement
    limitations: str = Field(min_length=1, max_length=1000)


class CreateReportDraftRequest(ContractModel):
    manual_content: ReportContent | None = None


class ReportDraft(ContractModel):
    report_id: UUID
    study_id: UUID
    version: int = Field(ge=1)
    status: Literal["draft", "approved", "rejected"]
    source_finding_ids: list[UUID]
    content: ReportContent
    created_by: str
    created_at: datetime
    generation_mode: Literal["meta_model_api", "manual_fallback"]
    model_id: str | None = None


class Box2D(ContractModel):
    """Normalized bounding box around a pretrained segmentation mask."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class SliceLocalization(ContractModel):
    slice_id: UUID
    index: int = Field(ge=0)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    box: Box2D | None = None
    mask_pixels: int = Field(ge=0)


class StudyLocalizations(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    study_id: UUID
    model_id: str = Field(min_length=1)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    device: str = Field(min_length=1)
    threshold: float = Field(gt=0, lt=1)
    score_semantics: Literal["SAMIHS binary ICH segmentation mask; research localization only"]
    slices: list[SliceLocalization] = Field(min_length=1)


class FindingReviewRequest(ContractModel):
    review_status: Literal["accepted", "rejected", "uncertain"]


class FindingCorrectionRequest(ContractModel):
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_slice_ids: list[UUID] | None = Field(default=None, min_length=1)


class FindingReviewEvent(ContractModel):
    review_event_id: UUID
    finding_id: UUID
    previous_review_status: FindingReviewStatus | None = None
    review_status: Literal["accepted", "rejected", "uncertain"]
    action: Literal["review", "edit"] = "review"
    version: int = Field(ge=1)
    previous_snapshot: dict[str, object] | None = None
    current_snapshot: dict[str, object] | None = None
    reviewer: str
    created_at: datetime

