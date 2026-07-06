from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthRead(BaseModel):
    status: str
    service: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class ProjectRead(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaperDocumentRead(BaseModel):
    id: int
    project_id: int
    filename: str
    title: str
    abstract: str
    sections: list[dict[str, Any]]
    paragraphs: list[dict[str, Any]]
    created_at: datetime


class CodeRepositoryRead(BaseModel):
    id: int
    project_id: int
    filename: str
    file_tree: list[dict[str, Any]]
    symbols: list[dict[str, Any]]
    imports: list[dict[str, Any]]
    pytorch_candidates: list[dict[str, Any]]
    created_at: datetime


class TraceLinkCreate(BaseModel):
    paper_ref: str = Field(min_length=1, max_length=255)
    code_ref: str = Field(min_length=1, max_length=255)
    relation_type: str = Field(default="implements", max_length=64)
    confidence: float = Field(default=0.5, ge=0, le=1)
    rationale: str = ""


class TraceLinkRead(BaseModel):
    id: int
    project_id: int
    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: float
    rationale: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TraceLinkSuggestion(BaseModel):
    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: float
    rationale: str

