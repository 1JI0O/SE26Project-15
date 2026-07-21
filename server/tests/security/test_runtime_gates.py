import pytest
from pydantic import SecretStr

from tracelab_server.core.config import ServerSettings


def production_settings(**overrides: object) -> ServerSettings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://user:password@postgres/tracelab",
        "public_origin": "https://sync.example.com",
        "account_link_origin": "https://app.example.com",
        "cloud_jwt_secret": SecretStr("a-secure-random-secret-with-at-least-32-bytes"),
        "cloud_cookie_secure": True,
        "cloud_sync_feature_enabled": True,
        "cloud_require_email_verification": True,
        "smtp_host": "smtp.example.com",
        "smtp_from": "tracelab@example.com",
        "backup_remote": "remote:tracelab",
    }
    values.update(overrides)
    return ServerSettings(**values)


def test_production_requires_email_delivery_and_external_backup() -> None:
    production_settings().validate_runtime()
    with pytest.raises(RuntimeError, match="SMTP"):
        production_settings(smtp_host="").validate_runtime()
    with pytest.raises(RuntimeError, match="BACKUP_REMOTE"):
        production_settings(backup_remote="").validate_runtime()


def test_sync_feature_is_disabled_by_default() -> None:
    assert ServerSettings(app_env="test").cloud_sync_feature_enabled is False


def test_production_requires_secure_public_and_account_link_origins() -> None:
    with pytest.raises(RuntimeError, match="HTTPS"):
        production_settings(public_origin="http://sync.example.com").validate_runtime()
    with pytest.raises(RuntimeError, match="ACCOUNT_LINK_ORIGIN"):
        production_settings(account_link_origin="http://127.0.0.1:1420").validate_runtime()
