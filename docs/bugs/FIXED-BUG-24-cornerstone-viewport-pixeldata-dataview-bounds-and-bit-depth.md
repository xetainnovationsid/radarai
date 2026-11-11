# BUG-24: `CornerstoneViewport` Unchecked `DataView` Bounds, Hardcoded 16-Bit Little-Endian Assumption, and High-Bit Overlay Contamination in HU Decoder

**Severity:** P2 (Medium)  
**Component:** `apps/web/components/CornerstoneViewport.tsx`  
**Found in:** Post-Sprint 2 Codebase Audit (2026-11-11)  
**Status:** Open / Fix Available  
**Type:** Client-Side DICOM Decoding / Voxel HU Accuracy / RangeError Crash  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/web/components/CornerstoneViewport.tsx`](../../apps/web/components/CornerstoneViewport.tsx) (lines 118–138), `parseDicomFromImageId()` decodes the raw DICOM `PixelData` (`7FE0,0010`) element into a `huData: Int16Array` buffer for interactive Hounsfield Unit (HU) probing and 2D window/level LUT rendering:

```typescript
// Lines 118-138 in apps/web/components/CornerstoneViewport.tsx:
const pixelElement = dataSet.elements.x7fe00010;
if (!pixelElement) {
  throw new Error(`DICOM dataset ${url} is missing PixelData (7FE0,0010)`);
}

const pixelRepresentation = dataSet.uint16("x00280103") ?? 0;
const totalPixels = rows * columns;
const huData = new Int16Array(totalPixels);
const pixelView = new DataView(
  byteArray.buffer,
  byteArray.byteOffset + pixelElement.dataOffset,
  pixelElement.length
);

for (let i = 0; i < totalPixels; i++) {
  const stored =
    pixelRepresentation === 1
      ? pixelView.getInt16(i * 2, true)
      : pixelView.getUint16(i * 2, true);
  huData[i] = Math.round(stored * rescaleSlope + rescaleIntercept);
}
```

### Root Cause
1. **Unchecked `DataView` Byte Length & Encapsulated/8-Bit Crash (`RangeError`)**:
   - The loop unconditionally reads `totalPixels * 2` bytes (`i * 2`) assuming uncompressed 16-bit (`BitsAllocated = 16`) pixel data.
   - If a valid CT DICOM slice uses `BitsAllocated = 8` (`1 byte/pixel`), a compressed transfer syntax (e.g., JPEG Lossless `1.2.840.10008.1.2.4.70` where `pixelElement.length` is smaller than `rows * columns * 2` or `hadUndefinedLength` is true), `pixelView.getUint16(i * 2, true)` throws an uncaught `RangeError: Offset is outside the bounds of the DataView`.
2. **Missing `BitsStored` (`0028,0101`) Masking & Two's-Complement Sign Extension**:
   - Clinical CT scanners frequently encode 12-bit (`BitsStored = 12`, `HighBit = 11`) or 14-bit (`BitsStored = 14`, `HighBit = 13`) samples inside a 16-bit (`BitsAllocated = 16`) word.
   - According to DICOM PS3.5 Section 8.1.1, unused high bits above `HighBit` may contain non-zero legacy overlay bits, and signed values (`PixelRepresentation = 1`) have their sign bit at `HighBit` (e.g., bit 11), not bit 15.
   - Reading `getUint16` / `getInt16` without masking to `BitsStored` and sign-extending from `HighBit` causes pixels with high-bit flags or negative 12-bit two's-complement values to jump by $+4096$ to $+32768$ HU, corrupting both the rendered canvas and the interactive HU hover probe.
3. **Hardcoded `MONOCHROME2` and Axial Identity Cosines in `customMetadataStore`**:
   - Lines 174 and 186 hardcode `imageOrientationPatient: [1, 0, 0, 0, 1, 0]` and `photometricInterpretation: "MONOCHROME2"`, ignoring `MONOCHROME1` inversion (which the backend preview endpoint at `main.py:1039` handles) and non-square `columns × rows` aspect ratios on the fixed `340×340` canvas container (lines 494–495).

---

## 2. Reproduction Steps

1. Upload a valid CT DICOM slice where `BitsAllocated = 8` or where a compressed transfer syntax has `pixelElement.length < rows * columns * 2`.
2. Open the study in Cornerstone3D mode (`/studies/{id}`).
3. Observe `RangeError: Offset is outside the bounds of the DataView` in the viewport.

---

## 3. Impact Analysis

- **Viewport Crash on Compressed or 8-Bit DICOMs**: Fails with a raw JavaScript `RangeError` instead of a descriptive message or fallback to the API PNG preview.
- **Inaccurate HU Probe Readings on 12-Bit Signed CT Slices**: Negative or high-bit-flagged 12-bit CT voxels display corrupted Hounsfield Unit values.

---

## 4. Recommended Remediation

Validate `bitsAllocated`, `bitsStored`, `highBit`, and `pixelElement.length` before reading `DataView`, and apply proper bit-masking and sign extension:

```typescript
const bitsAllocated = dataSet.uint16("x00280100") ?? 16;
const bitsStored = dataSet.uint16("x00280101") ?? bitsAllocated;
const bytesPerPixel = bitsAllocated / 8;
if (
  (bitsAllocated !== 8 && bitsAllocated !== 16) ||
  pixelElement.length < totalPixels * bytesPerPixel
) {
  throw new Error(
    "Compressed or unsupported PixelData format in browser decoder; switch to API PNG mode."
  );
}

const bitMask = bitsStored < 16 ? (1 << bitsStored) - 1 : 0xffff;
const signBit = 1 << (bitsStored - 1);

for (let i = 0; i < totalPixels; i++) {
  let raw =
    bitsAllocated === 8
      ? pixelView.getUint8(i)
      : pixelView.getUint16(i * 2, true);
  raw &= bitMask;
  if (pixelRepresentation === 1 && (raw & signBit) !== 0) {
    raw -= 1 << bitsStored;
  }
  huData[i] = Math.round(raw * rescaleSlope + rescaleIntercept);
}
```
