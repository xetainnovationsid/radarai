# Input Specification

This wrapper accepts one 3D brain CT NIfTI and writes one binary intracranial hemorrhage mask NIfTI. The model is a 2D slice SAMIHS model, so input array order and slice direction matter.

## Required Format

| Item | Requirement |
|---|---|
| File type | NIfTI, `.nii` or `.nii.gz`. DICOM folders are not accepted directly. |
| Dimensionality | Exactly 3D. 4D/time-series/multi-channel files are not supported. |
| Pixel data | Single-channel numeric CT-like image. Integer or float is acceptable. |
| Invalid values | Avoid NaN/Inf. The model was tested on finite CT volumes. |
| Output geometry | Output mask uses the same shape, affine, and header geometry as input. |
| Output values | `uint8` binary label, values `0` and `1`. |

## Recommended Image Domain

The model has been used and validated mainly on the project-standard brain CT volumes, for example:

```text
/data2/gzk/256_standardized_brain_rescale/**/*.nii
/data2/wxh/Medical/.../euler10/two_stage/nii/sample_*/real.nii.gz
/data2/wxh/Medical/.../euler10/two_stage/nii/sample_*/gen.nii.gz
```

Recommended input characteristics:

- Axial brain CT volume, already converted to NIfTI.
- Brain/head is centered and roughly aligned like the project data.
- Typical in-plane size is `256x256` or `512x512`; other sizes are resized slice-wise to `1024x1024` for the model.
- Typical slice count is much smaller than in-plane dimensions, e.g. `16-180` slices.
- CT contrast should be similar to the training/evaluation data. Raw HU-like or project windowed CT-like values are acceptable because the wrapper performs per-slice percentile clipping and min-max normalization before inference.

## Intensity Handling

The model does not threshold raw HU values directly. For each 2D slice, the wrapper does:

```text
clip slice to [0.5 percentile, 99.5 percentile]
min-max normalize clipped slice to [0, 1]
resize to 1024x1024
run SAMIHS
sigmoid(logits) >= 0.5 -> binary mask
```

Implications:

- Absolute HU scale is not preserved inside the model input.
- A globally rescaled CT can still run if local contrast is similar.
- Strongly different preprocessing can hurt results: inverted contrast, aggressive z-score normalization, heavily saturated windows, full-body/non-brain CT, or large black borders may cause domain shift.

## Direction and Axis Requirements

The wrapper does not reorient the NIfTI based on affine orientation. It reads the voxel array as stored and processes 2D slices along one axis.

Default behavior:

```text
--slice-axis auto
```

`auto` chooses the smallest dimension as the slice/depth axis. This is correct for common project volumes such as:

```text
(256, 256, 32) -> slice_axis = 2
(512, 512, 32) -> slice_axis = 2
(32, 512, 512) -> slice_axis = 0
```

If the depth axis is not the smallest dimension, set it explicitly:

```bash
--slice-axis 0
--slice-axis 1
--slice-axis 2
```

The original SAMIHS inference convention includes a 90-degree slice rotation before inference and the inverse rotation after inference. This wrapper keeps that behavior by default. Do not use `--no-rotate` unless you are testing a known different orientation convention.

## Practical Sanity Checks

After inference, check at least these properties:

```text
mask.shape == input.shape
mask affine == input affine
unique(mask) is subset of {0, 1}
mask nonzero voxel count is clinically plausible for the case
overlay mask on input CT to confirm left/right and anterior/posterior alignment
```

If the mask appears mirrored or rotated in an overlay, first verify:

- Whether `--slice-axis` is correct.
- Whether the input was transposed or reoriented before calling the wrapper.
- Whether `--no-rotate` was accidentally used.
- Whether the input follows the same orientation convention as the project-standard CT volumes.

## Known Limitation

This is not a 3D model. It segments each slice independently and stacks the results into a 3D mask. It does not use through-plane context, and it does not enforce 3D connectedness or temporal consistency.
