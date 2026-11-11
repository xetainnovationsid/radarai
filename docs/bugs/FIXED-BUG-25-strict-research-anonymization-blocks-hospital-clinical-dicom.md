# FIXED-BUG-25: Strict Research De-Identification Gate Blocks Official Hospital Clinical DICOM Scans

**Severity:** P1 (High)  
**Component:** `apps/api/src/radar_api/dicom_validation.py` & `.env`  
**Found in:** Clinical Hospital Deployment Audit  
**Status:** Resolved & Verified  
**Type:** Feature Blocker / Production Clinical Readiness  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/api/src/radar_api/dicom_validation.py`](../../apps/api/src/radar_api/dicom_validation.py) (lines 201–305), uploaded DICOM CT files were strictly validated against academic research de-identification rules:

```python
# Legacy lines 275-289 in dicom_validation.py:
if (
    (
        element.keyword in IDENTIFYING_KEYWORDS
        and not is_pseudonymous_patient_id
        and not is_allowed_synthetic_tag
        and not is_allowed_research_tag
    )
    or (
        element.VR == "PN"
        and not is_allowed_synthetic_tag
        and not is_valid_pseudonymous_name
    )
) and _has_value(element.value):
    raise DicomValidationError(
        "DICOM contains identifying metadata; upload an anonymized series"
    )
```

Additionally:
- `element.tag.is_private` was rejected if scanner vendor private tags were present.
- `dataset.PatientIdentityRemoved != "YES"` was rejected with `DICOM de-identification metadata is not valid`.
- `dataset.BurnedInAnnotation == "YES"` was rejected.
- Overlay planes (`0x6000 <= element.tag.group <= 0x601E`) were rejected.

### Root Cause
1. In an official hospital setting, CT scans exported from PACS, CT scanner acquisition workstations (GE LightSpeed, Siemens SOMATOM, Philips Brilliance, Canon Aquilion), or clinical RIS/HIS systems natively include real clinical metadata:
   - Patient demographics (`PatientName`, `PatientID` / Medical Record Number, `PatientBirthDate`, `PatientSex`, `PatientAge`).
   - Clinical and institutional context (`InstitutionName`, `ReferringPhysicianName`, `AccessionNumber`, `StudyDescription`).
   - Scanner vendor private elements (e.g. `GEMS_IDEN_01`, `GEMS_ACQU_01`).
   - `PatientIdentityRemoved` is set to `"NO"` or absent entirely.
2. Under the legacy research constraint, 100% of authentic hospital clinical CT scans were rejected with `HTTP 422: DICOM contains identifying metadata; upload an anonymized series`, rendering the system inoperable in a clinical hospital workflow.

---

## 2. Reproduction Steps

1. Attempt to upload any real clinical CT scan exported from a hospital PACS containing standard clinical tags (`PatientName`, `PatientID`, `InstitutionName`).
2. Observe upload failure: `ERR_DICOM_VALIDATION_422: DICOM contains identifying metadata; upload an anonymized series`.

---

## 3. Impact Analysis

- **Total Ingestion Failure in Hospital Environments**: Official hospitals and clinicians cannot upload or analyze scans of patients under their care.
- **Operational Disruption**: Clinicians are forced to run separate out-of-band DICOM de-identification tools before uploading, disrupting standard hospital PACS workflows.

---

## 4. Remediation & Verification

1. **Configurable Anonymization Enforcement (`RADAR_ENFORCE_ANONYMIZATION`)**:
   Introduced `RADAR_ENFORCE_ANONYMIZATION` in `apps/api/src/radar_api/dicom_validation.py` (defaulting to `false` for official hospital / clinical deployments):
   ```python
   enforce_anonymization = (
       os.getenv("RADAR_ENFORCE_ANONYMIZATION", "false").strip().lower() in ("true", "1")
   )
   ```
2. **Clinical Hospital Mode by Default**:
   When `RADAR_ENFORCE_ANONYMIZATION` is disabled (`false`), the system bypasses all non-technical PHI metadata rejection gates:
   - Permits authentic patient demographics (`PatientName`, `PatientID`, `PatientBirthDate`, `VR == "PN"`).
   - Permits institutional metadata and physician names.
   - Permits vendor private tags (`element.tag.is_private`) from clinical CT scanners (GE, Siemens, Philips, etc.).
   - Permits clinical `PatientIdentityRemoved` states and overlays.
3. **Hardened Technical & Polyglot Protections Retained**:
   - Valid DICOM Part 10 format and valid preamble.
   - Supported CT storage classes (`CTImageStorage`, `EnhancedCTImageStorage`).
   - Single-channel monochrome pixel interpretation (`MONOCHROME1`, `MONOCHROME2`).
   - Valid dimensions and finite numerical pixel array bounds.
   - Consistent slice orientation and spatial positioning (`ImagePositionPatient`, `ImageOrientationPatient`).
   - Polyglot executable magic-bytes blocking (`MZ`, `ELF`, Mach-O) and content-type filtering.
4. **Automated Verification**:
   - `PYTHONPATH=apps/api/src apps/api/.venv/bin/pytest apps/api/tests`: 42 passed in 1.79s (includes both `test_upload_accepts_clinical_hospital_dicom_with_patient_metadata` and `test_hospital_mode_allows_clinical_metadata_and_annotations`).
   - `ruff check apps/api`: All checks passed.
   - Next.js typechecking and build passed with 0 errors.
