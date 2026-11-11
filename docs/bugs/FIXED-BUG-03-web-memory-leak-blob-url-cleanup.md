# BUG-03: Object URL Memory Leak During Rapid CT Slice Scrubbing

**Severity:** P2 (Medium)  
**Component:** `apps/web/components/StudyViewerClient.tsx`  
**Found in:** Sprint 2 Audit  
**Type:** Client Memory Leak / Resource Retention

---

## 1. Description

In [`apps/web/components/StudyViewerClient.tsx`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/components/StudyViewerClient.tsx), slice preview images are fetched as binary blobs using authenticated API calls:

```typescript
useEffect(() => {
  if (!slice || !user) return;
  const targetSliceId = slice.slice_id;
  const controller = new AbortController();
  let createdObjectUrl = "";

  fetchAuthenticatedImageBlobUrl(studyId, targetSliceId, controller.signal)
    .then((objectUrl) => {
      createdObjectUrl = objectUrl;
      setBlobImage({ sliceId: targetSliceId, url: objectUrl });
    })
    .catch(() => {
      if (!controller.signal.aborted) {
        setBlobImage(null);
      }
    });

  return () => {
    controller.abort();
    if (createdObjectUrl) {
      URL.revokeObjectURL(createdObjectUrl);
    }
  };
}, [slice, studyId, user]);
```

### The Race Condition:
1. The user drags the slice range scrubber across 30 slices in 2 seconds.
2. For each intermediate slice, a `useEffect` mounts and unmounts rapidly.
3. When the cleanup function executes on unmount, `createdObjectUrl` is still `""` because the asynchronous network fetch has not settled yet.
4. When `fetchAuthenticatedImageBlobUrl` eventually completes, `URL.createObjectURL(blob)` has already allocated a new blob URL reference in browser memory.
5. Because the cleanup function already ran, `URL.revokeObjectURL(objectUrl)` is **never called** for that URL.
6. As a result, dozens to hundreds of image blobs remain pinned in browser memory until the page is reloaded.

---

## 2. Impact Analysis

- **Memory Consumption**: High-resolution CT images (up to hundreds of slices per volume) accumulate in heap memory.
- **Client Degradation**: Can cause browser tab tab-freezing or out-of-memory crashes on low-spec client workstations.

---

## 3. Recommended Fix

Track active URLs and revoke inside `.then()` if the effect has already been aborted or cleaned up:

```typescript
useEffect(() => {
  if (!slice || !user) return;
  const targetSliceId = slice.slice_id;
  const controller = new AbortController();
  let isCancelled = false;
  let activeUrl: string | null = null;

  fetchAuthenticatedImageBlobUrl(studyId, targetSliceId, controller.signal)
    .then((objectUrl) => {
      if (isCancelled) {
        URL.revokeObjectURL(objectUrl);
        return;
      }
      activeUrl = objectUrl;
      setBlobImage({ sliceId: targetSliceId, url: objectUrl });
    })
    .catch(() => {
      if (!controller.signal.aborted) {
        setBlobImage(null);
      }
    });

  return () => {
    isCancelled = true;
    controller.abort();
    if (activeUrl) {
      URL.revokeObjectURL(activeUrl);
    }
  };
}, [slice, studyId, user]);
```

