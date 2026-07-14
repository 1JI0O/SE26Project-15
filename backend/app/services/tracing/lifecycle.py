from __future__ import annotations

from typing import Literal

from sqlmodel import Session, select

from app.models.entities import CodeRepository, TraceLink, utc_now


def _stale_links(links: list[TraceLink], reason: str) -> int:
    changed = 0
    for link in links:
        if link.status not in {"proposed", "accepted"}:
            continue
        link.status = "stale"
        link.stale_reason = reason
        link.updated_at = utc_now()
        changed += 1
    return changed


def mark_noncurrent_traces_stale(
    session: Session,
    project_id: int,
    paper_document_id: int,
    code_repository_id: int,
    code_revision: int,
) -> int:
    links = list(session.exec(select(TraceLink).where(TraceLink.project_id == project_id)).all())
    changed = 0
    for link in links:
        if link.status not in {"proposed", "accepted"}:
            continue
        if link.paper_document_id != paper_document_id:
            changed += _stale_links([link], "paper_version_changed")
        elif link.code_repository_id != code_repository_id or link.code_revision != code_revision:
            changed += _stale_links([link], "code_revision_changed")
    return changed


def record_artifact_revision_change(
    session: Session,
    project_id: int,
    artifact: Literal["paper", "code"],
    artifact_id: int,
    reason: str,
) -> int:
    if artifact == "code":
        repository = session.get(CodeRepository, artifact_id)
        if repository is None or repository.project_id != project_id:
            raise ValueError("Code repository not found in project")
        repository.revision += 1
        repository.updated_at = utc_now()
        statement = select(TraceLink).where(
            TraceLink.project_id == project_id,
            TraceLink.code_repository_id == artifact_id,
            TraceLink.code_revision < repository.revision,
        )
    else:
        statement = select(TraceLink).where(
            TraceLink.project_id == project_id,
            TraceLink.paper_document_id != artifact_id,
        )
    links = list(session.exec(statement).all())
    return _stale_links(links, reason)
