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
