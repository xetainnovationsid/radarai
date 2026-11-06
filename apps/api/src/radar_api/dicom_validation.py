"""Validation for one anonymized, single-frame CT series."""

import re
from dataclasses import dataclass
from math import isclose, sqrt
from pathlib import Path

import numpy as np
from pydicom import dcmread
from pydicom.dataset import FileDataset
from pydicom.errors import InvalidDicomError
from pydicom.uid import UID, CTImageStorage, EnhancedCTImageStorage


class DicomValidationError(ValueError):
    """A safe, user-facing DICOM validation failure."""


@dataclass(frozen=True)
class ValidatedDicom:
    study_instance_uid: str | None
    series_instance_uid: str | None
    sop_instance_uid: str | None
    slice_position: float | None
    z_position_mm: float | None
    orientation: tuple[float, ...] | None
    instance_number: int | None
    rows: int
    columns: int
    is_synthetic_fixture: bool = False


IDENTIFYING_KEYWORDS = frozenset(
    {
        "PatientName",
        "PatientID",
        "PatientBirthDate",
        "PatientBirthTime",
        "PatientAddress",
        "PatientTelephoneNumbers",
        "OtherPatientIDs",
        "OtherPatientNames",
        "MedicalRecordLocator",
        "AccessionNumber",
        "InstitutionName",
        "InstitutionAddress",
        "ReferringPhysicianName",
        "PerformingPhysicianName",
        "PhysiciansOfRecord",
        "NameOfPhysiciansReadingStudy",
        "OperatorsName",
        "StudyID",
        "RequestingPhysician",
        "RequestingService",
        "StudyDescription",
        "SeriesDescription",
        "ProtocolName",
        "DeviceSerialNumber",
        "StationName",
        "ImageComments",
        "PatientComments",
        "PerformedProcedureStepID",
        "PerformedProcedureStepDescription",
        "InstitutionalDepartmentName",
        "IssuerOfPatientID",
        "IssuerOfAccessionNumberSequence",
        "ClinicalTrialSiteName",
        "ClinicalTrialSiteID",
        "OriginalAttributesSequence",
        "ModifiedAttributesSequence",
        "OtherPatientIDsSequence",
        "ConsultingPhysicianName",
        "HumanPerformerName",
        "VerifyingObserverName",
        "VerifyingObserverSequence",
        "AuthorObserverSequence",
        "ParticipantSequence",
        "CustodialOrganizationSequence",
        "ResponsiblePerson",
        "PatientMotherBirthName",
        "PatientReligiousPreference",
        "MilitaryRank",
        "BranchOfService",
        "CountryOfResidence",
        "RegionOfResidence",
        "CurrentPatientLocation",
        "PatientInstitutionResidence",
        "VisitComments",
        "AdmissionID",
        "IssuerOfAdmissionID",
    }
)
CT_STORAGE_CLASSES = {str(CTImageStorage), str(EnhancedCTImageStorage)}
ANONYMIZED_IDENTIFIER_PATTERN = re.compile(r"ID_[0-9A-Fa-f]{8,12}\Z")


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(_has_value(item) for item in value)
    return bool(str(value).strip())


def _is_valid_instance_identifier(value: str) -> bool:
    """Accept standard UIDs or the dataset's opaque, de-identified ID tokens."""
    return UID(value).is_valid or ANONYMIZED_IDENTIFIER_PATTERN.fullmatch(value) is not None


