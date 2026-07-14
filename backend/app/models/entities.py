from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class Project(SQLModel, table=True):
    __tablename__ = "project"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=160)
    description: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PaperDocument(SQLModel, table=True):
    __tablename__ = "paper_document"

    id: int | None = Field(default=None, primary_key=True)
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
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TraceLink(SQLModel, table=True):
    __tablename__ = "trace_link"
    __table_args__ = (
        UniqueConstraint("trace_id", name="uq_trace_link_trace_id"),
        UniqueConstraint("fingerprint", name="uq_trace_link_fingerprint"),
    )

    id: int | None = Field(default=None, primary_key=True)
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
