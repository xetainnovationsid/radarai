#!/usr/bin/env python3
"""Single-volume intracranial hemorrhage segmentation with SAMIHS.

Input:  a 3D brain CT NIfTI (.nii or .nii.gz)
Output: a binary uint8 NIfTI mask with the same shape/affine as the input.

The wrapper intentionally keeps the original SAMIHS project unchanged and loads
its modules through --samihs-root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import nibabel as nib
import numpy as np
import torch
import torch.nn.functional as F


PACKAGE_ROOT = Path(__file__).resolve().parent
LOCAL_SAMIHS_SRC = PACKAGE_ROOT / "samihs_src"
DEFAULT_SAMIHS_ROOT = LOCAL_SAMIHS_SRC if LOCAL_SAMIHS_SRC.exists() else Path("/data/wxh/Medical/to_cfff/metrics/brain_bleed/SAMIHS")
DEFAULT_CKPT = PACKAGE_ROOT / "weights" / "SAMIHS_09170527_2_0.483.pth"


def _import_samihs(samihs_root: Path) -> tuple[Any, Any, Any]:
    samihs_root = samihs_root.resolve()
    if not samihs_root.exists():
        raise FileNotFoundError(f"SAMIHS root not found: {samihs_root}")
    sys.path.insert(0, str(samihs_root))
    from utils.config import get_config  # type: ignore
    from models.model_dict import get_model  # type: ignore
    from utils.generate_prompts import get_click_prompt_eval  # type: ignore

    return get_config, get_model, get_click_prompt_eval


def _select_slice_axis(shape: tuple[int, int, int], requested: str) -> int:
    if requested != "auto":
        axis = int(requested)
        if axis not in (0, 1, 2):
            raise ValueError("--slice-axis must be auto, 0, 1, or 2")
        return axis
    # Clinical CT volumes here are usually HxWxD or DxHxW; the slice dimension
    # is normally the smallest dimension. This preserves common 256/512 x 32 data.
    return int(np.argmin(shape))


def _normalize_slice(slc: np.ndarray, clip_low: float, clip_high: float) -> np.ndarray:
    slc = slc.astype(np.float32, copy=False)
    lo_p, hi_p = np.percentile(slc, [clip_low, clip_high])
    slc = np.clip(slc, lo_p, hi_p)
    lo = float(np.min(slc))
    hi = float(np.max(slc))
    den = max(hi - lo, 1e-6)
    return np.nan_to_num((slc - lo) / den, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def load_model(
    ckpt: str | Path = DEFAULT_CKPT,
    samihs_root: str | Path = DEFAULT_SAMIHS_ROOT,
    device: str = "cuda:0",
    encoder_input_size: int = 1024,
    low_image_size: int = 256,
    vit_name: str = "vit_b",
    task: str = "Unlabeled",
):
    """Load the SAMIHS model and return (model, prompt_fn, device_obj)."""
    ckpt = Path(ckpt).resolve()
    if not ckpt.exists():
        raise FileNotFoundError(f"checkpoint not found: {ckpt}")

    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    device_obj = torch.device(device)

    get_config, get_model, get_click_prompt_eval = _import_samihs(Path(samihs_root))
    args = SimpleNamespace(
        encoder_input_size=int(encoder_input_size),
        low_image_size=int(low_image_size),
        vit_name=vit_name,
        sam_ckpt=str(ckpt),
    )
    opt = get_config(task)
    opt.mode = "test"
    opt.modelname = "SAMIHS"
    opt.load_path = str(ckpt)
    opt.device = device

    model = get_model("SAMIHS", args=args, opt=opt, ckpt_path=str(ckpt)).to(device_obj)
    model.eval()
    return model, get_click_prompt_eval, device_obj


@torch.no_grad()
def segment_array(
    volume: np.ndarray,
    model,
    get_click_prompt_eval,
    device: torch.device,
    slice_axis: int,
    encoder_input_size: int = 1024,
    batch_size: int = 8,
    threshold: float = 0.5,
    amp: bool = True,
    clip_low: float = 0.5,
    clip_high: float = 99.5,
    rotate_for_samihs: bool = True,
) -> np.ndarray:
    """Segment a 3D numpy volume and return a binary uint8 mask."""
    if volume.ndim != 3:
        raise ValueError(f"Expected a 3D volume, got shape={volume.shape}")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    vol_hwd = np.moveaxis(volume, slice_axis, -1) if slice_axis != 2 else volume
    h, w, d = vol_hwd.shape
    mask_hwd = np.zeros((h, w, d), dtype=np.uint8)

    opt_lite = type("OptLite", (), {"device": device})()
    model.eval()

    for k0 in range(0, d, batch_size):
        k1 = min(k0 + batch_size, d)
        tensors = []
        for k in range(k0, k1):
            slc = _normalize_slice(vol_hwd[:, :, k], clip_low=clip_low, clip_high=clip_high)
            t = torch.from_numpy(slc).unsqueeze(0).unsqueeze(0)
            t = F.interpolate(t, (encoder_input_size, encoder_input_size), mode="bilinear", align_corners=False)
            if rotate_for_samihs:
                t = torch.rot90(t, k=3, dims=(-2, -1))
            tensors.append(t)

        batch = torch.cat(tensors, dim=0).to(device=device, dtype=torch.float32)
        batch = torch.nan_to_num(batch, nan=0.0, posinf=0.0, neginf=0.0)
        pt = get_click_prompt_eval({"image": batch}, opt_lite)

        if amp and device.type == "cuda":
            with torch.amp.autocast("cuda", enabled=True):
                pred = model(batch, pt, bbox=None)
                prob = torch.sigmoid(pred["masks"])
        else:
            pred = model(batch, pt, bbox=None)
            prob = torch.sigmoid(pred["masks"])

        if rotate_for_samihs:
            prob = torch.rot90(prob, k=1, dims=(-2, -1))
        prob_hw = F.interpolate(prob, (h, w), mode="bilinear", align_corners=False)
        prob_hw = torch.nan_to_num(prob_hw, nan=0.0, posinf=0.0, neginf=0.0)
        batch_mask = (prob_hw >= threshold).to(torch.uint8).squeeze(1).cpu().numpy()

        for bi, k in enumerate(range(k0, k1)):
            mask_hwd[:, :, k] = batch_mask[bi]

    return np.moveaxis(mask_hwd, -1, slice_axis) if slice_axis != 2 else mask_hwd


def segment_nii(
    input_nii: str | Path,
    output_nii: str | Path,
    ckpt: str | Path = DEFAULT_CKPT,
    samihs_root: str | Path = DEFAULT_SAMIHS_ROOT,
    device: str = "cuda:0",
    encoder_input_size: int = 1024,
    batch_size: int = 8,
    threshold: float = 0.5,
    slice_axis: str = "auto",
    amp: bool = True,
    clip_low: float = 0.5,
    clip_high: float = 99.5,
    rotate_for_samihs: bool = True,
) -> dict[str, Any]:
    """Segment input_nii and save output_nii. Returns metadata."""
    input_nii = Path(input_nii).resolve()
    output_nii = Path(output_nii).resolve()
    if not input_nii.exists():
        raise FileNotFoundError(f"input NIfTI not found: {input_nii}")

    img = nib.load(str(input_nii))
    volume = img.get_fdata(dtype=np.float32)
    axis = _select_slice_axis(tuple(int(x) for x in volume.shape), slice_axis)
    model, prompt_fn, device_obj = load_model(
        ckpt=ckpt,
        samihs_root=samihs_root,
        device=device,
        encoder_input_size=encoder_input_size,
    )
    mask = segment_array(
        volume=volume,
        model=model,
        get_click_prompt_eval=prompt_fn,
        device=device_obj,
        slice_axis=axis,
        encoder_input_size=encoder_input_size,
        batch_size=batch_size,
        threshold=threshold,
        amp=amp,
        clip_low=clip_low,
        clip_high=clip_high,
        rotate_for_samihs=rotate_for_samihs,
    )

    output_nii.parent.mkdir(parents=True, exist_ok=True)
    header = img.header.copy()
    header.set_data_dtype(np.uint8)
    nib.save(nib.Nifti1Image(mask.astype(np.uint8), img.affine, header), str(output_nii))

    zooms = img.header.get_zooms()[:3]
    voxel_volume_mm3 = float(np.prod(zooms)) if len(zooms) == 3 else float("nan")
    metadata = {
        "input_nii": str(input_nii),
        "output_nii": str(output_nii),
        "ckpt": str(Path(ckpt).resolve()),
        "samihs_root": str(Path(samihs_root).resolve()),
        "shape": list(volume.shape),
        "slice_axis": axis,
        "encoder_input_size": int(encoder_input_size),
        "batch_size": int(batch_size),
        "threshold": float(threshold),
        "mask_nonzero_voxels": int(mask.sum()),
        "voxel_volume_mm3_from_header": voxel_volume_mm3,
        "mask_volume_ml_from_header": float(mask.sum()) * voxel_volume_mm3 / 1000.0,
    }
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Segment a 3D brain CT NIfTI into a binary ICH mask NIfTI using SAMIHS.")
    parser.add_argument("--input", required=True, help="Input 3D CT NIfTI path (.nii or .nii.gz)")
    parser.add_argument("--output", required=True, help="Output binary mask NIfTI path (.nii.gz recommended)")
    parser.add_argument("--ckpt", default=str(DEFAULT_CKPT), help="SAMIHS checkpoint path")
    parser.add_argument("--samihs-root", default=str(DEFAULT_SAMIHS_ROOT), help="Original SAMIHS project root")
    parser.add_argument("--device", default="cuda:0", help="Torch device, e.g. cuda:0 or cpu")
    parser.add_argument("--encoder-input-size", type=int, default=1024, help="2D encoder input size")
    parser.add_argument("--batch-size", type=int, default=8, help="Slice-level batch size")
    parser.add_argument("--threshold", type=float, default=0.5, help="Probability threshold for binary mask")
    parser.add_argument("--slice-axis", default="auto", choices=["auto", "0", "1", "2"], help="Axis treated as slice/depth; auto uses smallest dimension")
    parser.add_argument("--clip-low", type=float, default=0.5, help="Per-slice lower percentile for intensity clipping")
    parser.add_argument("--clip-high", type=float, default=99.5, help="Per-slice upper percentile for intensity clipping")
    parser.add_argument("--no-amp", action="store_true", help="Disable CUDA mixed precision")
    parser.add_argument("--no-rotate", action="store_true", help="Disable SAMIHS rot90 pre/post correction")
    parser.add_argument("--metadata-json", default="", help="Optional path to write run metadata JSON")
    args = parser.parse_args()

    metadata = segment_nii(
        input_nii=args.input,
        output_nii=args.output,
        ckpt=args.ckpt,
        samihs_root=args.samihs_root,
        device=args.device,
        encoder_input_size=args.encoder_input_size,
        batch_size=args.batch_size,
        threshold=args.threshold,
        slice_axis=args.slice_axis,
        amp=not args.no_amp,
        clip_low=args.clip_low,
        clip_high=args.clip_high,
        rotate_for_samihs=not args.no_rotate,
    )

    if args.metadata_json:
        meta_path = Path(args.metadata_json).resolve()
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
