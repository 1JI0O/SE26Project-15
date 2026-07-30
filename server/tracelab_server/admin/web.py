from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from tracelab_server.auth.password import verify_password
from tracelab_server.auth.service import audit, enforce_rate_limit, normalize_email
from tracelab_server.auth.tokens import token_hash
from tracelab_server.core.config import settings
from tracelab_server.db.session import get_session
from tracelab_server.models.cloud_entities import (
    AdminWebSession,
    AuditLog,
    AuthSession,
    BackgroundJob,
    BlobObject,
    CloudProject,
    EntityTombstone,
    SyncEvent,
    UserAccount,
    Workspace,
    WorkspaceMember,
)
from tracelab_server.models.entities import utc_now
from tracelab_server.storage.blob_store import blob_store

router = APIRouter(prefix="/admin-console", include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    expected = urlparse(settings.public_origin)
    supplied = urlparse(origin)
    # Allow both HTTP and HTTPS for the same host to handle self-signed cert redirects
    if expected.netloc == supplied.netloc:
        return True
    return (supplied.scheme, supplied.netloc) == (expected.scheme, expected.netloc)


def _admin_session(request: Request, session: Session) -> tuple[AdminWebSession, UserAccount]:
    raw_token = request.cookies.get(settings.admin_cookie_name, "")
    web_session = session.exec(
        select(AdminWebSession).where(AdminWebSession.token_hash == token_hash(raw_token))
    ).first()
    now = datetime.now(UTC)
    if web_session is None or web_session.expires_at.replace(tzinfo=UTC) <= now:
        raise HTTPException(status_code=401, detail="Admin sign-in required")
    user = session.get(UserAccount, web_session.user_id)
    if user is None or not user.is_platform_admin or user.status != "active":
        raise HTTPException(status_code=403, detail="Platform administrator required")
    web_session.last_seen_at = utc_now()
    session.add(web_session)
    return web_session, user


def _check_csrf(request: Request, web_session: AdminWebSession, supplied: str) -> None:
    cookie = request.cookies.get("tracelab_admin_csrf", "")
    if (
        not _same_origin(request)
        or not supplied
        or not hmac.compare_digest(cookie, supplied)
        or not hmac.compare_digest(web_session.csrf_hash, token_hash(supplied))
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def _redirect(path: str = "/admin-console") -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    session: Session = Depends(get_session),
) -> Response:
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="Untrusted origin")
    try:
        normalized = normalize_email(email)
    except HTTPException:
        normalized = ""
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    client_ip = forwarded or (request.client.host if request.client else "unknown")
    enforce_rate_limit(session, "admin-login", client_ip, normalized, 10)
    user = session.exec(
        select(UserAccount).where(UserAccount.email_normalized == normalized)
    ).first()
    if (
        user is None
        or not verify_password(user.password_hash, password)
        or user.status != "active"
        or not user.is_platform_admin
    ):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "账号或密码不正确"},
            status_code=401,
        )
    raw_token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    web_session = AdminWebSession(
        user_id=user.user_id,
        token_hash=token_hash(raw_token),
        csrf_hash=token_hash(csrf),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.admin_session_hours),
    )
    session.add(web_session)
    audit(session, "admin_console.login", actor_id=user.user_id, target="self")
    session.commit()
    response = _redirect()
    response.set_cookie(
        settings.admin_cookie_name,
        raw_token,
        max_age=settings.admin_session_hours * 3600,
        secure=settings.cloud_cookie_secure,
        httponly=True,
        samesite="strict",
        path="/admin-console",
    )
    response.set_cookie(
        "tracelab_admin_csrf",
        csrf,
        max_age=settings.admin_session_hours * 3600,
        secure=settings.cloud_cookie_secure,
        httponly=False,
        samesite="strict",
        path="/admin-console",
    )
    return response


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    web_session, user = _admin_session(request, session)
    users = session.exec(select(UserAccount).order_by(UserAccount.created_at.desc())).all()
    workspaces = session.exec(select(Workspace).order_by(Workspace.updated_at.desc())).all()
    projects = session.exec(select(CloudProject).order_by(CloudProject.updated_at.desc())).all()
    jobs = session.exec(
        select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(50)
    ).all()
    audits = session.exec(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(50)).all()
    member_counts = {
        workspace_id: count
        for workspace_id, count in session.exec(
            select(WorkspaceMember.workspace_id, func.count())
            .group_by(WorkspaceMember.workspace_id)
        ).all()
    }
    project_counts = {
        workspace_id: count
        for workspace_id, count in session.exec(
            select(CloudProject.workspace_id, func.count())
            .where(CloudProject.deleted_at.is_(None))
            .group_by(CloudProject.workspace_id)
        ).all()
    }
    blob_usage = {
        workspace_id: int(byte_size or 0)
        for workspace_id, byte_size in session.exec(
            select(BlobObject.workspace_id, func.sum(BlobObject.byte_size))
            .where(BlobObject.status == "ready")
            .group_by(BlobObject.workspace_id)
        ).all()
    }
    owners = {item.user_id: item.email_normalized for item in users}
    csrf = request.cookies.get("tracelab_admin_csrf", "")
    session.commit()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "admin": user,
            "csrf": csrf,
            "users": users,
            "workspaces": workspaces,
            "projects": projects,
            "jobs": jobs,
            "audits": audits,
            "member_counts": member_counts,
            "project_counts": project_counts,
            "blob_usage": blob_usage,
            "owners": owners,
            "disk_percent": round(blob_store.disk_percent(), 2),
            "web_session": web_session,
        },
    )


