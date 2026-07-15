from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.schemas.agent import (
    AgentConfirmationRead,
    AgentConversationCreate,
    AgentConversationDecisionResponse,
    AgentConversationDetail,
    AgentConversationRead,
    AgentConversationUpdate,
    AgentDecisionRequest,
    AgentMemoryCreate,
    AgentMemoryRead,
    AgentQueryRequest,
    AgentQueryResponse,
    AgentTurnRequest,
    AgentTurnResponse,
)
from app.services.agent.conversations import (
    create_conversation,
    decide_conversation_confirmation,
    get_conversation_detail,
    list_conversations,
    run_conversation_turn,
    update_conversation,
)
from app.services.agent.memory import (
    create_memory,
    delete_memory,
    list_memories,
    memory_to_read,
)
from app.services.agent.service import (
    confirmation_to_read,
    decide_confirmation,
    query_agent,
    read_confirmation,
)

router = APIRouter(prefix="/projects/{project_id}/agent", tags=["agent"])


@router.get("/conversations", response_model=list[AgentConversationRead])
def get_agent_conversations(
    project_id: int,
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> list[AgentConversationRead]:
    get_project_or_404(project_id, session)
    return list_conversations(session, project_id, include_archived=include_archived)


@router.post(
    "/conversations",
    response_model=AgentConversationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_conversation(
    project_id: int,
    payload: AgentConversationCreate,
    session: Session = Depends(get_session),
) -> AgentConversationRead:
    get_project_or_404(project_id, session)
    conversation = create_conversation(session, project_id, payload)
    detail = get_conversation_detail(session, project_id, conversation.conversation_id)
    if detail is None:
        raise HTTPException(status_code=500, detail="Conversation creation failed")
    return AgentConversationRead.model_validate(detail.model_dump())


@router.get(
    "/conversations/{conversation_id}",
    response_model=AgentConversationDetail,
)
def get_agent_conversation(
    project_id: int,
    conversation_id: str,
    session: Session = Depends(get_session),
) -> AgentConversationDetail:
    get_project_or_404(project_id, session)
    detail = get_conversation_detail(session, project_id, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.patch(
    "/conversations/{conversation_id}",
    response_model=AgentConversationRead,
)
def patch_agent_conversation(
    project_id: int,
    conversation_id: str,
    payload: AgentConversationUpdate,
    session: Session = Depends(get_session),
) -> AgentConversationRead:
    get_project_or_404(project_id, session)
    conversation = update_conversation(session, project_id, conversation_id, payload)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    detail = get_conversation_detail(session, project_id, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return AgentConversationRead.model_validate(detail.model_dump())


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AgentTurnResponse,
)
def send_agent_message(
    project_id: int,
    conversation_id: str,
    payload: AgentTurnRequest,
    session: Session = Depends(get_session),
) -> AgentTurnResponse:
    get_project_or_404(project_id, session)
    response = run_conversation_turn(session, project_id, conversation_id, payload)
    if response is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return response


@router.post(
    "/conversations/{conversation_id}/confirmations/{confirmation_id}/decision",
    response_model=AgentConversationDecisionResponse,
)
def decide_agent_conversation_confirmation(
    project_id: int,
    conversation_id: str,
    confirmation_id: str,
    payload: AgentDecisionRequest,
    session: Session = Depends(get_session),
) -> AgentConversationDecisionResponse:
    get_project_or_404(project_id, session)
    response = decide_conversation_confirmation(
        session,
        project_id,
        conversation_id,
        confirmation_id,
        payload.decision,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    return response


@router.get("/memories", response_model=list[AgentMemoryRead])
def get_agent_memories(
    project_id: int,
    session: Session = Depends(get_session),
) -> list[AgentMemoryRead]:
    get_project_or_404(project_id, session)
    return [memory_to_read(item) for item in list_memories(session, project_id)]


@router.post(
    "/memories",
    response_model=AgentMemoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_memory(
    project_id: int,
    payload: AgentMemoryCreate,
    session: Session = Depends(get_session),
) -> AgentMemoryRead:
    get_project_or_404(project_id, session)
    memory = create_memory(session, project_id, payload, source={"type": "manual"})
    return memory_to_read(memory)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_memory(
    project_id: int,
    memory_id: str,
    session: Session = Depends(get_session),
) -> Response:
    get_project_or_404(project_id, session)
    if not delete_memory(session, project_id, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    request = decide_confirmation(session, project_id, confirmation_id, payload.decision)
    if request is None:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    return confirmation_to_read(request)
