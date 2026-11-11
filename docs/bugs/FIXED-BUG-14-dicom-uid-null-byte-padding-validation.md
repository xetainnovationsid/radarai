# BUG-14: DICOM Part 5 Odd-Byte Trailing Null Pad (`\x00`) Rejection in UID Validation

**Severity:** P2 (Medium)  
**Component:** `apps/api/src/radar_api/dicom_validation.py`  
**Found in:** Comprehensive Codebase Bug Audit  
**Status:** Documented / Fix Available  
**Type:** Data Validation / Standards Compliance  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/api/src/radar_api/dicom_validation.py`](../../apps/api/src/radar_api/dicom_validation.py), uploaded DICOM CT slices are validated against identifying tags, storage class, and UID validity:

```python
# Lines 167-189 in dicom_validation.py:
transfer_syntax = str(getattr(dataset.file_meta, "TransferSyntaxUID", "")).strip()
dataset_sop_instance = str(getattr(dataset, "SOPInstanceUID", "")).strip()
media_sop_instance = str(getattr(dataset.file_meta, "MediaStorageSOPInstanceUID", "")).strip()
...
if not transfer_syntax or not UID(transfer_syntax).is_valid:
    raise DicomValidationError(
        "DICOM File Meta has a missing or invalid Transfer Syntax UID"
    )
```

### Root Cause
1. According to the **DICOM Standard (PS 3.5, Section 9.1: Unique Identifier (UI) Value Representation)**:
   > *"A UID string value is a series of numeric components separated by the period character. [...] If the length of the string is odd, it shall be padded with a trailing NULL character (`00H`) to make its length even."*
2. Standard hospital PACS exporters and scanner workstations frequently output UIDs with a single trailing null byte `\x00`.
3. In Python, string `.strip()` only strips standard ASCII whitespace characters (`\t\n\r\x0b\x0c` and spaces). It **does not strip null bytes (`\x00`)**.
4. When `pydicom.uid.UID(transfer_syntax)` receives a string ending with `\x00` (e.g. `'1.2.840.10008.1.2.1\x00'`), it emits a `UserWarning: Invalid value for VR UI` and sets `is_valid = False`.
5. As a result, `validate_ct_slice` prematurely rejects fully compliant real-world DICOM files with `HTTP 422 Unprocessable Entity` (`"DICOM File Meta has a missing or invalid Transfer Syntax UID"` or `"DICOM SOP Instance UID is malformed"`).

---

## 2. Reproduction Steps

Execute the following Python verification snippet:

```python
from pydicom.uid import UID

raw_uid = "1.2.840.10008.1.2.1\x00"
stripped_whitespace = raw_uid.strip()
print(f"Whitespace strip: {repr(stripped_whitespace)}")  # '1.2.840.10008.1.2.1\x00'
print(f"Is valid: {UID(stripped_whitespace).is_valid}")  # False (triggers UserWarning)

properly_stripped = raw_uid.strip(" \t\n\r\0")
print(f"Null-safe strip: {repr(properly_stripped)}")  # '1.2.840.10008.1.2.1'
print(f"Is valid: {UID(properly_stripped).is_valid}")  # True
```

---

## 3. Impact Analysis

- **PACS Ingestion Failures**: Compliant cranial CT series exported from Siemens, GE, or Philips scanners that enforce 16-bit word alignment on odd-length UIDs are rejected during upload.
- **Silent Rejection in Production**: Radiologists and researchers are blocked from reviewing valid CT scans with an opaque validation error.

---

## 4. Recommended Remediation

Update all UID string sanitization in `dicom_validation.py` to strip null bytes alongside standard whitespace:

```python
def _clean_uid(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip(" \t\n\r\0")
```

Apply `_clean_uid` across `TransferSyntaxUID`, `SOPClassUID`, `MediaStorageSOPClassUID`, `SOPInstanceUID`, `MediaStorageSOPInstanceUID`, `StudyInstanceUID`, and `SeriesInstanceUID`.

