"""Automatic background trace coordinator.

Starts Agent analysis (architecture, then trace) as soon as a project has a parsed
paper, a current code analysis, and a configured Agent provider — without any manual
button. It is deterministic and idempotent: candidate discovery and every semantic
verdict still belong to the Agent; this module only decides *when* to enqueue work.

Safe to call from any completion hook (paper parsed, code analysis ready, provider
enabled, workbench opened). ``create_analysis_job`` dedupes by fingerprint, so repeated
calls never create duplicate jobs, and failures here never break the triggering flow.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.db.session import engine
from app.models.entities import PaperDocument

logger = logging.getLogger(__name__)


def _provider_ready(session: Session) -> bool:
    from app.services.agent.service import _provider_from_settings

    provider, _reason = _provider_from_settings(session)
    return provider is not None


def _latest_paper(session: Session, project_id: int) -> PaperDocument | None:
    return session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()


def maybe_start_trace(project_id: int) -> list[str]:
    """Enqueue architecture + trace jobs when paper, code, and provider are all ready.

    Returns the list of job ids that were created or reused (empty when not yet ready).
    Never raises: any error is logged and swallowed so the caller's flow is unaffected.
    """

    from app.schemas.agent import AgentAnalysisJobCreate
    from app.services.agent.analysis_jobs import create_analysis_job
    from app.services.analysis_jobs import _latest_repository, analysis_is_current

    job_ids: list[str] = []
    try:
        with Session(engine) as session:
            paper = _latest_paper(session, project_id)
            if paper is None or paper.parse_status != "succeeded":
                return []
            repository = _latest_repository(session, project_id)
            if repository is None or not analysis_is_current(repository):
                return []
            if not _provider_ready(session):
                return []
            # Architecture first so the trace run can reference the current graph artifact.
            for kind in ("architecture", "trace"):
                job = create_analysis_job(session, project_id, AgentAnalysisJobCreate(kind=kind))
                job_ids.append(job.job_id)
    except Exception:  # pragma: no cover - best-effort background trigger
        logger.exception("auto trace coordinator failed for project %s", project_id)
        return []
    return job_ids
