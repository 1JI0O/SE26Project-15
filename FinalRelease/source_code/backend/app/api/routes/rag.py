"""Retrieval index inspection and manual rebuild.

The indexes are maintained automatically by the paper-parse, code-analysis, and trace-review
hooks, so these endpoints exist for visibility and for the cases automation cannot cover:
switching embedder, recovering from a failed remote call, or seeding a project whose paper and
code were imported before this feature existed.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.routes.projects import get_project_or_404
from app.db.session import get_session
from app.schemas.rag import (
    RagIndexStatusRead,
    RagRebuildRequest,
    RagRebuildResult,
    RagScopeResult,
    RagSearchResult,
)
from app.services.rag import build_index, index_status, search
from app.services.rag.service import SCOPES

router = APIRouter(prefix="/projects/{project_id}/rag", tags=["rag"])


@router.get("/status", response_model=RagIndexStatusRead)
def read_rag_status(
    project_id: int,
    session: Session = Depends(get_session),
) -> RagIndexStatusRead:
    get_project_or_404(project_id, session)
    return RagIndexStatusRead.model_validate(index_status(session, project_id))


@router.post("/rebuild", response_model=RagRebuildResult)
def rebuild_rag_index(
    project_id: int,
    payload: RagRebuildRequest,
    session: Session = Depends(get_session),
) -> RagRebuildResult:
    """Rebuild one scope, or every scope when ``scope`` is omitted.

    Runs inline: a rebuild is bounded by the corpus size, and the caller asked for it, so a
    synchronous answer with real counts beats a fire-and-forget job it would have to poll.
    """

    get_project_or_404(project_id, session)
    scopes = (payload.scope,) if payload.scope else SCOPES
    results = [
        RagScopeResult.model_validate(
            build_index(session, project_id, scope, force=payload.force)
        )
        for scope in scopes
    ]
    return RagRebuildResult(results=results)


@router.get("/search", response_model=RagSearchResult)
def search_rag_index(
    project_id: int,
    query: str = Query(min_length=1, max_length=1000),
    scope: str = Query(default="paper"),
    limit: int = Query(default=5, ge=1, le=20),
    session: Session = Depends(get_session),
) -> RagSearchResult:
    get_project_or_404(project_id, session)
    if scope not in SCOPES:
        raise HTTPException(status_code=422, detail=f"scope must be one of {', '.join(SCOPES)}")
    return RagSearchResult.model_validate(
        search(session, project_id, scope, query, limit=limit)
    )
