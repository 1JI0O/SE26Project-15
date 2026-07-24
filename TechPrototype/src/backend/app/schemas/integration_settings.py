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
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)

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


class IntegrationSettingsRead(BaseModel):
    agent: AgentIntegrationRead
    mineru: MinerUIntegrationRead
    source: Literal["environment", "application"]
    updated_at: datetime | None = None


class IntegrationSettingsUpdate(BaseModel):
    agent: AgentIntegrationUpdate
    mineru: MinerUIntegrationUpdate
