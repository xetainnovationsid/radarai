# CT inference baseline and handoff

**RADAR AI / RDA-2 — Sprint 1**  
**Prepared:** 2026-10-26 (WIB)  
**Status:** Local binary baseline trained; local web inference wired; class semantics remain unconfirmed
**Scope:** Research prototype only — **NOT FOR CLINICAL USE**

## Runner

`apps/api/src/radar_api/ct_inference.py` and `apps/api/scripts/score_ct.py` provide an offline
DenseNet121 runner for binary and six-label checkpoints. The API can also score an uploaded study
with a configured binary checkpoint through `GET /v1/studies/{study_id}/scores`. The runner:

- Loads only an operator-supplied local checkpoint, with no weight downloads or fallback model.
- Requires a strict DenseNet121 state dict with six outputs in the documented label order:
  `any`, `epidural`, `intraparenchymal`, `intraventricular`, `subarachnoid`, `subdural`.
- Uses `decode_and_window` from the ingestion handoff, resizes each grayscale CT window to 224 × 224,
  repeats it across three channels, and applies ImageNet mean/std normalization.
- Runs sigmoid on the six model logits and writes per-slice scores, model metadata, device,
  preprocessing configuration, and the checkpoint file SHA-256 to JSON.
- Defaults to CUDA and fails clearly if CUDA is unavailable. CPU is available for local plumbing.

The output values are checkpoint-derived model scores. The runner does not certify that the supplied
checkpoint was trained correctly, that scores are calibrated, or that the model is suitable for any
medical decision. The checkpoint must come from the authorized modeling workstream and remain in
approved private storage; do not check weights into Git or attach them to a public PR.

## Checkpoint contract

The input is a `torch.save` mapping with these top-level keys:

```python
{
    "metadata": {
        "schema": "radar-ai.densenet121-ich-checkpoint/v1",
        "model_id": "<model and revision>",
        "training_data": "<authorized dataset and version>",
        "weights_sha256": "<source weights SHA-256>",
        "preprocessing": {
            "dicom_window_center": 40.0,
            "dicom_window_width": 80.0,
            "resize": 224,
            "channels": "grayscale_repeated_rgb",
            "normalization": "ImageNet mean/std"
        },
        "labels": [
            "any", "epidural", "intraparenchymal", "intraventricular",
            "subarachnoid", "subdural"
        ]
    },
    "state_dict": model.state_dict()
}
```

The model is torchvision DenseNet121 with its classifier replaced by a six-output linear layer.
The runner rejects checkpoints whose preprocessing metadata differs from its versioned 40/80 CT
window, 224-pixel resize, repeated-RGB, ImageNet-normalized input contract.
Load checkpoints with `torch.load(..., weights_only=True)` compatibility. No example checkpoint is
created here because random weights would generate meaningless scores and would violate the
no-fabricated-predictions requirement.

## Run offline

Install PyTorch and torchvision builds compatible with the workstation's CUDA driver, then install
the API requirements. On a 3050-equipped workstation, confirm `torch.cuda.is_available()` before
running; select `--device cuda` (the default). Once the checkpoint and fixture DICOMs are already on
disk, inference has no network dependency:

```powershell
cd apps/api
$env:PYTHONPATH = "src"
python scripts/score_ct.py `
  --checkpoint "D:\radar-private\ich-densenet121.pt" `
  --input "D:\radar-private\reference-ct" `
  --output "D:\radar-private\reference-scores.json" `
  --device cuda
```

The input directory currently expects `*.dcm` files. Pass a single DICOM path to score one slice.
Do not place patient data, fixtures, labels, or output score files in this repository.

## Web viewer integration

The local API lazily loads `data/model-artifacts/ct-binary-densenet121.pt` relative to `apps/api`.
Override the path with `RADAR_CT_CHECKPOINT`; `RADAR_CT_DEVICE=auto` selects CUDA when available and
otherwise uses CPU. The checkpoint is ignored by Git and must be placed on each API host locally.
When the viewer opens a study, it requests per-slice class scores from the API and shows the highest
class-1 slice as navigable evidence. Missing or incompatible checkpoints return an explicit
unavailable status; the UI does not invent scores.

