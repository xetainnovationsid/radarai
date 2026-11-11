# BUG-22: Failing Backend `pytest` Suite (`DetachedInstanceError` on Deferred `dicom_data` & Missing Form Fields in Security Tests) and 21 `ruff` CI Errors

**Severity:** P1 (High)  
**Component:** `apps/api/tests/test_security.py`, `apps/api/tests/test_studies.py`, `apps/api/src/radar_api/models.py`, & `apps/api/src/radar_api/main.py`  
**Found in:** Post-Sprint 2 Codebase Audit (2026-11-11)  
**Status:** Open / Fix Available  
**Type:** Test Suite Failure / SQLAlchemy Deferred Loading / CI Quality Gate Regression  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

Running the backend quality checks documented in `README.md` (`python -m pytest` and `python -m ruff check .`) currently fails with **2 failing unit tests** and **21 linter errors**:

### Root Cause 1: `DetachedInstanceError` on Deferred `ImageAssetRecord.dicom_data` (`test_studies.py:234`)
In [`apps/api/src/radar_api/models.py`](../../apps/api/src/radar_api/models.py) (lines 90–92), `dicom_data` is configured as a deferred column:
```python
dicom_data: Mapped[bytes | None] = mapped_column(
    LargeBinary, nullable=True, deferred=True
)
```
In [`apps/api/tests/test_studies.py`](../../apps/api/tests/test_studies.py) (lines 231–234):
```python
with TestSession() as session:
    assets = list(session.scalars(select(ImageAssetRecord)).all())
assert len(assets) == 2
assert {asset.dicom_data for asset in assets} == {first, second}
```
Because `select(ImageAssetRecord)` does not include `.options(undefer(ImageAssetRecord.dicom_data))`, `dicom_data` is not loaded while `session` is open. Accessing `asset.dicom_data` on line 234 after the `with TestSession() as session:` block exits attempts a lazy load on a detached instance and crashes with:
```text
sqlalchemy.orm.exc.DetachedInstanceError: Parent instance <ImageAssetRecord> is not bound to a Session; deferred load operation of attribute 'dicom_data' cannot proceed
```
Additionally, in [`apps/api/src/radar_api/main.py`](../../apps/api/src/radar_api/main.py):
- `get_slice_dicom` (line 973) and `get_slice_preview` (line 1011) query `StudySliceRecord` with `.options(selectinload(StudySliceRecord.image_asset))` **without `.undefer(ImageAssetRecord.dicom_data)`**, causing an extra synchronous lazy-load SQL query every time `record.image_asset.dicom_data` is accessed.
- Conversely, `get_study_model_scores` (line 598) and `get_study_localizations` (line 763) eagerly load `selectinload(StudySliceRecord.image_asset)` even though neither endpoint ever accesses `image_asset`.

### Root Cause 2: Missing `Form(...)` Fields in `test_security.py:324-356`
In [`apps/api/tests/test_security.py`](../../apps/api/tests/test_security.py) (lines 324–356), `test_upload_blocks_executable_magic_bytes_and_forbidden_dicom_annotations` sends `POST /v1/studies/{study_id}/dicom` with `files=...` only, omitting the newly required `data={"index": "0", "total_files": "1", "finalize": "true"}` form fields.
FastAPI rejects the request during form parameter validation before `upload_dicom_series` even executes, returning a `list` of Pydantic validation errors in `response.json()["detail"]` and crashing the test with:
```text
AttributeError: 'list' object has no attribute 'lower'
```
Worse, this means the security test is no longer testing executable magic-byte blocking, forbidden MIME types, burned-in annotations, or overlay plane rejection!

### Root Cause 3: 21 `ruff check` Linter Violations Across `apps/api`
Running `python -m ruff check apps/api` fails with 21 errors (`I001` unsorted imports and `E501` line length > 100 characters) across:
- `apps/api/migrations/versions/20261111_0005_persistent_dicom_uploads.py`
- `apps/api/migrations/versions/20261111_0006_worker_job_leases.py`
- `apps/api/migrations/versions/20261111_0007_persisted_samihs_localizations.py`
- `apps/api/scripts/check_deepseek_model_access.py`
- `apps/api/scripts/train_ct_binary.py`
- `apps/api/src/radar_api/main.py`
- `apps/api/src/radar_api/models.py`
- `apps/api/src/radar_api/report_service.py`
- `apps/api/src/radar_api/worker_bridge.py`
- `apps/api/tests/test_studies.py`

---

## 2. Reproduction Steps

```bash
PYTHONPATH=apps/api/src python3 -m pytest apps/api/tests
python3 -m ruff check apps/api
```

---

## 3. Impact Analysis

- **CI Pipeline Failure**: Both `pytest` and `ruff check` fail on `main`, blocking pull request merges under branch protection rules.
- **Unverified Security Controls**: `test_upload_blocks_executable_magic_bytes_and_forbidden_dicom_annotations` fails at FastAPI parameter parsing before exercising any security validation logic.
- **Extra Database Round-Trips**: Every CT slice preview (`/image`) and DICOM download (`/dicom`) executes an unnecessary lazy-load query for `dicom_data`.

---

## 4. Recommended Remediation

1. **In `apps/api/tests/test_security.py`**: Include `data={"index": "0", "total_files": "1", "finalize": "true"}` in all four `client.post(f"/v1/studies/{study_id}/dicom", ...)` calls in `test_upload_blocks_executable_magic_bytes_and_forbidden_dicom_annotations`.
2. **In `apps/api/tests/test_studies.py`**: Use `select(ImageAssetRecord).options(undefer(ImageAssetRecord.dicom_data))` (or evaluate `{asset.dicom_data for asset in assets}` inside the `with TestSession() as session:` context).
3. **In `apps/api/src/radar_api/main.py`**: Add `.undefer(ImageAssetRecord.dicom_data)` to `get_slice_dicom` and `get_slice_preview`, and remove the unused `.selectinload(StudySliceRecord.image_asset)` from `get_study_model_scores` and `get_study_localizations`.
4. **Format Imports and Line Lengths**: Run `python -m ruff check --fix apps/api` and wrap lines exceeding 100 characters.