@router.post("/logout")
def logout(
    request: Request,
    csrf: str = Form(),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    web_session, user = _admin_session(request, session)
    _check_csrf(request, web_session, csrf)
    audit(session, "admin_console.logout", actor_id=user.user_id, target="self")
    session.delete(web_session)
    session.commit()
    response = _redirect("/admin-console/login")
    response.delete_cookie(settings.admin_cookie_name, path="/admin-console")
    response.delete_cookie("tracelab_admin_csrf", path="/admin-console")
    return response


@router.post("/users/{user_id}/status")
def user_status(
    user_id: str,
    request: Request,
    status: str = Form(),
    csrf: str = Form(),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    web_session, admin = _admin_session(request, session)
    _check_csrf(request, web_session, csrf)
    if status not in {"active", "disabled"}:
        raise HTTPException(status_code=422, detail="Invalid account status")
    target = session.get(UserAccount, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.user_id == admin.user_id and status == "disabled":
        raise HTTPException(status_code=409, detail="Cannot disable the current admin")
    target.status = status
    target.updated_at = utc_now()
    session.add(target)
    if status == "disabled":
        for auth_session in session.exec(
            select(AuthSession).where(AuthSession.user_id == user_id)
        ).all():
            auth_session.revoked_at = utc_now()
            session.add(auth_session)
        for target_web_session in session.exec(
            select(AdminWebSession).where(AdminWebSession.user_id == user_id)
        ).all():
            session.delete(target_web_session)
    audit(
        session,
        "admin.user_status",
        actor_id=admin.user_id,
        target=user_id,
        metadata={"status": status},
    )
    session.commit()
    return _redirect("/admin-console#users")


@router.post("/users/{user_id}/force-logout")
def force_logout(
    user_id: str,
    request: Request,
    csrf: str = Form(),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    web_session, admin = _admin_session(request, session)
    _check_csrf(request, web_session, csrf)
    for auth_session in session.exec(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
    ).all():
        auth_session.revoked_at = utc_now()
        session.add(auth_session)
    for target_web_session in session.exec(
        select(AdminWebSession).where(AdminWebSession.user_id == user_id)
    ).all():
        session.delete(target_web_session)
    audit(session, "admin.force_logout", actor_id=admin.user_id, target=user_id)
    session.commit()
    return _redirect("/admin-console#users")


@router.post("/workspaces/{workspace_id}/quota")
def update_quota(
    workspace_id: str,
    request: Request,
    storage_limit_bytes: int = Form(),
    csrf: str = Form(),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    web_session, admin = _admin_session(request, session)
    _check_csrf(request, web_session, csrf)
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if storage_limit_bytes < 1:
        raise HTTPException(status_code=422, detail="Quota must be positive")
    workspace.storage_limit_bytes = storage_limit_bytes
    workspace.updated_at = utc_now()
    session.add(workspace)
    audit(
        session,
        "admin.quota_update",
        actor_id=admin.user_id,
        workspace_id=workspace_id,
        target=workspace_id,
        metadata={"storage_limit_bytes": storage_limit_bytes},
    )
    session.commit()
    return _redirect("/admin-console#workspaces")


@router.post("/projects/{project_id}/lifecycle")
def project_lifecycle(
    project_id: str,
    request: Request,
    operation: str = Form(),
    csrf: str = Form(),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    web_session, admin = _admin_session(request, session)
    _check_csrf(request, web_session, csrf)
    project = session.get(CloudProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if operation == "soft_delete":
        project.deleted_at = utc_now()
        project.version += 1
        existing = session.exec(
            select(EntityTombstone).where(
                EntityTombstone.workspace_id == project.workspace_id,
                EntityTombstone.entity_type == "project",
                EntityTombstone.entity_public_id == project.public_id,
            )
        ).first()
        if existing is None:
            session.add(
                EntityTombstone(
                    workspace_id=project.workspace_id,
                    entity_type="project",
                    entity_public_id=project.public_id,
                    deleted_version=project.version,
                    expires_at=datetime.now(UTC)
                    + timedelta(days=settings.cloud_tombstone_days),
                )
            )
    elif operation == "restore":
        project.deleted_at = None
        project.version += 1
        existing = session.exec(
            select(EntityTombstone).where(
                EntityTombstone.workspace_id == project.workspace_id,
                EntityTombstone.entity_type == "project",
                EntityTombstone.entity_public_id == project.public_id,
            )
        ).first()
        if existing is not None:
            session.delete(existing)
    else:
        raise HTTPException(status_code=422, detail="Invalid lifecycle operation")
    project.updated_by = admin.user_id
    project.updated_at = utc_now()
    session.add(project)
    workspace = session.exec(
        select(Workspace)
        .where(Workspace.workspace_id == project.workspace_id)
        .with_for_update()
    ).one()
    workspace.workspace_seq += 1
    workspace.updated_at = utc_now()
    session.add(workspace)
    event_payload = (
        {"deleted": True}
        if operation == "soft_delete"
        else {
            "name": project.name,
            "description": project.description,
            "agent_history_sync": project.agent_history_sync,
        }
    )
    session.add(
        SyncEvent(
            workspace_id=project.workspace_id,
            workspace_seq=workspace.workspace_seq,
            entity_type="project",
            entity_public_id=project.public_id,
            operation="delete" if operation == "soft_delete" else "upsert",
            entity_version=project.version,
            payload_json=event_payload,
        )
    )
    audit(
        session,
        f"admin.project_{operation}",
        actor_id=admin.user_id,
        workspace_id=project.workspace_id,
        target=project.public_id,
    )
    session.commit()
    return _redirect("/admin-console#projects")


@router.post("/maintenance/{job_type}")
def queue_maintenance(
    job_type: str,
    request: Request,
    csrf: str = Form(),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    web_session, admin = _admin_session(request, session)
    _check_csrf(request, web_session, csrf)
    allowed = {"gc_tombstones", "compact_sync_events"}
    if job_type not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported maintenance job")
    job = BackgroundJob(job_type=job_type, idempotency_key=f"admin:{job_type}:{uuid4()}")
    session.add(job)
    audit(session, "admin.maintenance_queue", actor_id=admin.user_id, target=job.job_id)
    session.commit()
    return _redirect("/admin-console#jobs")
