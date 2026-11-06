# DICOM preprocessing and split handoff

**RADAR AI / RDA-2 — Sprint 1**  
**Prepared:** 2026-10-26 (WIB)  
**Status:** Implementation and synthetic-fixture tests included; authorized source-data run pending  
**Scope:** Research prototype only — **NOT FOR CLINICAL USE**

## Implementation

`apps/api/src/radar_api/dicom_preprocessing.py` provides:

- `decode_and_window`: deterministic pydicom decoding for one single-frame image, `RescaleSlope`/`RescaleIntercept`, the DICOM linear VOI window, MONOCHROME1 inversion, and contiguous float32 output in `[0, 1]`. It checks the file-size and pixel-count limits before loading pixel data. The defaults are a 512 MiB file cap, 16,777,216 pixels, and center 40 / width 80. Record any window override alongside model configuration.
- `build_split_manifest`: deterministic HMAC-SHA256 grouping on patient ID, with studies kept together and conflicts rejected. A patient identifier is mandatory; the splitter fails closed instead of silently treating studies as different patients. It requires a private key of at least 32 bytes. Keep that key stable and private to reproduce a split.
- `iter_dicom_batches`: lazy image decode with no cross-batch image cache. Its conservative estimate reserves 32 bytes per pixel for temporary decode and stack buffers and enforces a caller-configured ceiling no greater than 12 GiB. The default budget is 2 GiB. The caller remains responsible for setting a pixel limit appropriate to the authorized source.

The generated split manifest uses schema `radar-ai.split-manifest/v1` and `manifest_version: 1`. Each assignment contains only HMAC pseudonyms for patient and study identifiers plus the split name. It still represents sensitive linkage data: write it and store its HMAC key only in approved private storage, outside Git, PRs, and shared artifacts. The checked-in code and this schema/handoff document are the versioned artifact; no generated assignment manifest is checked in because the authorized DICOM/labels source and approved private storage are not available in this workspace.

Example invocation from `apps/api` after authorized data access:

```python
import os
from pathlib import Path

from radar_api.dicom_preprocessing import SplitRecord, build_split_manifest, write_split_manifest

key = bytes.fromhex(os.environ["RADAR_SPLIT_HMAC_KEY_HEX"])
manifest = build_split_manifest(records, key=key, seed="radar-rda2-2026-v1")
write_split_manifest(manifest, Path(os.environ["RADAR_PRIVATE_DATA_DIR"]) / "splits-v1.json")
```

`records` must cover every slice with its source patient ID and `StudyInstanceUID`; each study must map to one patient. Do not add those source identifiers, DICOM headers, images, labels, or the generated private manifest to the repository. Keep the source fingerprint and exact private-data version in the approved internal data record.

## Validation and remaining handoff

Tests construct synthetic DICOM files and cover fixed rescale/window output, MONOCHROME1 handling, invalid inputs, stable patient grouping, identifier-free manifest entries, batch memory budgeting, and the 12 GiB ceiling. No RSNA data are present, so local label counts, actual patient/study split distribution, codec compatibility with the authorized source copy, and end-to-end source profiling remain to be run by the dependent ingestion/modeling workstream.

The receiver should use the split's study assignments when building train/validation/test image examples and must not recompute per-slice assignments independently. Preserve this handoff with the RDA-2 implementation and link the review artifact/PR when available. Dataset access and scope remain subject to [the RSNA licensing and profile assessment](./rsna-ich-licensing-and-profile.md).

