# BUG-21: SAMIHS Localization Permanently Returns `HTTP 503` in Default Local Mode and Races Ahead of Inference Job Polling in `StudyViewerClient`

**Severity:** P1 (High)  
**Component:** `apps/api/src/radar_api/main.py`, `apps/api/src/radar_api/inference_jobs.py`, & `apps/web/components/StudyViewerClient.tsx`  
**Found in:** Post-Sprint 2 Codebase Audit (2026-11-11)  
**Status:** Open / Fix Available  
**Type:** Broken Feature Integration / Async Race Condition  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

Two defects prevent SAMIHS hemorrhage mask localization (`GET /v1/studies/{study_id}/localizations`) from working in both local mode (`RADAR_INFERENCE_MODE=local`) and laptop worker mode (`RADAR_INFERENCE_MODE=laptop_worker`):

### Root Cause 1: Local Inference Mode Never Runs or Persists SAMIHS Localization
In commit `49456af`, `get_study_localizations` in [`apps/api/src/radar_api/main.py`](../../apps/api/src/radar_api/main.py) (lines 753–794) was modified to stop calling `localize_dicom_series()` and instead only query persisted `StudyLocalizationRecord` rows:

```python
# Lines 770-781 in apps/api/src/radar_api/main.py:
record = session.scalar(
    select(StudyLocalizationRecord)
    .where(StudyLocalizationRecord.study_id == study_id)
    .options(selectinload(StudyLocalizationRecord.model_version))
    .order_by(StudyLocalizationRecord.created_at.desc(), StudyLocalizationRecord.localization_id.desc())
    .limit(1)
)
if record is None:
    raise HTTPException(
        status_code=503,
        detail="SAMIHS results are unavailable until the laptop worker completes localization.",
    )
```

However, when the backend runs in its default local inference mode (`RADAR_INFERENCE_MODE=local`, see `worker_bridge.py:60`), background jobs are executed by `run_inference_job()` in [`apps/api/src/radar_api/inference_jobs.py`](../../apps/api/src/radar_api/inference_jobs.py) (lines 73–192), which **only calls `score_local_checkpoint(paths)`** and never invokes `localize_dicom_series()` or writes a `StudyLocalizationRecord`!
As a result, in local mode, `GET /v1/studies/{study_id}/localizations` **permanently returns `HTTP 503`** even when the SAMIHS model and checkpoint are properly installed locally.

### Root Cause 2: `StudyViewerClient` Fires `fetchStudyLocalizations` Before the Inference Job Finishes and Never Re-Fetches
In [`apps/web/components/StudyViewerClient.tsx`](../../apps/web/components/StudyViewerClient.tsx) (lines 459–495, 380–406, and 309–333), opening a study or clicking **Segarkan Inference** launches `fetchModelScores(safeStudyId)` and `fetchStudyLocalizations(safeStudyId)` **concurrently at $t = 0$**:

```typescript
// Lines 459-495 in apps/web/components/StudyViewerClient.tsx:
void fetchModelScores(safeStudyId)
  .then((scores) => {
    if (!ignore) {
      setModelScores(scores);
      void fetchStudyAnalysis(safeStudyId).then((value) => {
        if (!ignore) setAnalysis(value);
      });
      ...
    }
  })
  ...
void fetchStudyLocalizations(safeStudyId)
  .then((result) => {
    if (!ignore) setLocalizations(result);
  })
  .catch((cause: unknown) => {
    if (!ignore) {
      setLocalizationError(
        cause instanceof Error ? cause.message : "Lokalisasi lesi tidak tersedia."
      );
    }
  });
```

1. `fetchModelScores(safeStudyId)` sends `POST /v1/studies/{id}/inference-jobs` to enqueue the job and polls `/v1/studies/{id}/inference-jobs/{job_id}` every 1 second until the job transitions to `"completed"`.
2. At the exact same moment ($t = 0$), `fetchStudyLocalizations(safeStudyId)` calls `GET /v1/studies/{id}/localizations` while the inference job is still `"queued"` or `"processing"`.
3. `GET /v1/studies/{id}/localizations` immediately fails with `HTTP 503` because the worker has not completed the job yet.
4. When `fetchModelScores(safeStudyId)` finishes polling and the job completes, it re-fetches `fetchStudyAnalysis(safeStudyId)`, **but never re-fetches `fetchStudyLocalizations(safeStudyId)`**!

---

## 2. Reproduction Steps

1. Upload a new CT series and open `/studies/{study_id}` while the laptop worker (or local inference runner) is active.
2. Observe the Network tab:
   - `POST /v1/studies/{id}/inference-jobs` (`202 Accepted`, status `"queued"`) and `GET /v1/studies/{id}/localizations` (`503 Service Unavailable`) are sent at the same time.
   - Several seconds later, `/inference-jobs/{job_id}` returns `"completed"`, and `/scores` + `/analysis` succeed (`200 OK`), but `/localizations` is never requested again.
3. The sidebar remains stuck showing `ERR_SAMIHS_503: SAMIHS results are unavailable until the laptop worker completes localization.` until the user manually reloads the page.

---

## 3. Impact Analysis

- **100% Broken SAMIHS Localization in Local Mode**: Researchers running the API locally without the separate laptop pull-worker cannot use SAMIHS localization at all.
- **Guaranteed `HTTP 503` on First Study Load in Worker Mode**: Every newly uploaded study displays a false SAMIHS `503` error in the viewer even after the laptop worker successfully persists `StudyLocalizationRecord`.

---

## 4. Recommended Remediation

1. **In `apps/api/src/radar_api/inference_jobs.py`**: Run optional `localize_dicom_series` inside `run_inference_job` (matching `run_laptop_inference_worker.py`) and persist `StudyLocalizationRecord` when available.
2. **In `apps/web/components/StudyViewerClient.tsx`**: Call `fetchStudyLocalizations(safeStudyId)` **after** `fetchModelScores(safeStudyId)` resolves (inside the `.then()` handler alongside `fetchStudyAnalysis`), so localizations are fetched once the inference job has completed.
