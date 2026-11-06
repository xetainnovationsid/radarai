/** Shared response contract v1.0.0. Research prototype only; not for clinical use. */

export type StudyStatus = "uploaded" | "processing" | "ready" | "failed";
export type FindingReviewStatus = "pending" | "accepted" | "rejected" | "uncertain";
export type ReportReviewStatus = "draft" | "in_review" | "approved" | "rejected";

export interface StudySlice {
  slice_id: string;
  index: number;
  image_asset_id: string;
  z_position_mm: number | null;
}

export interface Study {
  study_id: string;
  modality: "CT";
  status: StudyStatus;
  slices: StudySlice[];
}

export interface CreateStudyRequest {
  modality?: "CT";
}

export interface ModelVersion {
  model_version_id: string;
  provider: "meta_model_api" | "local_checkpoint" | "approved_alternate" | "demo_fixture";
  model_id: string;
  prompt_version: string;
  preprocessing_version?: string | null;
  artifact_sha256?: string | null;
  device?: string | null;
}

export interface Finding {
  finding_id: string;
  category: "suspected_intracranial_hemorrhage";
  evidence_slice_ids: string[];
  confidence: number;
  review_status: FindingReviewStatus;
  model_version_id: string;
  revision?: number;
}

export interface StudyAnalysisResponse {
  schema_version: "1.0.0";
  study: Study;
  findings: Finding[];
  model_version: ModelVersion;
}

export interface StudySliceScore {
  slice_id: string;
  index: number;
  class_0_score: number;
  class_1_score: number;
}

export interface StudyModelScores {
  schema_version: "1.0.0";
  study_id: string;
  model_id: string;
  checkpoint_sha256: string;
  device: string;
  score_semantics: "Uncalibrated RSNA ICH slice-label scores; not a diagnosis";
  class_1_label_semantics: "RSNA ICH slice label 1 means hemorrhage annotated present; research score only";
  slices: StudySliceScore[];
}

export interface InferenceJob {
  job_id: string;
  study_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Box2D {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SliceLocalization {
  slice_id: string;
  index: number;
  image_width: number;
  image_height: number;
  box: Box2D | null;
  mask_pixels: number;
}

export interface StudyLocalizations {
  schema_version: "1.0.0";
  study_id: string;
  model_id: string;
  checkpoint_sha256: string;
  device: string;
  threshold: number;
  score_semantics: "SAMIHS binary ICH segmentation mask; research localization only";
  slices: SliceLocalization[];
}

export interface FindingReviewEvent {
  review_event_id: string;
  finding_id: string;
  previous_review_status: FindingReviewStatus | null;
  review_status: Exclude<FindingReviewStatus, "pending">;
  action: "review" | "edit";
  version: number;
  previous_snapshot: Record<string, unknown> | null;
  current_snapshot: Record<string, unknown> | null;
  reviewer: string;
  created_at: string;
}

export interface ClinicalReportDraft {
  report_id: string;
  study_id: string;
  study_code: string;
  status: ReportReviewStatus;
  clinical_indication: string;
  technique: string;
  findings: string;
  impression: string;
  reviewer_notes: string;
  reviewer_id: string;
  concurrence_confirmed: boolean;
  created_at: string;
  updated_at: string;
  signed_at: string | null;
  non_clinical_disclaimer: string;
}


