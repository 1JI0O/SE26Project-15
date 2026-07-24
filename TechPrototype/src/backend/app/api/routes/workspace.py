from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.schemas.workspace import (
    WorkspaceAnalyzeJob,
    WorkspaceAnalyzeRequest,
    WorkspaceConflictItem,
    WorkspaceFlowNode,
    WorkspaceRead,
    WorkspaceReportCard,
)
from app.services import workspace_service
from app.services.workspace_placeholder import workspace_payload

router = APIRouter(prefix="/projects/{project_id}/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceRead)
def read_workspace(project_id: str, session: Session = Depends(get_session)) -> WorkspaceRead:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        return WorkspaceRead(**workspace_payload(project_id))

    get_project_or_404(numeric_id, session)
    return WorkspaceRead(**workspace_service.build_workspace_payload(session, numeric_id))


@router.get("/flow-graph", response_model=list[WorkspaceFlowNode])
def read_flow_graph(project_id: str) -> list[WorkspaceFlowNode]:
    payload = workspace_payload(project_id)
    return [WorkspaceFlowNode(**item) for item in payload["flow_nodes"]]


@router.get("/conflicts", response_model=list[WorkspaceConflictItem])
def read_conflicts(project_id: str) -> list[WorkspaceConflictItem]:
    payload = workspace_payload(project_id)
    return [WorkspaceConflictItem(**item) for item in payload["conflict_items"]]


@router.get("/report-summary", response_model=list[WorkspaceReportCard])
def read_report_summary(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspaceReportCard]:
    numeric_id = parse_workspace_project_id(project_id)
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
