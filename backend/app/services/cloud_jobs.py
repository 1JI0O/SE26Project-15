from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlmodel import Session, func, select

from app.auth.tokens import create_email_token
from app.core.config import settings
from app.db.session import engine
from app.models.cloud_entities import (
    ArtifactVersion,
    AuthSession,
    BackgroundJob,
    BlobContent,
    BlobObject,
    BlobReference,
    CloudEntity,
    CloudProject,
    Device,
    EntityTombstone,
    SyncDeviceCursor,
    SyncEvent,
    UploadSession,
    Workspace,
    WorkspaceMember,
)
from app.models.entities import utc_now
from app.services.analysis_jobs import ANALYZER_VERSION
from app.services.cloud_mailer import send_account_email
from app.services.code_analysis.analyzer import analyze_code_archive
from app.services.paper_parser import parse_pdf
from app.storage.blob_store import blob_store

_analysis_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cloud-analysis")
SUPPORTED_JOB_TYPES = {
    "parse_paper",
    "analyze_code",
    "send_email",
    "gc_tombstones",
    "compact_sync_events",
}


def _release_entity_blob(session: Session, entity: CloudEntity) -> None:
    if entity.payload_json.get("_blob_reference_released"):
        return
    references = session.exec(
        select(BlobReference).where(
            BlobReference.workspace_id == entity.workspace_id,
            BlobReference.entity_type == entity.entity_type,
            BlobReference.entity_public_id == entity.public_id,
            BlobReference.deleted_at.is_(None),
        )
    ).all()
    if references:
        for reference in references:
            blob = session.get(BlobObject, reference.blob_id)
            if blob is not None:
                blob.reference_count = max(0, blob.reference_count - 1)
                session.add(blob)
            reference.deleted_at = utc_now()
            session.add(reference)
        for version in session.exec(
            select(ArtifactVersion).where(
                ArtifactVersion.workspace_id == entity.workspace_id,
                ArtifactVersion.entity_type == entity.entity_type,
                ArtifactVersion.entity_public_id == entity.public_id,
                ArtifactVersion.deleted_at.is_(None),
            )
        ).all():
            version.deleted_at = utc_now()
            version.is_current = False
            session.add(version)
        return
    blob_id = entity.payload_json.get("blob_id") or entity.payload_json.get("result_blob_id")
    if isinstance(blob_id, str):
        blob = session.get(BlobObject, blob_id)
        if blob is not None:
            blob.reference_count = max(0, blob.reference_count - 1)
            session.add(blob)


def _derived_blob(
    session: Session,
    source: BlobObject,
    payload: dict,
    suffix: str,
) -> BlobObject:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    existing = session.exec(
        select(BlobObject).where(
            BlobObject.workspace_id == source.workspace_id,
            BlobObject.sha256 == digest,
        )
    ).first()
    if existing is not None:
        if existing.status != "ready":
            raise RuntimeError("Derived blob hash is already uploading")
        existing.reference_count += 1
        session.add(existing)
        return existing
    workspace = session.get(Workspace, source.workspace_id)
    usage = int(
        session.exec(
            select(func.coalesce(func.sum(BlobObject.byte_size), 0)).where(
                BlobObject.workspace_id == source.workspace_id,
                BlobObject.status == "ready",
            )
        ).one()
    )
    project_usage = int(
        session.exec(
            select(func.coalesce(func.sum(BlobObject.byte_size), 0)).where(
                BlobObject.workspace_id == source.workspace_id,
                BlobObject.project_public_id == source.project_public_id,
                BlobObject.status == "ready",
            )
        ).one()
    )
    if workspace is None or usage + len(encoded) > workspace.storage_limit_bytes:
        raise RuntimeError("Workspace storage quota exceeded by derived result")
    if project_usage + len(encoded) > settings.cloud_project_quota_bytes:
        raise RuntimeError("Project storage quota exceeded by derived result")
    if blob_store.disk_percent() >= settings.cloud_disk_stop_percent:
        raise RuntimeError("Server storage threshold reached")
    result = BlobObject(
        workspace_id=source.workspace_id,
        project_public_id=source.project_public_id,
        sha256=digest,
        byte_size=len(encoded),
        mime_type="application/json",
        filename=f"{source.filename}.{suffix}.json",
        created_by=source.created_by,
        status="ready",
        reference_count=1,
        completed_at=utc_now(),
    )
    temporary = blob_store.temporary_path(result.blob_id)
    temporary.write_bytes(encoded)
    destination = blob_store.promote(temporary, digest)
    result.storage_key = str(destination.relative_to(blob_store.root))
    content = session.exec(
        select(BlobContent).where(BlobContent.sha256 == digest).with_for_update()
    ).first()
    if content is None:
        content = BlobContent(
            sha256=digest,
            byte_size=len(encoded),
            mime_type="application/json",
            storage_key=result.storage_key,
            physical_ref_count=1,
        )
    else:
        content.physical_ref_count += 1
    session.add(content)
    session.flush()
    result.content_id = content.content_id
    session.add(result)
    return result


