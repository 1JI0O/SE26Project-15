from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.models.entities import CodeRepository, PaperDocument, TraceLink
from app.schemas.traces import (
    TraceLinkCreate,
    TraceLinkRead,
    TraceLinkSuggestion,
    WorkspaceTraceRow,
)
from app.services import workspace_service
from app.services.trace_suggester import suggest_trace_links
from app.services.workspace_placeholder import workspace_payload

router = APIRouter(prefix="/projects/{project_id}/trace-links", tags=["trace-links"])
workspace_router = APIRouter(prefix="/projects/{project_id}/workspace", tags=["tracing"])


@router.get("", response_model=list[TraceLinkRead])
def list_trace_links(project_id: int, session: Session = Depends(get_session)) -> list[TraceLink]:
    get_project_or_404(project_id, session)
    statement = select(TraceLink).where(TraceLink.project_id == project_id).order_by(TraceLink.id)
    return list(session.exec(statement).all())


@router.post("", response_model=TraceLinkRead, status_code=status.HTTP_201_CREATED)
def create_trace_link(
    project_id: int,
    payload: TraceLinkCreate,
    session: Session = Depends(get_session),
) -> TraceLink:
    get_project_or_404(project_id, session)
    link = TraceLink(project_id=project_id, **payload.model_dump())
    session.add(link)
    session.commit()
    session.refresh(link)
    return link


@router.post("/suggest", response_model=list[TraceLinkSuggestion])
def suggest_links(
    project_id: int,
    session: Session = Depends(get_session),
) -> list[TraceLinkSuggestion]:
    get_project_or_404(project_id, session)
    paper = session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()
    code = session.exec(
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    ).first()
    if paper is None or code is None:
        raise HTTPException(
            status_code=409,
            detail="Upload both a paper PDF and a code ZIP before requesting suggestions",
        )

    suggestions = suggest_trace_links(
        sections=paper.sections_json,
        paragraphs=paper.paragraphs_json,
        symbols=code.symbols_json,
        pytorch_candidates=code.pytorch_candidates_json,
    )
    return [TraceLinkSuggestion(**item) for item in suggestions]


@workspace_router.get("/trace-matrix", response_model=list[WorkspaceTraceRow])
def read_trace_matrix(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[WorkspaceTraceRow]:
    numeric_id = parse_workspace_project_id(project_id)
    if numeric_id is None:
        payload = workspace_payload(project_id)
        return [WorkspaceTraceRow(**item) for item in payload["trace_rows"]]

    get_project_or_404(numeric_id, session)
    rows = workspace_service.get_trace_rows(session, numeric_id)
    return [WorkspaceTraceRow(**item) for item in rows]