The local `bags_train.csv` follows the TorchMIL `RSNA_ICH` bag format and provides per-slice
`instance_label` values. TorchMIL documents this dataset as an adaptation of RSNA Intracranial
Hemorrhage Detection: `slice_label=1` means the slice contains evidence of hemorrhage, while
`slice_label=0` is negative. The model's class 1 is therefore mapped to the dataset's positive
hemorrhage annotation target; it is not a confirmed finding on a newly uploaded scan. Scores remain
uncalibrated research outputs, are not diagnostic, and are not automatically persisted as findings.
See the [TorchMIL RSNA dataset documentation](https://torchmil.readthedocs.io/en/main/api/datasets/rsnamil_dataset/)
and its [CT classification example](https://torchmil.readthedocs.io/en/main/examples/ctscan_classification/).

## Evidence and dependent-workstream handoff

The local binary checkpoint was trained and scored on an NVIDIA GeForce RTX 3050 6GB Laptop GPU.
The private checkpoint, CT files, and detailed metrics remain in the ignored local
`apps/api/data/model-artifacts/` directory and are not source-controlled. The summary below records
one experiment only; it does not establish clinical performance or external validity. Dataset
terms and the RSNA reference profile are tracked in
[`rsna-ich-licensing-and-profile.md`](./rsna-ich-licensing-and-profile.md). The prototype remains
**NOT FOR CLINICAL USE**.

## Local binary dataset training

For a local dataset that supplies binary per-slice labels in `bags_train.csv` and `bags_test.csv`,
use `apps/api/scripts/train_ct_binary.py`. The script initializes DenseNet121 from torchvision's
ImageNet1K_V1 weights, fine-tunes a one-logit classifier with weighted binary cross entropy, and
uses the same 40/80 window and 224-pixel normalization as the inference runner. It splits internal
validation by DICOM `PatientID`, aggregates maximum slice score by bag for study-level metrics, and
removes any patient found on both the train and test lists from the test metrics. It writes the
checkpoint and aggregate metrics under the ignored local `apps/api/data/model-artifacts/` directory.

Example from `apps/api`:

```powershell
$env:PYTHONPATH = "src"
python scripts/train_ct_binary.py `
  --data-root "C:\Users\<user>\Downloads\radar-private" `
  --device cuda `
  --epochs 3 `
  --batch-size 4
```

The local profile found 34,496 train slices and 5,254 test slices. The four CSVs map to the DICOM
filenames; labels are binary 0/1 and `bag_label` equals the maximum instance label for each bag.
There are 1,000 train bags and 150 test bags. Three patients occur in both official splits, so the
script excludes those three test bags (109 slices) before reporting test metrics. Ten training
slices failed pixel-data decoding and were counted and skipped; the source files were not changed.

The initial one-epoch RTX 3050 run used the ImageNet1K_V1 DenseNet121 weights and a
patient-grouped validation split. Its 0.5-threshold study accuracy was 0.497, so fine-tuning was
continued for two epochs from that checkpoint with a lower learning rate. The best checkpoint was
epoch 2 by validation study AUROC. On the patient-overlap-purged holdout (5,145 slices / 147 bags),
it reached study AUROC 0.945. At a fixed 0.5 threshold, study accuracy was 0.701. Selecting a
threshold of 0.9487 on the validation studies (90.4% validation accuracy) gave 0.864 test study
accuracy, with 0.743 sensitivity and 0.974 specificity (52 TP, 18 FN, 75 TN, 2 FP). The test set
was not used to choose the threshold. Slice-level test AUROC was 0.949 and slice accuracy at 0.5
was 0.883. These are results from one small holdout evaluation, not a guarantee of performance or
clinical validation. The sensitivity means this operating point missed 18 of 70 positive studies.
A one-slice inference smoke run also loaded the checkpoint offline on CUDA and wrote a real model
score locally.

The checkpoint and per-fixture score JSON are in the ignored local `apps/api/data/model-artifacts/`
folder and must not be committed or shared. This dataset profile is local workspace evidence, not a
source or licensing determination. Confirm that label `1` has the intended meaning and check the
dataset's own usage terms before interpreting or sharing results.



