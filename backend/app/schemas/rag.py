from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RagScopeState(BaseModel):
    scope: Literal["paper", "code", "trace"]
    status: Literal["pending", "building", "ready", "failed"]
    chunk_count: int
    embedder: str
    model: str
    dimensions: int
    error: str | None = None
    built_at: datetime | None = None


class RagIndexStatusRead(BaseModel):
    enabled: bool
    embedder: str
    model: str
    scopes: list[RagScopeState]


class RagRebuildRequest(BaseModel):
    scope: Literal["paper", "code", "trace"] | None = None
    # Rebuild even when the stored generation already matches the source.
    force: bool = False


class RagScopeResult(BaseModel):
    # ``build_index`` returns extra keys (``reused``, ``reason``) depending on the path taken.
    model_config = ConfigDict(extra="allow")

    scope: str
    status: str
    chunk_count: int


class RagRebuildResult(BaseModel):
    results: list[RagScopeResult]


class RagSearchResult(BaseModel):
    ok: bool
    items: list[dict[str, Any]] = Field(default_factory=list)
    query: str = ""
    scope: str = ""
    embedder: str = ""
    reason: str | None = None
    searched: int = 0
