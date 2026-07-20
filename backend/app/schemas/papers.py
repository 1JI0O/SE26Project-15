from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PaperDocumentRead(BaseModel):
    id: int
    project_id: int
    filename: str
    title: str
    abstract: str
    sections: list[dict[str, Any]]
    paragraphs: list[dict[str, Any]]
    parser: str
    parser_version: str
    parse_status: str
    content_hash: str
    created_at: datetime


class WorkspacePaperPage(BaseModel):
    page_number: int
    title: str
    body: list[str]
    anchors: list[dict[str, Any]]


class WorkspacePaperSection(BaseModel):
    id: str
    title: str
    level: int
    page: int | None = None


class WorkspacePaperDocument(BaseModel):
    document_id: int
    filename: str
    title: str
    markdown: str
    sections: list[WorkspacePaperSection]
    asset_base_url: str
    parser: str
    parser_version: str
    source: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class PaperParseJobRead(BaseModel):
    id: str
    project_id: int
    filename: str
    parser: str
    status: str
    created_at: str
    updated_at: str
    external_task_id: str | None = None
    error: str | None = None
    cached: bool = False
    document_id: int | None = None


class PaperParseResultRead(BaseModel):
    job: PaperParseJobRead
    document: PaperDocumentRead
    parser: str
    parser_version: str
    pages: list[dict[str, Any]]
