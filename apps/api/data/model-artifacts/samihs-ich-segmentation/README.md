---
license: mit
tags:
  - medical-imaging
  - ct
  - segmentation
  - intracranial-hemorrhage
  - nifti
pipeline_tag: image-segmentation
---

# SAMIHS Intracranial Hemorrhage Segmentation

This repository packages the SAMIHS intracranial hemorrhage segmentation model used in the Medical project. It provides a simple interface:

```text
3D brain CT NIfTI -> binary hemorrhage mask NIfTI
```

The model is a 2D slice model. It processes each slice independently and stacks the predicted slices back into a 3D NIfTI mask.

## Files

| Path | Description |
|---|---|
| `segment_ich.py` | CLI/API wrapper for one 3D NIfTI input. |
| `weights/SAMIHS_09170527_2_0.483.pth` | Model checkpoint. |
| `samihs_src/models`, `samihs_src/utils` | Minimal SAMIHS source needed for inference. |
| `INPUT_SPEC.md` | Input format, intensity, and orientation requirements. |
| `requirements.txt` | Python dependencies. |

## Installation

```bash
git clone https://huggingface.co/<ORG_OR_USER>/<REPO_NAME>
cd <REPO_NAME>
pip install -r requirements.txt
```

Use a PyTorch/CUDA environment compatible with your GPU. In the original project this was tested with:

```text
/data/wxh/miniconda3/envs/flowmatching/bin/python
torch 2.8.0+cu128
```

## Usage

```bash
python segment_ich.py \
  --input /path/to/brain_ct.nii.gz \
  --output /path/to/brain_ct_ich_mask.nii.gz \
  --device cuda:0 \
  --batch-size 8 \
  --threshold 0.5
```

Output is a `uint8` NIfTI with the same shape and affine as the input. Values are `0` and `1`.

## Python API

```python
from segment_ich import segment_nii

metadata = segment_nii(
    input_nii="/path/to/brain_ct.nii.gz",
    output_nii="/path/to/brain_ct_ich_mask.nii.gz",
    device="cuda:0",
    batch_size=8,
    threshold=0.5,
)
print(metadata)
```

## Input Requirements

Read `INPUT_SPEC.md` before using the model. Key points:

- Input must be a single 3D NIfTI file, `.nii` or `.nii.gz`.
- DICOM folders, 4D NIfTI, and multi-channel images are not supported directly.
- The wrapper does not reorient based on NIfTI affine; it uses stored voxel array order.
- Default `--slice-axis auto` uses the smallest dimension as the slice/depth axis. Set `--slice-axis 0/1/2` explicitly if needed.
- Internally each slice is clipped to `[0.5, 99.5]` percentile and min-max normalized to `[0, 1]` before inference.

## Default Parameters

```text
encoder_input_size = 1024
batch_size = 8
threshold = 0.5
slice_axis = auto
amp = true
rotate_for_samihs = true
```

If CUDA OOM occurs, reduce `--batch-size` to `4`, `2`, or `1`.

## Validation

This packaged wrapper was checked against the existing project SAMIHS inference output on a 256x256x32 sample. The wrapper output matched the previous mask exactly, with zero differing voxels.
