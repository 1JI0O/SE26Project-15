from pydantic import BaseModel, Field

from app.schemas.papers import WorkspacePaperPage
from app.schemas.repositories import (
    WorkspaceCodeFileRead,
    WorkspaceCodeTreeNode,
    WorkspaceTensorFlowRead,
)
from app.schemas.traces import WorkspaceTraceRow


class WorkspaceImportStep(BaseModel):
    index: str
    title: str
    description: str
    status: str
    tag_type: str
    action: str | None = None


class WorkspaceFlowNode(BaseModel):
    stage: str
    title: str
    description: str


class WorkspaceConflictItem(BaseModel):
    id: str = ""
    category: str = "behavior_regression"
    severity: str = "low"
    confidence: float = 0
    level: str
    type: str
    title: str
    description: str
    affected_files: list[str]
    status: str


class WorkspaceChangeSummary(BaseModel):
    repository_revision: int
    analysis_status: str
    analysis_current: bool
    has_changes: bool
    changed_file_count: int
    changed_line_count: int
    latest_conflict_job_id: str | None = None
    latest_conflict_artifact_id: str | None = None
    analyzed_revision: int | None = None
    report_stale: bool = False


class WorkspaceReportCard(BaseModel):
    value: str
    title: str
    description: str


class WorkspaceRead(BaseModel):
    project_id: str
    project_name: str
    import_steps: list[WorkspaceImportStep]
    paper_pages: list[WorkspacePaperPage]
    code_tree: list[WorkspaceCodeTreeNode]
    code_files: list[WorkspaceCodeFileRead]
    trace_rows: list[WorkspaceTraceRow]
    flow_nodes: list[WorkspaceFlowNode]
    tensor_flow: WorkspaceTensorFlowRead
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
