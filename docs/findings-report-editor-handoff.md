# Findings Sidebar, Report Editor & Reviewer Actions Handoff (RDA-4)

**Sprint:** 2 | **Epic:** RDA-4 | **Priority:** P0  
**Owner:** Bryan Christian Shine — Frontend (`apps/web`, `packages/contracts`)  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Overview & Acceptance Criteria Alignment

This handoff documents the end-to-end human-in-the-loop researcher workflow across **Upload → View → Infer → Draft → Edit/Approve**:

| Stage | Component / Route | Behavior & Contract |
| :--- | :--- | :--- |
| **1. Upload** | [`apps/web/app/page.tsx`](../apps/web/app/page.tsx) | Validates DICOM Part 10 headers (`DICM` at offset 128), rejects executables, creates study (`POST /v1/studies`), and uploads series (`POST /v1/studies/{id}/dicom`). |
| **2. View** | [`StudyViewerClient.tsx`](../apps/web/components/StudyViewerClient.tsx) & [`CornerstoneViewport.tsx`](../apps/web/components/CornerstoneViewport.tsx) | Renders Part 10 DICOM slices with Hounsfield Unit (HU) cursor probing, cranial window presets (`Brain`, `Subdural`, `Bone`, `Stroke`), and slice evidence navigation. |
| **3. Infer** | [`FindingsSidebar.tsx`](../apps/web/components/FindingsSidebar.tsx) | Retrieves persisted analysis (`GET /v1/studies/{id}/analysis`), DenseNet-121 slice scores (`GET /v1/studies/{id}/scores`), and SAMIHS masks (`GET /v1/studies/{id}/localizations`) with manual re-run triggers and visible failure recovery. |
| **4. Draft** | [`ReportEditor.tsx`](../apps/web/components/ReportEditor.tsx) | Automatically synthesizes a structured 5-section radiology research report (`ClinicalReportDraft`) from study geometry, cited evidence slices, model confidence scores, and SAMIHS masks. |
| **5. Edit & Approve** | [`ReportEditor.tsx`](../apps/web/components/ReportEditor.tsx) & [`FindingsSidebar.tsx`](../apps/web/components/FindingsSidebar.tsx) | Supports manual report editing, active slice citation injection (`[Irisan #X, Z: ... mm]`), per-finding audit decisions (`POST /v1/studies/{id}/findings/{id}/review`), formal report sign-off (`approved`), and multi-format export (`.md`, `.json`, Clipboard, Print/PDF). |

---

## 2. Shared Data Contract (`@radar-ai/contracts`)

Defined in [`packages/contracts/src/radar-api.ts`](../packages/contracts/src/radar-api.ts):

```ts
export type ReportReviewStatus = "draft" | "in_review" | "approved" | "rejected";

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
```

---

## 3. Failure Visibility & Recovery Matrix

All network and client operations surface explicit error banners with machine-readable telemetry codes and recovery actions:

| Failure Scenario | Surfaced Telemetry Code | Recovery Action |
| :--- | :--- | :--- |
| Unauthenticated review submission (`HTTP 401`) | `ERR_REVIEW_API` | Prompts researcher to sign in via Firebase OAuth or configure API key. |
| Rate limit exceeded (`HTTP 429`) | `ERR_REVIEW_API` / `ERR_RATE_LIMIT_429` | Displays backoff guidance and preserves current UI state. |
| Local DenseNet-121 checkpoint unconfigured (`HTTP 503`) | `ERR_SCORES_503` / `DEMO_FIXTURE` | Displays warning card with `Coba Lagi Skor Model` button (`onRetryInference`). |
| Local SAMIHS localizer unconfigured (`HTTP 503`/`422`) | `ERR_SAMIHS_503` / `DEMO_FIXTURE` | Displays warning card with `Coba Lagi Lokalisasi` button (`onRetryInference`). |
| Approving report without manual concurrence | `ERR_REPORT_CONCURRENCE_REQUIRED` | Blocks approval until the researcher checks the non-clinical concurrence confirmation. |
| Approving report with empty findings/impression | `ERR_REPORT_EMPTY_FIELDS` | Alerts reviewer to complete required sections before sign-off. |

---

## 4. Safety & Non-Diagnostic Guardrails

1. **Immutable Disclaimer**: Every synthesized report, exported file (`.md`, `.json`), and print stylesheet embeds `PROTOTYPING ONLY — NOT FOR CLINICAL USE`.
2. **Edit Invalidation on Approved Reports**: If a reviewer modifies any clinical text field after a report has been marked `approved`, the editor automatically transitions the report status back to `in_review` and clears `signed_at`, requiring fresh human sign-off.
3. **Zero Patient Data**: All report identifiers (`report_id`, `study_id`, `study_code`) use anonymized UUIDs and synthetic study codes.

