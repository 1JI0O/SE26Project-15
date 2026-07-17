from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import text
from sqlmodel import Session, func, select

from app.api.routes.cloud_access import require_cloud_sync_feature, require_workspace_access
from app.auth.dependencies import CurrentIdentity, require_verified
from app.auth.service import audit
from app.core.config import settings
from app.db.session import get_session
from app.models.cloud_entities import (
    BackgroundJob,
    BlobContent,
    BlobObject,
    BlobReference,
    CloudProject,
    DeviceProjectBinding,
    UploadSession,
    Workspace,
)
from app.models.entities import utc_now
from app.schemas.cloud import BlobCompleteRead, BlobUploadInit, BlobUploadInitRead
from app.storage.blob_store import blob_store

router = APIRouter(
    prefix="/blobs",
    tags=["cloud-blobs"],
    dependencies=[Depends(require_cloud_sync_feature)],
)


def _reserved_usage(session: Session, workspace_id: str, project_id: str | None = None) -> int:
    statement = select(func.coalesce(func.sum(BlobObject.byte_size), 0)).where(
        BlobObject.workspace_id == workspace_id,
        BlobObject.status.in_(["uploading", "ready"]),
    )
    if project_id:
        statement = statement.where(BlobObject.project_public_id == project_id)
    return int(session.exec(statement).one())


def _project_referenced_usage(session: Session, workspace_id: str, project_id: str) -> int:
    blob_ids = set(
        session.exec(
            select(BlobReference.blob_id).where(
                BlobReference.workspace_id == workspace_id,
                BlobReference.project_public_id == project_id,
                BlobReference.deleted_at.is_(None),
            )
        ).all()
    )
    return sum(
        item.byte_size
        for blob_id in blob_ids
        if (item := session.get(BlobObject, blob_id)) is not None and item.status == "ready"
    )


def _lock_content_hash(session: Session, sha256: str) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    key = int(sha256[:16], 16)
    if key >= 2**63:
        key -= 2**64
    session.exec(text("SELECT pg_advisory_xact_lock(:key)").bindparams(key=key))


def _validate_upload(payload: BlobUploadInit) -> None:
    lower = payload.filename.lower()
    source_extensions = {
        ".c",
        ".cc",
        ".cpp",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
    }
    if lower.endswith(".pdf"):
        if payload.byte_size > settings.cloud_pdf_max_bytes:
            raise HTTPException(status_code=413, detail="PDF exceeds the configured limit")
        if payload.mime_type not in {"application/pdf", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail="Invalid PDF MIME type")
    elif lower.endswith(".zip"):
        if payload.byte_size > settings.cloud_zip_max_bytes:
            raise HTTPException(status_code=413, detail="ZIP exceeds the configured limit")
        if payload.mime_type not in {
            "application/zip",
            "application/x-zip-compressed",
            "application/octet-stream",
        }:
            raise HTTPException(status_code=415, detail="Invalid ZIP MIME type")
    else:
        suffix = Path(lower).suffix
        if suffix not in source_extensions and lower not in {"dockerfile", "makefile"}:
            raise HTTPException(status_code=415, detail="Unsupported attachment extension")
        if payload.byte_size > settings.cloud_zip_max_bytes:
            raise HTTPException(status_code=413, detail="Attachment exceeds the configured limit")


