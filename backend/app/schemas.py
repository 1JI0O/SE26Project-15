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


class WorkspaceImportStep(BaseModel):
    index: str
    title: str
    description: str
    status: str
    tag_type: str
    action: str | None = None


class WorkspacePaperPage(BaseModel):
    page_number: int
    title: str
    body: list[str]
    anchors: list[dict[str, Any]]


class WorkspaceCodeFileSummary(BaseModel):
    path: str
    name: str
    badge: str
    status: str
    status_type: str
    symbol: str
    paper_ref: str


class WorkspaceCodeFileRead(WorkspaceCodeFileSummary):
    content: str
    linked_lines: list[int]


class WorkspaceTraceRow(BaseModel):
    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: int = Field(ge=0, le=100)
    rationale: str


class WorkspaceFlowNode(BaseModel):
    stage: str
    title: str
    description: str


class WorkspaceConflictItem(BaseModel):
    level: str
    type: str
    title: str
    description: str
    affected_files: list[str]
    status: str


class WorkspaceReportCard(BaseModel):
    value: str
    title: str
    description: str


class WorkspaceRead(BaseModel):
    project_id: str
    project_name: str
    import_steps: list[WorkspaceImportStep]
    paper_pages: list[WorkspacePaperPage]
    code_files: list[WorkspaceCodeFileRead]
    trace_rows: list[WorkspaceTraceRow]
    flow_nodes: list[WorkspaceFlowNode]
    conflict_items: list[WorkspaceConflictItem]
    report_cards: list[WorkspaceReportCard]


class WorkspaceAnalyzeRequest(BaseModel):
    mode: str = Field(default="full", max_length=64)
    targets: list[str] = Field(default_factory=list)


class WorkspaceAnalyzeJob(BaseModel):
    project_id: str
    job_id: str
    status: str
    message: str
