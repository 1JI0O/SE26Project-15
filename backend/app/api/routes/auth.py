from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session, select

from app.auth.dependencies import CurrentIdentity, get_current_identity
from app.auth.password import hash_password
from app.auth.service import (
    audit,
    authenticate,
    consume_email_token,
    create_account,
    create_login_session,
    enforce_rate_limit,
    normalize_email,
    rotate_refresh_token,
    user_read,
)
from app.auth.tokens import (
    InvalidTokenError,
    create_csrf_token,
    create_email_token,
    refresh_session_id,
    token_hash,
)
from app.core.config import settings
from app.db.session import get_session
from app.models.cloud_entities import (
    AuthSession,
    Device,
    EmailToken,
    UserAccount,
    Workspace,
    WorkspaceMember,
)
from app.models.entities import utc_now
from app.schemas.cloud import (
    AuthRead,
    DeviceRead,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserRead,
    VerifyEmailRequest,
    WorkspaceRead,
)
from app.services.cloud_mailer import queue_account_email

router = APIRouter(prefix="/auth", tags=["cloud-auth"])
REFRESH_COOKIE = "tracelab_refresh"
CSRF_COOKIE = "tracelab_csrf"


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _validate_browser_origin(request: Request) -> None:
    if settings.app_env != "production":
        return
    if request.headers.get("origin") != settings.cloud_public_origin.rstrip("/"):
        raise HTTPException(status_code=403, detail="Untrusted origin")


def _validate_csrf(request: Request) -> None:
    _validate_browser_origin(request)
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or cookie != header:
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def _set_browser_cookies(response: Response, refresh: str, csrf: str) -> None:
    max_age = settings.cloud_refresh_token_days * 24 * 60 * 60
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=max_age,
        httponly=True,
        secure=settings.cloud_cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,
        secure=settings.cloud_cookie_secure,
        samesite="lax",
        # The SPA must be able to read this value after a page reload. The
        # refresh cookie remains scoped to the authentication endpoints.
        path="/",
    )


def _clear_browser_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _default_workspace(session: Session, user_id: str) -> WorkspaceRead | None:
    membership = session.exec(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(WorkspaceMember.id)
    ).first()
    workspace = session.get(Workspace, membership.workspace_id) if membership else None
    if membership is None or workspace is None:
        return None
    return WorkspaceRead(
        workspace_id=workspace.workspace_id,
        name=workspace.name,
        role=membership.role,
        plan=workspace.plan,
        storage_limit_bytes=workspace.storage_limit_bytes,
        workspace_seq=workspace.workspace_seq,
    )


