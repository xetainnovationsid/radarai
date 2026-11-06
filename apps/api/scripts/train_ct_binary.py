"""Train a research-only binary DenseNet121 CT slice classifier."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import random
import sys
import warnings
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np
import torch
from pydicom import dcmread
from pydicom.config import IGNORE, settings
from torch import Tensor, nn
from torch.optim import AdamW
from torchvision.models import DenseNet121_Weights, densenet121

from radar_api.ct_inference import (
    BINARY_LABELS,
    CHECKPOINT_SCHEMA,
    PREPROCESSING,
    preprocess_ct_array,
)
from radar_api.dicom_preprocessing import PreprocessingError, decode_and_window


@dataclass(frozen=True)
class LabeledSlice:
    path: Path
    label: int
    bag_name: str
    bag_label: int
    patient_id: str


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _dicom_path(split_dir: Path, name: str) -> Path:
    basename = Path(name.replace("\\", "/")).name
    if not Path(basename).suffix:
        basename = f"{basename}.dcm"
    path = split_dir / basename
    if not path.is_file():
        raise ValueError("A CSV image reference does not resolve to a DICOM file")
    return path


def _patient_and_study(path: Path) -> tuple[str, str]:
    logging.getLogger("pydicom.valuerep").setLevel(logging.ERROR)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        dataset = dcmread(path, stop_before_pixels=True, force=False)
    patient_id = str(getattr(dataset, "PatientID", "")).strip()
    study_uid = str(getattr(dataset, "StudyInstanceUID", "")).strip()
    if not patient_id or not study_uid:
        raise ValueError(
            "DICOM is missing PatientID or StudyInstanceUID required for grouped splits"
        )
    return patient_id, study_uid


def load_labeled_split(data_root: Path, split: str) -> list[LabeledSlice]:
    """Load labels and use one representative DICOM header per bag for grouping."""
    # The source has nonconforming UI values. Grouping still requires PatientID
    # and StudyInstanceUID fields, but this research runner doesn't validate UIDs.
    settings.reading_validation_mode = IGNORE
    csv_path = data_root / f"bags_{split}.csv"
    split_dir = data_root / "Brain_CT_data" / split
    rows = _read_csv(csv_path)
    required = {"instance_label", "instance_name", "bag_name", "bag_label"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{csv_path.name} must contain the expected instance and bag columns")

    records: list[LabeledSlice] = []
    bag_labels: dict[str, set[int]] = defaultdict(set)
    bag_instance_labels: dict[str, list[int]] = defaultdict(list)
    bag_identity: dict[str, tuple[str, str]] = {}
    path_labels: set[Path] = set()
    for row in rows:
        try:
            label = int(row["instance_label"])
            bag_label = int(row["bag_label"])
        except (KeyError, ValueError) as error:
            raise ValueError("CSV labels must be integer 0 or 1 values") from error
        if label not in (0, 1) or bag_label not in (0, 1):
            raise ValueError("CSV labels must be integer 0 or 1 values")
        bag_name = row["bag_name"].strip()
        if not bag_name:
            raise ValueError("Every slice must have a non-empty bag_name")
        path = _dicom_path(split_dir, row["instance_name"])
        if path in path_labels:
            raise ValueError("CSV contains a duplicate DICOM reference")
        path_labels.add(path)
        bag_labels[bag_name].add(bag_label)
        bag_instance_labels[bag_name].append(label)
        identity = bag_identity.get(bag_name)
        if identity is None:
            identity = _patient_and_study(path)
            bag_identity[bag_name] = identity
        records.append(
            LabeledSlice(
                path=path,
                label=label,
                bag_name=bag_name,
                bag_label=bag_label,
                patient_id=bag_identity[bag_name][0],
            )
        )

    for bag_name, labels in bag_labels.items():
        if len(labels) != 1:
            raise ValueError("Each bag must have exactly one consistent bag_label")
        patient_id, study_uid = bag_identity[bag_name]
        if not patient_id or not study_uid:
            raise ValueError("A bag is missing required DICOM patient/study identifiers")
        if max(bag_instance_labels[bag_name]) != next(iter(labels)):
            raise ValueError("bag_label must equal the maximum instance_label in that bag")
    return records


def grouped_validation_patients(
    records: list[LabeledSlice], *, fraction: float, seed: int
) -> set[str]:
    """Choose validation patients deterministically, stratified by bag-level label."""
    if not 0.05 <= fraction <= 0.4:
        raise ValueError("Validation fraction must be between 0.05 and 0.4")
    patient_label: dict[str, int] = defaultdict(int)
    for record in records:
        patient_label[record.patient_id] = max(
            patient_label[record.patient_id], record.bag_label
        )
    rng = random.Random(seed)
    validation: set[str] = set()
    for label in (0, 1):
        patients = [patient for patient, value in patient_label.items() if value == label]
        rng.shuffle(patients)
        count = max(1, round(len(patients) * fraction)) if len(patients) > 1 else 0
        validation.update(patients[:count])
    if validation == set(patient_label):
        raise ValueError("Grouped split left no training patients")
    return validation


def state_dict_sha256(state_dict: dict[str, Tensor]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(state_dict.items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(np.asarray(tensor.shape, dtype=np.int64).tobytes())
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def _auc(labels: list[int], scores: list[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(zip(scores, labels, strict=True), key=lambda pair: pair[0])
    rank_sum = 0.0
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][0] == ordered[start][0]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        rank_sum += average_rank * sum(label for _, label in ordered[start:end])
        start = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _metrics(labels: list[int], scores: list[float]) -> dict[str, float | None]:
    return {
        "auc": _auc(labels, scores),
        "accuracy_at_0_5": (
            sum((score >= 0.5) == bool(label) for label, score in zip(labels, scores, strict=True))
            / len(labels)
            if labels
            else None
        ),
    }


def _best_accuracy_threshold(labels: list[int], scores: list[float]) -> tuple[float, float]:
    """Select a study-level threshold using validation labels only."""
    if not labels or len(labels) != len(scores):
        raise ValueError("Threshold selection needs aligned, non-empty validation scores")
    candidates = sorted({0.0, 0.5, 1.0, *scores})
    scored = [
        (
            sum(
                (score >= threshold) == bool(label)
                for label, score in zip(labels, scores, strict=True)
            )
            / len(labels),
            threshold,
        )
        for threshold in candidates
    ]
    accuracy, threshold = max(scored, key=lambda pair: (pair[0], -abs(pair[1] - 0.5)))
    return threshold, accuracy


def _iter_model_batches(
    records: list[LabeledSlice],
    *,
    batch_size: int,
    seed: int,
    decode_errors: Counter[str],
) -> Iterator[tuple[Tensor, Tensor, tuple[str, ...]]]:
    order = np.arange(len(records))
    np.random.default_rng(seed).shuffle(order)
    images: list[Tensor] = []
    labels: list[float] = []
    bags: list[str] = []
    for index in order:
        record = records[int(index)]
        try:
            image = decode_and_window(record.path)
        except PreprocessingError as error:
            cause = type(error.__cause__).__name__ if error.__cause__ else "PreprocessingError"
            decode_errors[cause] += 1
            continue
        images.append(preprocess_ct_array(image))
        labels.append(float(record.label))
        bags.append(record.bag_name)
        if len(images) == batch_size:
            yield torch.stack(images), torch.tensor(labels), tuple(bags)
            images.clear()
            labels.clear()
            bags.clear()
    if images:
        yield torch.stack(images), torch.tensor(labels), tuple(bags)


def evaluate(
    model: nn.Module,
    records: list[LabeledSlice],
    *,
    batch_size: int,
    device: torch.device,
    seed: int,
) -> tuple[
    float,
    dict[str, float | None],
    dict[str, float | None],
    int,
    dict[str, int],
    list[int],
    list[float],
]:
    model.eval()
    total_loss = 0.0
    count = 0
    labels: list[int] = []
    probabilities: list[float] = []
    bag_probabilities: dict[str, float] = {}
    bag_labels: dict[str, int] = {}
    decode_errors: Counter[str] = Counter()
    with torch.inference_mode():
        for inputs_cpu, targets_cpu, batch_bags in _iter_model_batches(
            records,
            batch_size=batch_size,
            seed=seed,
            decode_errors=decode_errors,
        ):
            inputs = inputs_cpu.to(device)
            targets = targets_cpu.to(device=device, dtype=torch.float32)
            logits = model(inputs).squeeze(1)
            loss = nn.functional.binary_cross_entropy_with_logits(logits, targets)
            probs = torch.sigmoid(logits).cpu().tolist()
            ys = targets.cpu().to(torch.int64).tolist()
            total_loss += float(loss) * len(ys)
            count += len(ys)
            labels.extend(ys)
            probabilities.extend(probs)
            for study, label, probability in zip(batch_bags, ys, probs, strict=True):
                bag_probabilities[study] = max(bag_probabilities.get(study, 0.0), probability)
                bag_labels[study] = max(bag_labels.get(study, 0), label)
    if not count:
        raise ValueError("No decodable slices were available for evaluation")
    study_labels = list(bag_labels.values())
    study_scores = [bag_probabilities[name] for name in bag_labels]
    return (
        total_loss / max(1, count),
        _metrics(labels, probabilities),
        _metrics(study_labels, study_scores),
        count,
        dict(decode_errors),
        study_labels,
        study_scores,
    )


def _train_epoch(
    model: nn.Module,
    optimizer: AdamW,
    criterion: nn.Module,
    records: list[LabeledSlice],
    *,
    batch_size: int,
    device: torch.device,
    seed: int,
    log_every: int = 500,
) -> tuple[float, int, dict[str, int]]:
    model.train()
    total_loss = 0.0
    count = 0
    decode_errors: Counter[str] = Counter()
    batches = 0
    for inputs_cpu, targets_cpu, _ in _iter_model_batches(
        records,
        batch_size=batch_size,
        seed=seed,
        decode_errors=decode_errors,
    ):
        inputs = inputs_cpu.to(device)
        targets = targets_cpu.to(device=device, dtype=torch.float32)
        optimizer.zero_grad(set_to_none=True)
        logits = model(inputs).squeeze(1)
        loss = criterion(logits, targets)
        loss.backward()
        optimizer.step()
        total_loss += float(loss.detach()) * len(targets)
        count += len(targets)
        batches += 1
        if log_every > 0 and batches % log_every == 0:
            print(
                json.dumps(
                    {
                        "training_batches": batches,
                        "decoded_slices": count,
                        "loss": float(loss.detach()),
                    }
                ),
                flush=True,
            )
    if not count:
        raise ValueError("No decodable slices were available for training")
    return total_loss / count, count, dict(decode_errors)


def _count_labels(records: list[LabeledSlice]) -> dict[str, int]:
    return {
        "0": sum(record.label == 0 for record in records),
        "1": sum(record.label == 1 for record in records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Folder containing bags_*.csv and Brain_CT_data/",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/model-artifacts/ct-binary-densenet121.pt"),
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=Path("data/model-artifacts/ct-binary-metrics.json"),
    )
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--resume-checkpoint", type=Path)
    parser.add_argument("--log-every", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1 or args.learning_rate <= 0 or args.log_every < 0:
        parser.error(
            "epochs, batch size, and learning rate must be positive; "
            "log-every cannot be negative"
        )
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA was requested, but torch.cuda.is_available() is false")
    device = torch.device(args.device)
    try:
        train_records = load_labeled_split(args.data_root, "train")
        test_records = load_labeled_split(args.data_root, "test")
        train_patients = {record.patient_id for record in train_records}
        overlapping_patients = train_patients & {record.patient_id for record in test_records}
        test_before_purge = test_records
        test_records = [
            record for record in test_records if record.patient_id not in overlapping_patients
        ]
        if not test_records:
            raise ValueError("Removing train/test patient overlap left no independent test data")

        validation_patients = grouped_validation_patients(
            train_records, fraction=args.validation_fraction, seed=args.seed
        )
        training = [r for r in train_records if r.patient_id not in validation_patients]
        validation = [r for r in train_records if r.patient_id in validation_patients]
        if {r.patient_id for r in training} & {r.patient_id for r in validation}:
            raise RuntimeError("Patient leakage detected in the train/validation split")

        positive = sum(r.label == 1 for r in training)
        negative = len(training) - positive
        if positive == 0 or negative == 0:
            raise ValueError("Training partition must contain both labels")
        weights = DenseNet121_Weights.DEFAULT
        model = densenet121(weights=weights)
        pretrained_sha256 = state_dict_sha256(model.state_dict())
        model.classifier = nn.Linear(model.classifier.in_features, 1)
        start_epoch = 0
        best_validation_auc = -1.0
        best_validation_loss = float("inf")
        history: list[dict[str, object]] = []
        if args.resume_checkpoint:
            resume = torch.load(args.resume_checkpoint, map_location="cpu", weights_only=True)
            if resume.get("metadata", {}).get("labels") != list(BINARY_LABELS):
                raise ValueError("Resume checkpoint is not a compatible binary CT checkpoint")
            model.load_state_dict(resume["state_dict"], strict=True)
            pretrained_sha256 = resume["metadata"].get("weights_sha256", pretrained_sha256)
            if args.metrics_output.is_file():
                previous = json.loads(args.metrics_output.read_text(encoding="utf-8"))
                history = list(previous.get("epoch_history", []))
                best_epoch = int(previous.get("best_epoch", len(history)))
                best_row = next((row for row in history if row.get("epoch") == best_epoch), None)
                if best_row:
                    best_validation_auc = float(
                        best_row["validation_study_metrics"].get("auc") or -1.0
                    )
                    best_validation_loss = float(best_row.get("validation_loss", float("inf")))
                start_epoch = max((int(row.get("epoch", 0)) for row in history), default=0)
            print(f"Resuming from {args.resume_checkpoint} at epoch {start_epoch + 1}", flush=True)
        model.to(device)
        optimizer = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
        criterion = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([negative / positive], device=device, dtype=torch.float32)
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
        best_epoch = (
            int(best_epoch)
            if args.resume_checkpoint and args.metrics_output.is_file()
            else 0
        )
        for epoch in range(args.epochs):
            train_loss, train_decoded, train_decode_errors = _train_epoch(
                model,
                optimizer,
                criterion,
                training,
                batch_size=args.batch_size,
                device=device,
                seed=args.seed + start_epoch + epoch,
                log_every=args.log_every,
            )
            (
                validation_loss,
                validation_slice,
                validation_study,
                validation_decoded,
                validation_decode_errors,
                validation_study_labels,
                validation_study_scores,
            ) = evaluate(
                model,
                validation,
                batch_size=args.batch_size,
                device=device,
                seed=args.seed,
            )
            val_auc = validation_study["auc"]
            rank = float(val_auc) if val_auc is not None else -1.0
            improved = rank > best_validation_auc or (
                rank == best_validation_auc and validation_loss < best_validation_loss
            )
            row = {
                "epoch": start_epoch + epoch + 1,
                "train_loss": train_loss,
                "train_decoded_slices": train_decoded,
                "train_decode_failures": train_decode_errors,
                "validation_loss": validation_loss,
                "validation_decoded_slices": validation_decoded,
                "validation_decode_failures": validation_decode_errors,
                "validation_slice_metrics": validation_slice,
                "validation_study_metrics": validation_study,
            }
            history.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
            if improved:
                best_validation_auc = rank
                best_validation_loss = validation_loss
                best_epoch = start_epoch + epoch + 1
                metadata = {
                    "schema": CHECKPOINT_SCHEMA,
                    "model_id": "torchvision DenseNet121; ImageNet1K_V1 initialized and fine-tuned",
                    "training_data": "Brain_CT_data; binary instance labels from bags_train.csv",
                    "label_source": "RSNA_ICH bags_train.csv instance_label",
                    "label_semantics": {
                        "0": "No hemorrhage annotation on this slice",
                        "1": "Hemorrhage annotated present on this slice",
                    },
                    "weights_sha256": pretrained_sha256,
                    "labels": list(BINARY_LABELS),
                    "preprocessing": PREPROCESSING,
                    "patient_grouped_split": True,
                    "validation_patient_count": len(validation_patients),
                    "training_patient_count": len({r.patient_id for r in training}),
                }
                temporary_checkpoint = args.output.with_name(args.output.name + ".tmp")
                torch.save(
                    {"metadata": metadata, "state_dict": model.state_dict()},
                    temporary_checkpoint,
                )
                temporary_checkpoint.replace(args.output)

        checkpoint = torch.load(args.output, map_location=device, weights_only=True)
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        model.eval()

        (
            validation_loss,
            validation_slice_metrics,
            validation_study_metrics,
            validation_decoded,
            validation_decode_errors,
            validation_study_labels,
            validation_study_scores,
        ) = evaluate(
            model,
            validation,
            batch_size=args.batch_size,
            device=device,
            seed=args.seed,
        )

        (
            test_loss,
            test_slice_metrics,
            test_study_metrics,
            test_decoded,
            test_decode_errors,
            test_study_labels,
            test_study_scores,
        ) = evaluate(
            model,
            test_records,
            batch_size=args.batch_size,
            device=device,
            seed=args.seed,
        )
        threshold, validation_accuracy = _best_accuracy_threshold(
            validation_study_labels, validation_study_scores
        )
        test_accuracy_at_validation_threshold = sum(
            (score >= threshold) == bool(label)
            for label, score in zip(test_study_labels, test_study_scores, strict=True)
        ) / len(test_study_labels)
        results = {
            "scope": "research prototype; NOT FOR CLINICAL USE",
            "device": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu",
            "checkpoint": str(args.output.resolve()),
            "best_epoch": best_epoch,
            "test_patient_overlap_purged": len(overlapping_patients),
            "test_bags_before_purge": len({r.bag_name for r in test_before_purge}),
            "test_bags_after_purge": len({r.bag_name for r in test_records}),
            "test_slices_before_purge": len(test_before_purge),
            "test_slices_after_purge": len(test_records),
            "test_decoded_slices": test_decoded,
            "test_decode_failures": test_decode_errors,
            "train_slices": len(training),
            "validation_slices": len(validation),
            "train_label_counts": _count_labels(training),
            "validation_label_counts": _count_labels(validation),
            "test_label_counts": _count_labels(test_records),
            "selected_checkpoint_validation_loss": validation_loss,
            "selected_checkpoint_validation_decoded_slices": validation_decoded,
            "selected_checkpoint_validation_decode_failures": validation_decode_errors,
            "selected_checkpoint_validation_slice_metrics": validation_slice_metrics,
            "selected_checkpoint_validation_study_metrics": validation_study_metrics,
            "test_loss": test_loss,
            "test_slice_metrics": test_slice_metrics,
            "test_study_metrics_max_slice_score": test_study_metrics,
            "validation_selected_study_threshold": threshold,
            "validation_study_accuracy_at_selected_threshold": validation_accuracy,
            "test_study_accuracy_at_validation_selected_threshold": (
                test_accuracy_at_validation_threshold
            ),
            "epoch_history": history,
            "warning": "Scores are experimental and are not clinically validated.",
        }
        args.metrics_output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        summary = {key: value for key, value in results.items() if key != "epoch_history"}
        print(json.dumps(summary, sort_keys=True))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Training failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

