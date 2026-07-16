import json
import os
import shutil
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import (
    AgentConversation,
    AgentMemory,
    AgentMessage,
    AgentRun,
    AgentRunEvent,
    AgentToolRequest,
    CodeRepository,
    PaperDocument,
    Project,
    RepositoryAnalysisJob,
    TraceLink,
)


def _unique_project_ids(project_ids: list[int]) -> list[int]:
    return list(dict.fromkeys(project_ids))


def _delete_project_rows(session: Session, project_ids: list[int]) -> list[int]:
    projects = list(session.exec(select(Project).where(Project.id.in_(project_ids))).all())
    existing_ids = {project.id for project in projects if project.id is not None}
    if not existing_ids:
        return []

    for model in (
        AgentToolRequest,
        AgentRunEvent,
        AgentMessage,
        AgentRun,
        AgentMemory,
        AgentConversation,
        TraceLink,
        PaperDocument,
        RepositoryAnalysisJob,
        CodeRepository,
    ):
        rows = session.exec(select(model).where(model.project_id.in_(existing_ids))).all()
        for row in rows:
            session.delete(row)
    for project in projects:
        session.delete(project)
    session.commit()
    return [project_id for project_id in project_ids if project_id in existing_ids]


def _delete_project_job_metadata(project_ids: set[int]) -> None:
    jobs_root = Path(os.getenv("TRACELAB_PAPER_JOB_ROOT", "./data/paper-jobs")) / "jobs"
    if not jobs_root.is_dir():
        return
    for path in jobs_root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("project_id", -1)) in project_ids:
                path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue


def _delete_project_uploads(project_ids: set[int]) -> None:
    upload_root = Path(settings.upload_root).resolve()
    for project_id in project_ids:
        target = (upload_root / f"project-{project_id}").resolve()
        if target.parent == upload_root:
            shutil.rmtree(target, ignore_errors=True)


def delete_projects(session: Session, project_ids: list[int]) -> tuple[list[int], list[int]]:
    requested_ids = _unique_project_ids(project_ids)
    deleted_ids = _delete_project_rows(session, requested_ids)
    deleted_set = set(deleted_ids)
    if deleted_set:
        _delete_project_uploads(deleted_set)
        _delete_project_job_metadata(deleted_set)
    missing_ids = [project_id for project_id in requested_ids if project_id not in deleted_set]
    return deleted_ids, missing_ids
