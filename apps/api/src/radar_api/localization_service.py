"""Optional offline SAMIHS hemorrhage localization for private CT series.

The model and all weights must be installed locally before use. This module never
downloads weights and never trains or fine-tunes a model.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydicom import dcmread

API_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_ROOT = API_ROOT / "data" / "model-artifacts" / "samihs-ich-segmentation"
DEFAULT_CHECKPOINT_NAME = "SAMIHS_09170527_2_0.483.pth"
DEFAULT_MAX_VOLUME_BYTES = 1024 * 1024 * 1024
_INFERENCE_LOCK = threading.Lock()


class LocalizationUnavailableError(RuntimeError):
    """Pretrained localization model is not configured or cannot be loaded."""


class LocalizationInputError(RuntimeError):
    """Stored DICOM images cannot be safely passed to the localizer."""


def _model_root() -> Path:
    value = os.getenv("RADAR_ICH_SEGMENTATION_ROOT", "").strip()
    path = Path(value).expanduser() if value else DEFAULT_MODEL_ROOT
    return (path if path.is_absolute() else API_ROOT / path).resolve()


def _checkpoint_path() -> Path:
    value = os.getenv("RADAR_ICH_SEGMENTATION_CHECKPOINT", "").strip()
    if value:
        path = Path(value).expanduser()
        return (path if path.is_absolute() else API_ROOT / path).resolve()
    return (_model_root() / "weights" / DEFAULT_CHECKPOINT_NAME).resolve()


def _device() -> str:
    try:
        import torch
    except ImportError as error:
        raise LocalizationUnavailableError("PyTorch is unavailable") from error
    requested = os.getenv("RADAR_ICH_SEGMENTATION_DEVICE", "auto").strip().lower()
    if requested == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if requested == "cuda":
        requested = "cuda:0"
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise LocalizationUnavailableError("CUDA was requested but is unavailable")
    if requested != "cpu" and not requested.startswith("cuda:"):
        raise LocalizationUnavailableError(
            "RADAR_ICH_SEGMENTATION_DEVICE must be auto, cpu, cuda, or cuda:N"
        )
    return requested


@lru_cache(maxsize=1)
def _load_model(
    model_root: str,
    checkpoint_path: str,
    checkpoint_modified_ns: int,
    checkpoint_size: int,
    device: str,
) -> tuple[Any, Any, Any, Any]:
    del checkpoint_modified_ns, checkpoint_size
    root = Path(model_root)
    source = root / "segment_ich.py"
    if not source.is_file():
        raise LocalizationUnavailableError(
            "SAMIHS source is missing; install the pinned pretrained model package"
        )
    spec = importlib.util.spec_from_file_location("radar_samihs_segment_ich", source)
    if spec is None or spec.loader is None:
        raise LocalizationUnavailableError("SAMIHS inference module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        model, prompt_fn, device_obj = module.load_model(
            ckpt=checkpoint_path,
            samihs_root=root / "samihs_src",
            device=device,
        )
    except Exception as error:
        raise LocalizationUnavailableError(
            "SAMIHS pretrained checkpoint or runtime dependencies could not be loaded"
        ) from error
    return module, model, prompt_fn, device_obj


def _read_hu_volume(paths: tuple[str, ...]) -> tuple[np.ndarray, int, int]:
    max_volume_bytes = int(
        os.getenv("RADAR_ICH_SEGMENTATION_MAX_VOLUME_BYTES", str(DEFAULT_MAX_VOLUME_BYTES))
    )
    if max_volume_bytes <= 0:
        raise LocalizationUnavailableError(
            "RADAR_ICH_SEGMENTATION_MAX_VOLUME_BYTES must be positive"
        )

    slices: list[np.ndarray] = []
    expected_shape: tuple[int, int] | None = None
    estimated_bytes = 0
    expected_orientation: tuple[float, ...] | None = None
    expected_position: float | None = None
    geometry_state: bool | None = None
    for path_value in paths:
        try:
            dataset = dcmread(path_value, force=False)
            modality = str(getattr(dataset, "Modality", "")).strip().upper()
            if modality and modality != "CT":
                raise LocalizationInputError("Stored series contains a non-CT image")
            if int(getattr(dataset, "NumberOfFrames", 1)) != 1:
                raise LocalizationInputError("SAMIHS supports single-frame CT slices only")
            if len(paths) > 1:
                has_position = "ImagePositionPatient" in dataset
                has_orientation = "ImageOrientationPatient" in dataset
                if has_position != has_orientation:
                    raise LocalizationInputError("CT slice geometry is incomplete")
                has_geometry = has_position and has_orientation
                if geometry_state is None:
                    geometry_state = has_geometry
                elif geometry_state != has_geometry:
                    raise LocalizationInputError("CT slice geometry is incomplete")
                if has_geometry:
                    orientation = tuple(float(value) for value in dataset.ImageOrientationPatient)
                    position = tuple(float(value) for value in dataset.ImagePositionPatient)
                    if len(orientation) != 6 or len(position) != 3:
                        raise LocalizationInputError("CT slice geometry is incomplete")
                    if expected_orientation is None:
                        expected_orientation = orientation
                    elif not np.allclose(orientation, expected_orientation, atol=1e-4, rtol=0):
                        raise LocalizationInputError("CT slices do not share one image orientation")
                    normal = np.cross(orientation[:3], orientation[3:])
                    projected_position = float(np.dot(position, normal))
                    if expected_position is not None and projected_position < (
                        expected_position - 1e-4
                    ):
                        raise LocalizationInputError(
                            "CT slices are not in non-decreasing physical order"
                        )
                    expected_position = projected_position

            pixels = dataset.pixel_array
            if pixels.ndim != 2 or pixels.size == 0:
                raise LocalizationInputError("CT slice does not contain one 2D image")
            if expected_shape is None:
                expected_shape = pixels.shape
            elif pixels.shape != expected_shape:
                raise LocalizationInputError("CT slices have inconsistent image dimensions")
            slope = float(getattr(dataset, "RescaleSlope", 1.0))
            intercept = float(getattr(dataset, "RescaleIntercept", 0.0))
            if not math.isfinite(slope) or not math.isfinite(intercept):
                raise LocalizationInputError("CT rescale metadata is invalid")
            hu = pixels.astype(np.float32, copy=False) * np.float32(slope) + np.float32(
                intercept
            )
            if not np.isfinite(hu).all():
                raise LocalizationInputError("CT pixels contain non-finite values")
            estimated_bytes += int(hu.size) * np.dtype(np.float32).itemsize
            if estimated_bytes > max_volume_bytes:
                raise LocalizationInputError(
                    "CT series exceeds the configured localizer volume memory limit"
                )
            slices.append(np.ascontiguousarray(hu))
        except LocalizationInputError:
            raise
        except (OSError, AttributeError, EOFError, TypeError, ValueError, RuntimeError) as error:
            raise LocalizationInputError("Stored CT series could not be decoded") from error

    if not slices or expected_shape is None:
        raise LocalizationInputError("CT series has no slices")
    return np.stack(slices, axis=2), expected_shape[1], expected_shape[0]


@lru_cache(maxsize=8)
def localize_dicom_series(paths: tuple[str, ...]) -> dict[str, Any]:
    """Run the configured pretrained SAMIHS model and return normalized boxes."""
    model_root = _model_root()
    checkpoint_path = _checkpoint_path()
    if not checkpoint_path.is_file():
        raise LocalizationUnavailableError(
            "SAMIHS pretrained weights are unavailable; set RADAR_ICH_SEGMENTATION_ROOT"
        )
    device = _device()
    stat = checkpoint_path.stat()
    volume, width, height = _read_hu_volume(paths)
    try:
        module, model, prompt_fn, device_obj = _load_model(
            str(model_root), str(checkpoint_path), stat.st_mtime_ns, stat.st_size, device
        )
        threshold = float(os.getenv("RADAR_ICH_SEGMENTATION_THRESHOLD", "0.5"))
        if not math.isfinite(threshold) or not 0 < threshold < 1:
            raise LocalizationUnavailableError(
                "RADAR_ICH_SEGMENTATION_THRESHOLD must be between 0 and 1"
            )
        batch_size = int(os.getenv("RADAR_ICH_SEGMENTATION_BATCH_SIZE", "1"))
        with _INFERENCE_LOCK:
            mask = module.segment_array(
                volume=volume,
                model=model,
                get_click_prompt_eval=prompt_fn,
                device=device_obj,
                slice_axis=2,
                encoder_input_size=1024,
                batch_size=batch_size,
                threshold=threshold,
                amp=device_obj.type == "cuda",
                rotate_for_samihs=True,
            )
        if mask.shape != volume.shape or mask.ndim != 3:
            raise ValueError("SAMIHS output mask shape does not match the CT volume")
    except LocalizationUnavailableError:
        raise
    except Exception as error:
        raise LocalizationUnavailableError(
            "SAMIHS inference could not process this CT series"
        ) from error

    boxes: list[dict[str, Any]] = []
    for index in range(mask.shape[2]):
        ys, xs = np.nonzero(mask[:, :, index])
        box = None
        pixels = int(len(xs))
        if pixels:
            left, right = int(xs.min()), int(xs.max()) + 1
            top, bottom = int(ys.min()), int(ys.max()) + 1
            box = {
                "x": left / width,
                "y": top / height,
                "width": (right - left) / width,
                "height": (bottom - top) / height,
            }
        boxes.append(
            {
                "index": index,
                "image_width": width,
                "image_height": height,
                "box": box,
                "mask_pixels": pixels,
            }
        )

    digest = hashlib.sha256()
    with checkpoint_path.open("rb") as checkpoint:
        for block in iter(lambda: checkpoint.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "model_id": "SAMIHS pretrained ICH slice segmentation",
        "checkpoint_sha256": digest.hexdigest(),
        "device": device,
        "threshold": float(os.getenv("RADAR_ICH_SEGMENTATION_THRESHOLD", "0.5")),
        "slices": boxes,
    }
