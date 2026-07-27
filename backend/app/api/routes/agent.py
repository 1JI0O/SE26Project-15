import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    AgentConversation,
    AgentRun,
    AgentRunEvent,
    CodeRepository,
    Project,
    RepositoryAnalysisJob,
    as_utc,
    utc_now,
)
from app.schemas.agent import (
    AgentAnalysisArtifactRead,
    AgentAnalysisDiagnosticsRead,
    AgentAnalysisJobCreate,
    AgentAnalysisJobRead,
    AgentQueueItemRead,
    AgentQueueRead,
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
queue_router = APIRouter(prefix="/agent", tags=["agent"])

_ACTIVE_JOB_STATUSES = {"queued", "running", "validating", "cancelling"}
_STALE_AFTER_SECONDS = 15 * 60


def _is_stale(updated_at) -> bool:
    return (utc_now() - as_utc(updated_at)).total_seconds() > _STALE_AFTER_SECONDS

def _queue_time(value):
    return as_utc(value) if value is not None else None


def _project_names(session: Session) -> dict[int, str]:
    return {
        project.id or 0: project.name
        for project in session.exec(select(Project).where(Project.deleted_at.is_(None))).all()
    }


def _latest_terminal_event(session: Session, run_id: str) -> str | None:
    event = session.exec(
        select(AgentRunEvent)
        .where(
            AgentRunEvent.run_id == run_id,
            AgentRunEvent.event_type.in_(
                ["analysis.completed", "analysis.failed", "run.completed", "run.failed"]
            ),
        )
        .order_by(AgentRunEvent.sequence.desc())
    ).first()
    return event.event_type if event is not None else None


def _latest_analysis_artifact(session: Session, job_id: str) -> AgentAnalysisArtifact | None:
    return session.exec(
        select(AgentAnalysisArtifact)
        .where(AgentAnalysisArtifact.job_id == job_id)
        .order_by(AgentAnalysisArtifact.created_at.desc())
    ).first()


def _complete_analysis_job(
    session: Session,
    job: AgentAnalysisJob,
    run: AgentRun | None,
    artifact: AgentAnalysisArtifact | None,
    message: str = "Agent 分析完成",
) -> None:
    now = utc_now()
    job.status = "succeeded"
    job.error_code = None
    job.progress_json = {"message": message}
    if artifact is not None:
        job.artifact_id = artifact.artifact_id
    if run is not None:
        run.status = "completed"
        run.updated_at = now
        run.completed_at = run.completed_at or now
        session.add(run)
    job.updated_at = now
    job.completed_at = job.completed_at or now
    session.add(job)


def _fail_analysis_job(
    session: Session,
    job: AgentAnalysisJob,
    run: AgentRun | None,
    code: str,
    message: str = "Agent 分析失败",
) -> None:
    now = utc_now()
    job.status = "failed"
    job.error_code = job.error_code or code[:128]
    job.progress_json = {"message": message, "code": job.error_code}
    if run is not None:
        run.status = "failed"
        run.degraded_reason = run.degraded_reason or job.error_code
        run.updated_at = now
        run.completed_at = run.completed_at or now
        session.add(run)
    job.updated_at = now
    job.completed_at = job.completed_at or now
    session.add(job)


def _reconcile_analysis_job(session: Session, job: AgentAnalysisJob) -> None:
    if job.status not in _ACTIVE_JOB_STATUSES:
        return
    run = session.get(AgentRun, job.agent_run_id) if job.agent_run_id else None
    terminal_event = _latest_terminal_event(session, job.agent_run_id) if job.agent_run_id else None
    artifact = _latest_analysis_artifact(session, job.job_id)
    if run is not None and run.status in {"completed", "failed"}:
        terminal_event = terminal_event or (
            "run.completed" if run.status == "completed" else "run.failed"
        )
    if terminal_event in {"analysis.completed", "run.completed"}:
        _complete_analysis_job(session, job, run, artifact)
        return
    if terminal_event in {"analysis.failed", "run.failed"}:
        _fail_analysis_job(session, job, run, "run_finished_failed")
        return
    if not _is_stale(job.updated_at):
        return
    if artifact is not None:
        _complete_analysis_job(
            session,
            job,
            run,
            artifact,
            "Agent 分析超时未更新，已保留已发布结果",
        )
        return
    _fail_analysis_job(
        session,
        job,
        run,
        "analysis_stale_timeout",
        "Agent 分析超时未更新，已自动结束",
    )


@queue_router.get("/queue", response_model=AgentQueueRead)
def list_agent_queue(session: Session = Depends(get_session)) -> AgentQueueRead:
    projects = _project_names(session)
    items: list[AgentQueueItemRead] = []

    active_jobs = list(
        session.exec(
            select(AgentAnalysisJob)
            .where(AgentAnalysisJob.status.in_(_ACTIVE_JOB_STATUSES))
            .order_by(AgentAnalysisJob.updated_at.desc())
        ).all()
    )
    for job in active_jobs:
        _reconcile_analysis_job(session, job)
    session.commit()
    analysis_jobs = [job for job in active_jobs if job.status in _ACTIVE_JOB_STATUSES]
    linked_run_ids = {job.agent_run_id for job in analysis_jobs if job.agent_run_id}
    for job in analysis_jobs:
        progress = dict(job.progress_json or {})
        summary = str(progress.get("message") or job.error_code or "等待 Agent 分析")
        items.append(
            AgentQueueItemRead(
                id=job.job_id,
                project_id=job.project_id,
                project_name=projects.get(job.project_id, f"项目 {job.project_id}"),
                category="agent_analysis",
                kind=job.kind,
                status=job.status,
                summary=summary,
                run_id=job.agent_run_id,
                job_id=job.job_id,
                created_at=_queue_time(job.created_at),
                updated_at=_queue_time(job.updated_at),
                completed_at=_queue_time(job.completed_at),
                stale=_is_stale(job.updated_at),
            )
        )

    runs = list(
        session.exec(
            select(AgentRun)
            .where(AgentRun.status.in_(["queued", "running", "cancelling"]))
            .order_by(AgentRun.updated_at.desc())
        ).all()
    )
    conversation_ids = {run.conversation_id for run in runs}
    conversations = {
        conv.conversation_id: conv
        for conv in session.exec(
            select(AgentConversation).where(AgentConversation.conversation_id.in_(conversation_ids))
        ).all()
    } if conversation_ids else {}
    for run in runs:
        if run.run_id in linked_run_ids:
            continue
        conv = conversations.get(run.conversation_id)
        stale = _is_stale(run.updated_at)
        items.append(
            AgentQueueItemRead(
                id=run.run_id,
                project_id=run.project_id,
                project_name=projects.get(run.project_id, f"项目 {run.project_id}"),
                category="agent_run" if conv is not None else "orphan_run",
                kind=conv.kind if conv is not None else "unknown",
                status=run.status,
                summary=conv.title if conv is not None else "孤立 Agent 运行记录",
                model_name=run.model_name or None,
                run_id=run.run_id,
                created_at=_queue_time(run.created_at),
                updated_at=_queue_time(run.updated_at),
                completed_at=_queue_time(run.completed_at),
                stale=stale,
            )
        )

    repository_jobs = list(
        session.exec(
            select(RepositoryAnalysisJob)
            .where(RepositoryAnalysisJob.status.in_(["queued", "running"]))
            .order_by(RepositoryAnalysisJob.created_at.desc())
        ).all()
    )
    repository_ids = {job.repository_id for job in repository_jobs}
    repositories = {
        repo.id or 0: repo
        for repo in session.exec(
            select(CodeRepository).where(CodeRepository.id.in_(repository_ids))
        ).all()
    } if repository_ids else {}
    for job in repository_jobs:
        repo = repositories.get(job.repository_id)
        updated_at = job.started_at or job.created_at
        items.append(
            AgentQueueItemRead(
                id=job.job_id,
                project_id=job.project_id,
                project_name=projects.get(job.project_id, f"项目 {job.project_id}"),
                category="repository_analysis",
                kind="code",
                status=job.status,
                summary=job.error_summary or (repo.filename if repo is not None else "代码仓库分析"),
                job_id=job.job_id,
                created_at=_queue_time(job.created_at),
                updated_at=_queue_time(updated_at),
                completed_at=_queue_time(job.completed_at),
                stale=_is_stale(updated_at),
            )
        )

    items.sort(key=lambda item: item.updated_at, reverse=True)
    return AgentQueueRead(
        items=items,
        active_count=len(items),
        stale_count=sum(1 for item in items if item.stale),
        capacity=2,
    )


def _finish_run(session: Session, run: AgentRun, reason: str) -> None:
    now = utc_now()
    run.status = "failed"
    run.degraded_reason = reason
    run.updated_at = now
    run.completed_at = now
    session.add(run)


def _finish_analysis_job(session: Session, job: AgentAnalysisJob, reason: str) -> None:
    now = utc_now()
    if job.agent_run_id:
        run = session.get(AgentRun, job.agent_run_id)
        if run is not None and run.status in {"queued", "running", "cancelling"}:
            _finish_run(session, run, reason)
    job.status = "failed"
    job.error_code = reason
    job.progress_json = {"message": "任务已从队列移除", "code": reason}
    job.updated_at = now
    job.completed_at = now
    session.add(job)


def _finish_repository_job(session: Session, job: RepositoryAnalysisJob, reason: str) -> None:
    now = utc_now()
    job.status = "failed"
    job.error_summary = reason
    job.completed_at = now
    repository = session.get(CodeRepository, job.repository_id)
    if repository is not None and repository.analysis_status in {"queued", "running"}:
        repository.analysis_status = "failed"
        repository.analysis_error = reason
        repository.updated_at = now
        session.add(repository)
    session.add(job)


@queue_router.post("/queue/{category}/{item_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
def stop_agent_queue_item(
    category: str,
    item_id: str,
    session: Session = Depends(get_session),
) -> Response:
    if category == "agent_analysis":
        job = session.get(AgentAnalysisJob, item_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Queue item not found")
        cancel_analysis_job(session, job.project_id, job.job_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if category in {"agent_run", "orphan_run"}:
        run = session.get(AgentRun, item_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Queue item not found")
        _finish_run(session, run, "queue_stop_requested")
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if category == "repository_analysis":
        job = session.get(RepositoryAnalysisJob, item_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Queue item not found")
        _finish_repository_job(session, job, "queue_stop_requested")
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    raise HTTPException(status_code=404, detail="Queue item not found")


@queue_router.delete("/queue/{category}/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_queue_item(
    category: str,
    item_id: str,
    session: Session = Depends(get_session),
) -> Response:
    if category == "agent_analysis":
        job = session.get(AgentAnalysisJob, item_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Queue item not found")
        _finish_analysis_job(session, job, "queue_delete_requested")
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if category in {"agent_run", "orphan_run"}:
        run = session.get(AgentRun, item_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Queue item not found")
        _finish_run(session, run, "queue_delete_requested")
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if category == "repository_analysis":
        job = session.get(RepositoryAnalysisJob, item_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Queue item not found")
        _finish_repository_job(session, job, "queue_delete_requested")
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    raise HTTPException(status_code=404, detail="Queue item not found")


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
    "/analysis-jobs/{job_id}/diagnostics",
    response_model=AgentAnalysisDiagnosticsRead,
)
def get_analysis_diagnostics(
    project_id: int,
    job_id: str,
    event_limit: int = Query(default=200, ge=1, le=2000),
    step_limit: int = Query(default=60, ge=1, le=500),
    session: Session = Depends(get_session),
) -> AgentAnalysisDiagnosticsRead:
    """Everything known about one analysis run, for the workbench debug panel.

    ``error_code`` alone hides the real cause (a provider 400, a rejected quote, a SQLite lock all
    look alike from the outside), so this returns the run's degraded reason, its recorded events and
    the tail of its model/tool step trace. Read-only; safe to poll after a failure.
    """

    get_project_or_404(project_id, session)
    job = session.get(AgentAnalysisJob, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    run = session.get(AgentRun, job.agent_run_id) if job.agent_run_id else None
    events = (
        list_run_events(session, project_id, job.agent_run_id)[-event_limit:]
        if job.agent_run_id
        else []
    )
    steps = list(run.trace_json or [])[-step_limit:] if run is not None else []
    published = 0
    if job.artifact_id:
        artifact = session.get(AgentAnalysisArtifact, job.artifact_id)
        if artifact is not None:
            published = len(artifact.payload_json.get("candidates", []) or [])
    return AgentAnalysisDiagnosticsRead(
        job_id=job.job_id,
        project_id=job.project_id,
        kind=job.kind,
        status=job.status,
        error_code=job.error_code,
        progress=job.progress_json or {},
        run_id=job.agent_run_id,
        run_status=run.status if run is not None else None,
        degraded_reason=run.degraded_reason if run is not None else None,
        provider_name=run.provider_name if run is not None else None,
        model_name=run.model_name if run is not None else None,
        step_count=run.step_count if run is not None else 0,
        published_link_count=published,
        events=events,
        steps=steps,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


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
