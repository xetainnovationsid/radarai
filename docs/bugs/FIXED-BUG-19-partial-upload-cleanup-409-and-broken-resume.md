# BUG-19: Unfinalized Multi-Slice Upload Failure Triggers `HTTP 409` on Cleanup, Leaks Orphaned `ImageAssetRecord` Rows, and Fails to Resume on Retry

**Severity:** P1 (High)  
**Component:** `apps/web/app/page.tsx`, `apps/web/lib/api-client.ts`, `apps/api/src/radar_api/main.py`, & `apps/api/src/radar_api/models.py`  
**Found in:** Post-Sprint 2 Codebase Audit (2026-11-11)  
**Status:** Open / Fix Available  
**Type:** State Management / Orphaned Database Records / Broken Retry Flow  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

When uploading a multi-slice DICOM series, the frontend ([`apps/web/app/page.tsx`](../../apps/web/app/page.tsx)) creates a study via `POST /v1/studies` and then uploads slices sequentially (`index = 0 .. N-1`) via `uploadDicomSeriesWithProgress`.

If an error or cancellation occurs after at least one slice has been uploaded (for example, on slice `index = 1`), three cascading defects occur across the frontend and backend:

### Root Cause

#### A. Cleanup `DELETE /v1/studies/{study_id}` Always Fails with `HTTP 409 Conflict`
In [`apps/web/app/page.tsx`](../../apps/web/app/page.tsx) (lines 343–348), the `catch` handler attempts to clean up the partially uploaded study:
```typescript
} catch (cause) {
  if (createdStudyId) {
    await apiFetch(`/v1/studies/${createdStudyId}`, {
      method: "DELETE",
    }).catch(() => undefined);
  }
```
However, in [`apps/api/src/radar_api/main.py`](../../apps/api/src/radar_api/main.py) (lines 323–347), `delete_empty_study` rejects deletion whenever `study.slices` is non-empty—even when the study is still in `status == "uploaded"` (unfinalized):
```python
if study.slices:
    raise HTTPException(
        status_code=409,
        detail="A study with uploaded slices cannot be deleted",
    )
```
Because each slice is committed to the database in its own request, any failure on slice `index >= 1` causes `DELETE /v1/studies/{study_id}` to fail with `HTTP 409`, leaving the incomplete study permanently in the user's Study Library.

#### B. "Try Again" Creates a Duplicate Study Instead of Resuming the Partial Study
In [`apps/web/lib/api-client.ts`](../../apps/web/lib/api-client.ts) (line 420), the network error message promises resumable uploads:
> `"Koneksi terputus saat mengunggah irisan ${index + 1} dari ${files.length}. Coba ulang; irisan yang sudah tersimpan akan dilanjutkan dengan aman."`

And the backend (`main.py:1118-1123`) explicitly implements idempotent slice deduplication for resumed uploads on the same `study_id`. **However**, `createdStudyId` in `apps/web/app/page.tsx:263` is a local variable inside `executeUpload()` that is discarded on error. Clicking **Try again** (`page.tsx:567`) calls `executeUpload(selectedFiles)` which executes `POST /v1/studies` again, creating a brand-new `StudyRecord` and abandoning the partial study forever. The abandoned study can neither run inference (`HTTP 409: Finish and finalize the CT series upload before requesting inference`) nor be deleted (`HTTP 409: A study with uploaded slices cannot be deleted`).

#### C. Foreign Key Direction Prevents `ImageAssetRecord` Cleanup
In [`apps/api/src/radar_api/models.py`](../../apps/api/src/radar_api/models.py) (lines 69–73):
```python
image_asset_id: Mapped[UUID] = mapped_column(
    Uuid(as_uuid=True),
    ForeignKey("image_assets.image_asset_id", ondelete="CASCADE"),
    nullable=False,
)
```
Because `study_slices` references `image_assets` (and not vice-versa), deleting a `StudyRecord` cascades to `study_slices`, but **never deletes the parent `ImageAssetRecord` rows** (which store multi-megabyte `dicom_data` `LargeBinary` blobs in Postgres/SQLite).

---

## 2. Reproduction Steps

1. In the web app (`/`), select 5 DICOM slices where slice 1 is valid CT and slice 2 is invalid (or disconnect network / cancel upload after slice 1 finishes).
2. Observe that `DELETE /v1/studies/{id}` returns `HTTP 409 Conflict` in the Network tab.
3. Refresh the Study Library: an incomplete study with `1 slices` and status `Uploaded` (`uploaded`) is stuck in the list.
4. Open that study in `/studies/{id}`: inference fails with `HTTP 409: Finish and finalize the CT series upload before requesting inference`.
5. Click **Try again** on the upload panel: a *second* study is created instead of resuming the first study.

---

## 3. Impact Analysis

- **Permanent Zombie Studies in User Workspace**: Any interrupted multi-slice upload leaves an unusable, undeletable study in the researcher's queue.
- **Database Storage Bloat**: Even if unfinalized studies are deleted, `image_assets` rows and their `dicom_data` binary blobs remain orphaned in the database.
- **Misleading User Recovery Copy**: The UI promises safe upload continuation on retry, but actually restarts from scratch under a new `study_id`.

---

## 4. Recommended Remediation

1. **Allow Deleting Unfinalized (`status == "uploaded"`) Studies and Clean Up `ImageAssetRecord` Rows** in `apps/api/src/radar_api/main.py`:
```python
@app.delete("/v1/studies/{study_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["studies"])
def delete_empty_study(
    study_id: UUID,
    session: Session = Depends(get_session),
    _principal: Principal = Depends(require_authenticated_principal),
    _owner: Principal = Depends(require_owned_study),
) -> Response:
    study = session.scalar(
        select(StudyRecord)
        .where(StudyRecord.study_id == study_id)
        .options(selectinload(StudyRecord.slices))
        .with_for_update()
    )
    if study is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if study.status == "ready" and study.slices:
        raise HTTPException(
            status_code=409,
            detail="A finalized study with uploaded slices cannot be deleted",
        )
    asset_ids = [item.image_asset_id for item in study.slices]
    session.delete(study)
    session.flush()
    if asset_ids:
        for asset in session.scalars(
            select(ImageAssetRecord).where(ImageAssetRecord.image_asset_id.in_(asset_ids))
        ):
            session.delete(asset)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```
2. **Persist `resumableStudyId` in `DashboardPage` (`apps/web/app/page.tsx`)** when a network or rate-limit failure occurs so clicking **Try again** reuses the existing `study_id`, and only call `DELETE /v1/studies/{id}` when the user clicks **Cancel** or **Reset selection** (or when a non-recoverable DICOM validation error occurs).
