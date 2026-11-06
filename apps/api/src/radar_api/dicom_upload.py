"""Size limits and streaming helpers for DICOM series uploads."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile

from radar_api.storage import PrivateImageStore

CHUNK_SIZE = 1024 * 1024

FORBIDDEN_MIME_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "application/javascript",
        "text/javascript",
        "image/svg+xml",
        "application/x-msdownload",
        "application/x-executable",
        "application/x-sh",
        "application/x-httpd-php",
    }
)

FORBIDDEN_MAGIC_PREFIXES = (
    b"MZ",
    b"\x7fELF",
    b"#!",
    b"<?php",
    b"<script",
    b"<!doctype html",
    b"<html",
    b"%PDF-",
    b"PK\x03\x04",
)


class UploadTooLarge(ValueError):
    """The upload exceeded a configured size or file-count limit."""


@dataclass(frozen=True)
class UploadLimits:
    max_file_bytes: int = 64 * 1024 * 1024
    max_series_bytes: int = 512 * 1024 * 1024
    max_files: int = 512
    max_pixels: int = 16_777_216

    @classmethod
    def from_environment(cls) -> "UploadLimits":
        defaults = cls()
        configured = {
            "max_file_bytes": ("RADAR_MAX_DICOM_FILE_BYTES", defaults.max_file_bytes),
            "max_series_bytes": ("RADAR_MAX_DICOM_SERIES_BYTES", defaults.max_series_bytes),
            "max_files": ("RADAR_MAX_DICOM_FILES", defaults.max_files),
            "max_pixels": ("RADAR_MAX_DICOM_PIXELS", defaults.max_pixels),
        }
        values: dict[str, int] = {}
        for field, (name, default) in configured.items():
            try:
                value = int(os.getenv(name, str(default)))
            except ValueError as error:
                raise RuntimeError(f"{name} must be a positive integer") from error
            if value <= 0:
                raise RuntimeError(f"{name} must be a positive integer")
            values[field] = value
        return cls(**values)


@dataclass(frozen=True)
class StagedUpload:
    path: Path
    size_bytes: int
    sha256: str


def _write_chunk(destination: BinaryIO, chunk: bytes, digest: "hashlib._Hash") -> None:
    destination.write(chunk)
    digest.update(chunk)


async def stage_upload(
    upload: UploadFile,
    store: PrivateImageStore,
    limits: UploadLimits,
    *,
    already_staged_bytes: int,
) -> StagedUpload:
    """Stream one multipart file into a private temporary file with bounded size."""

    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if content_type in FORBIDDEN_MIME_TYPES:
        raise ValueError("Forbidden file content type; only DICOM Part 10 files are accepted")

    descriptor, path = store.create_temporary_file()
    size_bytes = 0
    digest = hashlib.sha256()
    checked_header = False
    try:
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := await upload.read(CHUNK_SIZE):
                if not checked_header:
                    checked_header = True
                    head_lower = chunk[:32].lstrip().lower()
                    if any(chunk.startswith(prefix) for prefix in FORBIDDEN_MAGIC_PREFIXES) or any(
                        head_lower.startswith(prefix)
                        for prefix in (b"<!doctype html", b"<html", b"<script", b"<?php")
                    ):
                        raise ValueError("Upload contains forbidden executable or active content")
                size_bytes += len(chunk)
                if size_bytes > limits.max_file_bytes:
                    raise UploadTooLarge("DICOM file exceeds the per-file size limit")
                if already_staged_bytes + size_bytes > limits.max_series_bytes:
                    raise UploadTooLarge("DICOM series exceeds the total size limit")
                _write_chunk(destination, chunk, digest)
        if size_bytes == 0:
            raise ValueError("DICOM files must not be empty")
        return StagedUpload(path=path, size_bytes=size_bytes, sha256=digest.hexdigest())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
