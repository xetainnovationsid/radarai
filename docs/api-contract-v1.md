# RADAR API contract v1.0.0

This is the shared contract for the web and API workstreams in RDA-18. Python models in
`apps/api/src/radar_api/contracts.py` validate API payloads; the matching TypeScript types live in
`packages/contracts/src/radar-api.ts`.

## Study analysis response

```json
{
  "schema_version": "1.0.0",
  "study": {
    "study_id": "00000000-0000-4000-8000-000000000001",
    "modality": "CT",
    "status": "ready",
    "slices": [
      {
        "slice_id": "00000000-0000-4000-8000-000000000002",
        "index": 0,
        "image_asset_id": "00000000-0000-4000-8000-000000000003",
        "z_position_mm": 1.5
      }
    ]
  },
  "findings": [
    {
      "finding_id": "00000000-0000-4000-8000-000000000005",
      "category": "suspected_intracranial_hemorrhage",
      "evidence_slice_ids": ["00000000-0000-4000-8000-000000000002"],
      "confidence": 0.25,
      "review_status": "pending",
      "model_version_id": "00000000-0000-4000-8000-000000000004"
    }
  ],
  "model_version": {
    "model_version_id": "00000000-0000-4000-8000-000000000004",
    "provider": "local_checkpoint",
    "model_id": "radar-densenet121-ct",
    "prompt_version": "radar-findings-v1",
    "preprocessing_version": "densenet121-ct-preprocessing/v2",
    "artifact_sha256": "<checkpoint sha256>",
    "device": "cpu"
  }
}
```

`confidence` is a model-reported score in `[0, 1]`, not a calibrated probability. Every finding
must cite one or more evidence slices and is `pending` human review by default. The contract
contains opaque internal UUIDs and intentionally has no patient name, date of birth, or DICOM UID.
Unknown fields are rejected by the API models so incompatible changes surface during development.

## Study metadata endpoints

- `POST /v1/studies` accepts `CreateStudyRequest` (`{}` or `{"modality":"CT"}`) and returns a
  new `Study` with status `uploaded` and no slices yet.
- `GET /v1/studies` returns the saved studies as a JSON array of `Study` values.
- `GET /v1/studies/{study_id}` returns one `Study` or `404` when it does not exist.

The API stores opaque study and slice UUIDs only. It does not accept patient names, dates of birth,
DICOM UIDs, or image bytes. The dependent upload workstream handles DICOM validation and private
image storage. OpenAPI exposes the route and request/response schemas at `/openapi.json`.

`GET /v1/studies/{study_id}/slices/{slice_id}/image` renders a validated stored slice to a
windowed PNG preview and sends `Cache-Control: private, no-store`.
`GET /v1/studies/{study_id}/slices/{slice_id}/dicom` streams the validated stored Part 10 DICOM
slice (`application/dicom`) with `Cache-Control: private, no-store` so the Cornerstone3D viewer
can perform client-side Hounsfield Unit calibration and windowing on the exact uploaded slice.

`GET /v1/studies/{study_id}/analysis` returns persisted findings in the v1 contract, or `404` if
the study has no completed analysis. It never generates a placeholder finding. Review decisions
are submitted through `POST /v1/studies/{study_id}/findings/{finding_id}/review` with
`{"review_status":"accepted"}`, `rejected`, or `uncertain`. Each decision is stored in
`finding_review_events` and can be read from the corresponding `/reviews` route. Reviewer identity
uses the verified caller identity in production (or `local-reviewer` in local development). Each
audit event stores both the previous and newly selected review status. Study metadata, files,
scores, findings, reports, and job status are scoped to the authenticated study owner. A caller
that does not own a study receives `404`.

`PUT /v1/studies/{study_id}/findings/{finding_id}` accepts a corrected confidence and/or evidence
slice IDs. Evidence must belong to the same study. An edit moves the finding back to `uncertain`
for another explicit decision, increments its revision, and stores before/after snapshots in the
append-only review event log. Review actions also increment the revision and retain snapshots.

### Upload one anonymized CT series

`POST /v1/studies/{study_id}/dicom` accepts repeated multipart `files` fields and returns the
updated `Study`. The series must contain readable, single-frame CT images with matching study and
series identifiers, unique SOP instances, valid image geometry, and decodable pixel data. Direct
patient and institution identifiers are rejected. A study accepts one series; use the study UUID
returned by `POST /v1/studies`.

