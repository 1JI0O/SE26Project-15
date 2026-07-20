from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TraceStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE = "stale"


class TraceRelationType(StrEnum):
    IMPLEMENTS = "implements"
    INVOKES = "invokes"
    CONFIGURES = "configures"
    TESTS = "tests"
    MENTIONS = "mentions"


class TraceEvidence(BaseModel):
    side: str = Field(pattern="^(paper|code)$")
    ref: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=2000)
    path: str | None = Field(default=None, max_length=1000)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class TraceUncertainty(BaseModel):
    level: str = Field(pattern="^(low|medium|high)$")
    reasons: list[str] = Field(default_factory=list, max_length=8)


class TraceModelInfo(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(default="trace-v1", max_length=64)


class TraceLinkCreate(BaseModel):
    paper_ref: str = Field(min_length=1, max_length=255)
    code_ref: str = Field(min_length=1, max_length=255)
    relation_type: TraceRelationType = TraceRelationType.IMPLEMENTS
    confidence: float = Field(default=0.5, ge=0, le=1)
    rationale: str = Field(default="", max_length=5000)
    evidence: list[TraceEvidence] = Field(default_factory=list)


class TraceLinkRead(BaseModel):
    id: str
    project_id: int
    paper_document_id: int | None
    paper_block_id: str
    code_repository_id: int | None
    code_revision: int
    code_symbol_id: str
    relation_type: TraceRelationType
    confidence: float = Field(ge=0, le=1)
    static_confidence: float = Field(ge=0, le=1)
    llm_confidence: float | None = Field(default=None, ge=0, le=1)
    source: str
    evidence: list[TraceEvidence]
    rationale: str
    uncertainty: TraceUncertainty
    model: TraceModelInfo | None
    status: TraceStatus
    stale_reason: str | None
    created_at: datetime
    updated_at: datetime


class TraceSuggestionRequest(BaseModel):
    use_llm: bool = True
    paper_document_id: int | None = None
    code_repository_id: int | None = None


class TraceSuggestionResponse(BaseModel):
    mode: str = Field(pattern=r"^(static|static\+llm)$")
    degraded: bool
    degraded_reason: str | None = None
    items: list[TraceLinkRead]


class TraceStatusUpdate(BaseModel):
    status: TraceStatus


class TraceLinkSuggestion(BaseModel):
    """Iteration 1 compatibility schema for workspace aggregation."""

    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: float
    rationale: str


class WorkspaceTraceRow(BaseModel):
    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: int = Field(ge=0, le=100)
    rationale: str