def _auth_response(
    session: Session,
    user: UserAccount,
    access: str,
    refresh: str,
    client_kind: str,
    response: Response,
    device_id: str,
) -> AuthRead:
    csrf = create_csrf_token() if client_kind == "browser" else None
    if client_kind == "browser":
        _set_browser_cookies(response, refresh, csrf or "")
    return AuthRead(
        access_token=access,
        expires_in=settings.cloud_access_token_minutes * 60,
        csrf_token=csrf,
        refresh_token=refresh if client_kind == "desktop" else None,
        device_id=device_id,
        user=UserRead(**user_read(user)),
        default_workspace=_default_workspace(session, user.user_id),
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> UserRead:
    normalized = normalize_email(payload.email)
    enforce_rate_limit(session, "register", _client_ip(request), normalized, 5)
    if session.exec(
        select(UserAccount.user_id).where(UserAccount.email_normalized == normalized)
    ).first():
        return UserRead(
            user_id=str(uuid4()),
            email=normalized,
            display_name=payload.display_name.strip() or normalized.split("@", 1)[0],
            status="active",
            email_verified=False,
        )
    user, raw_token, token_id = create_account(
        session, payload.email, payload.password, payload.display_name
    )
    queue_account_email(
        session,
        recipient=user.email_normalized,
        purpose="verify_email",
        token_id=token_id,
    )
    session.commit()
    if settings.app_env != "production":
        response.headers["X-Debug-Email-Token"] = raw_token
    return UserRead(**user_read(user))


@router.post("/login", response_model=AuthRead)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> AuthRead:
    if payload.client_kind == "browser":
        _validate_browser_origin(request)
    normalized = normalize_email(payload.email)
    enforce_rate_limit(session, "login", _client_ip(request), normalized, 10)
    user = authenticate(session, payload.email, payload.password)
    auth_session, access, refresh = create_login_session(
        session,
        user,
        device_id=payload.device_id,
        name=payload.device_name,
        platform=payload.platform,
        client_version=payload.client_version,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    return _auth_response(
        session,
        user,
        access,
        refresh,
        payload.client_kind,
        response,
        auth_session.device_id,
    )


@router.post("/refresh", response_model=AuthRead)
def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> AuthRead:
    if payload.client_kind == "browser":
        _validate_csrf(request)
        raw_token = request.cookies.get(REFRESH_COOKIE)
    else:
        raw_token = payload.refresh_token
    if not raw_token:
        raise HTTPException(status_code=401, detail="Refresh token required")
    refresh_email = "unknown"
    try:
        candidate_session = session.get(AuthSession, refresh_session_id(raw_token))
    except InvalidTokenError:
        candidate_session = None
    if candidate_session is not None:
        candidate_user = session.get(UserAccount, candidate_session.user_id)
        if candidate_user is not None:
            refresh_email = candidate_user.email_normalized
    enforce_rate_limit(session, "refresh", _client_ip(request), refresh_email, 30)
    user, auth_session, access, new_refresh = rotate_refresh_token(session, raw_token)
    return _auth_response(
        session,
        user,
        access,
        new_refresh,
        payload.client_kind,
        response,
        auth_session.device_id,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    identity: CurrentIdentity = Depends(get_current_identity),
    session: Session = Depends(get_session),
) -> None:
    identity.auth_session.revoked_at = utc_now()
    session.add(identity.auth_session)
    audit(session, "auth.logout", actor_id=identity.user_id, target=identity.device_id)
    session.commit()
    _clear_browser_cookies(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    response: Response,
    identity: CurrentIdentity = Depends(get_current_identity),
    session: Session = Depends(get_session),
) -> None:
    sessions = session.exec(
        select(AuthSession).where(AuthSession.user_id == identity.user_id)
    ).all()
    for item in sessions:
        item.revoked_at = utc_now()
        session.add(item)
    audit(session, "auth.logout_all", actor_id=identity.user_id, target="all_devices")
    session.commit()
    _clear_browser_cookies(response)


@router.get("/me", response_model=AuthRead)
def me(
    identity: CurrentIdentity = Depends(get_current_identity),
    session: Session = Depends(get_session),
) -> AuthRead:
    return AuthRead(
        access_token="",
        expires_in=0,
        device_id=identity.device_id,
        user=UserRead(**user_read(identity.user)),
        default_workspace=_default_workspace(session, identity.user_id),
    )


@router.get("/devices", response_model=list[DeviceRead])
def devices(
    identity: CurrentIdentity = Depends(get_current_identity),
    session: Session = Depends(get_session),
) -> list[DeviceRead]:
    rows = session.exec(
        select(Device)
        .where(Device.user_id == identity.user_id)
        .order_by(Device.last_seen_at.desc())
    ).all()
    return [
        DeviceRead(
            device_id=item.device_id,
            name=item.name,
            platform=item.platform,
            client_version=item.client_version,
            last_seen_at=item.last_seen_at,
            current=item.device_id == identity.device_id,
        )
        for item in rows
    ]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(
    device_id: str,
    identity: CurrentIdentity = Depends(get_current_identity),
    session: Session = Depends(get_session),
) -> None:
    device = session.get(Device, device_id)
    if device is None or device.user_id != identity.user_id:
        raise HTTPException(status_code=404, detail="Device not found")
    rows = session.exec(select(AuthSession).where(AuthSession.device_id == device_id)).all()
    for item in rows:
        item.revoked_at = utc_now()
        session.add(item)
    audit(session, "auth.device_revoke", actor_id=identity.user_id, target=device_id)
    session.commit()


@router.post("/verify-email", response_model=UserRead)
def verify_email(payload: VerifyEmailRequest, session: Session = Depends(get_session)) -> UserRead:
    user = consume_email_token(session, payload.token, "verify_email")
    user.email_verified_at = utc_now()
    user.updated_at = utc_now()
    session.add(user)
    audit(session, "auth.email_verified", actor_id=user.user_id, target="self")
    session.commit()
    return UserRead(**user_read(user))


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    normalized = normalize_email(payload.email)
    enforce_rate_limit(session, "forgot", _client_ip(request), normalized, 5)
    user = session.exec(
        select(UserAccount).where(UserAccount.email_normalized == normalized)
    ).first()
    if user is not None:
        email_token = EmailToken(
            user_id=user.user_id,
            purpose="reset_password",
            token_hash="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        raw_token = create_email_token(email_token.token_id)
        email_token.token_hash = token_hash(raw_token)
        session.add(email_token)
        audit(session, "auth.password_forgot", actor_id=user.user_id, target="self")
        queue_account_email(
            session,
            recipient=user.email_normalized,
            purpose="reset_password",
            token_id=email_token.token_id,
        )
        session.commit()
        if settings.app_env != "production":
            response.headers["X-Debug-Email-Token"] = raw_token
    else:
        session.commit()
    return {"detail": "If the account exists, a reset message has been sent"}


@router.post("/password/reset", response_model=UserRead)
def reset_password(
    payload: ResetPasswordRequest, session: Session = Depends(get_session)
) -> UserRead:
    user = consume_email_token(session, payload.token, "reset_password")
    user.password_hash = hash_password(payload.password)
    user.updated_at = utc_now()
    sessions = session.exec(select(AuthSession).where(AuthSession.user_id == user.user_id)).all()
    for item in sessions:
        item.revoked_at = utc_now()
        session.add(item)
    session.add(user)
    audit(session, "auth.password_reset", actor_id=user.user_id, target="self")
    session.commit()
    return UserRead(**user_read(user))
