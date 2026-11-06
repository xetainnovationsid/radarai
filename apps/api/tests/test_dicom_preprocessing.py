from pathlib import Path

import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from radar_api.dicom_preprocessing import (
    DicomExample,
    PreprocessingError,
    SplitRecord,
    build_split_manifest,
    decode_and_window,
    iter_dicom_batches,
)


def write_ct(path: Path, pixels: np.ndarray, *, photo: str = "MONOCHROME2") -> Path:
    sop = generate_uid()
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = sop
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = sop
    ds.Modality = "CT"
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photo
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.RescaleSlope = 2
    ds.RescaleIntercept = -100
    ds.PixelData = pixels.astype("<i2").tobytes()
    ds.save_as(path)
    return path


def test_decode_and_window_is_deterministic_and_applies_rescale(tmp_path: Path) -> None:
    path = write_ct(tmp_path / "slice.dcm", np.array([[-1000, 0, 1000]], dtype=np.int16))

    first = decode_and_window(path, center=-99.5, width=401)
    second = decode_and_window(path, center=-99.5, width=401)

    np.testing.assert_array_equal(first, second)
    assert first.dtype == np.float32
    assert first.shape == (1, 3)
    assert first[0, 0] == pytest.approx(0.0)  # -2100 HU after rescale, clipped
    assert first[0, 1] == pytest.approx(0.5)  # -100 HU after rescale
    assert first[0, 2] == pytest.approx(1.0)  # 0 HU after rescale


def test_monochrome1_inverts_the_windowed_image(tmp_path: Path) -> None:
    path = write_ct(
        tmp_path / "inverse.dcm", np.array([[-200, 200]], dtype=np.int16), photo="MONOCHROME1"
    )
    image = decode_and_window(path, center=-100, width=201)
    assert image[0, 0] == pytest.approx(1.0)
    assert image[0, 1] == pytest.approx(0.0)


def test_width_one_uses_a_deterministic_threshold(tmp_path: Path) -> None:
    path = write_ct(tmp_path / "threshold.dcm", np.array([[0, 1]], dtype=np.int16))
    image = decode_and_window(path, center=-99.5, width=1)
    np.testing.assert_array_equal(image, np.array([[0.0, 1.0]], dtype=np.float32))


def test_invalid_window_is_rejected() -> None:
    with pytest.raises(PreprocessingError, match="width"):
        decode_and_window(Path("unused"), width=0)


def test_pixel_limit_is_checked_from_header_before_decode(tmp_path: Path) -> None:
    path = write_ct(tmp_path / "oversized.dcm", np.zeros((2, 2), dtype=np.int16))
    with pytest.raises(PreprocessingError, match="pixel limit"):
        decode_and_window(path, max_pixels=3)


def test_split_groups_patients_and_studies_and_is_reproducible() -> None:
    key = b"private test key with more than 32 bytes"
    records = [
        SplitRecord("patient-a", "study-a1"),
        SplitRecord("patient-a", "study-a2"),
        SplitRecord("patient-b", "study-b1"),
        SplitRecord("patient-c", "study-c1"),
        SplitRecord("patient-c", "study-c1"),  # multiple slices in one study
    ]
    manifest = build_split_manifest(records, key=key)
    assert manifest == build_split_manifest(records, key=key)
    assert manifest["manifest_version"] == 1
    assignments = manifest["assignments"]
    by_patient = {}
    for row in assignments:
        by_patient.setdefault(row["patient_ref"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in by_patient.values())
    assert len(assignments) == 4
    assert "patient-a" not in repr(manifest)
    assert "study-a1" not in repr(manifest)


def test_split_rejects_missing_ids_and_conflicting_study_owner() -> None:
    key = b"private test key with more than 32 bytes"
    with pytest.raises(ValueError, match="requires"):
        build_split_manifest([SplitRecord("", "study")], key=key)
    with pytest.raises(ValueError, match="multiple patient"):
        build_split_manifest(
            [SplitRecord("patient-a", "study"), SplitRecord("patient-b", "study")], key=key
        )


def test_iterable_loader_batches_without_exceeding_configured_estimate(tmp_path: Path) -> None:
    examples = [
        DicomExample(
            write_ct(tmp_path / f"{index}.dcm", np.zeros((4, 4), dtype=np.int16)),
            f"study-{index}",
            (float(index),),
        )
        for index in range(5)
    ]
    batches = list(
        iter_dicom_batches(
            examples,
            batch_size=5,
            memory_budget_bytes=4 * 4 * 32 * 2,
            max_pixels_per_image=16,
        )
    )
    assert [len(batch.study_uids) for batch in batches] == [2, 2, 1]
    assert all(batch.images.dtype == np.float32 for batch in batches)
    assert all(batch.images.shape[1:] == (4, 4) for batch in batches)
    assert all(batch.labels.shape[1:] == (1,) for batch in batches)


def test_loader_rejects_budgets_above_12_gib() -> None:
    with pytest.raises(ValueError, match="12 GiB"):
        list(
            iter_dicom_batches(
                [], memory_budget_bytes=12 * 1024**3 + 1
            )
        )

