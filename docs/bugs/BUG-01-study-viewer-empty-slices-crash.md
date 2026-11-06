# BUG-01: `StudyViewerClient` Runtime Crash on Empty Model Slices

**Severity:** P1 (High)  
**Component:** `apps/web/components/StudyViewerClient.tsx`  
**Found in:** Sprint 2 Audit  
**Type:** Uncaught Runtime Exception (`TypeError: Reduce of empty array with no initial value`)

---

## 1. Description

In [`apps/web/components/StudyViewerClient.tsx`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/components/StudyViewerClient.tsx), the candidate with the highest model score is computed across slice scores using `Array.prototype.reduce`:

```typescript
// Line 55:
const topCandidate = modelScores?.slices.reduce((best, current) =>
  current.class_1_score > best.class_1_score ? current : best
);

// Line 309:
const topSlice = modelScores.slices.reduce((best, current) =>
  current.class_1_score > best.class_1_score ? current : best
);

// Line 358:
const candidate = modelScores.slices.reduce((best, current) =>
  current.class_1_score > best.class_1_score ? current : best
);
```

When `modelScores` is returned from the API but contains an empty array (`slices: []`) — for example when a study was uploaded without slices or when a series filtering step yields 0 slices — calling `reduce` without an initial value throws an uncaught JavaScript runtime exception:

```text
TypeError: Reduce of empty array with no initial value
    at Array.reduce (<anonymous>)
    at StudyViewerClient (StudyViewerClient.tsx:55)
```

This crashes the entire React component tree and leaves the researcher with a broken blank screen or an unhandled React error boundary.

---

## 2. Reproduction Steps

1. Start API and Web servers.
2. Create an empty study without uploading slices: `POST /v1/studies`.
3. If an empty `StudyModelScores` payload is returned (`{ slices: [] }`), open `/studies/<study_id>`.
4. Observe immediate crash in browser console: `TypeError: Reduce of empty array with no initial value`.

---

## 3. Impact Analysis

- **User Experience**: Complete failure to render study view.
- **Reliability**: Any study with missing or filtered slice scores triggers a client crash.

---

## 4. Recommended Fix

Provide a fallback guard or pass `null` as initial accumulator:

```typescript
// Safe helper
const topCandidate = useMemo(() => {
  if (!modelScores?.slices || modelScores.slices.length === 0) return null;
  return modelScores.slices.reduce((best, current) =>
    current.class_1_score > best.class_1_score ? current : best
  );
}, [modelScores]);
```

Apply the same guard before lines 309 and 358:

```typescript
if (!modelScores.slices || modelScores.slices.length === 0) {
  return <p className="muted-copy">Tidak ada skor irisan tersedia.</p>;
}
```

