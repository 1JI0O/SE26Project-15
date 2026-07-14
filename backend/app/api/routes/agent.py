from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.schemas.agent import (
    AgentConfirmationRead,
    AgentDecisionRequest,
    AgentQueryRequest,
    AgentQueryResponse,
)
from app.services.agent.service import (
    confirmation_to_read,
    decide_confirmation,
    query_agent,
    read_confirmation,
)

router = APIRouter(prefix="/projects/{project_id}/agent", tags=["agent"])


@router.post("/query", response_model=AgentQueryResponse)
def agent_query(
    project_id: int,
    payload: AgentQueryRequest,
    session: Session = Depends(get_session),
) -> AgentQueryResponse:
    get_project_or_404(project_id, session)
    return query_agent(session, project_id, payload)


@router.get("/confirmations/{confirmation_id}", response_model=AgentConfirmationRead)
def get_confirmation(
    project_id: int,
    confirmation_id: str,
    session: Session = Depends(get_session),
) -> AgentConfirmationRead:
    get_project_or_404(project_id, session)
    request = read_confirmation(session, project_id, confirmation_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    return confirmation_to_read(request)


@router.post(
    "/confirmations/{confirmation_id}/decision",
    response_model=AgentConfirmationRead,
)
def decide_agent_confirmation(
    project_id: int,
    confirmation_id: str,
    payload: AgentDecisionRequest,
    session: Session = Depends(get_session),
) -> AgentConfirmationRead:
    get_project_or_404(project_id, session)
    request = decide_confirmation(
        session, project_id, confirmation_id, payload.decision
    )
    if request is None:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    return confirmation_to_read(request)
