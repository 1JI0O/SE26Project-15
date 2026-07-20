from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    app_name: str = "Paper Code Trace Workbench"
    app_env: str = "local"
    runtime_mode: str = Field(default="local", pattern="^(local|cloud|worker)$")
    database_url: str = "sqlite:///./data/workbench.db"
    upload_root: str = "./uploads"
    cloud_public_origin: str = "http://127.0.0.1:5173"
    cloud_jwt_secret: SecretStr = SecretStr("development-only-change-me")
    cloud_access_token_minutes: int = Field(default=15, ge=5, le=60)
    cloud_refresh_token_days: int = Field(default=30, ge=1, le=90)
    cloud_cookie_secure: bool = False
    cloud_blob_root: str = "./data/cloud-blobs"
    cloud_tmp_root: str = "./data/cloud-tmp"
    cloud_account_quota_bytes: int = Field(default=5 * 1024**3, ge=1)
    cloud_project_quota_bytes: int = Field(default=2 * 1024**3, ge=1)
    cloud_pdf_max_bytes: int = Field(default=100 * 1024**2, ge=1)
    cloud_zip_max_bytes: int = Field(default=500 * 1024**2, ge=1)
    cloud_upload_chunk_bytes: int = Field(default=8 * 1024**2, ge=1024**2, le=32 * 1024**2)
    cloud_disk_warn_percent: int = Field(default=80, ge=50, le=95)
    cloud_disk_stop_percent: int = Field(default=90, ge=60, le=99)
    cloud_tombstone_days: int = Field(default=30, ge=30, le=365)
    cloud_blob_gc_grace_days: int = Field(default=7, ge=1, le=90)
    cloud_run_migrations_on_start: bool = False
    cloud_sync_feature_enabled: bool = False
    cloud_require_email_verification: bool = False
    cloud_require_ops_gates: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_starttls: bool = True
    backup_remote: str = ""
    tracelab_llm_enabled: bool = False
    tracelab_llm_base_url: str = ""
    tracelab_llm_api_key: SecretStr = SecretStr("")
    tracelab_llm_model: str = ""
    tracelab_llm_thinking_mode: str = Field(default="", pattern="^(|enabled|disabled)$")
    tracelab_llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    tracelab_llm_max_candidates: int = Field(default=10, ge=1, le=30)
    tracelab_llm_max_context_chars: int = Field(default=12_000, ge=1000, le=100_000)
    tracelab_agent_max_loop_steps: int = Field(default=18, ge=4, le=64)
    tracelab_agent_skill_roots: list[str] | str = Field(default_factory=list)
    tracelab_agent_plugin_roots: list[str] | str = Field(default_factory=list)
    tracelab_analysis_inline_max_bytes: int = Field(default=512_000, ge=0)
    tracelab_analysis_workers: int = Field(default=2, ge=1, le=8)
    tracelab_agent_confirmation_ttl_seconds: int = Field(default=900, ge=30, le=86_400)
    github_clone_timeout_seconds: int = Field(default=60, ge=5, le=300)
    backend_cors_origins: list[str] | str = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )

    # Desktop settings moved into SQLite. Ignore obsolete keys left in a
    # developer/user .env instead of making the packaged backend unbootable.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: list[str] | str) -> list[str] | str:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator(
        "tracelab_agent_skill_roots",
        "tracelab_agent_plugin_roots",
        mode="before",
    )
    @classmethod
    def parse_path_list(cls, value: list[str] | str) -> list[str] | str:
        if isinstance(value, str):
            return [path.strip() for path in value.split(",") if path.strip()]
        return value

    @property
    def cors_origins(self) -> list[str]:
        configured = (
            [self.backend_cors_origins]
            if isinstance(self.backend_cors_origins, str)
            else list(self.backend_cors_origins)
        )
        if self.runtime_mode == "local":
            configured.extend(
                ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]
            )
        return list(dict.fromkeys(configured))

    @property
    def is_cloud(self) -> bool:
        return self.runtime_mode == "cloud"

    def validate_cloud_runtime(self) -> None:
        if self.runtime_mode not in {"cloud", "worker"} or self.app_env != "production":
            return
        if self.database_url.startswith("sqlite"):
            raise RuntimeError("Cloud production requires PostgreSQL")
        if self.runtime_mode == "worker":
            return
        jwt_secret = self.cloud_jwt_secret.get_secret_value()
        if (
            jwt_secret == "development-only-change-me"
            or jwt_secret.startswith("replace-")
            or len(jwt_secret) < 32
        ):
            raise RuntimeError("CLOUD_JWT_SECRET must be changed in production")
        if not self.cloud_cookie_secure:
            raise RuntimeError("Cloud production requires secure cookies")
        if not self.cloud_public_origin.startswith("https://"):
            raise RuntimeError("Cloud production requires an HTTPS public origin")
        if not self.cloud_require_ops_gates:
            return
        if self.cloud_sync_feature_enabled and (not self.smtp_host or not self.smtp_from):
            raise RuntimeError("Production cloud sync requires SMTP configuration")
        if self.cloud_sync_feature_enabled and not self.backup_remote:
            raise RuntimeError("Production cloud sync requires off-server BACKUP_REMOTE")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
