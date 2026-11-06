"""Deterministic, research-only CT decoding and bounded-memory data utilities.

The helpers in this module are for offline prototyping. They are not a validated
medical device pipeline and must not be used for clinical decisions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydicom import dcmread

SplitName = Literal["train", "validation", "test"]
SPLIT_MANIFEST_VERSION = 1
MAX_LOADER_MEMORY_BYTES = 12 * 1024**3


class PreprocessingError(ValueError):
    """A DICOM image or preprocessing configuration cannot be used."""


def decode_and_window(
    path: Path,
    *,
    center: float = 40.0,
    width: float = 80.0,
    max_pixels: int = 16_777_216,
    max_file_bytes: int = 512 * 1024**2,
) -> np.ndarray:
    """Decode one single-frame DICOM slice to a deterministic float32 [0, 1] image.

    RescaleSlope/Intercept are applied before the DICOM linear VOI window.
    MONOCHROME1 is inverted after windowing. The default (40/80) is a fixed
    soft-tissue window; callers should record any different window in config.
    """
    if not math.isfinite(center) or not math.isfinite(width) or width < 1:
        raise PreprocessingError("Window center must be finite and width must be at least 1")
    if max_pixels < 1 or max_file_bytes < 1:
        raise PreprocessingError("DICOM file and pixel limits must be positive")
    try:
        if path.stat().st_size > max_file_bytes:
            raise PreprocessingError("DICOM file exceeds the configured byte limit")
        header = dcmread(path, force=False, stop_before_pixels=True)
        if int(getattr(header, "NumberOfFrames", 1)) != 1:
            raise PreprocessingError("Only single-frame DICOM images are supported")
        rows, columns = int(header.Rows), int(header.Columns)
        if rows < 1 or columns < 1 or rows * columns > max_pixels:
            raise PreprocessingError("DICOM image exceeds the configured pixel limit")
        dataset = dcmread(path, force=False)
        if int(getattr(dataset, "NumberOfFrames", 1)) != 1:
            raise PreprocessingError("Only single-frame DICOM images are supported")
        photo = str(getattr(dataset, "PhotometricInterpretation", "MONOCHROME2"))
        if photo not in {"MONOCHROME1", "MONOCHROME2"}:
            raise PreprocessingError("Only monochrome DICOM images are supported")
        raw = dataset.pixel_array
        if raw.ndim != 2 or raw.size == 0:
            raise PreprocessingError("DICOM must contain one non-empty 2D image")
        slope = float(getattr(dataset, "RescaleSlope", 1.0))
        intercept = float(getattr(dataset, "RescaleIntercept", 0.0))
        if not math.isfinite(slope) or not math.isfinite(intercept):
            raise PreprocessingError("DICOM rescale values must be finite")
        hu = raw.astype(np.float32, copy=False) * np.float32(slope) + np.float32(intercept)

        # DICOM PS3.3 C.11.2 LINEAR window, including its half-unit boundary.
        if width == 1:
            image = (hu > center - 0.5).astype(np.float32)
        else:
            lower = center - 0.5 - (width - 1.0) / 2.0
            upper = center - 0.5 + (width - 1.0) / 2.0
            image = np.clip((hu - lower) / (upper - lower), 0.0, 1.0).astype(
                np.float32, copy=False
            )
        if photo == "MONOCHROME1":
            image = np.float32(1.0) - image
        return np.ascontiguousarray(image, dtype=np.float32)
    except PreprocessingError:
        raise
    except (
        OSError,
        EOFError,
        AttributeError,
        TypeError,
        ValueError,
        NotImplementedError,
        RuntimeError,
    ) as error:
        raise PreprocessingError("DICOM is corrupted or cannot be decoded") from error


@dataclass(frozen=True)
class SplitRecord:
    """One image's identifiers for grouped splitting; identifiers stay local."""

    patient_id: str
    study_uid: str


def _pseudonym(key: bytes, namespace: bytes, value: str) -> str:
    return hmac.new(key, namespace + b"\0" + value.encode("utf-8"), hashlib.sha256).hexdigest()