def _get_blob_for_user(
    session: Session,
    identity: CurrentIdentity,
    blob_id: str,
    role: str = "viewer",
) -> BlobObject:
    item = session.get(BlobObject, blob_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Blob not found")
    require_workspace_access(session, identity, item.workspace_id, role)
    return item


@router.post("/upload-init", response_model=BlobUploadInitRead)
def upload_init(
    payload: BlobUploadInit,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> BlobUploadInitRead:
    require_workspace_access(session, identity, payload.workspace_id, "editor")
    _validate_upload(payload)
    workspace = session.exec(
        select(Workspace).where(Workspace.workspace_id == payload.workspace_id).with_for_update()
    ).one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if payload.project_public_id:
        project = session.get(CloudProject, payload.project_public_id)
        if (
            project is None
            or project.workspace_id != payload.workspace_id
            or project.sync_mode != "cloud_enabled"
            or project.deleted_at is not None
        ):
            raise HTTPException(status_code=409, detail="Project is not accepting uploads")
        binding = session.exec(
            select(DeviceProjectBinding).where(
                DeviceProjectBinding.device_id == identity.device_id,
                DeviceProjectBinding.project_public_id == payload.project_public_id,
            )
        ).first()
        if binding is None or binding.sync_mode != "cloud_enabled":
            raise HTTPException(status_code=409, detail="This device has paused project sync")
    existing = session.exec(
        select(BlobObject).where(
            BlobObject.workspace_id == payload.workspace_id,
            BlobObject.sha256 == payload.sha256,
        )
    ).first()
    if existing is not None:
        if existing.status == "failed":
            blob_store.temporary_path(existing.blob_id).unlink(missing_ok=True)
            session.delete(existing)
            session.flush()
            existing = None
    if existing is not None:
        if existing.status == "ready":
            if payload.project_public_id:
                already_referenced = session.exec(
                    select(BlobReference).where(
                        BlobReference.workspace_id == payload.workspace_id,
                        BlobReference.project_public_id == payload.project_public_id,
                        BlobReference.blob_id == existing.blob_id,
                        BlobReference.deleted_at.is_(None),
                    )
                ).first()
                if (
                    already_referenced is None
                    and _project_referenced_usage(
                        session, payload.workspace_id, payload.project_public_id
                    )
                    + existing.byte_size
                    > settings.cloud_project_quota_bytes
                ):
                    raise HTTPException(status_code=413, detail="Project storage quota exceeded")
            return BlobUploadInitRead(
                blob_id=existing.blob_id,
                status="reuse",
                chunk_size=settings.cloud_upload_chunk_bytes,
                uploaded_bytes=existing.byte_size,
            )
        if existing.created_by != identity.user_id:
            raise HTTPException(status_code=409, detail="Matching upload is already in progress")
        return BlobUploadInitRead(
            blob_id=existing.blob_id,
            status="upload",
            chunk_size=settings.cloud_upload_chunk_bytes,
            uploaded_bytes=blob_store.uploaded_bytes(existing.blob_id),
        )
    if (
        _reserved_usage(session, payload.workspace_id) + payload.byte_size
        > workspace.storage_limit_bytes
    ):
        raise HTTPException(status_code=413, detail="Workspace storage quota exceeded")
    if (
        payload.project_public_id
        and _reserved_usage(session, payload.workspace_id, payload.project_public_id)
        + payload.byte_size
        > settings.cloud_project_quota_bytes
    ):
        raise HTTPException(status_code=413, detail="Project storage quota exceeded")
    if blob_store.disk_percent() >= settings.cloud_disk_stop_percent:
        raise HTTPException(status_code=507, detail="Server storage threshold reached")
    item = BlobObject(
        workspace_id=payload.workspace_id,
        project_public_id=payload.project_public_id,
        sha256=payload.sha256,
        byte_size=payload.byte_size,
        mime_type=payload.mime_type,
        filename=payload.filename,
        created_by=identity.user_id,
    )
    session.add(item)
    session.add(
        UploadSession(
            blob_id=item.blob_id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    audit(
        session,
        "blob.upload_init",
        actor_id=identity.user_id,
        workspace_id=payload.workspace_id,
        target=item.blob_id,
        metadata={"byte_size": payload.byte_size, "mime_type": payload.mime_type},
    )
    session.commit()
    return BlobUploadInitRead(
        blob_id=item.blob_id,
        status="upload",
        chunk_size=settings.cloud_upload_chunk_bytes,
    )


@router.put("/{blob_id}/chunks/{index}")
async def upload_chunk(
    blob_id: str,
    index: int,
    request: Request,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    if index < 0:
        raise HTTPException(status_code=422, detail="Chunk index must be non-negative")
    item = _get_blob_for_user(session, identity, blob_id, "editor")
    if item.status != "uploading" or item.created_by != identity.user_id:
        raise HTTPException(status_code=409, detail="Blob is not accepting chunks")
    content = await request.body()
    uploaded = blob_store.write_chunk(blob_id, index, content)
    if uploaded > item.byte_size:
        blob_store.temporary_path(blob_id).unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="Upload exceeds declared size")
    upload_session = session.exec(
        select(UploadSession).where(UploadSession.blob_id == blob_id)
    ).first()
    if upload_session is not None:
        upload_session.uploaded_bytes = uploaded
        session.add(upload_session)
        session.commit()
    return {"uploaded_bytes": uploaded}


@router.post("/{blob_id}/complete", response_model=BlobCompleteRead)
def complete_upload(
    blob_id: str,
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> BlobCompleteRead:
    item = _get_blob_for_user(session, identity, blob_id, "editor")
    if item.status == "ready":
        return BlobCompleteRead(
            blob_id=item.blob_id, status=item.status, sha256=item.sha256, byte_size=item.byte_size
        )
    if item.created_by != identity.user_id:
        raise HTTPException(status_code=403, detail="Upload owner required")
    try:
        source = blob_store.verify(item.blob_id, item.byte_size, item.sha256, item.filename)
    except HTTPException:
        blob_store.temporary_path(item.blob_id).unlink(missing_ok=True)
        item.status = "failed"
        session.add(item)
        session.commit()
        raise
    destination = blob_store.promote(source, item.sha256)
    _lock_content_hash(session, item.sha256)
    content = session.exec(
        select(BlobContent).where(BlobContent.sha256 == item.sha256).with_for_update()
    ).first()
    if content is None:
        content = BlobContent(
            sha256=item.sha256,
            byte_size=item.byte_size,
            mime_type=item.mime_type,
            storage_key=str(destination.relative_to(blob_store.root)),
            physical_ref_count=1,
        )
    else:
        if content.byte_size != item.byte_size:
            raise HTTPException(status_code=409, detail="Blob hash metadata mismatch")
        content.physical_ref_count += 1
    session.add(content)
    session.flush()
    item.content_id = content.content_id
    item.storage_key = str(destination.relative_to(blob_store.root))
    item.status = "ready"
    item.completed_at = utc_now()
    session.add(item)
    upload_session = session.exec(
        select(UploadSession).where(UploadSession.blob_id == item.blob_id)
    ).first()
    if upload_session is not None:
        session.delete(upload_session)
    job_type = (
        "parse_paper"
        if item.filename.lower().endswith(".pdf")
        else "analyze_code"
        if item.filename.lower().endswith(".zip")
        else None
    )
    if job_type is not None:
        session.add(
            BackgroundJob(
                workspace_id=item.workspace_id,
                job_type=job_type,
                idempotency_key=f"{job_type}:{item.blob_id}",
                payload_json={"blob_id": item.blob_id, "project_public_id": item.project_public_id},
            )
        )
    audit(
        session,
        "blob.upload_complete",
        actor_id=identity.user_id,
        workspace_id=item.workspace_id,
        target=item.blob_id,
        metadata={"byte_size": item.byte_size, "mime_type": item.mime_type},
    )
    session.commit()
    return BlobCompleteRead(
        blob_id=item.blob_id, status=item.status, sha256=item.sha256, byte_size=item.byte_size
    )


def _range_stream(path: Path, start: int, end: int):
    with path.open("rb") as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/{blob_id}/download")
def download_blob(
    blob_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    identity: CurrentIdentity = Depends(require_verified),
    session: Session = Depends(get_session),
) -> Response:
    item = _get_blob_for_user(session, identity, blob_id)
    if item.status != "ready":
        raise HTTPException(status_code=409, detail="Blob is not ready")
    path = (blob_store.root / item.storage_key).resolve()
    if blob_store.root.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Blob content is unavailable")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{item.filename.replace(chr(34), "")}"',
        "Cache-Control": "private, max-age=3600",
    }
    audit(
        session,
        "blob.download",
        actor_id=identity.user_id,
        workspace_id=item.workspace_id,
        target=item.blob_id,
        metadata={"range": bool(range_header)},
    )
    session.commit()
    if not range_header:
        return FileResponse(
            path, media_type=item.mime_type, filename=item.filename, headers=headers
        )
    try:
        unit, value = range_header.split("=", 1)
        start_text, end_text = value.split("-", 1)
        if unit != "bytes" or not start_text:
            raise ValueError
        start = int(start_text)
        end = min(int(end_text) if end_text else item.byte_size - 1, item.byte_size - 1)
        if start < 0 or start > end:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=416, detail="Invalid byte range") from None
    headers["Content-Range"] = f"bytes {start}-{end}/{item.byte_size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        _range_stream(path, start, end),
        status_code=206,
        media_type=item.mime_type,
        headers=headers,
    )