def _persist_derived_result(
    session: Session,
    source: BlobObject,
    *,
    entity_type: str,
    version_label: str,
    result_payload: dict,
) -> None:
    derived = _derived_blob(session, source, result_payload, entity_type)
    public_id = str(uuid5(NAMESPACE_URL, f"tracelab:{entity_type}:{source.blob_id}"))
    entity = session.exec(
        select(CloudEntity).where(
            CloudEntity.workspace_id == source.workspace_id,
            CloudEntity.entity_type == entity_type,
            CloudEntity.public_id == public_id,
        )
    ).first()
    previous_blob_id = entity.payload_json.get("result_blob_id") if entity else None
    if entity is None:
        entity = CloudEntity(
            public_id=public_id,
            workspace_id=source.workspace_id,
            project_public_id=source.project_public_id,
            entity_type=entity_type,
            created_by=source.created_by,
            updated_by=source.created_by,
        )
    else:
        entity.version += 1
        entity.updated_by = source.created_by
    entity.payload_json = {
        "project_public_id": source.project_public_id,
        "source_blob_id": source.blob_id,
        "source_hash": source.sha256,
        "processor_version": version_label,
        "result_blob_id": derived.blob_id,
        "status": "ready",
    }
    entity.updated_at = utc_now()
    session.add(entity)
    if isinstance(previous_blob_id, str) and previous_blob_id != derived.blob_id:
        previous = session.get(BlobObject, previous_blob_id)
        if previous is not None:
            previous.reference_count = max(0, previous.reference_count - 1)
            session.add(previous)
    workspace = session.exec(
        select(Workspace).where(Workspace.workspace_id == source.workspace_id).with_for_update()
    ).one()
    workspace.workspace_seq += 1
    session.add(workspace)
    session.add(
        SyncEvent(
            workspace_id=source.workspace_id,
            workspace_seq=workspace.workspace_seq,
            entity_type=entity_type,
            entity_public_id=public_id,
            operation="upsert",
            entity_version=entity.version,
            payload_json=entity.payload_json,
        )
    )


def _execute_analysis_job(session: Session, job: BackgroundJob) -> None:
    blob_id = job.payload_json.get("blob_id")
    source = session.get(BlobObject, blob_id) if isinstance(blob_id, str) else None
    if source is None or source.status != "ready":
        raise RuntimeError("Source blob is unavailable")
    path = (blob_store.root / source.storage_key).resolve()
    if blob_store.root.resolve() not in path.parents or not path.is_file():
        raise RuntimeError("Source blob file is unavailable")
    if job.job_type == "parse_paper":
        _persist_derived_result(
            session,
            source,
            entity_type="paper_analysis",
            version_label="pypdf-compat-v1",
            result_payload=parse_pdf(path),
        )
    elif job.job_type == "analyze_code":
        _persist_derived_result(
            session,
            source,
            entity_type="repository_analysis",
            version_label=ANALYZER_VERSION,
            result_payload=analyze_code_archive(path),
        )


