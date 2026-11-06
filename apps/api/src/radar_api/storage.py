"""Private local storage for uploaded DICOM assets."""

import os
import tempfile
from pathlib import Path
from uuid import UUID


class PrivateImageStore:
    """Store images below a non-public root using generated, path-safe keys."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured_root = root or os.getenv("RADAR_STORAGE_DIR", "data/private-images")
        self.root = Path(configured_root).expanduser().resolve()

    def prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)

    def create_temporary_file(self) -> tuple[int, Path]:
        self.prepare()
        descriptor, name = tempfile.mkstemp(prefix="incoming-", suffix=".tmp", dir=self.root)
        path = Path(name)
        if os.name != "nt":
            path.chmod(0o600)
        return descriptor, path

    @staticmethod
    def storage_key(study_id: UUID, image_asset_id: UUID) -> str:
        """Build a storage key exclusively from server-generated UUIDs."""

        return f"{study_id.hex}/{image_asset_id.hex}.dcm"

    def path_for(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage key resolves outside the private root")
        return path

    def publish(self, temporary_path: Path, storage_key: str) -> Path:
        destination = self.path_for(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            destination.parent.chmod(0o700)
        if destination.exists():
            raise FileExistsError("Generated storage key already exists")
        os.replace(temporary_path, destination)
        if os.name != "nt":
            destination.chmod(0o600)
        return destination

    def delete(self, storage_key: str) -> None:
        try:
            self.path_for(storage_key).unlink(missing_ok=True)
        except (OSError, ValueError):
            # Cleanup must not mask the validation or database error that caused it.
            return
