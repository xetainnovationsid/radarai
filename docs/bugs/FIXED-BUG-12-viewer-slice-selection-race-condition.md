# BUG-12: Race Condition in `StudyViewerClient` Initial Slice Selection vs Async `fetchModelScores`

**Severity:** P3 (Low)  
**Component:** `apps/web/components/StudyViewerClient.tsx`  
**Found in:** Sprint 2 Hardening Audit  
**Status:** Resolved (RDA-4 Sprint 2)  
**Type:** Async State Race Condition / UI Scrubbing Jitter  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/web/components/StudyViewerClient.tsx`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/components/StudyViewerClient.tsx), the study is loaded and the initial slice index is set:

```typescript
// Lines 274:
setIndex(resolveInitialSliceIndex(value, resolvedAnalysis));

// Lines 281-290:
void fetchModelScores(safeStudyId)
  .then((scores) => {
    setModelScores(scores);
    if (!resolvedAnalysis?.findings.length && scores.slices.length > 0) {
      const best = scores.slices.reduce((a, b) =>
        b.class_1_score > a.class_1_score ? b : a
      );
      setIndex((current) => (current === 0 ? best.index : current));
    }
  })
```

### Root Cause
1. `setIndex(resolveInitialSliceIndex(...))` runs when the study metadata arrives.
2. `fetchModelScores` is asynchronous and may resolve several hundred milliseconds later over slower network connections.
3. The guard `setIndex((current) => (current === 0 ? best.index : current))` assumes that if `current === 0`, the user hasn't touched the slice slider yet.
4. However, if a researcher begins actively scrubbing slices (e.g. scrolls from slice #5 to slice #0, or stays on slice #0 intentionally to observe cranial vertex anatomy) right when `fetchModelScores` finishes resolving, the condition `current === 0` evaluates to `true`.
5. This abruptly teleports the viewer from slice #0 to `best.index` (e.g. slice #28), interrupting the user's manual navigation and causing a jarring visual jump.

---

## 2. Reproduction Steps

1. Throttle network speed to "Slow 3G" or add an artificial 500 ms delay to `GET /v1/studies/{id}/scores`.
2. Open a study page `/studies/{study_id}` that has model scores but 0 findings.
3. Rapidly scrub the slice slider or press `←` until the active slice is `0`.
4. Wait for the `fetchModelScores` network request to complete.
5. Observe: The viewer suddenly jumps from slice `0` to the highest score slice index (e.g. slice `24`), overriding the user's current scrub position.

---

## 3. Impact Analysis

- **User Navigation Friction**: Researchers experience unexpected slice snapping while examining cranial vertex slices (index 0).
- **Perceived UI Glitch**: The viewer appears jittery or unresponsive to deliberate slice positioning.

---

## 4. Recommended Remediation

Track whether the user has performed manual interaction using a `userInteractedRef = useRef(false)` flag, or perform the candidate slice jump only inside a single synchronized loading sequence:

```typescript
const userInteractedRef = useRef(false);

// In slice navigation handlers:
const handleSliceChange = (nextIndex: number) => {
  userInteractedRef.current = true;
  setIndex(nextIndex);
};

// In fetchModelScores callback:
if (!resolvedAnalysis?.findings.length && scores.slices.length > 0) {
  const best = scores.slices.reduce((a, b) =>
    b.class_1_score > a.class_1_score ? b : a
  );
  if (!userInteractedRef.current) {
    setIndex(best.index);
  }
}
```

---

## 5. Resolution Verification (RDA-4)

Implemented in `apps/web/components/StudyViewerClient.tsx`:
- Added `userInteractedRef = useRef(false)`.
- Set `userInteractedRef.current = true` on `selectSlice()` and Left/Right keyboard navigation.
- Evaluated `!userInteractedRef.current` inside the `fetchModelScores` promise callback before overriding slice index.
- Verified in automated test suite `apps/web/scripts/verify-dicom-fixture.mjs`.