def _execute_email_job(job: BackgroundJob) -> None:
    recipient = job.payload_json.get("recipient")
    purpose = job.payload_json.get("purpose")
    token_id = job.payload_json.get("token_id")
    if not all(isinstance(value, str) for value in (recipient, purpose, token_id)):
        raise RuntimeError("Email job payload is invalid")
    raw_token = create_email_token(token_id)
    if purpose == "verify_email":
        subject = "验证 TraceLab 邮箱"
        url = f"{settings.cloud_public_origin.rstrip('/')}/verify-email#token={raw_token}"
    elif purpose == "reset_password":
        subject = "重置 TraceLab 密码"
        url = f"{settings.cloud_public_origin.rstrip('/')}/reset-password#token={raw_token}"
    else:
        raise RuntimeError("Email job purpose is invalid")
    if not send_account_email(recipient, subject, url):
        raise RuntimeError("Email delivery failed")


def _compact_sync_events(session: Session) -> int:
    """Drop only events acknowledged by every cursor known for a workspace.

    New devices bootstrap from current entities/tombstones. Existing devices are
    protected by the minimum acknowledged cursor, and the age floor provides a
    recovery window even after every device has acknowledged the events.
    """

    cutoff = datetime.now(UTC) - timedelta(days=settings.cloud_blob_gc_grace_days)
    removed = 0
    for workspace in session.exec(select(Workspace)).all():
        member_user_ids = set(
            session.exec(
                select(WorkspaceMember.user_id).where(
                    WorkspaceMember.workspace_id == workspace.workspace_id
                )
            ).all()
        )
        valid_device_ids = {
            device.device_id
            for device in session.exec(
                select(Device).where(
                    Device.user_id.in_(member_user_ids),
                    Device.platform != "web",
                )
            ).all()
            if session.exec(
                select(AuthSession.session_id).where(
                    AuthSession.device_id == device.device_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > datetime.now(UTC),
                )
            ).first()
            is not None
        }
        if not valid_device_ids:
            continue
        cursors = session.exec(
            select(SyncDeviceCursor).where(
                SyncDeviceCursor.workspace_id == workspace.workspace_id
            )
        ).all()
        cursor_by_device = {cursor.device_id: cursor for cursor in cursors}
        if not valid_device_ids.issubset(cursor_by_device):
            continue
        acknowledged_floor = min(
            cursor_by_device[device_id].last_pulled_seq for device_id in valid_device_ids
        )
        if acknowledged_floor <= 0:
            continue
        events = session.exec(
            select(SyncEvent).where(
                SyncEvent.workspace_id == workspace.workspace_id,
                SyncEvent.workspace_seq <= acknowledged_floor,
                SyncEvent.created_at < cutoff,
            )
        ).all()
        for event in events:
            session.delete(event)
            removed += 1
    return removed


