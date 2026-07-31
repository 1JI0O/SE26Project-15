from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    app_name: str = "Paper Code Trace Workbench"
    app_env: str = "local"
    database_url: str = "sqlite:///./data/workbench.db"
    upload_root: str = "./uploads"
    tracelab_llm_enabled: bool = False
    tracelab_llm_base_url: str = ""
    tracelab_llm_api_key: SecretStr = SecretStr("")
    tracelab_llm_model: str = ""
    tracelab_llm_thinking_mode: str = Field(default="", pattern="^(|enabled|disabled)$")
    tracelab_llm_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    tracelab_llm_max_candidates: int = Field(default=10, ge=1, le=30)
    tracelab_llm_max_context_chars: int = Field(default=12_000, ge=1000, le=100_000)
    tracelab_agent_max_loop_steps: int = Field(default=18, ge=4, le=64)
    tracelab_agent_skill_roots: list[str] | str = Field(default_factory=list)
    tracelab_agent_plugin_roots: list[str] | str = Field(default_factory=list)
    tracelab_analysis_inline_max_bytes: int = Field(default=512_000, ge=0)
    tracelab_analysis_workers: int = Field(default=2, ge=1, le=8)
    # Parallel fan-out for trace analysis sub-agents (0/1 disables parallelism; the
    # dispatch tool still works, regions just run sequentially).
    tracelab_trace_subagent_parallelism: int = Field(default=3, ge=0, le=8)
    # Per-region step budget for one trace sub-agent run.
    tracelab_trace_subagent_steps: int = Field(default=14, ge=4, le=30)
    tracelab_agent_confirmation_ttl_seconds: int = Field(default=900, ge=30, le=86_400)
    github_clone_timeout_seconds: int = Field(default=60, ge=5, le=300)
    # Loopback cloud reverse proxy. The desktop WebView cannot bypass TLS errors
    # from the self-signed cloud certificate, so the local backend forwards
    # cloud API calls upstream over a pinned CA. Empty upstream disables it.
    tracelab_cloud_upstream: str = ""
    tracelab_cloud_ca_file: str = ""
    tracelab_cloud_tls_verify: bool = True
    tracelab_cloud_proxy_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
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
        configured.extend(
            ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]
        )
        return list(dict.fromkeys(configured))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