def _position_and_normal(
    dataset: FileDataset,
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    try:
        position = tuple(float(value) for value in dataset.ImagePositionPatient)
        orientation = tuple(float(value) for value in dataset.ImageOrientationPatient)
    except (AttributeError, TypeError, ValueError) as error:
        raise DicomValidationError("DICOM image geometry is incomplete") from error

    if len(position) != 3 or len(orientation) != 6:
        raise DicomValidationError("DICOM image geometry is invalid")

    row, column = orientation[:3], orientation[3:]
    row_norm = sqrt(sum(value * value for value in row))
    column_norm = sqrt(sum(value * value for value in column))
    dot_product = sum(left * right for left, right in zip(row, column))
    if not isclose(row_norm, 1.0, abs_tol=1e-3) or not isclose(
        column_norm, 1.0, abs_tol=1e-3
    ) or not isclose(dot_product, 0.0, abs_tol=1e-3):
        raise DicomValidationError("DICOM image orientation is invalid")

    normal = (
        row[1] * column[2] - row[2] * column[1],
        row[2] * column[0] - row[0] * column[2],
        row[0] * column[1] - row[1] * column[0],
    )
    return position, normal, orientation


def validate_ct_slice(path: Path, *, max_pixels: int) -> ValidatedDicom:
    """Read and validate one DICOM CT image without returning its PHI or UIDs to clients."""

    try:
        dataset = dcmread(path, force=False)
        if not isinstance(dataset, FileDataset) or not dataset.file_meta:
            raise DicomValidationError("Upload must be a DICOM Part 10 image")

        modality = str(getattr(dataset, "Modality", "")).strip().upper()
        dataset_sop_class = str(getattr(dataset, "SOPClassUID", "")).strip()
        media_sop_class = str(
            getattr(dataset.file_meta, "MediaStorageSOPClassUID", "")
        ).strip()
        if dataset_sop_class and media_sop_class and dataset_sop_class != media_sop_class:
            raise DicomValidationError(
                "DICOM file-meta Media Storage SOP Class UID differs from the image SOP Class UID"
            )
        sop_class_uid = dataset_sop_class or media_sop_class
        if not sop_class_uid:
            raise DicomValidationError("DICOM file is missing its CT storage class")
        if sop_class_uid not in CT_STORAGE_CLASSES:
            raise DicomValidationError("DICOM object is not a supported CT image")
        if modality and modality != "CT":
            raise DicomValidationError("Only CT images are accepted")

        media_sop_instance = str(
            getattr(dataset.file_meta, "MediaStorageSOPInstanceUID", "")
        ).strip()
        transfer_syntax = str(getattr(dataset.file_meta, "TransferSyntaxUID", "")).strip()
        dataset_sop_instance = str(getattr(dataset, "SOPInstanceUID", "")).strip()
        if media_sop_class != sop_class_uid:
            raise DicomValidationError(
                "DICOM File Meta is missing or has a different Media Storage SOP Class UID"
            )
        if (
            media_sop_instance
            and dataset_sop_instance
            and media_sop_instance != dataset_sop_instance
        ):
            raise DicomValidationError(
                "DICOM File Meta SOP Instance UID differs from the image SOP Instance UID"
            )
        if any(
            value and not _is_valid_instance_identifier(value)
            for value in (media_sop_instance, dataset_sop_instance)
        ):
            raise DicomValidationError("DICOM SOP Instance UID is malformed")
        if not transfer_syntax or not UID(transfer_syntax).is_valid:
            raise DicomValidationError(
                "DICOM File Meta has a missing or invalid Transfer Syntax UID"
            )

        is_synthetic_phantom_fixture = (
            str(getattr(dataset, "PatientIdentityRemoved", "")).strip().upper() == "YES"
            and str(getattr(dataset, "DeidentificationMethod", "")).strip()
            == "SYNTHETIC_MATHEMATICAL_PHANTOM_NO_PATIENT_DATA"
            and str(getattr(dataset, "PatientName", "")).strip() == "ANONYMIZED^BRAIN^CT"
            and not _has_value(getattr(dataset, "PatientBirthDate", None))
        )
        synthetic_allowed_keywords = {
            "PatientName",
            "PatientID",
            "AccessionNumber",
            "StudyDescription",
            "SeriesDescription",
            "StudyID",
            "ImageComments",
        }

        for element in dataset.iterall():
            is_pseudonymous_patient_id = (
                element.keyword == "PatientID"
                and ANONYMIZED_IDENTIFIER_PATTERN.fullmatch(
                    str(element.value).strip()
                )
                is not None
            )
            is_allowed_synthetic_tag = (
                is_synthetic_phantom_fixture
                and element.keyword in synthetic_allowed_keywords
            )
            if element.tag.is_private and _has_value(element.value):
                raise DicomValidationError("DICOM private metadata must be removed before upload")
            if 0x6000 <= element.tag.group <= 0x601E and _has_value(element.value):
                raise DicomValidationError("DICOM overlay planes must be removed before upload")
            if (
                (
                    element.keyword in IDENTIFYING_KEYWORDS
                    and not is_pseudonymous_patient_id
                    and not is_allowed_synthetic_tag
                )
                or (element.VR == "PN" and not is_allowed_synthetic_tag)
            ) and _has_value(element.value):
                raise DicomValidationError(
                    "DICOM contains identifying metadata; upload an anonymized series"
                )

        if (
            "BurnedInAnnotation" in dataset
            and str(dataset.BurnedInAnnotation).strip().upper() == "YES"
        ):
            raise DicomValidationError(
                "DICOM image has burned-in annotations that may contain PHI"
            )

        if (
            "PatientIdentityRemoved" in dataset
            and str(dataset.PatientIdentityRemoved).upper() != "YES"
        ):
            raise DicomValidationError("DICOM de-identification metadata is not valid")

        study_uid = str(getattr(dataset, "StudyInstanceUID", "")).strip()
        series_uid = str(getattr(dataset, "SeriesInstanceUID", "")).strip()
        sop_uid = dataset_sop_instance or media_sop_instance
        for value in (study_uid, series_uid, sop_uid):
            if value and not _is_valid_instance_identifier(value):
                raise DicomValidationError(
                    "DICOM Study/Series/SOP identifiers are malformed. Use valid DICOM UIDs "
                    "or consistent anonymized IDs in the ID_<hex> format."
                )
        study_uid = study_uid or None
        series_uid = series_uid or None
        sop_uid = sop_uid or None
        rows, columns = int(dataset.Rows), int(dataset.Columns)
        if rows <= 0 or columns <= 0 or rows * columns > max_pixels:
            raise DicomValidationError("DICOM image dimensions exceed the supported limit")
        if int(getattr(dataset, "SamplesPerPixel", 1)) != 1:
            raise DicomValidationError("Only single-channel CT images are accepted")
        if str(getattr(dataset, "PhotometricInterpretation", "")) not in {
            "MONOCHROME1",
            "MONOCHROME2",
        }:
            raise DicomValidationError("DICOM CT pixel interpretation is invalid")
        if int(getattr(dataset, "NumberOfFrames", 1)) != 1 or "PixelData" not in dataset:
            raise DicomValidationError("Each DICOM file must contain one complete image slice")

        pixels = dataset.pixel_array
        if (
            not isinstance(pixels, np.ndarray)
            or pixels.shape != (rows, columns)
            or not np.isfinite(pixels).all()
        ):
            raise DicomValidationError("DICOM pixel data is incomplete or invalid")

        has_position = "ImagePositionPatient" in dataset
        has_orientation = "ImageOrientationPatient" in dataset
        if has_position != has_orientation:
            raise DicomValidationError("DICOM image geometry is incomplete")
        if has_position:
            position, normal, orientation = _position_and_normal(dataset)
            slice_position = sum(value * axis for value, axis in zip(position, normal))
            z_position_mm = position[2]
        else:
            position = None
            orientation = None
            slice_position = None
            z_position_mm = None
        try:
            instance_number = (
                int(str(dataset.InstanceNumber).strip())
                if _has_value(getattr(dataset, "InstanceNumber", None))
                else None
            )
        except (TypeError, ValueError) as error:
            raise DicomValidationError("DICOM instance number is invalid") from error
        return ValidatedDicom(
            study_instance_uid=study_uid,
            series_instance_uid=series_uid,
            sop_instance_uid=sop_uid,
            slice_position=slice_position,
            z_position_mm=z_position_mm,
            orientation=orientation,
            instance_number=instance_number,
            rows=rows,
            columns=columns,
            is_synthetic_fixture=is_synthetic_phantom_fixture,
        )
    except DicomValidationError:
        raise
    except (
        InvalidDicomError,
        OSError,
        EOFError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        NotImplementedError,
        RuntimeError,
    ) as error:
        raise DicomValidationError("DICOM file is corrupted or cannot be decoded") from error


