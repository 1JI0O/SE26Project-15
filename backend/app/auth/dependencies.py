from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session

from app.auth.tokens import InvalidTokenError, as_utc, decode_access_token
from app.core.config import settings
from app.db.session import get_session
from app.models.cloud_entities import AuthSession, UserAccount


@dataclass(frozen=True)
class CurrentIdentity:
    user: UserAccount
    auth_session: AuthSession

    @property
    def user_id(self) -> str:
        return self.user.user_id

    @property
    def device_id(self) -> str:
        return self.auth_session.device_id


def get_current_identity(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> CurrentIdentity:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized
    try:
        claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
    except InvalidTokenError:
        raise unauthorized from None
    user = session.get(UserAccount, claims.get("sub"))
    auth_session = session.get(AuthSession, claims.get("sid"))
    if (
        user is None
        or auth_session is None
        or auth_session.user_id != user.user_id
        or auth_session.device_id != claims.get("dev")
        or auth_session.revoked_at is not None
        or as_utc(auth_session.expires_at) <= datetime.now(UTC)
        or user.status != "active"
    ):
        raise unauthorized
    return CurrentIdentity(user=user, auth_session=auth_session)


def require_verified(identity: CurrentIdentity = Depends(get_current_identity)) -> CurrentIdentity:
    if settings.cloud_require_email_verification and identity.user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Email verification required")
    return identity


def require_platform_admin(
    identity: CurrentIdentity = Depends(get_current_identity),
) -> CurrentIdentity:
    if not identity.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    return identity
