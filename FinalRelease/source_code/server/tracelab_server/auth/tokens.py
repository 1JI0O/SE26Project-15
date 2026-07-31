from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from tracelab_server.core.config import settings


class InvalidTokenError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def privacy_hash(value: str) -> str:
    secret = settings.cloud_jwt_secret.get_secret_value().encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def create_access_token(user_id: str, session_id: str, device_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "sid": session_id,
        "dev": device_id,
        "iat": now,
        "exp": now + settings.cloud_access_token_minutes * 60,
        "iss": "tracelab-cloud",
        "aud": "tracelab-client",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(
        settings.cloud_jwt_secret.get_secret_value().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
        signing_input = f"{header}.{payload}"
        expected = hmac.new(
            settings.cloud_jwt_secret.get_secret_value().encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            raise InvalidTokenError("invalid signature")
        result = json.loads(_b64decode(payload))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("invalid access token") from exc
    if result.get("iss") != "tracelab-cloud" or result.get("aud") != "tracelab-client":
        raise InvalidTokenError("invalid token audience")
    if int(result.get("exp", 0)) <= int(time.time()):
        raise InvalidTokenError("access token expired")
    return result


def create_refresh_token(session_id: str) -> str:
    return f"{session_id}.{secrets.token_urlsafe(48)}"


def refresh_session_id(token: str) -> str:
    try:
        session_id, secret = token.split(".", 1)
    except ValueError as exc:
        raise InvalidTokenError("invalid refresh token") from exc
    if len(session_id) != 36 or len(secret) < 48:
        raise InvalidTokenError("invalid refresh token")
    return session_id


def create_email_token(token_id: str | None = None) -> str:
    if token_id is None:
        return secrets.token_urlsafe(48)
    secret = settings.cloud_jwt_secret.get_secret_value().encode("utf-8")
    digest = hmac.new(secret, f"email:{token_id}".encode(), hashlib.sha256).digest()
    return f"{token_id}.{_b64encode(digest)}"


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.cloud_refresh_token_days)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
