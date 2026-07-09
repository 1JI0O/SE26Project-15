from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
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
from app.services import workspace_service
from app.services.code_analyzer import is_editor_readable_file
from app.services.workspace_placeholder import (
    code_file_payload,
    tensor_flow_payload,
    workspace_payload,
)

router = APIRouter(prefix="/projects/{project_id}/workspace", tags=["workspace"])


def _parse_project_id(project_id: str) -> int | None:
    if project_id == "prototype":
        return None
    try:
        return int(project_id)
    except ValueError:
        return None


def _placeholder_workspace(project_id: str) -> WorkspaceRead:
    return WorkspaceRead(**workspace_payload(project_id))


@router.get("", response_model=WorkspaceRead)
def read_workspace(project_id: str, session: Session = Depends(get_session)) -> WorkspaceRead:
    numeric_id = _parse_project_id(project_id)
    if numeric_id is None:
        return _placeholder_workspace(project_id)

    get_project_or_404(numeric_id, session)
    payload = workspace_service.build_workspace_payload(session, numeric_id)
    return WorkspaceRead(**payload)


@router.get("/paper-pages", response_model=list[WorkspacePaperPage])
def read_paper_pages(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspacePaperPage]:
    numeric_id = _parse_project_id(project_id)
    if numeric_id is None:
        payload = workspace_payload(project_id)
        return [WorkspacePaperPage(**item) for item in payload["paper_pages"]]

    get_project_or_404(numeric_id, session)
    pages = workspace_service.get_paper_pages(session, numeric_id)
    if not pages:
        raise HTTPException(status_code=404, detail="Paper has not been uploaded or parsed")
    return [WorkspacePaperPage(**item) for item in pages]


@router.get("/code-tree", response_model=list[WorkspaceCodeTreeNode])
def read_code_tree(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspaceCodeTreeNode]:
    numeric_id = _parse_project_id(project_id)
    if numeric_id is None:
        payload = workspace_payload(project_id)
        return [WorkspaceCodeTreeNode(**item) for item in payload["code_tree"]]

    get_project_or_404(numeric_id, session)
    tree = workspace_service.get_code_tree(session, numeric_id)
    if not tree:
        raise HTTPException(status_code=404, detail="Code archive has not been uploaded")
    return [WorkspaceCodeTreeNode(**item) for item in tree]


@router.get("/code-files/{file_path:path}", response_model=WorkspaceCodeFileRead)
def read_code_file(
    project_id: str,
    file_path: str,
    session: Session = Depends(get_session),
) -> WorkspaceCodeFileRead:
    numeric_id = _parse_project_id(project_id)
    if numeric_id is None:
        payload = code_file_payload(project_id, file_path)
        if payload is None:
            raise HTTPException(status_code=404, detail="Code file not found in placeholder workspace")
        return WorkspaceCodeFileRead(**payload)

    get_project_or_404(numeric_id, session)
    if not is_editor_readable_file(file_path):
        raise HTTPException(
            status_code=415,
            detail="该文件类型不支持在编辑器中打开，请选择代码或文本文件。",
        )
    payload = workspace_service.get_code_file(session, numeric_id, file_path)
    if payload is None:
        raise HTTPException(status_code=404, detail="Code file not found")
    return WorkspaceCodeFileRead(**payload)


@router.put("/code-files/{file_path:path}", response_model=WorkspaceCodeFileSaveResult)
def save_code_file(
    project_id: str,
    file_path: str,
    payload: WorkspaceCodeFileUpdate,
    session: Session = Depends(get_session),
) -> WorkspaceCodeFileSaveResult:
    numeric_id = _parse_project_id(project_id)
    if numeric_id is None:
        if code_file_payload(project_id, file_path) is None:
            raise HTTPException(status_code=404, detail="Code file not found in placeholder workspace")
        return WorkspaceCodeFileSaveResult(
            project_id=project_id,
            path=file_path,
            status="accepted",
            message=f"Placeholder save accepted with {len(payload.content)} characters.",
        )

    get_project_or_404(numeric_id, session)
    if not is_editor_readable_file(file_path):
        raise HTTPException(
            status_code=415,
            detail="该文件类型不支持在编辑器中打开，请选择代码或文本文件。",
        )
    try:
        result = workspace_service.save_code_file(session, numeric_id, file_path, payload.content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WorkspaceCodeFileSaveResult(**result)


@router.get("/trace-matrix", response_model=list[WorkspaceTraceRow])
def read_trace_matrix(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspaceTraceRow]:
    numeric_id = _parse_project_id(project_id)
    if numeric_id is None:
        payload = workspace_payload(project_id)
        return [WorkspaceTraceRow(**item) for item in payload["trace_rows"]]

    get_project_or_404(numeric_id, session)
    rows = workspace_service.get_trace_rows(session, numeric_id)
    return [WorkspaceTraceRow(**item) for item in rows]


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
def read_report_summary(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspaceReportCard]:
    numeric_id = _parse_project_id(project_id)
    if numeric_id is None:
        payload = workspace_payload(project_id)
        return [WorkspaceReportCard(**item) for item in payload["report_cards"]]

    get_project_or_404(numeric_id, session)
    workspace = workspace_service.build_workspace_payload(session, numeric_id)
    return [WorkspaceReportCard(**item) for item in workspace["report_cards"]]


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
        job_id=f"workspace-{uuid4().hex[:12]}",
        status="queued",
        message=f"Analysis accepted in {payload.mode!r} mode.",
    )
