from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


def _validate_http_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized and not normalized.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    return normalized


class AgentIntegrationRead(BaseModel):
    enabled: bool
    base_url: str
    model: str
    analysis_model: str
    thinking_mode: Literal["", "enabled", "disabled"]
    timeout_seconds: float
    api_key_configured: bool


class AgentIntegrationUpdate(BaseModel):
    enabled: bool = False
    base_url: str = Field(default="", max_length=500)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    model: str = Field(default="", max_length=160)
    analysis_model: str = Field(default="", max_length=160)
    thinking_mode: Literal["", "enabled", "disabled"] = ""
    # A single agent step can carry a large publish payload and a thinking model can spend
    # minutes on it, so the ceiling is generous; 120s was routinely hit mid-run.
    timeout_seconds: float = Field(default=120.0, gt=0, le=600)

    _normalize_url = field_validator("base_url")(_validate_http_url)


class MinerUIntegrationRead(BaseModel):
    provider: Literal["local", "official"]
    local_url: str
    backend: str
    language: str
    parse_method: str
    official_api_url: str
    official_api_model: str
    api_token_configured: bool
    ocr: bool
    formula_enable: bool
    table_enable: bool
    request_timeout_seconds: float
    request_retries: int
    task_timeout_seconds: float
    poll_interval_seconds: float


class MinerUIntegrationUpdate(BaseModel):
    provider: Literal["local", "official"] = "local"
    local_url: str = Field(default="http://127.0.0.1:8001", max_length=500)
    backend: str = Field(default="pipeline", min_length=1, max_length=64)
    language: str = Field(default="ch", min_length=1, max_length=32)
    parse_method: str = Field(default="auto", min_length=1, max_length=32)
    official_api_url: str = Field(default="https://mineru.net/api/v4", max_length=500)
    official_api_token: SecretStr | None = None
    clear_api_token: bool = False
    official_api_model: str = Field(default="vlm", min_length=1, max_length=64)
    ocr: bool = True
    formula_enable: bool = True
    table_enable: bool = True
    request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    request_retries: int = Field(default=3, ge=1, le=10)
    task_timeout_seconds: float = Field(default=600.0, gt=0, le=7200)
    poll_interval_seconds: float = Field(default=2.0, gt=0, le=30)

    _normalize_local_url = field_validator("local_url")(_validate_http_url)
    _normalize_official_url = field_validator("official_api_url")(_validate_http_url)


class RagIntegrationRead(BaseModel):
    enabled: bool
    embedder: Literal["local", "remote"]
    base_url: str
    model: str
    dimensions: int
    timeout_seconds: float
    api_key_configured: bool
    vector_store: Literal["sqlite", "lancedb"] = "sqlite"


class RagIntegrationUpdate(BaseModel):
    """Retrieval settings. ``local`` needs no network and is the default."""

    enabled: bool = True
    embedder: Literal["local", "remote"] = "local"
    base_url: str = Field(default="", max_length=500)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    model: str = Field(default="", max_length=160)
    dimensions: int = Field(default=512, ge=64, le=4096)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    vector_store: Literal["sqlite", "lancedb"] = "sqlite"

    _normalize_url = field_validator("base_url")(_validate_http_url)


class IntegrationSettingsRead(BaseModel):
    agent: AgentIntegrationRead
    mineru: MinerUIntegrationRead
    rag: RagIntegrationRead
    source: Literal["environment", "application"]
    updated_at: datetime | None = None


class IntegrationSettingsUpdate(BaseModel):
    agent: AgentIntegrationUpdate
    mineru: MinerUIntegrationUpdate
    # Optional so an older client that does not know about retrieval keeps working: omitting
    # it preserves whatever is stored rather than silently resetting the embedder.
    rag: RagIntegrationUpdate | None = None


class IntegrationProbeRequest(BaseModel):
    """Test one endpoint with the values currently typed into the settings dialog.

    Secrets are optional: omit them to probe with whatever is already stored on this machine,
    matching the dialog's "已配置，留空则保留" behaviour.
    """

    target: Literal["agent", "mineru"]
    base_url: str = Field(default="", max_length=500)
    api_key: SecretStr | None = None
    model: str = Field(default="", max_length=160)
    mineru_provider: Literal["local", "official"] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)

    _normalize_url = field_validator("base_url")(_validate_http_url)


class IntegrationProbeResult(BaseModel):
    target: Literal["agent", "mineru"]
    ok: bool
    code: str = Field(max_length=64)
    detail: str = Field(default="", max_length=600)
    latency_ms: int | None = None