def build_split_manifest(
    records: Iterable[SplitRecord],
    *,
    key: bytes,
    seed: str = "radar-ai-split-v1",
    train_fraction: float = 0.8,
    validation_fraction: float = 0.1,
) -> dict[str, object]:
    """Assign whole patients and studies deterministically, requiring a private HMAC key.

    Keep the resulting manifest and key in approved private storage. The public
    repository should contain only this manifest format/version, never generated
    assignments or patient/study identifiers.
    """
    if len(key) < 32:
        raise ValueError("Split HMAC key must contain at least 32 bytes")
    if not math.isfinite(train_fraction) or not math.isfinite(validation_fraction):
        raise ValueError("Split fractions must be finite")
    if train_fraction <= 0 or validation_fraction < 0 or train_fraction + validation_fraction >= 1:
        raise ValueError("Fractions must be positive and leave a non-empty test fraction")

    study_patients: dict[str, str] = {}
    unique_patients: set[str] = set()
    for record in records:
        patient, study = record.patient_id.strip(), record.study_uid.strip()
        if not patient or not study:
            raise ValueError("Every split record requires patient_id and study_uid")
        prior_patient = study_patients.setdefault(study, patient)
        if prior_patient != patient:
            raise ValueError("A study UID maps to multiple patient IDs")
        unique_patients.add(patient)

    assignments: dict[str, SplitName] = {}
    for patient in unique_patients:
        digest = hmac.new(
            key, f"{seed}\0{patient}".encode(), hashlib.sha256
        ).digest()
        score = int.from_bytes(digest[:8], "big") / 2**64
        split: SplitName = (
            "train" if score < train_fraction else
            "validation" if score < train_fraction + validation_fraction else
            "test"
        )
        assignments[patient] = split

    manifest_studies = [
        {
            "patient_ref": _pseudonym(key, b"patient", patient),
            "study_ref": _pseudonym(key, b"study", study),
            "split": assignments[patient],
        }
        for study, patient in sorted(study_patients.items())
    ]
    return {
        "schema": "radar-ai.split-manifest/v1",
        "manifest_version": SPLIT_MANIFEST_VERSION,
        "algorithm": "hmac-sha256-patient-grouped-thresholds-v1",
        "seed": seed,
        "fractions": {
            "train": train_fraction,
            "validation": validation_fraction,
            "test": 1.0 - train_fraction - validation_fraction,
        },
        "counts": {
            "patients": len(unique_patients),
            "studies": len(study_patients),
            "train_studies": sum(row["split"] == "train" for row in manifest_studies),
            "validation_studies": sum(row["split"] == "validation" for row in manifest_studies),
            "test_studies": sum(row["split"] == "test" for row in manifest_studies),
        },
        "assignments": manifest_studies,
    }


def write_split_manifest(manifest: dict[str, object], path: Path) -> None:
    """Write a stable JSON representation; caller must choose private storage."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@dataclass(frozen=True)
class DicomExample:
    path: Path
    study_uid: str
    label: Sequence[float] = ()


@dataclass(frozen=True)
class DicomBatch:
    images: np.ndarray
    labels: np.ndarray
    study_uids: tuple[str, ...]


def iter_dicom_batches(
    examples: Sequence[DicomExample],
    *,
    batch_size: int = 16,
    memory_budget_bytes: int = 2 * 1024**3,
    max_pixels_per_image: int = 16_777_216,
    center: float = 40.0,
    width: float = 80.0,
    shuffle_seed: int | None = None,
) -> Iterator[DicomBatch]:
    """Yield decoded batches lazily under a conservative 12 GiB process budget.

    Images are never cached across batches. The estimate reserves 32 bytes per
    pixel for decoder, scaling, stack, and label-independent temporary buffers.
    """
    if batch_size < 1 or memory_budget_bytes < 1 or max_pixels_per_image < 1:
        raise ValueError("Batch size, memory budget, and pixel limit must be positive")
    if memory_budget_bytes > MAX_LOADER_MEMORY_BYTES:
        raise ValueError("Loader memory budget cannot exceed 12 GiB")
    labels_per_image = {len(example.label) for example in examples}
    if len(labels_per_image) > 1:
        raise ValueError("Every example must have the same label width")

    order = np.arange(len(examples))
    if shuffle_seed is not None:
        np.random.default_rng(shuffle_seed).shuffle(order)
    pending_images: list[np.ndarray] = []
    pending_labels: list[Sequence[float]] = []
    pending_studies: list[str] = []
    estimated_bytes = 0

    def emit() -> DicomBatch:
        labels = np.asarray(pending_labels, dtype=np.float32)
        if labels.ndim == 1:
            labels = labels.reshape(-1, 0)
        return DicomBatch(
            images=np.stack(pending_images).astype(np.float32, copy=False),
            labels=labels,
            study_uids=tuple(pending_studies),
        )

    for index in order:
        example = examples[int(index)]
        image = decode_and_window(
            example.path,
            center=center,
            width=width,
            max_pixels=max_pixels_per_image,
        )
        image_cost = int(image.size) * 32
        if image_cost > memory_budget_bytes:
            raise ValueError("One decoded image exceeds the loader memory budget")
        if pending_images and (
            len(pending_images) >= batch_size or estimated_bytes + image_cost > memory_budget_bytes
        ):
            yield emit()
            pending_images.clear()
            pending_labels.clear()
            pending_studies.clear()
            estimated_bytes = 0
        if pending_images and image.shape != pending_images[0].shape:
            raise PreprocessingError("Every image in a batch must have the same dimensions")
        pending_images.append(image)
        pending_labels.append(example.label)
        pending_studies.append(example.study_uid)
        estimated_bytes += image_cost
    if pending_images:
        yield emit()

