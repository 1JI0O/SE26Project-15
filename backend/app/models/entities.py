from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
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
    sections_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    paragraphs_json: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
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
    created_at: datetime = Field(default_factory=utc_now)


class TraceLink(SQLModel, table=True):
    __tablename__ = "trace_link"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    paper_ref: str = Field(max_length=255)
    code_ref: str = Field(max_length=255)
    relation_type: str = Field(max_length=64)
    confidence: float = Field(default=0)
    rationale: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)
