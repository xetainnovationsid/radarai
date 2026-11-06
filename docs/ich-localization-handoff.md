# Pretrained ICH localization handoff

RADAR's existing DenseNet121 remains the slice-level RSNA-label scorer. A separate, optional
SAMIHS binary segmentation model now supplies the lesion-area mask from which the viewer draws a
bounding box. The app does not derive a box from the DenseNet score, and it does not generate one
when the pretrained localizer is unavailable.

## Provisioning (no training)

The model package is pinned to Hugging Face revision `29aaa12`. Download its source and existing
checkpoint into the API's ignored `data/model-artifacts` directory:

```powershell
cd apps/api
python -m pip install -r requirements.txt
python scripts/download_samihs_model.py
```

For an NVIDIA GPU on Windows, install a CUDA-enabled PyTorch build after the base API requirements.
The CUDA 13.0 wheel was used with the RTX 3050 in this workspace:

```powershell
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
python -m pip install -r data/model-artifacts/samihs-ich-segmentation/requirements.txt
```

The downloader fetches the inference wrapper, its minimal SAMIHS source, the published checkpoint,
and the model package's `requirements.txt`. It never runs training or fine-tuning. The checkpoint
is about 376 MB and is not committed. Check its requirements before installing them; keep the
PyTorch/CUDA build compatible with the local GPU. The app's current default model root is
`apps/api/data/model-artifacts/samihs-ich-segmentation`. Override it with
`RADAR_ICH_SEGMENTATION_ROOT` and restart the API after provisioning.

For offline use, complete the one-time package/dependency download before disconnecting. Inference
then reads the local weights only. The upstream package recommends brain CT volumes with about
16–180 slices and processes each slice independently. A one-slice upload may validly produce an
empty mask; the application shows no box for an empty mask.
On an RTX 3050, begin with
`RADAR_ICH_SEGMENTATION_BATCH_SIZE=1`; use `RADAR_ICH_SEGMENTATION_DEVICE=auto` to select CUDA when
PyTorch reports it available, or set `cpu` explicitly. The default mask cutoff is 0.5 and can be
changed with `RADAR_ICH_SEGMENTATION_THRESHOLD`.

## API and viewer

`GET /v1/studies/{study_id}/localizations` runs the pretrained segmenter on the uploaded ordered
CT volume and returns per-slice normalized boxes, mask pixel counts, device, threshold, and the
checkpoint SHA-256. The viewer draws a box only when the model returns a non-empty mask. Results
are cached in process memory by the immutable private DICOM storage paths; no mask or image is
written to the public web tree.

Multi-slice series must have consistent orientation, dimensions, and increasing physical slice
positions. A single CT image can be localized without series geometry. Unsupported geometry,
missing weights, or inference errors yield an explicit unavailable response instead of a fabricated
box. The SAMIHS package expects CT-like intensities and its own per-slice normalization; the adapter
passes DICOM values after applying Rescale Slope/Intercept.

## Limits

The mask is binary “ICH area” localization, not a subtype diagnosis, radiology report, or volume
estimate. The published package is MIT-licensed and describes its output as research use; its
wrapper reports matching one existing sample, while the underlying SAMIHS work is research. There
is no project-specific external validation on RADAR's uploaded data. The box is a bounding envelope
around all mask pixels in that slice, so separate mask regions may be enclosed by one box. This is
prototyping only and not for clinical use.
