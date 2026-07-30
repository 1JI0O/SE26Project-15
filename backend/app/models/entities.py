from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime.

    Every timestamp here is written as aware UTC via :func:`utc_now`, but SQLite has no
    timezone-aware type: a value read back from the database comes out **naive**. Mixing the
    two in a comparison or subtraction raises ``TypeError: can't subtract offset-naive and
    offset-aware datetimes``, so anything that compares a stored timestamp against
    :func:`utc_now` must normalize it through here first.
    """

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Project(SQLModel, table=True):
    __tablename__ = "project"

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    cloud_workspace_id: str | None = Field(default=None, index=True, max_length=36)
    name: str = Field(index=True, max_length=160)
    description: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    version: int = Field(default=1, ge=1)
    sync_mode: str = Field(default="local_only", max_length=24, index=True)
    agent_history_sync: bool = Field(default=True)
    deleted_at: datetime | None = Field(default=None)


class PaperDocument(SQLModel, table=True):
    __tablename__ = "paper_document"

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    blob_id: str | None = Field(default=None, max_length=36)
    project_id: int = Field(foreign_key="project.id", index=True)
    filename: str = Field(max_length=255)
    storage_path: str
    title: str = Field(default="")
    abstract: str = Field(default="")
    parser: str = Field(default="legacy", max_length=64)
    parser_version: str = Field(default="", max_length=128)
    parse_status: str = Field(default="succeeded", max_length=32)
    content_hash: str = Field(default="", max_length=64)
    sections_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    paragraphs_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    pages_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)


class CodeRepository(SQLModel, table=True):
    __tablename__ = "code_repository"

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    blob_id: str | None = Field(default=None, max_length=36)
    project_id: int = Field(foreign_key="project.id", index=True)
    filename: str = Field(max_length=255)
    storage_path: str
    file_tree_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    symbols_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    imports_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    pytorch_candidates_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    tensor_graph_json: dict[str, Any] = Field(
        default_factory=lambda: {"nodes": [], "edges": []},
        sa_column=Column(JSON, nullable=False),
    )
    analysis_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    analysis_revision: int = Field(default=0, ge=0)
    analysis_version: str = Field(default="", max_length=64)
    analysis_status: str = Field(default="pending", max_length=24, index=True)
    analysis_error: str | None = Field(default=None, max_length=500)
    analysis_updated_at: datetime | None = Field(default=None)
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class LocalArtifactVersion(SQLModel, table=True):
    __tablename__ = "local_artifact_version"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_public_id",
            "version_number",
            name="uq_local_artifact_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    entity_type: str = Field(index=True, max_length=64)
    entity_public_id: str = Field(index=True, max_length=36)
    version_number: int = Field(ge=1)
    blob_id: str | None = Field(default=None, max_length=36)
    cloud_version_id: str | None = Field(default=None, max_length=36)
    filename: str = Field(max_length=255)
    storage_path: str
    is_current: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TraceLink(SQLModel, table=True):
    __tablename__ = "trace_link"
    __table_args__ = (
        UniqueConstraint("trace_id", name="uq_trace_link_trace_id"),
        UniqueConstraint("fingerprint", name="uq_trace_link_fingerprint"),
    )

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    trace_id: str = Field(
        default_factory=lambda: f"trace-{uuid4().hex}",
        index=True,
        max_length=64,
    )
    project_id: int = Field(foreign_key="project.id", index=True)
    paper_document_id: int | None = Field(default=None, foreign_key="paper_document.id", index=True)
    paper_ref: str = Field(max_length=255)
    code_repository_id: int | None = Field(
        default=None,
        foreign_key="code_repository.id",
        index=True,
    )
    code_revision: int = Field(default=1, ge=1)
    code_ref: str = Field(max_length=255)
    relation_type: str = Field(max_length=64)
    confidence: float = Field(default=0)
    static_confidence: float = Field(default=0)
    llm_confidence: float | None = Field(default=None)
    source: str = Field(default="static", max_length=32)
    evidence_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    rationale: str = Field(default="", sa_column=Column(Text, nullable=False))
    uncertainty_json: dict[str, Any] = Field(
        default_factory=lambda: {"level": "high", "reasons": []},
        sa_column=Column(JSON, nullable=False),
    )
    model_info_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    artifact_id: str | None = Field(default=None, index=True, max_length=72)
    paper_target_id: str | None = Field(default=None, index=True, max_length=72)
    code_target_id: str | None = Field(default=None, index=True, max_length=72)
    relevance: float = Field(default=0)
    score_basis_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    provenance_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    supersedes_trace_id: str | None = Field(default=None, index=True, max_length=64)
    fingerprint: str = Field(default_factory=lambda: f"manual-{uuid4().hex}", max_length=64)
    status: str = Field(default="proposed", max_length=32, index=True)
    stale_reason: str | None = Field(default=None, max_length=128)
    decided_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def paper_block_id(self) -> str:
        return self.paper_ref

    @property
    def code_symbol_id(self) -> str:
        return self.code_ref


class AgentToolRequest(SQLModel, table=True):
    __tablename__ = "agent_tool_request"
    __table_args__ = (UniqueConstraint("confirmation_id", name="uq_agent_confirmation_id"),)

    id: int | None = Field(default=None, primary_key=True)
    confirmation_id: str = Field(
        default_factory=lambda: f"confirm-{uuid4().hex}",
        index=True,
        max_length=72,
    )
    project_id: int = Field(foreign_key="project.id", index=True)
    conversation_id: str | None = Field(
        default=None,
        foreign_key="agent_conversation.conversation_id",
        index=True,
        max_length=72,
    )
    run_id: str | None = Field(
        default=None,
        foreign_key="agent_run.run_id",
        index=True,
        max_length=72,
    )
    tool_name: str = Field(max_length=64)
    private_arguments_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    parameter_summary_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="pending", max_length=32, index=True)
    user_decision: str | None = Field(default=None, max_length=16)
    result_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_summary: str | None = Field(default=None, max_length=500)
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = Field(default=None)
    executed_at: datetime | None = Field(default=None)


class AgentConversation(SQLModel, table=True):
    __tablename__ = "agent_conversation"

    conversation_id: str = Field(
        default_factory=lambda: f"conv-{uuid4().hex}",
        primary_key=True,
        max_length=72,
    )
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str = Field(default="interactive", max_length=24, index=True)
    title: str = Field(default="新对话", max_length=160)
    status: str = Field(default="active", max_length=24, index=True)
    summary: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class AgentMessage(SQLModel, table=True):
    __tablename__ = "agent_message"
    __table_args__ = (UniqueConstraint("message_id", name="uq_agent_message_id"),)

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    message_id: str = Field(
        default_factory=lambda: f"msg-{uuid4().hex}",
        index=True,
        max_length=72,
    )
    conversation_id: str = Field(
        foreign_key="agent_conversation.conversation_id",
        index=True,
        max_length=72,
    )
    project_id: int = Field(foreign_key="project.id", index=True)
    role: str = Field(max_length=24, index=True)
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    citations_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AgentRun(SQLModel, table=True):
    __tablename__ = "agent_run"

    run_id: str = Field(
        default_factory=lambda: f"run-{uuid4().hex}",
        primary_key=True,
        max_length=72,
    )
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    conversation_id: str = Field(
        foreign_key="agent_conversation.conversation_id",
        index=True,
        max_length=72,
    )
    project_id: int = Field(foreign_key="project.id", index=True)
    status: str = Field(default="running", max_length=32, index=True)
    provider_name: str = Field(default="", max_length=64)
    model_name: str = Field(default="", max_length=160)
    step_count: int = Field(default=0, ge=0)
    trace_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    capability_snapshot_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    degraded_reason: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class AgentRunEvent(SQLModel, table=True):
    __tablename__ = "agent_run_event"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_agent_run_event_id"),
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
    )

    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    event_id: str = Field(
        default_factory=lambda: f"event-{uuid4().hex}",
        index=True,
        max_length=72,
    )
    run_id: str = Field(foreign_key="agent_run.run_id", index=True, max_length=72)
    conversation_id: str = Field(
        foreign_key="agent_conversation.conversation_id",
        index=True,
        max_length=72,
    )
    project_id: int = Field(foreign_key="project.id", index=True)
    sequence: int = Field(ge=1)
    event_type: str = Field(max_length=64, index=True)
    payload_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AgentMemory(SQLModel, table=True):
    __tablename__ = "agent_memory"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_agent_memory_fingerprint"),)

    memory_id: str = Field(
        default_factory=lambda: f"memory-{uuid4().hex}",
        primary_key=True,
        max_length=72,
    )
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    conversation_id: str | None = Field(
        default=None,
        foreign_key="agent_conversation.conversation_id",
        index=True,
        max_length=72,
    )
    scope: str = Field(default="project", max_length=24, index=True)
    kind: str = Field(default="fact", max_length=32, index=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    source_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    importance: float = Field(default=0.5, ge=0, le=1)
    fingerprint: str = Field(max_length=64, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_used_at: datetime | None = Field(default=None)


class AgentCapabilitySetting(SQLModel, table=True):
    __tablename__ = "agent_capability_setting"

    capability_id: str = Field(primary_key=True, max_length=160)
    enabled: bool = Field(default=False, index=True)
    trusted: bool = Field(default=False, index=True)
    config_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    updated_at: datetime = Field(default_factory=utc_now)


class RepositoryAnalysisJob(SQLModel, table=True):
    __tablename__ = "repository_analysis_job"

    job_id: str = Field(
        default_factory=lambda: f"analysis-{uuid4().hex}",
        primary_key=True,
        max_length=72,
    )
    project_id: int = Field(foreign_key="project.id", index=True)
    repository_id: int = Field(foreign_key="code_repository.id", index=True)
    repository_revision: int = Field(ge=1, index=True)
    status: str = Field(default="queued", max_length=24, index=True)
    targets_json: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    error_summary: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class AgentAnalysisJob(SQLModel, table=True):
    __tablename__ = "agent_analysis_job"

    job_id: str = Field(
        default_factory=lambda: f"agent-analysis-{uuid4().hex}",
        primary_key=True,
        max_length=72,
    )
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str = Field(max_length=24, index=True)
    status: str = Field(default="queued", max_length=24, index=True)
    paper_document_id: int | None = Field(
        default=None, foreign_key="paper_document.id", index=True
    )
    code_repository_id: int = Field(foreign_key="code_repository.id", index=True)
    code_revision: int = Field(ge=1, index=True)
    root_symbol: str | None = Field(default=None, max_length=500)
    requested_depth: int = Field(default=2, ge=1, le=3)
    agent_run_id: str | None = Field(
        default=None, foreign_key="agent_run.run_id", index=True, max_length=72
    )
    artifact_id: str | None = Field(default=None, index=True, max_length=72)
    fingerprint: str = Field(index=True, unique=True, max_length=64)
    progress_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    error_code: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class AgentAnalysisArtifact(SQLModel, table=True):
    __tablename__ = "agent_analysis_artifact"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_agent_analysis_artifact_fp"),)

    artifact_id: str = Field(
        default_factory=lambda: f"artifact-{uuid4().hex}",
        primary_key=True,
        max_length=72,
    )
    job_id: str = Field(foreign_key="agent_analysis_job.job_id", index=True, max_length=72)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str = Field(max_length=24, index=True)
    schema_version: str = Field(max_length=64)
    payload_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    paper_document_id: int | None = Field(
        default=None, foreign_key="paper_document.id", index=True
    )
    code_repository_id: int = Field(foreign_key="code_repository.id", index=True)
    code_revision: int = Field(ge=1, index=True)
    agent_run_id: str = Field(foreign_key="agent_run.run_id", index=True, max_length=72)
    model_info_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    capability_snapshot_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    fingerprint: str = Field(max_length=64, index=True)
    is_current: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class IntegrationConfig(SQLModel, table=True):
    __tablename__ = "integration_config"

    id: int = Field(default=1, primary_key=True)
    agent_enabled: bool = Field(default=False)
    agent_base_url: str = Field(default="", max_length=500)
    agent_api_key: str = Field(default="", sa_column=Column(Text, nullable=False), repr=False)
    agent_model: str = Field(default="", max_length=160)
    agent_analysis_model: str = Field(default="", max_length=160)
    agent_thinking_mode: str = Field(default="", max_length=16)
    agent_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    mineru_provider: str = Field(default="local", max_length=16)
    mineru_local_url: str = Field(default="http://127.0.0.1:8001", max_length=500)
    mineru_backend: str = Field(default="pipeline", max_length=64)
    mineru_language: str = Field(default="ch", max_length=32)
    mineru_parse_method: str = Field(default="auto", max_length=32)
    mineru_official_api_url: str = Field(default="https://mineru.net/api/v4", max_length=500)
    mineru_official_api_token: str = Field(
        default="", sa_column=Column(Text, nullable=False), repr=False
    )
    mineru_official_api_model: str = Field(default="vlm", max_length=64)
    mineru_ocr: bool = Field(default=True)
    mineru_formula_enable: bool = Field(default=True)
    mineru_table_enable: bool = Field(default=True)
    mineru_request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    mineru_request_retries: int = Field(default=3, ge=1, le=10)
    mineru_task_timeout_seconds: float = Field(default=600.0, gt=0, le=7200)
    mineru_poll_interval_seconds: float = Field(default=2.0, gt=0, le=30)
    rag_enabled: bool = Field(default=True)
    rag_embedder: str = Field(default="local", max_length=16)
    rag_base_url: str = Field(default="", max_length=500)
    rag_api_key: str = Field(default="", sa_column=Column(Text, nullable=False), repr=False)
    rag_model: str = Field(default="", max_length=160)
    rag_dimensions: int = Field(default=512, ge=64, le=4096)
    rag_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    updated_at: datetime = Field(default_factory=utc_now)


class RagChunk(SQLModel, table=True):
    """One embedded retrieval unit (paper block, code symbol, or confirmed trace case).

    Chunks are derived data: every row is rebuilt from its source (paper document, code
    revision, trace links) and keyed by ``scope`` + ``source_key`` so a rebuild replaces the
    previous generation wholesale. ``embedding`` is a base64 float32 vector — SQLite has no
    vector type and the corpora here are small enough (thousands of chunks) that an exact
    in-Python cosine scan beats taking on a native index dependency inside the PyInstaller
    sidecar.
    """

    __tablename__ = "rag_chunk"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    # "paper" | "code" | "trace"
    scope: str = Field(max_length=16, index=True)
    # Identifies the indexed generation: paper content hash, code revision, or "trace".
    source_key: str = Field(max_length=128, index=True)
    # Stable id of the underlying object (paper block id, code symbol id, trace id).
    ref: str = Field(max_length=500)
    text: str = Field(sa_column=Column(Text, nullable=False))
    embedding: str = Field(sa_column=Column(Text, nullable=False), repr=False)
    dimensions: int = Field(default=0, ge=0)
    embedder: str = Field(default="local", max_length=64)
    token_count: int = Field(default=0, ge=0)
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=utc_now)


class RagIndexState(SQLModel, table=True):
    """Bookkeeping for one (project, scope) index so rebuilds are skipped when current."""

    __tablename__ = "rag_index_state"
    __table_args__ = (UniqueConstraint("project_id", "scope", name="uq_rag_index_project_scope"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    scope: str = Field(max_length=16, index=True)
    source_key: str = Field(default="", max_length=128)
    embedder: str = Field(default="local", max_length=64)
    model: str = Field(default="", max_length=160)
    dimensions: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    # "pending" | "building" | "ready" | "failed"
    status: str = Field(default="pending", max_length=16, index=True)
    error: str | None = Field(default=None, max_length=500)
    built_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utc_now)


class PaperTarget(SQLModel, table=True):
    """A precise, hoverable anchor inside the paper (formula/variable/algorithm/etc.).

    Identity is (section_path + quote + occurrence + quote_hash); ``block_id`` is only a
    navigation hint because MinerU block IDs can drift across re-parses.
    """

    __tablename__ = "paper_target"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_paper_target_fingerprint"),)

    target_id: str = Field(
        default_factory=lambda: f"ptarget-{uuid4().hex}", primary_key=True, max_length=72
    )
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    project_id: int = Field(foreign_key="project.id", index=True)
    artifact_id: str = Field(
        foreign_key="agent_analysis_artifact.artifact_id", index=True, max_length=72
    )
    paper_document_id: int = Field(foreign_key="paper_document.id", index=True)
    target_type: str = Field(max_length=32, index=True)
    block_id: str = Field(max_length=255, index=True)
    section_path_json: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    quote: str = Field(sa_column=Column(Text, nullable=False))
    occurrence: int = Field(default=1, ge=1)
    char_start: int | None = Field(default=None)
    char_end: int | None = Field(default=None)
    quote_hash: str = Field(max_length=64, index=True)
    bbox_json: list[float] | None = Field(default=None, sa_column=Column(JSON))
    asset_path: str | None = Field(default=None, max_length=1000)
    salience: float = Field(default=0)
    salience_reason: str = Field(default="", sa_column=Column(Text, nullable=False))
    anchor_status: str = Field(default="validated", max_length=32, index=True)
    fingerprint: str = Field(max_length=64, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class CodeTarget(SQLModel, table=True):
    """A precise, hoverable anchor inside the repository at a pinned revision.

    Identity is (path + code_quote_hash + occurrence); line numbers are only an initial
    search window, not identity.
    """

    __tablename__ = "code_target"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_code_target_fingerprint"),)

    target_id: str = Field(
        default_factory=lambda: f"ctarget-{uuid4().hex}", primary_key=True, max_length=72
    )
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    project_id: int = Field(foreign_key="project.id", index=True)
    artifact_id: str = Field(
        foreign_key="agent_analysis_artifact.artifact_id", index=True, max_length=72
    )
    code_repository_id: int = Field(foreign_key="code_repository.id", index=True)
    code_revision: int = Field(index=True)
    path: str = Field(max_length=1000, index=True)
    symbol_id: str | None = Field(default=None, max_length=500, index=True)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    column_start: int | None = Field(default=None)
    column_end: int | None = Field(default=None)
    quote: str = Field(sa_column=Column(Text, nullable=False))
    occurrence: int = Field(default=1, ge=1)
    code_quote_hash: str = Field(max_length=64, index=True)
    role: str = Field(max_length=64, index=True)
    salience: float = Field(default=0)
    salience_reason: str = Field(default="", sa_column=Column(Text, nullable=False))
    anchor_status: str = Field(default="validated", max_length=32, index=True)
    fingerprint: str = Field(max_length=64, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TraceReviewEvent(SQLModel, table=True):
    """Append-only human/agent decision log for trace links (accept/reject/modify/...)."""

    __tablename__ = "trace_review_event"

    event_id: str = Field(
        default_factory=lambda: f"review-{uuid4().hex}", primary_key=True, max_length=72
    )
    public_id: str = Field(
        default_factory=lambda: str(uuid4()), index=True, unique=True, max_length=36
    )
    version: int = Field(default=1, ge=1)
    project_id: int = Field(foreign_key="project.id", index=True)
    trace_id: str = Field(max_length=64, index=True)
    action: str = Field(max_length=32)
    actor_type: str = Field(max_length=24)
    actor_ref: str | None = Field(default=None, max_length=160)
    before_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    after_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    reason: str = Field(default="", sa_column=Column(Text, nullable=False))
    job_id: str | None = Field(default=None, max_length=72)
    run_id: str | None = Field(default=None, max_length=72)
    created_at: datetime = Field(default_factory=utc_now)
