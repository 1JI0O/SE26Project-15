from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from tracelab_server.auth.password import hash_password, verify_password
from tracelab_server.auth.tokens import (
    InvalidTokenError,
    as_utc,
    create_access_token,
    create_email_token,
    create_refresh_token,
    privacy_hash,
    refresh_expiry,
    refresh_session_id,
    token_hash,
)
from tracelab_server.core.config import settings
from tracelab_server.models.cloud_entities import (
    AuditLog,
    AuthRateLimit,
    AuthSession,
    Device,
    EmailToken,
    UserAccount,
    Workspace,
    WorkspaceMember,
)
from tracelab_server.models.entities import utc_now

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email: str) -> str:
    value = email.strip().casefold()
    if len(value) > 320 or not EMAIL_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail="Invalid email address")
    return value


def user_read(user: UserAccount) -> dict:
    email_verified = user.email_verified_at is not None
    if not settings.cloud_require_email_verification:
        email_verified = True
    return {
        "user_id": user.user_id,
        "email": user.email_normalized,
        "display_name": user.display_name,
        "status": user.status,
        "email_verified": email_verified,
        "is_platform_admin": user.is_platform_admin,
    }


def audit(
    session: Session,
    action: str,
    *,
    actor_id: str | None = None,
    workspace_id: str | None = None,
    target: str = "",
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            workspace_id=workspace_id,
            action=action,
            target=target[:255],
            metadata_json=metadata or {},
        )
    )


def enforce_rate_limit(session: Session, category: str, ip: str, email: str, limit: int) -> None:
    now = datetime.now(UTC)
    for dimension_name, value in (("ip", ip), ("email", email)):
        key = f"{category}:{dimension_name}:{privacy_hash(value or 'unknown')}"
        if session.get_bind().dialect.name == "postgresql":
            lock_key = int(privacy_hash(key)[:16], 16)
            if lock_key >= 2**63:
                lock_key -= 2**64
            session.exec(text("SELECT pg_advisory_xact_lock(:key)").bindparams(key=lock_key))
        bucket = session.exec(
            select(AuthRateLimit).where(AuthRateLimit.bucket_key == key).with_for_update()
        ).first()
        if bucket is None:
            bucket = AuthRateLimit(bucket_key=key, window_started_at=now, attempt_count=1)
        elif as_utc(bucket.window_started_at) + timedelta(minutes=1) <= now:
            bucket.window_started_at = now
            bucket.attempt_count = 1
        else:
            bucket.attempt_count += 1
            if bucket.attempt_count > limit:
                session.add(bucket)
                session.commit()
                raise HTTPException(status_code=429, detail="Too many requests")
        session.add(bucket)
    # Persist counters before authentication can fail and roll back its own
    # transaction; otherwise invalid attempts would never accumulate.
    session.commit()


