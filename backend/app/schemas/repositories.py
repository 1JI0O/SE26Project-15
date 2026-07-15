from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CodeRepositoryRead(BaseModel):
    id: int
    project_id: int
    filename: str
    file_tree: list[dict[str, Any]]
    symbols: list[dict[str, Any]]
    imports: list[dict[str, Any]]
    calls: list[dict[str, Any]] = Field(default_factory=list)
    pytorch_candidates: list[dict[str, Any]]
    tensor_graph: "TensorGraphRead | None" = None
    summary: "RepositorySummary | None" = None
    revision: int
    created_at: datetime


class RepositorySummary(BaseModel):
    file_count: int
    python_file_count: int
    symbol_count: int
    call_count: int
    ignored_count: int
    total_bytes: int


class TensorGraphNode(BaseModel):
    id: str
    op: str
    label: str
    kind: str
    description: str
    symbol_id: str
    shape: list[int | None] | None = None
    shape_reason: str | None = None
    source_path: str
    line_start: int
    line_end: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class TensorGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: str
    label: str


class TensorGraphRead(BaseModel):
    nodes: list[TensorGraphNode]
    edges: list[TensorGraphEdge]
    entry_symbols: list[str] = Field(default_factory=list)
    shape_status: str
    shape_reason: str | None = None


class CodeAnalysisRead(BaseModel):
    symbols: list[dict[str, Any]]
    imports: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    pytorch_candidates: list[dict[str, Any]]
    tensor_graph: TensorGraphRead
    summary: RepositorySummary


class GitHubRepositoryImport(BaseModel):
    url: str = Field(min_length=19, max_length=500)


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


class WorkspaceCodeFileUpdate(BaseModel):
    content: str


class WorkspaceCodeFileSaveResult(BaseModel):
    project_id: str
    path: str
    status: str
    message: str
    repository_revision: int
    stale_trace_count: int


class WorkspaceCodeTreeNode(BaseModel):
    name: str
    path: str
    kind: str
    meta: str
    size: int | None = None
    child_count: int = 0
    descendant_count: int = 0
    has_children: bool = False
    children: list["WorkspaceCodeTreeNode"] = Field(default_factory=list)


class WorkspaceTensorFlowNode(BaseModel):
    id: str
    label: str
    kind: str
    description: str
    source_path: str
    line_start: int
    line_end: int
    tensor_shape: str | list[int | None] | None
    shape_reason: str | None = None
    op: str = "unknown"
    symbol_id: str = ""
    component_symbol_id: str | None = None
    expandable: bool = False
    external: bool = False
    x: int
    y: int
    width: int
    height: int


class WorkspaceTensorFlowEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    kind: str = "tensor"
    points: list[list[int]]


class WorkspaceTensorFlowRead(BaseModel):
    project_id: str
    renderer: str
    view: str = "architecture"
    root_symbol: str | None = None
    root_label: str | None = None
    available_roots: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[WorkspaceTensorFlowNode]
    edges: list[WorkspaceTensorFlowEdge]
