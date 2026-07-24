from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings


def save_upload(project_id: int, artifact_type: str, upload: UploadFile) -> Path:
    upload_dir = Path(settings.upload_root) / f"project-{project_id}" / artifact_type
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "").suffix.lower()
    path = upload_dir / f"{uuid4().hex}{suffix}"
    with path.open("wb") as target:
        while chunk := upload.file.read(1024 * 1024):
            target.write(chunk)
    upload.file.seek(0)
    return path