def create_account(
    session: Session, email: str, password: str, display_name: str
) -> tuple[UserAccount, str, str]:
    normalized = normalize_email(email)
    if session.exec(select(UserAccount).where(UserAccount.email_normalized == normalized)).first():
        raise HTTPException(status_code=409, detail="Account could not be created")
    verified_at = None if settings.cloud_require_email_verification else datetime.now(UTC)
    user = UserAccount(
        email_normalized=normalized,
        password_hash=hash_password(password),
        display_name=display_name.strip() or normalized.split("@", 1)[0],
        email_verified_at=verified_at,
    )
    session.add(user)
    session.flush()
    workspace = Workspace(
        name=f"{user.display_name} 的工作区",
        created_by=user.user_id,
        storage_limit_bytes=settings.cloud_account_quota_bytes,
    )
    session.add(workspace)
    session.flush()
    session.add(
        WorkspaceMember(workspace_id=workspace.workspace_id, user_id=user.user_id, role="owner")
    )
    email_token = EmailToken(
        user_id=user.user_id,
        purpose="verify_email",
        token_hash="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    raw_token = create_email_token(email_token.token_id)
    email_token.token_hash = token_hash(raw_token)
    session.add(email_token)
    audit(session, "auth.register", actor_id=user.user_id, target="self")
    session.flush()
    session.refresh(user)
    return user, raw_token, email_token.token_id


def authenticate(session: Session, email: str, password: str) -> UserAccount:
    normalized = normalize_email(email)
    user = session.exec(
        select(UserAccount).where(UserAccount.email_normalized == normalized)
    ).first()
    if user is None or not verify_password(user.password_hash, password) or user.status != "active":
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user


def create_login_session(
    session: Session,
    user: UserAccount,
    *,
    device_id: str | None,
    name: str,
    platform: str,
    client_version: str,
    ip: str,
    user_agent: str,
) -> tuple[AuthSession, str, str]:
    device = session.get(Device, device_id) if device_id else None
    if device is not None and device.user_id != user.user_id:
        device = None
    if device is None:
        device = Device(
            user_id=user.user_id,
            name=name,
            platform=platform,
            client_version=client_version,
        )
        session.add(device)
        session.flush()
    else:
        device.name = name
        device.platform = platform
        device.client_version = client_version
        device.last_seen_at = utc_now()
    auth_session = AuthSession(
        user_id=user.user_id,
        device_id=device.device_id,
        refresh_token_hash="pending",
        expires_at=refresh_expiry(),
        last_ip_hash=privacy_hash(ip or "unknown"),
        user_agent_summary=user_agent[:255],
    )
    session.add(auth_session)
    session.flush()
    refresh = create_refresh_token(auth_session.session_id)
    auth_session.refresh_token_hash = token_hash(refresh)
    audit(session, "auth.login", actor_id=user.user_id, target=device.device_id)
    session.commit()
    return (
        auth_session,
        create_access_token(user.user_id, auth_session.session_id, device.device_id),
        refresh,
    )


def rotate_refresh_token(
    session: Session, raw_token: str
) -> tuple[UserAccount, AuthSession, str, str]:
    try:
        session_id = refresh_session_id(raw_token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from None
    auth_session = session.exec(
        select(AuthSession).where(AuthSession.session_id == session_id).with_for_update()
    ).first()
    supplied_hash = token_hash(raw_token)
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if not hmac_compare(auth_session.refresh_token_hash, supplied_hash):
        if not auth_session.previous_refresh_token_hash or not hmac_compare(
            auth_session.previous_refresh_token_hash, supplied_hash
        ):
            # A guessed secret paired with a session id from an access token
            # must not become a device-wide logout primitive.
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        # A rotated token appearing again means the whole device credential
        # chain is compromised, including parallel sessions for that device.
        revoked_at = utc_now()
        device_sessions = session.exec(
            select(AuthSession).where(
                AuthSession.device_id == auth_session.device_id,
                AuthSession.revoked_at.is_(None),
            )
        ).all()
        for device_session in device_sessions:
            device_session.revoked_at = revoked_at
            session.add(device_session)
        audit(
            session,
            "auth.refresh_reuse",
            actor_id=auth_session.user_id,
            target=auth_session.device_id,
        )
        session.commit()
        raise HTTPException(status_code=401, detail="Refresh token reuse detected")
    if auth_session.revoked_at is not None or as_utc(auth_session.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Refresh token expired")
    user = session.get(UserAccount, auth_session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Account unavailable")
    new_refresh = create_refresh_token(auth_session.session_id)
    auth_session.previous_refresh_token_hash = auth_session.refresh_token_hash
    auth_session.refresh_token_hash = token_hash(new_refresh)
    auth_session.expires_at = refresh_expiry()
    session.add(auth_session)
    session.commit()
    access = create_access_token(user.user_id, auth_session.session_id, auth_session.device_id)
    return user, auth_session, access, new_refresh


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def consume_email_token(session: Session, raw_token: str, purpose: str) -> UserAccount:
    item = session.exec(
        select(EmailToken).where(
            EmailToken.token_hash == token_hash(raw_token),
            EmailToken.purpose == purpose,
        )
    ).first()
    if item is None or item.used_at is not None or as_utc(item.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user = session.get(UserAccount, item.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    item.used_at = utc_now()
    session.add(item)
    return user
