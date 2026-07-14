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
