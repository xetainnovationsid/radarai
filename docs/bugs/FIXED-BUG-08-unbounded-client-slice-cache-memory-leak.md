# BUG-08: Unbounded Client-Side Memory Growth in `CornerstoneViewport` (`parsedSliceCache` & `customMetadataStore`)

**Severity:** P2 (Medium)  
**Component:** `apps/web/components/CornerstoneViewport.tsx`  
**Found in:** Sprint 2 Hardening Audit  
**Type:** Client-Side Memory Leak / Unbounded Cache Retention  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/web/components/CornerstoneViewport.tsx`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/components/CornerstoneViewport.tsx), parsed DICOM slice pixel arrays and metadata records are cached globally at module scope:

```typescript
// Lines 71-72 of CornerstoneViewport.tsx:
const parsedSliceCache = new Map<string, ParsedDicomSlice>();
const customMetadataStore = new Map<string, Record<string, unknown>>();
```

Inside `parseDicomFromImageId(imageId: string)`:
```typescript
const totalPixels = rows * columns;
const huData = new Int16Array(totalPixels);
// ...
parsedSliceCache.set(imageId, parsed);
customMetadataStore.set(imageId, { ... });
```

### Root Cause
Both `parsedSliceCache` and `customMetadataStore` are standard JavaScript `Map` instances without eviction policies:
- No maximum size limit (`MAX_CACHE_SIZE`).
- No Least Recently Used (LRU) or Least Frequently Used (LFU) eviction mechanism.
- No lifecycle cleanup tied to study navigation or component unmount.

Each 512×512 16-bit CT slice retains an `Int16Array` of 262,144 elements (0.5 MB) plus associated object graph metadata (~0.1 MB). In a 64-slice series, one study occupies ~38 MB in memory. When a researcher browses 15–20 CT series in a single session, the browser tab retains 600 MB–1 GB of non-garbage-collected typed arrays, leading to browser tab memory inflation, severe garbage collector (GC) pauses, and eventual browser tab crashes on lower-memory workstations.

---

## 2. Reproduction Steps

1. Launch web application in Google Chrome / Brave / Edge.
2. Open Chrome DevTools -> **Memory** tab -> Take Heap Snapshot (Baseline: ~35 MB).
3. Navigate sequentially through 15 different CT studies or toggle repeatedly between series with dozens of slices.
4. Scrub through all slices in each study to populate `parsedSliceCache`.
5. Take a second Heap Snapshot.
6. Observe: Retained size of `Int16Array` objects and `customMetadataStore` entries grows linearly with every slice viewed and never drops after unmounting the viewer component.

---

## 3. Impact Analysis

- **Client Stability**: Protracted clinical review sessions lead to tab out-of-memory (`OOM`) crashes or sluggish canvas painting during slice scrubbing.
- **Mobile/Tablet Review**: Tablet devices (e.g. iPads or portable review stations) with constrained browser memory limits (1–2 GB heap ceilings) will crash prematurely.

---

## 4. Recommended Remediation

Replace the unbounded `Map` instances with a bounded LRU cache or explicit eviction queue:

```typescript
// Implement bounded LRU or max-capacity eviction:
const MAX_PARSED_SLICE_CACHE_SIZE = 64; // Retain at most 64 active slices in memory

function pruneSliceCache(): void {
  if (parsedSliceCache.size > MAX_PARSED_SLICE_CACHE_SIZE) {
    const oldestKey = parsedSliceCache.keys().next().value;
    if (oldestKey) {
      parsedSliceCache.delete(oldestKey);
      customMetadataStore.delete(oldestKey);
    }
  }
}
```

Alternatively, expose a cache purge callback (`clearSliceCache()`) invoked when `studyId` changes in `StudyViewerClient.tsx`.

