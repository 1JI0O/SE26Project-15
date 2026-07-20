from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path

from fastapi import HTTPException

from app.core.config import settings


class BlobStore:
    def __init__(self, root: str | Path | None = None, tmp_root: str | Path | None = None) -> None:
        self.root = Path(root or settings.cloud_blob_root)
        self.tmp_root = Path(tmp_root or settings.cloud_tmp_root)
        self.quarantine = self.tmp_root / "quarantine"
        self.root.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)

    def temporary_path(self, blob_id: str) -> Path:
        return self.quarantine / f"{blob_id}.part"

    def content_path(self, sha256: str) -> Path:
        return self.root / "sha256" / sha256[:2] / sha256[2:4] / sha256

    def uploaded_bytes(self, blob_id: str) -> int:
        path = self.temporary_path(blob_id)
        return path.stat().st_size if path.exists() else 0

    def write_chunk(self, blob_id: str, index: int, content: bytes) -> int:
        if len(content) > settings.cloud_upload_chunk_bytes:
            raise HTTPException(status_code=413, detail="Chunk is too large")
        path = self.temporary_path(blob_id)
        expected_offset = index * settings.cloud_upload_chunk_bytes
        current = path.stat().st_size if path.exists() else 0
        if current != expected_offset:
            raise HTTPException(
                status_code=409,
                detail={"code": "chunk_offset_mismatch", "uploaded_bytes": current},
            )
        with path.open("ab") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        return current + len(content)

    def verify(self, blob_id: str, expected_size: int, expected_sha256: str, filename: str) -> Path:
        source = self.temporary_path(blob_id)
        if not source.is_file() or source.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail="Uploaded size does not match declaration")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise HTTPException(
                status_code=409, detail="Uploaded SHA-256 does not match declaration"
            )
        if filename.lower().endswith(".pdf"):
            with source.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise HTTPException(status_code=400, detail="Invalid PDF signature")
        if filename.lower().endswith(".zip"):
            self._validate_zip(source)
        return source

    def promote(self, source: Path, sha256: str) -> Path:
        destination = self.content_path(sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            source.unlink(missing_ok=True)
        else:
            os.replace(source, destination)
        return destination

    def disk_percent(self) -> float:
        usage = shutil.disk_usage(self.root)
        return usage.used / usage.total * 100 if usage.total else 100

    @staticmethod
    def _validate_zip(path: Path) -> None:
        try:
            with zipfile.ZipFile(path) as archive:
                total_uncompressed = 0
                for item in archive.infolist():
                    normalized = item.filename.replace("\\", "/")
                    if normalized.startswith("/") or ".." in Path(normalized).parts:
                        raise HTTPException(status_code=400, detail="ZIP contains an unsafe path")
                    total_uncompressed += item.file_size
                    if item.compress_size and item.file_size / item.compress_size > 200:
                        raise HTTPException(
                            status_code=400, detail="ZIP compression ratio is unsafe"
                        )
                    if total_uncompressed > settings.cloud_zip_max_bytes * 4:
                        raise HTTPException(
                            status_code=400, detail="ZIP expands beyond the safe limit"
                        )
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Invalid ZIP archive") from exc


blob_store = BlobStore()
