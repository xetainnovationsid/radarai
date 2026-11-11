# BUG-23: Laptop Worker Bridge `get_job_slice` Missing `PrivateImageStore` Fallback, Unbounded Poison-Job Lease Retries, and Unhandled Env Var Parse Errors

**Severity:** P2 (Medium)  
**Component:** `apps/api/src/radar_api/worker_bridge.py`, `apps/api/src/radar_api/inference_jobs.py`, & `apps/api/src/radar_api/main.py`  
**Found in:** Post-Sprint 2 Codebase Audit (2026-11-11)  
**Status:** Open / Fix Available  
**Type:** Worker Resilience / Storage Fallback Gap / Queue Starvation  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

Three reliability and edge-case bugs exist in the laptop pull-worker bridge ([`apps/api/src/radar_api/worker_bridge.py`](../../apps/api/src/radar_api/worker_bridge.py)) and background job runner ([`apps/api/src/radar_api/inference_jobs.py`](../../apps/api/src/radar_api/inference_jobs.py)):

### Root Cause 1: `get_job_slice` Lacks `PrivateImageStore` File Fallback When `dicom_data` Is `None`
Commit `8a5e3a6` updated `inference_jobs.py`, `get_slice_dicom`, and `get_slice_preview` to fall back to `PrivateImageStore().path_for(storage_key).read_bytes()` when `ImageAssetRecord.dicom_data` is `None`.
However, `get_job_slice` in [`apps/api/src/radar_api/worker_bridge.py`](../../apps/api/src/radar_api/worker_bridge.py) (lines 154–165) was missed:
```python
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
```
Any study whose slices are backed by `PrivateImageStore` on disk (`dicom_data is None`) fails with `HTTP 404 DICOM slice not found` when claimed by the laptop worker.

### Root Cause 2: Unbounded Poison-Job Re-Leasing (`attempt_count` Never Checked)
In `claim_next_job` (`apps/api/src/radar_api/worker_bridge.py:72-121`):
```python
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
...
job.attempt_count = (job.attempt_count or 0) + 1
```
Although `attempt_count` is incremented on every lease claim, `claim_next_job` never enforces a maximum attempt threshold (e.g., `MAX_WORKER_ATTEMPTS = 3`). If a malformed or huge study triggers a CUDA Out-Of-Memory kill or native segfault on the laptop worker before `_fail()` can report back to the API, its 10-minute lease expires and `claim_next_job` (which orders by `InferenceJobRecord.created_at` ascending) re-leases the same poison job indefinitely, starving all newer jobs in the queue.

### Root Cause 3: Uncaught `ValueError` on `RADAR_ICH_SCORE_THRESHOLD` & `list_report_drafts` N+1 / Null Dereference
- In `persist_worker_scores` (`worker_bridge.py:254`):
  `threshold = float(os.getenv("RADAR_ICH_SCORE_THRESHOLD", "0.5"))`
  If `RADAR_ICH_SCORE_THRESHOLD` is set to a malformed string (e.g. `""` or `"0.5f"`), `float(...)` raises an unhandled `ValueError` (returning `HTTP 500`) after `ModelVersionRecord`, `StudyAnalysisRecord`, and `StudyLocalizationRecord` have already been flushed.
- In `list_report_drafts` (`apps/api/src/radar_api/main.py:453-456`):
  ```python
  "model_id": (
      session.get(ModelVersionRecord, record.model_version_id).model_id
      if record.model_version_id
      else None
  ),
  ```
  This executes an $N+1$ database query per draft and raises `AttributeError: 'NoneType' object has no attribute 'model_id'` if the referenced `ModelVersionRecord` is not found.

---

## 2. Reproduction Steps

1. Insert a `StudySliceRecord` backed by a file in `PrivateImageStore` (`dicom_data=None`) and run `/internal/worker/jobs/{job_id}/slices/{slice_id}`: observe `HTTP 404`.
2. Simulate a worker crash during `"processing"` and advance lease expiration 3+ times: observe `attempt_count` incrementing without bound (`4, 5, 6, ...`) while blocking newer `"queued"` jobs.

---

## 3. Impact Analysis

- **Queue Head-of-Line Blocking**: One crashing job permanently stalls the laptop worker and starves all subsequent inference jobs.
- **Storage Backend Inconsistency**: Disk-backed slices work in local inference mode and viewer endpoints but fail in laptop worker mode.

---

## 4. Recommended Remediation

1. **Add `PrivateImageStore` Fallback to `get_job_slice`** in `apps/api/src/radar_api/worker_bridge.py`:
```python
payload = item.image_asset.dicom_data
if payload is None:
    try:
        payload = PrivateImageStore().path_for(item.image_asset.storage_key).read_bytes()
    except OSError as error:
        raise HTTPException(status_code=404, detail="DICOM slice not found") from error
```
2. **Cap Maximum Lease Attempts** in `claim_next_job` (e.g. `MAX_ATTEMPTS = 3`), automatically transitioning jobs with `attempt_count >= MAX_ATTEMPTS` to `status = "failed"` (`error_code = "worker_lease_exhausted"`).
3. **Parse `RADAR_ICH_SCORE_THRESHOLD` Safely** with `try ... except ValueError: threshold = 0.5`.
