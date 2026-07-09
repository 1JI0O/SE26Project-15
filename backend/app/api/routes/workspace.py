from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from app.schemas import (
    WorkspaceAnalyzeJob,
    WorkspaceAnalyzeRequest,
    WorkspaceCodeFileRead,
    WorkspaceCodeFileSaveResult,
    WorkspaceCodeFileUpdate,
    WorkspaceCodeTreeNode,
    WorkspaceConflictItem,
    WorkspaceFlowNode,
    WorkspacePaperPage,
    WorkspaceRead,
    WorkspaceReportCard,
    WorkspaceTensorFlowRead,
    WorkspaceTraceRow,
)
from app.services.workspace_placeholder import (
    code_file_payload,
    tensor_flow_payload,
    workspace_payload,
)

router = APIRouter(prefix="/projects/{project_id}/workspace", tags=["workspace-prototype"])


@router.get("", response_model=WorkspaceRead)
def read_workspace(project_id: str) -> WorkspaceRead:
    return WorkspaceRead(**workspace_payload(project_id))


@router.get("/paper-pages", response_model=list[WorkspacePaperPage])
def read_paper_pages(project_id: str) -> list[WorkspacePaperPage]:
    payload = workspace_payload(project_id)
    return [WorkspacePaperPage(**item) for item in payload["paper_pages"]]


@router.get("/code-tree", response_model=list[WorkspaceCodeTreeNode])
def read_code_tree(project_id: str) -> list[WorkspaceCodeTreeNode]:
    payload = workspace_payload(project_id)
    return [WorkspaceCodeTreeNode(**item) for item in payload["code_tree"]]


@router.get("/code-files/{file_path:path}", response_model=WorkspaceCodeFileRead)
def read_code_file(project_id: str, file_path: str) -> WorkspaceCodeFileRead:
    payload = code_file_payload(project_id, file_path)
    if payload is None:
        raise HTTPException(status_code=404, detail="Code file not found in placeholder workspace")
    return WorkspaceCodeFileRead(**payload)


@router.put("/code-files/{file_path:path}", response_model=WorkspaceCodeFileSaveResult)
def save_code_file(
    project_id: str,
    file_path: str,
    payload: WorkspaceCodeFileUpdate,
) -> WorkspaceCodeFileSaveResult:
    if code_file_payload(project_id, file_path) is None:
        raise HTTPException(status_code=404, detail="Code file not found in placeholder workspace")
    return WorkspaceCodeFileSaveResult(
        project_id=project_id,
        path=file_path,
        status="accepted",
        message=f"Placeholder save accepted with {len(payload.content)} characters.",
    )


@router.get("/trace-matrix", response_model=list[WorkspaceTraceRow])
def read_trace_matrix(project_id: str) -> list[WorkspaceTraceRow]:
    payload = workspace_payload(project_id)
    return [WorkspaceTraceRow(**item) for item in payload["trace_rows"]]


@router.get("/flow-graph", response_model=list[WorkspaceFlowNode])
def read_flow_graph(project_id: str) -> list[WorkspaceFlowNode]:
    payload = workspace_payload(project_id)
    return [WorkspaceFlowNode(**item) for item in payload["flow_nodes"]]


@router.get("/tensor-flow", response_model=WorkspaceTensorFlowRead)
def read_tensor_flow(project_id: str) -> WorkspaceTensorFlowRead:
    return WorkspaceTensorFlowRead(**tensor_flow_payload(project_id))


@router.get("/conflicts", response_model=list[WorkspaceConflictItem])
def read_conflicts(project_id: str) -> list[WorkspaceConflictItem]:
    payload = workspace_payload(project_id)
    return [WorkspaceConflictItem(**item) for item in payload["conflict_items"]]


@router.get("/report-summary", response_model=list[WorkspaceReportCard])
def read_report_summary(project_id: str) -> list[WorkspaceReportCard]:
    payload = workspace_payload(project_id)
    return [WorkspaceReportCard(**item) for item in payload["report_cards"]]


@router.post(
    "/analyze",
    response_model=WorkspaceAnalyzeJob,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_workspace_analysis(
    project_id: str,
    payload: WorkspaceAnalyzeRequest,
) -> WorkspaceAnalyzeJob:
    return WorkspaceAnalyzeJob(
        project_id=project_id,
        job_id=f"placeholder-{uuid4().hex[:12]}",
        status="queued",
        message=f"Placeholder analysis accepted in {payload.mode!r} mode.",
    )
