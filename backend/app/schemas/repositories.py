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
    pytorch_candidates: list[dict[str, Any]]
    created_at: datetime


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


class WorkspaceCodeTreeNode(BaseModel):
    name: str
    path: str
    kind: str
    meta: str
    children: list["WorkspaceCodeTreeNode"] = Field(default_factory=list)


class WorkspaceTensorFlowNode(BaseModel):
    id: str
    label: str
    kind: str
    description: str
    source_path: str
    line_start: int
    line_end: int
    tensor_shape: str
    x: int
    y: int
    width: int
    height: int


class WorkspaceTensorFlowEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    points: list[list[int]]


class WorkspaceTensorFlowRead(BaseModel):
    project_id: str
    renderer: str
    nodes: list[WorkspaceTensorFlowNode]
    edges: list[WorkspaceTensorFlowEdge]