def claim_jobs(session: Session, limit: int = 2) -> list[BackgroundJob]:
    now = datetime.now(UTC)
    jobs = list(
        session.exec(
            select(BackgroundJob)
            .where(
                BackgroundJob.status.in_(["queued", "running"]),
                BackgroundJob.available_at <= now,
                (BackgroundJob.lease_expires_at.is_(None) | (BackgroundJob.lease_expires_at < now)),
            )
            .order_by(BackgroundJob.available_at, BackgroundJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).all()
    )
    for job in jobs:
        job.status = "running"
        job.attempt_count += 1
        job.lease_expires_at = now + timedelta(minutes=15)
        session.add(job)
    session.commit()
    return jobs


def execute_job(job_id: str) -> None:
    with Session(engine) as session:
        job = session.get(BackgroundJob, job_id)
        if job is None or job.status != "running":
            return
        try:
            if job.job_type not in SUPPORTED_JOB_TYPES:
                raise RuntimeError("Unsupported background job type")
            if job.job_type in {"parse_paper", "analyze_code"}:
                _execute_analysis_job(session, job)
            elif job.job_type == "send_email":
                _execute_email_job(job)
            elif job.job_type == "compact_sync_events":
                _compact_sync_events(session)
            if job.job_type == "gc_tombstones":
                expired = session.exec(
                    select(EntityTombstone).where(EntityTombstone.expires_at <= datetime.now(UTC))
                ).all()
                for item in expired:
                    if item.entity_type == "project":
                        project = session.get(CloudProject, item.entity_public_id)
                        children = session.exec(
                            select(CloudEntity).where(
                                CloudEntity.workspace_id == item.workspace_id,
                                CloudEntity.project_public_id == item.entity_public_id,
                            )
                        ).all()
                        for child in children:
                            _release_entity_blob(session, child)
                            session.delete(child)
                        if project is not None:
                            session.delete(project)
                    else:
                        entity = session.exec(
                            select(CloudEntity).where(
                                CloudEntity.workspace_id == item.workspace_id,
                                CloudEntity.entity_type == item.entity_type,
                                CloudEntity.public_id == item.entity_public_id,
                            )
                        ).first()
                        if entity is not None:
                            _release_entity_blob(session, entity)
                            session.delete(entity)
                    session.delete(item)
                blob_cutoff = datetime.now(UTC) - timedelta(days=settings.cloud_blob_gc_grace_days)
                unreferenced = session.exec(
                    select(BlobObject).where(
                        BlobObject.status == "ready",
                        BlobObject.reference_count == 0,
                        BlobObject.completed_at <= blob_cutoff,
                    )
                ).all()
                for blob in unreferenced:
                    stale_references = session.exec(
                        select(BlobReference).where(
                            BlobReference.blob_id == blob.blob_id,
                            BlobReference.deleted_at.is_not(None),
                        )
                    ).all()
                    for reference in stale_references:
                        session.delete(reference)
                    session.flush()
                    stale_versions = session.exec(
                        select(ArtifactVersion).where(
                            ArtifactVersion.blob_id == blob.blob_id,
                            ArtifactVersion.deleted_at.is_not(None),
                        )
                    ).all()
                    for version in stale_versions:
                        session.delete(version)
                    session.flush()
                    content = session.get(BlobContent, blob.content_id) if blob.content_id else None
                    session.delete(blob)
                    session.flush()
                    other_handle = (
                        session.exec(
                            select(BlobObject.blob_id).where(
                                BlobObject.content_id == content.content_id
                            )
                        ).first()
                        if content is not None
                        else session.exec(
                            select(BlobObject.blob_id).where(
                                BlobObject.sha256 == blob.sha256,
                                BlobObject.storage_key == blob.storage_key,
                            )
                        ).first()
                    )
                    if content is not None:
                        content.physical_ref_count = max(0, content.physical_ref_count - 1)
                        if other_handle is None:
                            path = (blob_store.root / content.storage_key).resolve()
                            if blob_store.root.resolve() in path.parents:
                                path.unlink(missing_ok=True)
                            session.delete(content)
                        else:
                            session.add(content)
                    elif other_handle is None:
                        path = (blob_store.root / blob.storage_key).resolve()
                        if blob_store.root.resolve() in path.parents:
                            path.unlink(missing_ok=True)
                quarantine_cutoff = datetime.now(UTC) - timedelta(days=1)
                expired_uploads = session.exec(
                    select(UploadSession).where(UploadSession.expires_at <= datetime.now(UTC))
                ).all()
                for upload in expired_uploads:
                    blob_store.temporary_path(upload.blob_id).unlink(missing_ok=True)
                    uploading = session.get(BlobObject, upload.blob_id)
                    session.delete(upload)
                    if uploading is not None and uploading.status == "uploading":
                        session.delete(uploading)
                for temporary in blob_store.quarantine.glob("*.part"):
                    modified = datetime.fromtimestamp(temporary.stat().st_mtime, UTC)
                    if modified <= quarantine_cutoff:
                        temporary.unlink(missing_ok=True)
            job.status = "completed"
            job.completed_at = utc_now()
            job.lease_expires_at = None
            job.last_error = None
        except Exception as exc:
            job.status = "queued" if job.attempt_count < 5 else "failed"
            job.available_at = datetime.now(UTC) + timedelta(seconds=min(300, 2**job.attempt_count))
            job.lease_expires_at = None
            error = str(exc)
            for sensitive_root in (str(blob_store.root), str(blob_store.tmp_root)):
                error = error.replace(sensitive_root, "<storage>")
            job.last_error = error[:500]
        session.add(job)
        session.commit()


def run_worker_once(limit: int = 2) -> int:
    with Session(engine) as session:
        jobs = claim_jobs(session, limit)
        job_ids = [job.job_id for job in jobs]
    list(_analysis_pool.map(execute_job, job_ids))
    return len(job_ids)
