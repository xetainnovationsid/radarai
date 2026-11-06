# RADAR AI research model card

## Model and intended use

The API runner supports an operator-provided DenseNet121 checkpoint for binary RSNA intracranial
hemorrhage slice-label scores. The checkpoint contract and preprocessing are versioned in
`apps/api/src/radar_api/ct_inference.py` and documented in `docs/ct-inference-handoff.md`.
Outputs are experimental research scores. They are not diagnoses, not calibrated probabilities,
and must not be used for clinical decisions.

## Data and limitations

The checkpoint and source CT data are not distributed with this repository. Dataset licensing,
patient-level separation, model training evidence, and validation limits are recorded in
`docs/rsna-ich-licensing-and-profile.md` and `docs/ct-inference-handoff.md`. Operators must verify
the dataset license and local checkpoint provenance before use. The model has not been validated
for clinical use or generalization to an external site.

## Reproducibility and provenance

The API stores model ID, checkpoint SHA-256, preprocessing version, device, per-slice subtype
scores, evidence slice IDs, and a model version ID with each completed analysis. Jobs report a
failed state if the configured local checkpoint cannot be loaded or applied. The repository ships
no checkpoint; a deployment without one can still demonstrate upload, job failure recovery, human
review flows for synthetic fixtures, and manual report drafting.

## Human oversight

Findings begin in `pending` state. A human reviewer must explicitly accept, reject, or mark them
uncertain. Report drafts remain unsigned and cite their source finding IDs. The UI and API identify
this system as a research prototype, not for clinical use.
