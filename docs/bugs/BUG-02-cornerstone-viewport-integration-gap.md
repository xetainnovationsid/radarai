# BUG-02: Orphaned `CornerstoneViewport` & Documentation Drift

**Severity:** P2 (Medium)  
**Component:** `apps/web/components/CornerstoneViewport.tsx` & `apps/web/components/StudyViewerClient.tsx`  
**Found in:** Sprint 2 Audit  
**Type:** Architectural Drift / Unused Component

---

## 1. Description

[`docs/dicom-viewer-integration.md`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/docs/dicom-viewer-integration.md) states:

> *1. Dynamic Client Import (`ssr: false`):*
> *`StudyViewerClient.tsx` dynamically imports `CornerstoneViewport.tsx` with `next/dynamic(..., { ssr: false })`.*
> *The viewer renders local, de-identified Part 10 DICOM axial brain CT studies... provides interactive Hounsfield Unit (HU) voxel probing, and applies diagnostic CT windowing presets (Brain W:80 L:40, Subdural W:200 L:80, Bone W:2000 L:500).*

In reality:
- [`apps/web/components/CornerstoneViewport.tsx`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/components/CornerstoneViewport.tsx) was implemented with full Cornerstone3D WebGL2 stack rendering, custom metadata providers, and 2D canvas HU probing, but **is never imported anywhere in `apps/web`**.
- [`apps/web/components/StudyViewerClient.tsx`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/components/StudyViewerClient.tsx) instead renders a static `<img>` tag loading pre-windowed PNG images from `/v1/studies/{id}/slices/{slice_id}/image`.

---

## 2. Impact Analysis

- **Feature Loss**: Interactive Hounsfield Unit probing (`(x, y) -> HU`) and CT window presets (Subdural, Bone) are inaccessible to researchers in the UI.
- **Bundle Bloat**: `@cornerstonejs/core` and `dicom-parser` remain installed and bundled in dependencies without being mounted in the main viewer path.
- **Specification Mismatch**: Divergence between project architecture documentation and running frontend code.

---

## 3. Recommended Remediation

Option A (Full Integration):
- Import `CornerstoneViewport` via `next/dynamic` inside `StudyViewerClient.tsx` when viewing local synthetic DICOM fixtures or when raw `.dcm` files are streamed.
- Add window preset selector dropdown (Brain, Subdural, Bone) to the viewer UI.

Option B (Documentation Alignment):
- If the project intentionally uses backend PNG rendering (`/v1/studies/{id}/slices/{slice_id}/image`) to simplify deployment and client CPU/GPU usage, update `docs/dicom-viewer-integration.md` to reflect that `CornerstoneViewport` is an experimental secondary renderer.