Uploads are streamed to a private filesystem directory (default `apps/api/data/private-images` when
the API is run from `apps/api`). The directory is not mounted as static content. Storage paths use
server-generated UUIDs; client filenames and content types are ignored. On POSIX systems directories
are created with mode `0700` and files with mode `0600`. No DICOM tags or storage paths are returned.

Configurable limits are `RADAR_MAX_DICOM_FILE_BYTES` (64 MiB per file),
`RADAR_MAX_DICOM_SERIES_BYTES` (512 MiB per series), `RADAR_MAX_DICOM_FILES` (512 files), and
`RADAR_MAX_DICOM_PIXELS` (16,777,216 pixels per image). A size or file-count overflow returns `413`,
invalid or identifiable DICOM returns `422`, an unknown study returns `404`, and a study that already
has a series returns `409`.

### Background inference and traceability

- `POST /v1/studies/{study_id}/inference-jobs` returns a persisted job with `202 Accepted` and a
  `job_id`. Repeated requests reuse the active job or the latest completed job.
- `GET /v1/studies/{study_id}/inference-jobs/{job_id}` is the polling endpoint. Status is one of
  `queued`, `processing`, `completed`, or `failed`; failure responses expose a stable error code,
  never exception text or filesystem paths.
- `GET /v1/studies/{study_id}/scores` returns only persisted scores from the latest local analysis.
  It returns `404` until a local inference job completes.
- The API persists one `hemorrhage_absent` and `hemorrhage_present` score per slice with the study,
  slice, analysis, and model-version IDs. The model version stores checkpoint SHA-256, device,
  preprocessing version, and model ID. Findings cite exact positive-score slices and begin in
  `pending` review status.
- Inference uses only a locally provisioned DenseNet121 checkpoint. If `RADAR_CT_CHECKPOINT` is
  missing or invalid, the job becomes `failed` with `model_unavailable`; it never fabricates a
  completed result. Configure `RADAR_ICH_SCORE_THRESHOLD` only for research threshold experiments.

### Source-cited report drafts

- `POST /v1/studies/{study_id}/reports/drafts` generates a Meta draft from persisted, de-identified
  findings using structured JSON output. The model receives finding IDs, category, scores, review
  state, and evidence slice IDs; it does not receive DICOM bytes, patient identifiers, or study
  metadata. The API rejects citations that do not exist in the saved analysis.
- The output is an unsigned `draft`. Its statements must cite one or more source finding IDs; all
  drafts remain subject to human review and are research-only.
- If DeepSeek is not configured or unavailable, the endpoint returns `503` with a manual fallback
  instruction. Send `manual_content` in the same request to store an explicitly manual, cited draft.
- `GET /v1/studies/{study_id}/reports/drafts` returns immutable versioned drafts in newest-first
  order. A later manual or generated draft creates a new version.

## DeepSeek report drafting

The generated draft endpoint calls DeepSeek's OpenAI-compatible API at
`https://api.deepseek.com/chat/completions` with model slug `deepseek-flash` (DeepSeek V4.1 Flash).
Set `DEEPSEEK_API_KEY` only in the API deployment environment. The service sends de-identified
saved findings, requests JSON output, validates the response against `ReportContent`, and rejects
citations that do not match saved findings. It never sends CT images or patient identifiers.

References: [model catalog](https://api-docs.deepseek.com/api/list-models/),
[chat completions](https://api-docs.deepseek.com/api/create-chat-completion/), and
[JSON output](https://api-docs.deepseek.com/guides/json_mode/).

To check account access with a synthetic text-only request, set `DEEPSEEK_API_KEY` locally and run
`python scripts/check_deepseek_model_access.py` from `apps/api`. Never commit or paste the key.

## Fallback and safety

- If DeepSeek is unavailable, return an explicit unavailable/error state; do not silently mark an
  unvalidated model or static fixture as real inference.
- A `demo_fixture` provider is permitted only for synthetic demonstration data and must remain
  visibly marked as a fixture. Production/demo integrations can use an `approved_alternate` only
  after its access, cost, contract compatibility, and research validation are recorded.
- This is research prototyping only, not for clinical use. All model outputs require human review.
