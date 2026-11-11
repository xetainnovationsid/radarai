"""Vercel Python runtime entrypoint for the RADAR AI FastAPI application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from radar_api.main import app  # noqa: E402

__all__ = ["app"]
