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
    COMPUTES = "computes"
    DEFINES = "defines"
    CONSTRAINS = "constrains"
    UPDATES = "updates"
    CONFIGURES = "configures"
    INVOKES = "invokes"
    # Retained for backward compatibility with legacy/manual links.
    TESTS = "tests"
    MENTIONS = "mentions"


# Chat LLMs often invent near-synonyms that are not in the enum; map the common ones so a
# single bad string cannot 500 the whole GET /trace-links list after confirmation lands.
_RELATION_TYPE_ALIASES: dict[str, TraceRelationType] = {
    "references": TraceRelationType.MENTIONS,
    "reference": TraceRelationType.MENTIONS,
    "refers": TraceRelationType.MENTIONS,
    "refers_to": TraceRelationType.MENTIONS,
    "related": TraceRelationType.MENTIONS,
    "related_to": TraceRelationType.MENTIONS,
    "describes": TraceRelationType.MENTIONS,
    "mentions": TraceRelationType.MENTIONS,
    "implements": TraceRelationType.IMPLEMENTS,
    "computes": TraceRelationType.COMPUTES,
    "defines": TraceRelationType.DEFINES,
    "constrains": TraceRelationType.CONSTRAINS,
    "updates": TraceRelationType.UPDATES,
    "configures": TraceRelationType.CONFIGURES,
    "invokes": TraceRelationType.INVOKES,
    "tests": TraceRelationType.TESTS,
}


def normalize_relation_type(
    value: object,
    *,
    fallback: TraceRelationType = TraceRelationType.MENTIONS,
) -> TraceRelationType:
    """Coerce a free-form relation label into a known ``TraceRelationType``.

    Unknown values fall back to ``mentions`` so stored chat-tool rows remain listable even when
    the model invents a type the schema never declared (e.g. ``references``).
    """

    if isinstance(value, TraceRelationType):
        return value
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return fallback
    if raw in _RELATION_TYPE_ALIASES:
        return _RELATION_TYPE_ALIASES[raw]
    try:
        return TraceRelationType(raw)
    except ValueError:
        return fallback


class TraceEvidence(BaseModel):
    side: str = Field(pattern="^(paper|code)$")
    ref: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=3000)
    path: str | None = Field(default=None, max_length=1000)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    # Fragment-level anchoring (V1): pinpoints the exact occurrence for hover highlighting.
    target_id: str | None = Field(default=None, max_length=72)
    target_type: str | None = Field(default=None, max_length=32)
    role: str | None = Field(default=None, max_length=64)
    occurrence: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    column_start: int | None = Field(default=None, ge=0)
    column_end: int | None = Field(default=None, ge=0)
    quote_hash: str | None = Field(default=None, max_length=64)
    code_quote_hash: str | None = Field(default=None, max_length=64)
    salience: float | None = Field(default=None, ge=0, le=1)


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
    relevance: float = Field(default=0, ge=0, le=1)
    static_confidence: float = Field(ge=0, le=1)
    llm_confidence: float | None = Field(default=None, ge=0, le=1)
    source: str
    paper_target_id: str | None = None
    code_target_id: str | None = None
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


class TraceLinkUpdate(BaseModel):
    relation_type: TraceRelationType | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = Field(default=None, min_length=1, max_length=5000)


class TraceBatchStatusUpdate(BaseModel):
    status: TraceStatus
    # When omitted/empty, applies to every currently-proposed link in the project.
    trace_ids: list[str] | None = Field(default=None, max_length=1000)


class TraceBatchStatusResult(BaseModel):
    status: TraceStatus
    updated_count: int
    skipped_count: int
    updated: list[TraceLinkRead]


class TraceClearScope(StrEnum):
    """Which existing relations a clear request removes.

    ``proposed`` keeps every human decision (accepted/rejected) and only drops candidates
    nobody reviewed. ``agent`` additionally drops reviewed agent output but keeps manual
    relations. ``all`` empties the project's relation set.
    """

    PROPOSED = "proposed"
    AGENT = "agent"
    ALL = "all"


class TraceClearResult(BaseModel):
    scope: TraceClearScope
    deleted_count: int
    kept_count: int


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
