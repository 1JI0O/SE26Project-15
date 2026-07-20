from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.auth.dependencies import CurrentIdentity, require_platform_admin
from app.auth.service import audit, user_read
from app.core.config import settings
from app.db.session import get_session
from app.models.cloud_entities import (
    AuditLog,
    AuthSession,
    BackgroundJob,
    BlobObject,
    UserAccount,
    Workspace,
)
from app.models.entities import utc_now
from app.schemas.cloud import AdminQuotaPatch, AdminUserPatch, UserRead
from app.storage.blob_store import blob_store

router = APIRouter(prefix="/admin", tags=["cloud-admin"])


@router.get("/users", response_model=list[UserRead])
def list_users(
    _: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> list[UserRead]:
    return [
        UserRead(**user_read(item))
        for item in session.exec(select(UserAccount).order_by(UserAccount.created_at.desc())).all()
    ]


@router.get("/workspaces")
def list_workspaces(
    _: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Account/quota overview for platform operators. No project body content."""
    rows = session.exec(select(Workspace).order_by(Workspace.updated_at.desc())).all()
    owners = {
        user.user_id: user.email_normalized
        for user in session.exec(select(UserAccount)).all()
    }
    return [
        {
            "workspace_id": item.workspace_id,
            "name": item.name,
            "plan": item.plan,
            "storage_limit_bytes": item.storage_limit_bytes,
            "workspace_seq": item.workspace_seq,
            "created_by": item.created_by,
            "owner_email": owners.get(item.created_by, ""),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in rows
    ]


@router.patch("/users/{user_id}", response_model=UserRead)
def patch_user(
    user_id: str,
    payload: AdminUserPatch,
    identity: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> UserRead:
    user = session.get(UserAccount, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.status:
        user.status = payload.status
        user.updated_at = utc_now()
        session.add(user)
    if payload.force_logout or payload.status == "disabled":
        for item in session.exec(select(AuthSession).where(AuthSession.user_id == user_id)).all():
            item.revoked_at = utc_now()
            session.add(item)
    audit(
        session,
        "admin.user_update",
        actor_id=identity.user_id,
        target=user_id,
        metadata=payload.model_dump(),
    )
    session.commit()
    return UserRead(**user_read(user))


@router.patch("/workspaces/{workspace_id}/quota")
def patch_quota(
    workspace_id: str,
    payload: AdminQuotaPatch,
    identity: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    workspace.storage_limit_bytes = payload.storage_limit_bytes
    workspace.updated_at = utc_now()
    session.add(workspace)
    audit(
        session,
        "admin.quota_update",
        actor_id=identity.user_id,
        workspace_id=workspace_id,
        target=workspace_id,
        metadata={"storage_limit_bytes": payload.storage_limit_bytes},
    )
    session.commit()
    return {"workspace_id": workspace_id, "storage_limit_bytes": workspace.storage_limit_bytes}


@router.get("/metrics")
def metrics(
    _: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    disk_percent = round(blob_store.disk_percent(), 2)
    return {
        "users": int(session.exec(select(func.count()).select_from(UserAccount)).one()),
        "workspaces": int(session.exec(select(func.count()).select_from(Workspace)).one()),
        "ready_blobs": int(
            session.exec(
                select(func.count()).select_from(BlobObject).where(BlobObject.status == "ready")
            ).one()
        ),
        "queued_jobs": int(
            session.exec(
                select(func.count())
                .select_from(BackgroundJob)
                .where(BackgroundJob.status == "queued")
            ).one()
        ),
        "disk_percent": disk_percent,
        "disk_warning": int(disk_percent >= settings.cloud_disk_warn_percent),
        "uploads_blocked": int(disk_percent >= settings.cloud_disk_stop_percent),
    }


@router.get("/audit")
def read_audit(
    limit: int = 100,
    _: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.exec(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 500))
    ).all()
    return [
        {
            "audit_id": item.audit_id,
            "actor_id": item.actor_id,
            "workspace_id": item.workspace_id,
            "action": item.action,
            "target": item.target,
            "metadata": item.metadata_json,
            "created_at": item.created_at,
        }
        for item in rows
    ]


@router.get("/jobs")
def read_jobs(
    limit: int = 100,
    _: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.exec(
        select(BackgroundJob)
        .order_by(BackgroundJob.created_at.desc())
        .limit(min(max(limit, 1), 500))
    ).all()
    return [
        {
            "job_id": item.job_id,
            "workspace_id": item.workspace_id,
            "job_type": item.job_type,
            "status": item.status,
            "attempt_count": item.attempt_count,
            "available_at": item.available_at,
            "last_error": item.last_error,
            "created_at": item.created_at,
            "completed_at": item.completed_at,
        }
        for item in rows
    ]


@router.post("/maintenance/gc", status_code=202)
def queue_gc(
    identity: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    job = BackgroundJob(job_type="gc_tombstones", idempotency_key=f"manual-gc:{uuid4()}")
    session.add(job)
    audit(session, "admin.gc_queue", actor_id=identity.user_id, target=job.job_id)
    session.commit()
    return {"job_id": job.job_id, "status": job.status}


@router.post("/maintenance/compact-events", status_code=202)
def queue_event_compaction(
    identity: CurrentIdentity = Depends(require_platform_admin),
    session: Session = Depends(get_session),
) -> dict:
    job = BackgroundJob(
        job_type="compact_sync_events",
        idempotency_key=f"manual-event-compaction:{uuid4()}",
    )
    session.add(job)
    audit(
        session,
        "admin.event_compaction_queue",
        actor_id=identity.user_id,
        target=job.job_id,
    )
    session.commit()
    return {"job_id": job.job_id, "status": job.status}
