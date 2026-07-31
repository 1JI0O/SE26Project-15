from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    app_name: str = "TraceLab Sync Server"
    app_env: str = Field(default="development", pattern="^(development|test|staging|production)$")
    database_url: str = "postgresql+psycopg://tracelab:tracelab@postgres:5432/tracelab"
    # Per-process pool width. The defaults are deliberately small because the worker and
    # migrator import these settings too; the API service raises them in compose.yaml.
    # Budget the total against PostgreSQL max_connections -- see server/README.md.
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    # Bounded so an exhausted pool fails fast as a 503 instead of piling up requests
    # behind SQLAlchemy's 30s default until the client times out first.
    database_pool_timeout: int = Field(default=10, ge=1, le=120)
    public_origin: str = "http://127.0.0.1:8000"
    account_link_origin: str = "http://127.0.0.1:1420"
    allowed_origins: list[str] | str = Field(default_factory=list)

    cloud_jwt_secret: SecretStr = SecretStr("development-only-change-me")
    cloud_access_token_minutes: int = Field(default=15, ge=5, le=60)
    cloud_refresh_token_days: int = Field(default=30, ge=1, le=90)
    cloud_cookie_secure: bool = False
    cloud_sync_feature_enabled: bool = False
    cloud_require_email_verification: bool = True

    cloud_blob_root: str = "/srv/tracelab/blobs"
    cloud_tmp_root: str = "/srv/tracelab/tmp"
    cloud_account_quota_bytes: int = Field(default=5 * 1024**3, ge=1)
    cloud_project_quota_bytes: int = Field(default=2 * 1024**3, ge=1)
    cloud_pdf_max_bytes: int = Field(default=100 * 1024**2, ge=1)
    cloud_zip_max_bytes: int = Field(default=500 * 1024**2, ge=1)
    cloud_upload_chunk_bytes: int = Field(default=8 * 1024**2, ge=1024**2, le=32 * 1024**2)
    cloud_disk_warn_percent: int = Field(default=80, ge=50, le=95)
    cloud_disk_stop_percent: int = Field(default=90, ge=60, le=99)
    cloud_tombstone_days: int = Field(default=30, ge=30, le=365)
    cloud_blob_gc_grace_days: int = Field(default=7, ge=1, le=90)
    cloud_event_retention_days: int = Field(default=30, ge=7, le=365)

    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_starttls: bool = True
    backup_remote: str = ""

    admin_cookie_name: str = "tracelab_admin_session"
    admin_session_hours: int = Field(default=8, ge=1, le=24)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: list[str] | str) -> list[str] | str:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def cloud_public_origin(self) -> str:
        return self.public_origin

    @property
    def cors_origins(self) -> list[str]:
        values = (
            [self.allowed_origins]
            if isinstance(self.allowed_origins, str)
            else list(self.allowed_origins)
        )
        values.append(self.public_origin.rstrip("/"))
        return list(dict.fromkeys(value for value in values if value))

    def validate_runtime(self) -> None:
        if self.database_url.startswith("sqlite") and self.app_env != "test":
            raise RuntimeError("TraceLab server requires PostgreSQL outside tests")
        if self.app_env != "production":
            return
        secret = self.cloud_jwt_secret.get_secret_value()
        if (
            secret == "development-only-change-me"
            or secret.startswith("replace-")
            or len(secret) < 32
        ):
            raise RuntimeError("CLOUD_JWT_SECRET must be a random value of at least 32 bytes")
        if not self.cloud_cookie_secure or not self.public_origin.startswith("https://"):
            raise RuntimeError("Production requires HTTPS and secure cookies")
        if self.cloud_require_email_verification and not self.account_link_origin.startswith(
            "https://"
        ):
            raise RuntimeError("Production email links require an HTTPS ACCOUNT_LINK_ORIGIN")
        if self.cloud_sync_feature_enabled and self.cloud_require_email_verification:
            if not self.smtp_host or not self.smtp_from:
                raise RuntimeError("Verified production accounts require SMTP_HOST and SMTP_FROM")
        if self.cloud_sync_feature_enabled and not self.backup_remote:
            raise RuntimeError("Enabled production sync requires off-server BACKUP_REMOTE")


@lru_cache
def get_settings() -> ServerSettings:
    return ServerSettings()


settings = get_settings()
