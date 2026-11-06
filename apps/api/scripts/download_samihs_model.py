"""Download the pinned pretrained SAMIHS inference package (no training)."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import snapshot_download

API_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = API_ROOT / "data" / "model-artifacts" / "samihs-ich-segmentation"
REPOSITORY = "MooreMuaMu/samihs-ich-segmentation"
REVISION = "29aaa12"


def main() -> None:
    path = snapshot_download(
        repo_id=REPOSITORY,
        revision=REVISION,
        local_dir=DEFAULT_TARGET,
        allow_patterns=[
            "segment_ich.py",
            "samihs_src/**",
            "weights/SAMIHS_09170527_2_0.483.pth",
            "requirements.txt",
            "INPUT_SPEC.md",
            "README.md",
        ],
    )
    print(f"Pinned pretrained SAMIHS package downloaded to: {path}")
    print("This script only downloads existing source and weights; it does not train or fine-tune.")


if __name__ == "__main__":
    main()
