import hashlib

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.api.routes.helpers import parse_workspace_project_id
from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.models.entities import (
    CodeRepository,
    CodeTarget,
    PaperDocument,
    PaperTarget,
    TraceLink,
    utc_now,
)
from app.schemas.traces import (
    TraceBatchStatusResult,
    TraceBatchStatusUpdate,
    TraceClearResult,
    TraceClearScope,
    TraceLinkCreate,
    TraceLinkRead,
    TraceStatus,
    TraceStatusUpdate,
    TraceSuggestionRequest,
    TraceSuggestionResponse,
    WorkspaceTraceRow,
)
from app.services import workspace_service
from app.services.local_sync import record_local_operation, trace_payload
from app.services.tracing.service import suggest_and_persist, trace_to_read
from app.services.workspace_placeholder import workspace_payload

router = APIRouter(prefix="/projects/{project_id}/trace-links", tags=["trace-links"])
workspace_router = APIRouter(prefix="/projects/{project_id}/workspace", tags=["tracing"])


def _invalidate_trace_index(session: Session, project_id: int) -> None:
    """Mark the trace-precedent index stale after a review verdict changes.

    Reviewed links are the corpus for ``recall_trace_cases``, so a new accept/reject changes
    it. Invalidating (rather than rebuilding inline) keeps the review request fast; the next
    search rebuilds. Advisory only — a failure here must not fail the review.
    """

    from app.services.rag import invalidate

    invalidate(session, project_id, "trace")


def _latest_paper(session: Session, project_id: int) -> PaperDocument | None:
    return session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()


def _latest_code(session: Session, project_id: int) -> CodeRepository | None:
    return session.exec(
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    ).first()


@router.get("", response_model=list[TraceLinkRead])
def list_trace_links(
    project_id: int,
    trace_status: TraceStatus | None = Query(default=None, alias="status"),
    source: str | None = Query(default=None, max_length=32),
    session: Session = Depends(get_session),
) -> list[TraceLinkRead]:
    get_project_or_404(project_id, session)
    statement = select(TraceLink).where(TraceLink.project_id == project_id)
    if trace_status is not None:
        statement = statement.where(TraceLink.status == trace_status.value)
    if source is not None:
        statement = statement.where(TraceLink.source == source)
    statement = statement.order_by(TraceLink.created_at.desc(), TraceLink.id.desc())
    return [trace_to_read(link) for link in session.exec(statement).all()]


