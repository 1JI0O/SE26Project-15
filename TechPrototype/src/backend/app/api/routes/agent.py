import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.models.entities import AgentAnalysisArtifact, AgentAnalysisJob, AgentRun
from app.schemas.agent import (
    AgentAnalysisArtifactRead,
    AgentAnalysisJobCreate,
    AgentAnalysisJobRead,
    AgentCapabilityRead,
    AgentCapabilityUpdate,
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
    AgentRunEventRead,
    AgentRunSubmission,
    AgentTurnRequest,
    AgentTurnResponse,
)
from app.services.agent.analysis_jobs import (
    cancel_analysis_job,
    create_analysis_job,
    job_to_read,
)
from app.services.agent.capabilities import list_capabilities, update_capability
from app.services.agent.conversations import (
    create_conversation,
    decide_conversation_confirmation,
    get_conversation_detail,
    list_conversations,
    run_conversation_turn,
    submit_conversation_turn,
    update_conversation,
)
from app.services.agent.memory import (
    create_memory,
    delete_memory,
    list_memories,
    memory_to_read,
)
from app.services.agent.run_events import list_run_events
from app.services.agent.service import (
    confirmation_to_read,
    decide_confirmation,
    query_agent,
    read_confirmation,
)

router = APIRouter(prefix="/projects/{project_id}/agent", tags=["agent"])


