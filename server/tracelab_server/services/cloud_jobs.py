from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from tracelab_server.auth.tokens import create_email_token
from tracelab_server.core.config import settings
from tracelab_server.db.session import engine
from tracelab_server.models.cloud_entities import (
    AdminWebSession,
    ArtifactVersion,
    AuthSession,
    BackgroundJob,
    BlobContent,
    BlobObject,
    BlobReference,
    CloudEntity,
    CloudProject,
    Device,
    EmailToken,
    EntityTombstone,
    SyncDeviceCursor,
    SyncEvent,
    UploadSession,
    Workspace,
    WorkspaceMember,
)
from tracelab_server.models.entities import utc_now
from tracelab_server.services.cloud_mailer import send_account_email
from tracelab_server.storage.blob_store import blob_store

SUPPORTED_JOB_TYPES = {"send_email", "gc_tombstones", "compact_sync_events"}
_maintenance_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="server-maintenance")


def _release_entity_blob(session: Session, entity: CloudEntity) -> None:
    references = session.exec(
        select(BlobReference).where(
            BlobReference.workspace_id == entity.workspace_id,
            BlobReference.entity_type == entity.entity_type,
            BlobReference.entity_public_id == entity.public_id,
            BlobReference.deleted_at.is_(None),
        )
    ).all()
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


def _execute_email_job(job: BackgroundJob) -> None:
    recipient = job.payload_json.get("recipient")
    purpose = job.payload_json.get("purpose")
    token_id = job.payload_json.get("token_id")
    if not all(isinstance(value, str) for value in (recipient, purpose, token_id)):
        raise RuntimeError("Email job payload is invalid")
    raw_token = create_email_token(token_id)
    link_origin = settings.account_link_origin.rstrip("/")
    if purpose == "verify_email":
        subject = "验证 TraceLab 邮箱"
        url = f"{link_origin}/verify-email#token={raw_token}"
    elif purpose == "reset_password":
        subject = "重置 TraceLab 密码"
        url = f"{link_origin}/reset-password#token={raw_token}"
    else:
        raise RuntimeError("Email job purpose is invalid")
    if not send_account_email(recipient, subject, url):
        raise RuntimeError("Email delivery failed")


def _compact_sync_events(session: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=settings.cloud_event_retention_days)
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


def _delete_physical_content_if_unused(
    session: Session, blob: BlobObject, content: BlobContent | None
) -> None:
    other_handle = (
        session.exec(
            select(BlobObject.blob_id).where(BlobObject.content_id == content.content_id)
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


def _gc_tombstones_and_blobs(session: Session) -> None:
    now = datetime.now(UTC)
    for web_session in session.exec(
        select(AdminWebSession).where(AdminWebSession.expires_at <= now)
    ).all():
        session.delete(web_session)
    email_cutoff = now - timedelta(days=settings.cloud_tombstone_days)
    for email_token in session.exec(
        select(EmailToken).where(
            (EmailToken.expires_at <= email_cutoff)
            | (
                EmailToken.used_at.is_not(None)
                & (EmailToken.used_at <= email_cutoff)
            )
        )
    ).all():
        session.delete(email_token)
    for item in session.exec(
        select(EntityTombstone).where(EntityTombstone.expires_at <= now)
    ).all():
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

    blob_cutoff = now - timedelta(days=settings.cloud_blob_gc_grace_days)
    for blob in session.exec(
        select(BlobObject).where(
            BlobObject.status == "ready",
            BlobObject.reference_count == 0,
            BlobObject.completed_at <= blob_cutoff,
        )
    ).all():
        for reference in session.exec(
            select(BlobReference).where(
                BlobReference.blob_id == blob.blob_id,
                BlobReference.deleted_at.is_not(None),
            )
        ).all():
            session.delete(reference)
        for version in session.exec(
            select(ArtifactVersion).where(
                ArtifactVersion.blob_id == blob.blob_id,
                ArtifactVersion.deleted_at.is_not(None),
            )
        ).all():
            session.delete(version)
        content = session.get(BlobContent, blob.content_id) if blob.content_id else None
        session.delete(blob)
        session.flush()
        _delete_physical_content_if_unused(session, blob, content)

    for upload in session.exec(select(UploadSession).where(UploadSession.expires_at <= now)).all():
        blob_store.temporary_path(upload.blob_id).unlink(missing_ok=True)
        uploading = session.get(BlobObject, upload.blob_id)
        session.delete(upload)
        if uploading is not None and uploading.status == "uploading":
            session.delete(uploading)
    quarantine_cutoff = now - timedelta(days=1)
    for temporary in blob_store.quarantine.glob("*.part"):
        modified = datetime.fromtimestamp(temporary.stat().st_mtime, UTC)
        if modified <= quarantine_cutoff:
            temporary.unlink(missing_ok=True)


def claim_jobs(session: Session, limit: int = 2) -> list[BackgroundJob]:
    now = datetime.now(UTC)
    jobs = list(
        session.exec(
            select(BackgroundJob)
            .where(
                BackgroundJob.status.in_(["queued", "running"]),
                BackgroundJob.available_at <= now,
                (
                    BackgroundJob.lease_expires_at.is_(None)
                    | (BackgroundJob.lease_expires_at < now)
                ),
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
            if job.job_type == "send_email":
                _execute_email_job(job)
            elif job.job_type == "compact_sync_events":
                _compact_sync_events(session)
            elif job.job_type == "gc_tombstones":
                _gc_tombstones_and_blobs(session)
            job.status = "completed"
            job.completed_at = utc_now()
            job.lease_expires_at = None
            job.last_error = None
        except Exception as exc:
            job.status = "queued" if job.attempt_count < 5 else "failed"
            job.available_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**job.attempt_count)
            )
            job.lease_expires_at = None
            error = str(exc)
            for sensitive_root in (str(blob_store.root), str(blob_store.tmp_root)):
                error = error.replace(sensitive_root, "<storage>")
            job.last_error = error[:500]
        session.add(job)
        session.commit()


def run_worker_once(limit: int = 2) -> int:
    with Session(engine) as session:
        job_ids = [job.job_id for job in claim_jobs(session, min(max(limit, 1), 2))]
    list(_maintenance_pool.map(execute_job, job_ids))
    return len(job_ids)
