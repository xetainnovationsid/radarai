# BUG-18: Per-Slice Upload Refactor Exhausts `RADAR_UPLOAD_RATE_LIMIT_PER_MINUTE` on Standard CT Series (>19 Slices)

**Severity:** P1 (High)  
**Component:** `apps/api/src/radar_api/security.py`, `apps/api/src/radar_api/main.py`, & `apps/web/lib/api-client.ts`  
**Found in:** Post-Sprint 2 Codebase Audit (2026-11-11)  
**Status:** Open / Fix Available  
**Type:** Rate Limiting Self-DoS / Functional Ingestion Failure  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

Following the persistent one-slice-per-request upload refactor (`49456af`), [`apps/web/lib/api-client.ts`](../../apps/web/lib/api-client.ts) and [`apps/api/src/radar_api/main.py`](../../apps/api/src/radar_api/main.py) upload CT series by dispatching one `POST /v1/studies` request followed by **one separate `POST /v1/studies/{study_id}/dicom` request per DICOM slice**:

```python
# Lines 1086-1088 in apps/api/src/radar_api/main.py:
if len(files) != 1:
    raise HTTPException(status_code=422, detail="Upload exactly one DICOM slice per request")
if total_files < 1 or total_files > limits.max_files:
    raise HTTPException(status_code=413, detail="DICOM series contains too many files")
```

However, in [`apps/api/src/radar_api/security.py`](../../apps/api/src/radar_api/security.py), both `POST /v1/studies` and `POST /v1/studies/{study_id}/dicom` share the `"upload"` sliding-window rate-limit tier with a default limit of **20 requests per minute**:

```python
# Lines 583-584 in apps/api/src/radar_api/security.py:
if method == "POST" and (path == "/v1/studies" or path.endswith("/dicom")):
    return "upload", _env_int("RADAR_UPLOAD_RATE_LIMIT_PER_MINUTE", 20)
```

Meanwhile, `CLIENT_UPLOAD_LIMITS.maxFiles` in `api-client.ts` advertises support for up to **512 slices per series**, and `FindingsSidebar.tsx:500` explicitly prompts researchers to upload full cranial CT volumes of **16–180 slices**.

### Root Cause
1. Creating a study (`POST /v1/studies`) consumes **1 token** from the `"upload:{client_ip}"` bucket (`19` remaining).
2. Uploading slices `0` through `18` (`19` slices) via `POST /v1/studies/{study_id}/dicom` consumes the remaining **19 tokens** (`0` remaining).
3. On the **20th slice** (`index = 19`), `SlidingWindowRateLimiter.check()` rejects the request with `HTTP 429 Too Many Requests` (`Retry-After: 60`).
4. Consequently, **no CT series with 20 or more slices can ever be uploaded** under the default configuration, even though a standard clinical/research axial brain CT scan contains 24 to 64+ slices (and thin-slice scans contain 100–300+ slices).

---

## 2. Reproduction Steps

1. Start the FastAPI server with default environment settings (`RADAR_UPLOAD_RATE_LIMIT_PER_MINUTE` unset, defaulting to `20`).
2. Select a valid anonymized 25-slice brain CT DICOM series in the web workspace (`/`) and click **Validate and upload**.
3. Observe:
   - `POST /v1/studies` succeeds (`201 Created`).
   - Slices `1` through `19` (`index=0..18`) succeed (`201 Created`).
   - Slice `20` (`index=19`) fails immediately with `HTTP 429 Too Many Requests` (`ERR_RATE_LIMIT_429: Batas laju unggahan (rate limit) tercapai.`).

---

## 3. Impact Analysis

- **Complete Ingestion Blocker for Full Brain CT Volumes**: Any real-world cranial CT series with $\ge 20$ slices fails deterministically mid-upload.
- **Contradicts SAMIHS Volume Requirements**: `FindingsSidebar.tsx` instructs users to upload 16–180 slices for 3D volume segmentation, leaving only a narrow window of 16–19 slices that can both upload and satisfy the volume notice.
- **Leaves Corrupted/Unfinalized Studies Behind**: When combined with [BUG-19](./BUG-19-partial-upload-cleanup-409-and-broken-resume.md), the aborted upload leaves an undeletable, unfinalized 19-slice study in the database.

---

## 4. Recommended Remediation

1. **Separate Study Creation Limit from Per-Slice Upload Limit** in `apps/api/src/radar_api/security.py`, and size the slice upload rate limit to accommodate at least one full 512-slice series per minute (e.g., `600/min`):

```python
# In apps/api/src/radar_api/security.py:
if method == "POST" and path == "/v1/studies":
    return "create_study", _env_int("RADAR_CREATE_STUDY_RATE_LIMIT_PER_MINUTE", 20)
if method == "POST" and path.endswith("/dicom"):
    return "upload_slice", _env_int("RADAR_UPLOAD_RATE_LIMIT_PER_MINUTE", 600)
```

2. **Add `HTTP 429` Automatic Retry with `Retry-After` Backoff** in `apps/web/lib/api-client.ts` (`uploadDicomSeriesWithProgress`) so transient rate-limit throttling pauses and resumes the current slice rather than aborting the entire series.
