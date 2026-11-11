# BUG-11: Sub-Millimeter Floating-Point Slice Ordering Key Jitter in Multi-Slice DICOM Upload

**Severity:** P3 (Low)  
**Component:** `apps/api/src/radar_api/dicom_validation.py` & `apps/api/src/radar_api/main.py`  
**Found in:** Sprint 2 Hardening Audit  
**Type:** Numerical Precision / Floating-Point Non-Determinism  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/api/src/radar_api/dicom_validation.py`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/api/src/radar_api/dicom_validation.py), slice position along the patient imaging axis normal vector is computed via dot-product:

```python
# Lines 288-290 in dicom_validation.py:
position, normal, orientation = _position_and_normal(dataset)
slice_position = sum(value * axis for value, axis in zip(position, normal))
z_position_mm = position[2]
```

Later, in [`apps/api/src/radar_api/main.py`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/api/src/radar_api/main.py), slices are sorted along this key:

```python
# Lines 645-653 in main.py:
ordered = sorted(
    zip(staged, validated, strict=True),
    key=lambda item: (
        item[1].slice_position if item[1].slice_position is not None else float(
            item[1].instance_number or 0
        ),
        item[1].sop_instance_uid or item[0].sha256,
    ),
)
```

### Root Cause
1. In DICOM Part 10 files, `ImagePositionPatient` (0020,0032) and `ImageOrientationPatient` (0020,0037) are stored as ASCII Decimal String (`DS`) representations. Different scanner manufacturers (e.g. Siemens, GE Healthcare, Philips, Canon) format floating-point numbers with variable decimal precision (ranging from 4 up to 16 significant decimal figures).
2. The dot-product `sum(value * axis for ...)` computes a 64-bit IEEE-754 double precision float without rounding to a standardized spatial tolerance (e.g., 0.001 mm / 1 micron).
3. If two adjacent or overlapping reconstruction slices differ by microscopic numerical epsilon (e.g. $10^{-14}$ mm due to floating point representation differences such as `10.000000000000002` vs `9.999999999999998`), sort ordering becomes non-deterministic or fluctuates based on micro-jitter rather than actual physical slice spacing.
4. Furthermore, if a CT series was scanned in descending anatomical order (Craniocaudal vs Caudocranial) with flipped normal vectors, `slice_position` sorting without accounting for normal direction can invert the perceived cranial traversal in viewer UIs.

---

## 2. Reproduction Steps

1. Generate a test series where two consecutive slices have `ImagePositionPatient = [0, 0, 10.000000000000002]` and `[0, 0, 9.999999999999998]` created by separate scanner reconstruction kernels.
2. Upload the series to `POST /v1/studies/{id}/dicom`.
3. Compare the resulting slice indices against the scanner's expected `InstanceNumber`.
4. Observe micro-jitter in sorting order where a slice with an infinitesimally smaller float key precedes another despite identical nominal millimeter positions.

---

## 3. Impact Analysis

- **Slice Sorting Inconsistency**: Sub-millimeter slice ordering might transpose adjacent slices in ultra-high resolution (0.5 mm) bone-window CT series.
- **Cross-Scanner Reliability**: Inconsistencies appear when ingesting datasets exported from diverse PACS archives with disparate decimal string precisions.

---

## 4. Recommended Remediation

Round `slice_position` to 3 decimal places (1 micron precision) or prefer a composite key prioritizing `round(slice_position, 3)` before falling back to `instance_number`:

```python
# In dicom_validation.py:
raw_slice_position = sum(value * axis for value, axis in zip(position, normal))
slice_position = round(raw_slice_position, 3)
```

And in `main.py`:
```python
ordered = sorted(
    zip(staged, validated, strict=True),
    key=lambda item: (
        round(item[1].slice_position, 3) if item[1].slice_position is not None else float(
            item[1].instance_number or 0
        ),
        item[1].instance_number if item[1].instance_number is not None else 0,
        item[1].sop_instance_uid or item[0].sha256,
    ),
)
```

