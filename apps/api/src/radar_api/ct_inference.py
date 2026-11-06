"""Offline DenseNet121 inference for research CT checkpoints.

This module only reports scores from the checkpoint supplied by the operator. It
does not contain a fallback, download weights, or claim clinical validity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torch import Tensor, nn
from torchvision.models import densenet121

from radar_api.dicom_preprocessing import decode_and_window

CHECKPOINT_SCHEMA = "radar-ai.densenet121-ct-checkpoint/v2"
LEGACY_CHECKPOINT_SCHEMA = "radar-ai.densenet121-ich-checkpoint/v1"
ICH_LABELS = (
    "any",
    "epidural",
    "intraparenchymal",
    "intraventricular",
    "subarachnoid",
    "subdural",
)
BINARY_LABELS = ("0", "1")
IMAGE_SIZE = 224
PREPROCESSING = {
    "dicom_window_center": 40.0,
    "dicom_window_width": 80.0,
    "resize": IMAGE_SIZE,
    "channels": "grayscale_repeated_rgb",
    "normalization": "ImageNet mean/std",
}


class InferenceError(ValueError):
    """Checkpoint or inference input is incompatible with this runner."""


def load_checkpoint(path: Path, *, device: str = "cuda") -> tuple[nn.Module, dict[str, Any], str]:
    """Load a local binary or six-label DenseNet121 checkpoint offline.

    The checkpoint must contain a trained classifier state dict plus provenance
    metadata. Strict state-dict loading prevents silently scoring random layers.
    """
    target = torch.device(device)
    if target.type == "cuda" and not torch.cuda.is_available():
        raise InferenceError("CUDA was requested but is unavailable in this PyTorch environment")
    try:
        checkpoint_bytes = path.read_bytes()
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise InferenceError(f"Could not read checkpoint: {path}") from error
    if not isinstance(checkpoint, dict):
        raise InferenceError("Checkpoint must be a mapping")
    metadata = checkpoint.get("metadata")
    state_dict = checkpoint.get("state_dict")
    if not isinstance(metadata, dict) or not isinstance(state_dict, dict):
        raise InferenceError("Checkpoint requires metadata and state_dict mappings")
    labels = tuple(metadata.get("labels", ()))
    schema = metadata.get("schema")
    if schema == LEGACY_CHECKPOINT_SCHEMA:
        if labels != ICH_LABELS:
            raise InferenceError("Legacy checkpoint labels must use the documented RSNA order")
    elif schema == CHECKPOINT_SCHEMA:
        if labels not in (BINARY_LABELS, ICH_LABELS):
            raise InferenceError("Checkpoint labels must be [0, 1] or the RSNA six-label order")
    else:
        raise InferenceError(f"Checkpoint metadata schema must be {CHECKPOINT_SCHEMA}")
    if metadata.get("preprocessing") != PREPROCESSING:
        raise InferenceError("Checkpoint preprocessing must match this runner's versioned contract")
    for key in ("model_id", "training_data", "weights_sha256"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise InferenceError(f"Checkpoint metadata requires non-empty {key}")
    model = densenet121(weights=None)
    output_width = 1 if labels == BINARY_LABELS else len(ICH_LABELS)
    model.classifier = nn.Linear(model.classifier.in_features, output_width)
    try:
        model.load_state_dict(state_dict, strict=True)
    except RuntimeError as error:
        raise InferenceError(
            "Checkpoint state_dict does not match its DenseNet121 output contract"
        ) from error
    model.radar_labels = labels
    model.radar_binary = labels == BINARY_LABELS
    model.to(target).eval()
    digest = hashlib.sha256(checkpoint_bytes).hexdigest()
    return model, metadata, digest


def preprocess_ct_array(image: np.ndarray) -> Tensor:
    """Convert a windowed CT array into one normalized 3×224×224 model tensor."""
    if image.ndim != 2 or image.size == 0 or not np.isfinite(image).all():
        raise InferenceError("Preprocessed CT image must be a finite, non-empty 2D array")
    grayscale = Image.fromarray(np.uint8(np.clip(image, 0.0, 1.0) * 255.0), mode="L")
    rgb = np.asarray(grayscale.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR))
    tensor = torch.from_numpy(rgb.copy()).to(dtype=torch.float32).div_(255.0)
    tensor = tensor.unsqueeze(0).repeat(3, 1, 1)
    mean = torch.tensor((0.485, 0.456, 0.406), dtype=tensor.dtype).view(3, 1, 1)
    std = torch.tensor((0.229, 0.224, 0.225), dtype=tensor.dtype).view(3, 1, 1)
    return (tensor - mean) / std


def _prepare_input(image: np.ndarray, *, device: torch.device) -> Tensor:
    """Apply model preprocessing and add a one-image batch dimension."""
    return preprocess_ct_array(image).unsqueeze(0).to(device)


def score_dicom_files(
    model: nn.Module,
    paths: list[Path],
    *,
    device: str = "cuda",
    center: float = 40.0,
    width: float = 80.0,
) -> list[dict[str, object]]:
    """Return model-derived per-slice sigmoid scores for a list of DICOMs."""
    if not paths:
        raise InferenceError("At least one DICOM path is required")
    if (center, width) != (
        PREPROCESSING["dicom_window_center"],
        PREPROCESSING["dicom_window_width"],
    ):
        raise InferenceError("Window settings must match the checkpoint preprocessing contract")
    target = torch.device(device)
    outputs: list[dict[str, object]] = []
    model.eval()
    try:
        with torch.inference_mode():
            for path in paths:
                image = decode_and_window(path, center=center, width=width)
                logits = model(_prepare_input(image, device=target))
                labels = tuple(getattr(model, "radar_labels", ICH_LABELS))
                binary = bool(getattr(model, "radar_binary", False))
                expected_width = 1 if binary else len(labels)
                if logits.shape != (1, expected_width):
                    raise InferenceError("Model output width does not match checkpoint labels")
                probabilities = torch.sigmoid(logits[0]).detach().cpu().tolist()
                scores = (
                    [1.0 - probabilities[0], probabilities[0]]
                    if binary
                    else probabilities
                )
                outputs.append(
                    {"file": path.name, "scores": dict(zip(labels, scores, strict=True))}
                )
    except InferenceError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise InferenceError("Could not score one or more DICOM slices") from error
    return outputs


def write_results(
    output_path: Path,
    *,
    checkpoint_path: Path,
    checkpoint_metadata: dict[str, Any],
    checkpoint_sha256: str,
    scores: list[dict[str, object]],
    device: str,
    center: float,
    width: float,
) -> None:
    """Write reproducible scores and provenance as JSON."""
    result = {
        "scope": "research prototype; NOT FOR CLINICAL USE",
        "score_semantics": (
            "sigmoid outputs from the supplied model checkpoint; not clinically validated"
        ),
        "model": checkpoint_metadata,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "checkpoint_file_sha256": checkpoint_sha256,
        "device": device,
        "preprocessing": {
            "dicom_window_center": center,
            "dicom_window_width": width,
            "resize": [PREPROCESSING["resize"], PREPROCESSING["resize"]],
            "channels": PREPROCESSING["channels"],
            "normalization": PREPROCESSING["normalization"],
        },
        "slices": scores,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

