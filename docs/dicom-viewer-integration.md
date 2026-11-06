# RDA-4: Cornerstone3D DICOM Viewer & Synthetic Brain CT Fixture Integration

**Sprint:** 1 | **Epic:** RDA-4 | **Priority:** P0 | **Status:** Integrated & Verified  
**Scope:** Research prototype only — **NOT FOR CLINICAL USE**

---

## 1. Overview

This document defines the architecture, data governance compliance, and handoff specification for the **Cornerstone3D DICOM Viewer** integrated into the RADAR AI Next.js web application (`apps/web`).

The viewer renders local, de-identified Part 10 DICOM axial brain CT studies (`wadouri:/fixtures/dicom/brain-ct/slice-X.dcm`), supports bidirectional slice navigation (mouse wheel, accessible range scrubber, Prev/Next buttons, and direct slice jump controls), provides interactive Hounsfield Unit (HU) voxel probing, and applies diagnostic CT windowing presets (**Brain W:80 L:40**, **Subdural W:200 L:80**, **Bone W:2000 L:500**).

---

## 2. Architecture & Next.js SSR Boundary

Because `@cornerstonejs/core` and `@cornerstonejs/tools` rely on browser-specific WebGL2 contexts and DOM APIs, the viewer is architected with a strict client-only boundary:

1. **Dynamic Client Import (`ssr: false`)**:
   - [`StudyViewerClient.tsx`](../apps/web/components/StudyViewerClient.tsx) dynamically imports [`CornerstoneViewport.tsx`](../apps/web/components/CornerstoneViewport.tsx) with `next/dynamic(..., { ssr: false })`.
2. **Part 10 `wadouri:` Loader & Metadata Provider**:
   - `CornerstoneViewport.tsx` registers a `wadouri` loader with `@cornerstonejs/core` (`imageLoader.registerImageLoader`) backed by `dicom-parser`.
   - When a slice URL is requested, the binary `.dcm` Part 10 file is fetched over HTTP, parsed via `dicomParser.parseDicom`, calibrated to signed Hounsfield Units (`Int16Array`) using tags `(0028,1052) RescaleIntercept` and `(0028,1053) RescaleSlope`, and cached via `imageLoader.createAndCacheLocalImage`.
   - Cornerstone metadata modules (`imagePlaneModule`, `imagePixelModule`, `voiLutModule`, `modalityLutModule`, `generalSeriesModule`) are registered with `metaData.addProvider`.
3. **Dual-Layer Synchronized Rendering**:
   - `@cornerstonejs/core`'s `RenderingEngine` (`Enums.ViewportType.STACK`) manages the stack state and VOI LUT range (`utilities.windowLevel.toLowHighRange`).
   - A synchronized 2D HU LUT canvas renders exact Hounsfield Unit windowing and enables real-time cursor HU probing (`(x, y) -> HU`) even in headless or WebGL-restricted environments.

---

## 3. Synthetic Brain CT DICOM Fixture (`CT-2026-0101`)

To strictly honor [`docs/rsna-ich-licensing-and-profile.md`](./rsna-ich-licensing-and-profile.md) and ensure **zero real patient data** is committed or redistributed, the 5 axial DICOM slices in `apps/web/public/fixtures/dicom/brain-ct/` are deterministically synthesized by [`scripts/generate_dicom_fixture.py`](../scripts/generate_dicom_fixture.py).

### 3.1 De-identified DICOM Header Profile

| Tag | Keyword | Value |
| --- | --- | --- |
| `(0002,0010)` | `TransferSyntaxUID` | `1.2.840.10008.1.2.1` (Explicit VR Little Endian) |
| `(0008,0016)` | `SOPClassUID` | `1.2.840.10008.5.1.4.1.1.2` (CT Image Storage) |
| `(0008,0060)` | `Modality` | `CT` |
| `(0010,0010)` | `PatientName` | `ANONYMIZED^BRAIN^CT` |
| `(0010,0020)` | `PatientID` | `RADAR-CT-2026-0101` |
| `(0010,0030)` | `PatientBirthDate` | `""` (Empty) |
| `(0012,0062)` | `PatientIdentityRemoved` | `YES` |
| `(0012,0063)` | `DeidentificationMethod` | `SYNTHETIC_MATHEMATICAL_PHANTOM_NO_PATIENT_DATA` |
| `(0028,0010)` / `(0028,0011)` | `Rows` / `Columns` | `256` × `256` |
| `(0028,1050)` / `(0028,1051)` | `WindowCenter` / `WindowWidth` | `40` / `80` |
| `(0028,1052)` / `(0028,1053)` | `RescaleIntercept` / `RescaleSlope` | `-1024` / `1` |

### 3.2 Slice Stack & Calibrated Hounsfield Units

| Slice File | Index | Z-Pos (mm) | Cited Evidence | Basal Ganglia ROI HU | Anatomical Level |
| --- | ---: | ---: | :---: | ---: | --- |
| `slice-0.dcm` | `0` | `-15.0` | No | `+27 HU` | Skull base / posterior fossa |
| `slice-1.dcm` | `1` | `-10.0` | No | `+29 HU` | Mid-posterior fossa / petrous ridges |
| `slice-2.dcm` | `2` | `+1.5` | **Yes (★)** | **`+79 HU`** | Basal ganglia / lateral ventricles (simulated acute ICH core + edema halo) |
| `slice-3.dcm` | `3` | `+6.5` | **Yes (★)** | **`+78 HU`** | Superior basal ganglia / corona radiata (simulated ICH upper extent) |
| `slice-4.dcm` | `4` | `+11.5` | No | `+29 HU` | High frontoparietal convexity / centrum semiovale |

---

## 4. Handoff to Dependent Workstreams (Sprint 2 — RDA-4)

- **API & Model Inference Workstream (`RDA-18` & `RDA-2`)**:
  - `StudyAnalysisResponse.study.slices[].slice_id` maps 1:1 to the ordered `dicomImageIds` stack on the frontend.
  - When `findings[].evidence_slice_ids` cites a `slice_id`, [`StudyViewerClient.tsx`](../apps/web/components/StudyViewerClient.tsx) defaults to the first cited slice on load, badges the slice in the toolbar and quick-jump scrubber strip (`★`), and projects either the SAMIHS segmentation mask bounding box (`StudyLocalizations.slices[].box`) or the candidate ROI overlay when **Overlay Bukti AI** is active.
  - Clicking any cited slice button (`★ Irisan #3 (1.5 mm)`) on a finding card or in the slice pill strip immediately navigates the viewport to that slice index (`setIndex`).
  - Keyboard shortcuts (`ArrowLeft` / `ArrowRight`) and mouse-wheel scrubbing allow rapid slice traversal across the series.
- **Model Version & Non-Diagnostic Guardrails**:
  - The viewer displays `model_version` provenance (`provider`, `model_id`, `prompt_version`, `model_version_id`, checkpoint SHA-256, and compute device) in a dedicated metadata panel.
  - All prediction scores are accompanied by explicit non-diagnostic notices (`DisclaimerBanner`, `Skor model riset · belum terkalibrasi · BUKAN DIAGNOSIS`) and never imply clinical diagnosis.
- **Verification & Regeneration**:
  - Regenerate DICOM fixtures: `python3 scripts/generate_dicom_fixture.py`
  - Verify DICOM headers & HU calibration: `cd apps/web && npm test`
  - TypeScript & ESLint verification: `cd apps/web && npm run typecheck && npm run lint`