@router.post(
    "/analysis-jobs",
    response_model=AgentAnalysisJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_analysis_job(
    project_id: int,
    payload: AgentAnalysisJobCreate,
    session: Session = Depends(get_session),
) -> AgentAnalysisJobRead:
    get_project_or_404(project_id, session)
    try:
        return job_to_read(create_analysis_job(session, project_id, payload))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/analysis-jobs/{job_id}", response_model=AgentAnalysisJobRead)
def get_analysis_job(
    project_id: int,
    job_id: str,
    session: Session = Depends(get_session),
) -> AgentAnalysisJobRead:
    get_project_or_404(project_id, session)
    job = session.get(AgentAnalysisJob, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return job_to_read(job)


@router.post(
    "/analysis-jobs/{job_id}/retry",
    response_model=AgentAnalysisJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_analysis_job(
    project_id: int,
    job_id: str,
    session: Session = Depends(get_session),
) -> AgentAnalysisJobRead:
    get_project_or_404(project_id, session)
    job = session.get(AgentAnalysisJob, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    payload = AgentAnalysisJobCreate(
        kind=job.kind,
        paper_document_id=job.paper_document_id,
        code_repository_id=job.code_repository_id,
        root_symbol=job.root_symbol,
        depth=job.requested_depth,
        force=True,
    )
    return job_to_read(create_analysis_job(session, project_id, payload))


@router.post(
    "/analysis-jobs/{job_id}/cancel",
    response_model=AgentAnalysisJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_analysis_job_endpoint(
    project_id: int,
    job_id: str,
    session: Session = Depends(get_session),
) -> AgentAnalysisJobRead:
    get_project_or_404(project_id, session)
    job = cancel_analysis_job(session, project_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return job_to_read(job)


@router.get(
    "/analysis-jobs/{job_id}/artifact",
    response_model=AgentAnalysisArtifactRead,
)
def get_analysis_artifact(
    project_id: int,
    job_id: str,
    session: Session = Depends(get_session),
) -> AgentAnalysisArtifactRead:
    get_project_or_404(project_id, session)
    artifact = session.exec(
        select(AgentAnalysisArtifact).where(
            AgentAnalysisArtifact.project_id == project_id,
            AgentAnalysisArtifact.job_id == job_id,
        )
    ).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Analysis artifact not found")
    return AgentAnalysisArtifactRead(
        artifact_id=artifact.artifact_id,
        job_id=artifact.job_id,
        project_id=artifact.project_id,
        kind=artifact.kind,
        schema_version=artifact.schema_version,
        payload=artifact.payload_json,
        paper_document_id=artifact.paper_document_id,
        code_repository_id=artifact.code_repository_id,
        code_revision=artifact.code_revision,
        run_id=artifact.agent_run_id,
        model=artifact.model_info_json,
        is_current=artifact.is_current,
        created_at=artifact.created_at,
    )


@router.get("/analysis-jobs/{job_id}/events")
async def stream_analysis_job_events(
    project_id: int,
    job_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    get_project_or_404(project_id, session)
    job = session.get(AgentAnalysisJob, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Analysis job not found")

    async def events():
        cursor = after
        last_progress = ""
        while True:
            if await request.is_disconnected():
                break
            session.expire_all()
            current = session.get(AgentAnalysisJob, job_id)
            if current is None:
                break
            progress = dict(current.progress_json or {})
            message = str(progress.get("message") or "")
            # Jobs stay in `queued` with no agent_run_id until a worker slot opens.
            # Without this synthetic event the UI freezes on "等待 Agent 分析".
            if not current.agent_run_id:
                if current.status == "queued" and not message:
                    message = "排队等待 Agent 分析"
                if message and message != last_progress:
                    last_progress = message
                    payload = {
                        "event_type": "analysis.progress",
                        "sequence": cursor,
                        "payload": {
                            "message": message,
                            "activity": message,
                            "status": current.status,
                        },
                    }
                    data = json.dumps(payload, ensure_ascii=False)
                    yield f"event: analysis.progress\ndata: {data}\n\n"
                elif not message:
                    yield ": keep-alive\n\n"
                if current.status in {"succeeded", "failed", "stale"}:
                    break
                await asyncio.sleep(0.5)
                continue

            batch = list_run_events(session, project_id, current.agent_run_id, after=cursor)
            for item in batch:
                cursor = item.sequence
                data = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                yield f"id: {cursor}\nevent: {item.event_type}\ndata: {data}\n\n"
            if message and message != last_progress:
                last_progress = message
                payload = {
                    "event_type": "analysis.progress",
                    "sequence": cursor,
                    "payload": {
                        "message": message,
                        "activity": message,
                        "status": current.status,
                    },
                }
                data = json.dumps(payload, ensure_ascii=False)
                yield f"event: analysis.progress\ndata: {data}\n\n"
            if current.status in {"succeeded", "failed", "stale"} and not batch:
                break
            if not batch:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/capabilities", response_model=list[AgentCapabilityRead])
def get_agent_capabilities(
    project_id: int,
    session: Session = Depends(get_session),
) -> list[AgentCapabilityRead]:
    get_project_or_404(project_id, session)
    return list_capabilities(session)


@router.patch("/capabilities/{capability_id:path}", response_model=AgentCapabilityRead)
def patch_agent_capability(
    project_id: int,
    capability_id: str,
    payload: AgentCapabilityUpdate,
    session: Session = Depends(get_session),
) -> AgentCapabilityRead:
    get_project_or_404(project_id, session)
    capability = update_capability(session, capability_id, payload)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return capability


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
    "/conversations/{conversation_id}/runs",
    response_model=AgentRunSubmission,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_agent_run(
    project_id: int,
    conversation_id: str,
    payload: AgentTurnRequest,
    session: Session = Depends(get_session),
) -> AgentRunSubmission:
    get_project_or_404(project_id, session)
    submission = submit_conversation_turn(session, project_id, conversation_id, payload)
    if submission is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return submission


@router.get("/runs/{run_id}/event-list", response_model=list[AgentRunEventRead])
def get_agent_run_events(
    project_id: int,
    run_id: str,
    after: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[AgentRunEventRead]:
    get_project_or_404(project_id, session)
    return list_run_events(session, project_id, run_id, after=after)


@router.get("/runs/{run_id}/events")
async def stream_agent_run_events(
    project_id: int,
    run_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    get_project_or_404(project_id, session)
    run = session.get(AgentRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Run not found")

    async def events():
        cursor = after
        idle_ticks = 0
        while idle_ticks < 1200:
            if await request.is_disconnected():
                break
            session.expire_all()
            batch = list_run_events(session, project_id, run_id, after=cursor)
            if batch:
                idle_ticks = 0
                for item in batch:
                    cursor = item.sequence
                    data = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {cursor}\nevent: {item.event_type}\ndata: {data}\n\n"
            else:
                idle_ticks += 1
            current = session.get(AgentRun, run_id)
            if current is None or (
                current.status in {"completed", "failed", "waiting_confirmation"} and not batch
            ):
                break
            if idle_ticks and idle_ticks % 40 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
