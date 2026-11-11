# FIXED-BUG-26: CornerstoneViewport Missing Optional Chaining & SAMIHS Localization Semantics

**Severity:** P2 (Medium)  
**Component:** `apps/web/components/CornerstoneViewport.tsx`, `StudyViewerClient.tsx`, & `apps/api/src/radar_api/main.py`  
**Found in:** Full Quality Assurance & Crosscheck Audit  
**Status:** Resolved & Verified  
**Type:** Runtime Exception Guard & REST Semantics  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

### 1.1 CornerstoneViewport Runtime TypeError
In [`apps/web/components/CornerstoneViewport.tsx`](../../apps/web/components/CornerstoneViewport.tsx) (line 870):
```tsx
// Before:
{parsedSlice?.deidentificationMethod.includes("SYNTHETIC")
  ? "SYNTHETIC ANONYMIZED FIXTURE • NOT FOR CLINICAL USE"
  : "ANONYMIZED RESEARCH CT • NOT FOR CLINICAL USE"}
```
When a DICOM study was initially opening or during slice index transitions before `parsedSlice` completed parsing (or if `deidentificationMethod` is absent on raw hospital DICOMs), `parsedSlice?.deidentificationMethod` evaluates to `undefined`. Without optional chaining on `.includes()`, JavaScript evaluated `(undefined).includes(...)`, throwing:
`Uncaught TypeError: Cannot read properties of undefined (reading 'includes')`
causing the viewer HUD overlay to crash.

### 1.2 SAMIHS Localization HTTP 503 Console Noise
In [`apps/api/src/radar_api/main.py`](../../apps/api/src/radar_api/main.py) (lines 798–802):
When a study did not have localization masks generated (e.g. before background worker completion or when SAM-IHS was disabled), the backend returned `HTTP 503 Service Unavailable`.
In browsers, HTTP 503 is flagged as a fatal server failure in DevTools console, and frontend [`StudyViewerClient.tsx`](../../apps/web/components/StudyViewerClient.tsx) treated it as a hard failure banner rather than a pending/optional state.

---

## 2. Remediation & Verification

1. **Safe Navigation in Viewport HUD**:
   Added optional chaining in `CornerstoneViewport.tsx`:
   ```tsx
   {parsedSlice?.deidentificationMethod?.includes("SYNTHETIC")
     ? "SYNTHETIC ANONYMIZED FIXTURE • NOT FOR CLINICAL USE"
     : "ANONYMIZED RESEARCH CT • NOT FOR CLINICAL USE"}
   ```
   and removed unused import `cache`.

2. **Semantic HTTP 404 for Optional Localization**:
   In `main.py`, changed the missing localization record response status code to `HTTP 404 Not Found` (`detail="SAMIHS results are unavailable until localization completes."`).

3. **Graceful Degradation in Web Client**:
   Updated `fetchStudyLocalizations` in `StudyViewerClient.tsx` to return `null` without throwing when HTTP 404 or 503 is returned, eliminating unhandled red console errors while preserving the non-fatal UI status.

4. **Automated Verification**:
   - `ruff check apps/api`: All checks passed.
   - `pytest apps/api/tests`: 42 passed in 1.44s.
   - `npm --prefix apps/web run typecheck`: Passed (0 errors).
   - `npm --prefix apps/web test`: All fixture checks passed.
   - `npm --prefix apps/web run build`: Succeeded.
