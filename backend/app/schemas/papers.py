from datetime import datetime
from typing import Any

from pydantic import BaseModel


class PaperDocumentRead(BaseModel):
    id: int
    project_id: int
    filename: str
    title: str
    abstract: str
    sections: list[dict[str, Any]]
    paragraphs: list[dict[str, Any]]
    created_at: datetime


class WorkspacePaperPage(BaseModel):
    page_number: int
    title: str
    body: list[str]
    anchors: list[dict[str, Any]]


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