@router.post("", response_model=TraceLinkRead, status_code=status.HTTP_201_CREATED)
def create_trace_link(
    project_id: int,
    payload: TraceLinkCreate,
    session: Session = Depends(get_session),
) -> TraceLinkRead:
    project = get_project_or_404(project_id, session)
    sides = {evidence.side for evidence in payload.evidence}
    if sides != {"paper", "code"}:
        raise HTTPException(status_code=422, detail="Manual traces require paper and code evidence")
    paper = _latest_paper(session, project_id)
    code = _latest_code(session, project_id)
    if paper is None or code is None:
        raise HTTPException(
            status_code=409,
            detail="Upload both paper and code before creating traces",
        )
    fingerprint = hashlib.sha256(
        f"manual\x00{paper.id}\x00{code.id}\x00{code.revision}\x00{payload.paper_ref}\x00"
        f"{payload.code_ref}\x00{payload.relation_type.value}".encode()
    ).hexdigest()
    existing = session.exec(select(TraceLink).where(TraceLink.fingerprint == fingerprint)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Trace relation already exists")
    link = TraceLink(
        project_id=project_id,
        paper_document_id=paper.id,
        paper_ref=payload.paper_ref,
        code_repository_id=code.id,
        code_revision=code.revision,
        code_ref=payload.code_ref,
        relation_type=payload.relation_type.value,
        confidence=payload.confidence,
        static_confidence=payload.confidence,
        source="manual",
        evidence_json=[item.model_dump() for item in payload.evidence],
        rationale=payload.rationale,
        uncertainty_json={"level": "medium", "reasons": ["manual_relation"]},
        fingerprint=fingerprint,
    )
    session.add(link)
    session.flush()
    record_local_operation(
        session,
        project,
        "trace_link",
        link.public_id,
        trace_payload(project, link),
        base_version=0,
    )
    session.commit()
    session.refresh(link)
    return trace_to_read(link)


@router.post("/suggest", response_model=TraceSuggestionResponse)
def suggest_links(
    project_id: int,
    payload: TraceSuggestionRequest = Body(default=TraceSuggestionRequest()),
    session: Session = Depends(get_session),
) -> TraceSuggestionResponse:
    get_project_or_404(project_id, session)
    paper = (
        session.get(PaperDocument, payload.paper_document_id)
        if payload.paper_document_id is not None
        else _latest_paper(session, project_id)
    )
    code = (
        session.get(CodeRepository, payload.code_repository_id)
        if payload.code_repository_id is not None
        else _latest_code(session, project_id)
    )
    invalid_artifacts = (
        paper is None
        or code is None
        or paper.project_id != project_id
        or code.project_id != project_id
    )
    if invalid_artifacts:
        raise HTTPException(
            status_code=409,
            detail="Upload both a paper and a code repository before requesting suggestions",
        )
    items, mode, degraded, reason = suggest_and_persist(
        session,
        project_id,
        paper,
        code,
        use_llm=payload.use_llm,
    )
    return TraceSuggestionResponse(
        mode=mode,
        degraded=degraded,
        degraded_reason=reason,
        items=items,
    )


@router.patch("/{trace_id}/status", response_model=TraceLinkRead)
def update_trace_status(
    project_id: int,
    trace_id: str,
    payload: TraceStatusUpdate,
    session: Session = Depends(get_session),
) -> TraceLinkRead:
    project = get_project_or_404(project_id, session)
    link = session.exec(
        select(TraceLink).where(
            TraceLink.project_id == project_id,
            TraceLink.trace_id == trace_id,
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Trace link not found")
    if payload.status == TraceStatus.PROPOSED:
        # Undo a human review decision: the link returns to the review queue. Stale links
        # stay stale — they belong to an outdated code revision, not to a decision.
        if link.status not in {TraceStatus.ACCEPTED.value, TraceStatus.REJECTED.value}:
            raise HTTPException(
                status_code=409, detail="Only accepted or rejected traces can be reverted"
            )
        link.decided_at = None
    elif payload.status in {TraceStatus.ACCEPTED, TraceStatus.REJECTED}:
        if link.status != TraceStatus.PROPOSED.value:
            raise HTTPException(status_code=409, detail="Only proposed traces can be reviewed")
        link.decided_at = utc_now()
    else:
        raise HTTPException(
            status_code=422,
            detail="Only accepted, rejected, or proposed (revert) are allowed",
        )
    link.status = payload.status.value
    link.updated_at = utc_now()
    link.version += 1
    session.add(link)
    record_local_operation(
        session,
        project,
        "trace_link",
        link.public_id,
        trace_payload(project, link),
        base_version=link.version - 1,
    )
    session.commit()
    session.refresh(link)
    _invalidate_trace_index(session, project_id)
    return trace_to_read(link)


@router.post("/batch-status", response_model=TraceBatchStatusResult)
def batch_update_trace_status(
    project_id: int,
    payload: TraceBatchStatusUpdate,
    session: Session = Depends(get_session),
) -> TraceBatchStatusResult:
    """Accept, reject, or revert many trace links at once.

    ``trace_ids`` selects a subset; omit it to apply to every eligible link in the project.
    ``accepted``/``rejected`` move only ``proposed`` links; ``proposed`` reverts only
    ``accepted``/``rejected`` links back to the review queue. Ineligible or stale links are
    skipped, so the operation is idempotent and safe to retry.
    """

    project = get_project_or_404(project_id, session)
    if payload.status == TraceStatus.PROPOSED:
        source_statuses = {TraceStatus.ACCEPTED.value, TraceStatus.REJECTED.value}
    elif payload.status in {TraceStatus.ACCEPTED, TraceStatus.REJECTED}:
        source_statuses = {TraceStatus.PROPOSED.value}
    else:
        raise HTTPException(
            status_code=422,
            detail="Only accepted, rejected, or proposed (revert) are allowed",
        )
    statement = select(TraceLink).where(
        TraceLink.project_id == project_id,
        TraceLink.status.in_(source_statuses),
    )
    requested_ids = [tid for tid in (payload.trace_ids or []) if tid]
    if requested_ids:
        statement = statement.where(TraceLink.trace_id.in_(requested_ids))
    links = session.exec(statement).all()
    now = utc_now()
    for link in links:
        link.status = payload.status.value
        link.decided_at = None if payload.status == TraceStatus.PROPOSED else now
        link.updated_at = now
        link.version += 1
        session.add(link)
        record_local_operation(
            session,
            project,
            "trace_link",
            link.public_id,
            trace_payload(project, link),
            base_version=link.version - 1,
        )
    session.commit()
    for link in links:
        session.refresh(link)
    if links:
        _invalidate_trace_index(session, project_id)
    skipped = len(requested_ids) - len(links) if requested_ids else 0
    return TraceBatchStatusResult(
        status=payload.status,
        updated_count=len(links),
        skipped_count=max(skipped, 0),
        updated=[trace_to_read(link) for link in links],
    )


def _prune_orphan_targets(session: Session, project_id: int) -> None:
    """Drop paper/code targets no longer referenced by any remaining link.

    Targets only exist to anchor relations, so once every link that pointed at one is gone the
    row is dead weight — and leaving it behind would let repeated regenerations grow the table
    without bound.
    """

    live_paper = {
        row
        for row in session.exec(
            select(TraceLink.paper_target_id).where(TraceLink.project_id == project_id)
        ).all()
        if row
    }
    live_code = {
        row
        for row in session.exec(
            select(TraceLink.code_target_id).where(TraceLink.project_id == project_id)
        ).all()
        if row
    }
    for target in session.exec(
        select(PaperTarget).where(PaperTarget.project_id == project_id)
    ).all():
        if target.target_id not in live_paper:
            session.delete(target)
    for target in session.exec(select(CodeTarget).where(CodeTarget.project_id == project_id)).all():
        if target.target_id not in live_code:
            session.delete(target)


@router.delete("", response_model=TraceClearResult)
def clear_trace_links(
    project_id: int,
    scope: TraceClearScope = Query(default=TraceClearScope.PROPOSED),
    session: Session = Depends(get_session),
) -> TraceClearResult:
    """Discard previously generated relations before a fresh trace run.

    The workbench asks the user whether to keep the previous round when they hit 重新生成;
    choosing "clear" calls this. Deletions are mirrored into the sync outbox so a cloud-enabled
    project does not resurrect the removed relations on its next sync.
    """

    project = get_project_or_404(project_id, session)
    links = session.exec(select(TraceLink).where(TraceLink.project_id == project_id)).all()
    if scope is TraceClearScope.ALL:
        doomed = list(links)
    elif scope is TraceClearScope.AGENT:
        doomed = [link for link in links if link.source != "manual"]
    else:
        doomed = [link for link in links if link.status == TraceStatus.PROPOSED.value]
    for link in doomed:
        record_local_operation(
            session,
            project,
            "trace_link",
            link.public_id,
            trace_payload(project, link),
            operation="delete",
            base_version=link.version,
        )
        session.delete(link)
    session.flush()
    _prune_orphan_targets(session, project_id)
    session.commit()
    reviewed_statuses = {TraceStatus.ACCEPTED.value, TraceStatus.REJECTED.value}
    if any(link.status in reviewed_statuses for link in doomed):
        _invalidate_trace_index(session, project_id)
    return TraceClearResult(
        scope=scope,
        deleted_count=len(doomed),
        kept_count=len(links) - len(doomed),
    )


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
