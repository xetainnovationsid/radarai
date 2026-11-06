"""Lazy local checkpoint loading for research-only study scores."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKPOINT = API_ROOT / "data" / "model-artifacts" / "ct-binary-densenet121.pt"


class ModelUnavailableError(RuntimeError):
    """The local research checkpoint is missing or incompatible."""


class StudyScoringError(RuntimeError):
    """A stored CT slice could not be decoded or scored."""


def _checkpoint_path() -> Path:
    value = os.getenv("RADAR_CT_CHECKPOINT", "").strip()
    if not value:
        return DEFAULT_CHECKPOINT.resolve()
    path = Path(value).expanduser()
    return (path if path.is_absolute() else API_ROOT / path).resolve()


def _target_device() -> str:
    try:
        from torch import cuda
    except ImportError as error:
        raise ModelUnavailableError("PyTorch is unavailable in this API environment") from error

    requested = os.getenv("RADAR_CT_DEVICE", "auto").strip().lower()
    if requested == "auto":
        return "cuda" if cuda.is_available() else "cpu"
    if requested not in {"cuda", "cpu"}:
        raise ModelUnavailableError("RADAR_CT_DEVICE must be auto, cuda, or cpu")
    if requested == "cuda" and not cuda.is_available():
        raise ModelUnavailableError("CUDA is configured but unavailable")
    return requested


@lru_cache(maxsize=2)
def _load_cached(
    checkpoint_path: str,
    modified_ns: int,
    size_bytes: int,
    device: str,
) -> tuple[Any, dict[str, Any], str]:
    from radar_api.ct_inference import BINARY_LABELS, load_checkpoint

    del modified_ns, size_bytes
    model, metadata, digest = load_checkpoint(Path(checkpoint_path), device=device)
    if tuple(metadata.get("labels", ())) != BINARY_LABELS:
        raise ModelUnavailableError("Configured checkpoint is not a binary CT model")
    return model, metadata, digest


def score_local_checkpoint(paths: list[Path]) -> dict[str, Any]:
    """Score DICOM paths with the configured local binary checkpoint."""
    checkpoint_path = _checkpoint_path()
    if not checkpoint_path.is_file():
        raise ModelUnavailableError(
            "Local CT checkpoint is unavailable; configure RADAR_CT_CHECKPOINT"
        )
    try:
        from radar_api.ct_inference import BINARY_LABELS, InferenceError, score_dicom_files

        device = _target_device()
        stat = checkpoint_path.stat()
        model, metadata, digest = _load_cached(
            str(checkpoint_path), stat.st_mtime_ns, stat.st_size, device
        )
        if tuple(metadata.get("labels", ())) != BINARY_LABELS:
            raise ModelUnavailableError("Configured checkpoint is not a binary CT model")
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise ModelUnavailableError("Local CT checkpoint could not be loaded") from error
    try:
        scores = score_dicom_files(model, paths, device=device)
    except InferenceError as error:
        raise StudyScoringError("Stored CT slices could not be scored") from error
    return {
        "model_id": metadata["model_id"],
        "checkpoint_sha256": digest,
        "device": device,
        "slices": scores,
    }

