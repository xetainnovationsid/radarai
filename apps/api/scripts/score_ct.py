"""Run offline DenseNet121 scoring against local DICOM slices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pydicom.config import IGNORE, settings

from radar_api.ct_inference import InferenceError, load_checkpoint, score_dicom_files, write_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path, help="Local trained checkpoint")
    parser.add_argument("--input", required=True, type=Path, help="DICOM file or directory")
    parser.add_argument("--output", required=True, type=Path, help="JSON output path")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--window-center", type=float, default=40.0)
    parser.add_argument("--window-width", type=float, default=80.0)
    args = parser.parse_args()
    # Match the local training runner: this research source has nonconforming UI values.
    settings.reading_validation_mode = IGNORE

    paths = sorted(args.input.glob("*.dcm")) if args.input.is_dir() else [args.input]
    if not paths or any(not path.is_file() for path in paths):
        parser.error("--input must identify an existing DICOM file or a directory of *.dcm files")
    try:
        model, metadata, checkpoint_sha256 = load_checkpoint(args.checkpoint, device=args.device)
        scores = score_dicom_files(
            model,
            paths,
            device=args.device,
            center=args.window_center,
            width=args.window_width,
        )
        write_results(
            args.output,
            checkpoint_path=args.checkpoint,
            checkpoint_metadata=metadata,
            checkpoint_sha256=checkpoint_sha256,
            scores=scores,
            device=args.device,
            center=args.window_center,
            width=args.window_width,
        )
    except (InferenceError, OSError, ValueError) as error:
        print(f"Inference failed: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {len(scores)} real model score rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

