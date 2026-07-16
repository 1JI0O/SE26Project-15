from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import engine
from app.models.entities import CodeRepository, RepositoryAnalysisJob, utc_now
from app.services.code_analysis.analyzer import analyze_code_archive

ANALYZER_VERSION = "architecture-v3"

_executor = ThreadPoolExecutor(
    max_workers=max(settings.tracelab_analysis_workers, 1),
    thread_name_prefix="tracelab-analysis",
)
_submit_lock = Lock()
_submitted_jobs: set[str] = set()


def repository_edits_root(repository: CodeRepository) -> Path:
    repository_key = repository.id or Path(repository.storage_path).stem
    return (
        Path(settings.upload_root)
        / f"project-{repository.project_id}"
        / "code-edits"
        / str(repository_key)
    )


def persist_analysis(repository: CodeRepository, analysis: dict[str, Any]) -> None:
    repository.file_tree_json = analysis["file_tree"]
    repository.symbols_json = analysis["symbols"]
    repository.imports_json = analysis["imports"]
    repository.pytorch_candidates_json = analysis["pytorch_candidates"]
    repository.tensor_graph_json = analysis["tensor_graph"]
    repository.analysis_json = analysis
    repository.analysis_revision = repository.revision
    repository.analysis_version = ANALYZER_VERSION
    repository.analysis_status = "ready"
    repository.analysis_error = None
    repository.analysis_updated_at = utc_now()
    repository.updated_at = utc_now()


def analysis_is_current(repository: CodeRepository) -> bool:
    return bool(
        repository.analysis_json
        and repository.analysis_status == "ready"
        and repository.analysis_revision == repository.revision
        and repository.analysis_version == ANALYZER_VERSION
    )


def _latest_repository(session: Session, project_id: int) -> CodeRepository | None:
    return session.exec(
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    ).first()


def _submit(job_id: str) -> None:
    with _submit_lock:
        if job_id in _submitted_jobs:
            return
        _submitted_jobs.add(job_id)
    _executor.submit(_execute_job, job_id)


def _execute_job(job_id: str) -> None:
    try:
        with Session(engine) as session:
            job = session.get(RepositoryAnalysisJob, job_id)
            if job is None or job.status == "completed":
                return
            repository = session.get(CodeRepository, job.repository_id)
            if repository is None:
                job.status = "failed"
                job.error_summary = "repository_not_found"
                job.completed_at = utc_now()
                session.add(job)
                session.commit()
                return
            job.status = "running"
            job.started_at = utc_now()
            repository.analysis_status = "running"
            session.add(job)
            session.add(repository)
            session.commit()
            storage_path = repository.storage_path
            edits_root = repository_edits_root(repository)
            expected_revision = job.repository_revision

        analysis = analyze_code_archive(storage_path, edits_root=edits_root)

        with Session(engine) as session:
            job = session.get(RepositoryAnalysisJob, job_id)
            repository = session.get(CodeRepository, job.repository_id) if job else None
            if job is None or repository is None:
                return
            revision_changed = repository.revision != expected_revision
            if revision_changed:
                job.status = "superseded"
                job.error_summary = "repository_revision_changed"
                job.completed_at = utc_now()
                repository.analysis_status = "stale"
            else:
                persist_analysis(repository, analysis)
                job.status = "completed"
                job.error_summary = None
                job.completed_at = utc_now()
            session.add(job)
            session.add(repository)
            session.commit()
            if revision_changed:
                enqueue_repository_analysis(
                    repository.project_id,
                    ["all"],
                    f"revision-{repository.revision}",
                )
    except Exception as exc:
        with Session(engine) as session:
            job = session.get(RepositoryAnalysisJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_summary = str(exc)[:500]
                job.completed_at = utc_now()
                repository = session.get(CodeRepository, job.repository_id)
                if repository is not None:
                    repository.analysis_status = "failed"
                    repository.analysis_error = str(exc)[:500]
                    session.add(repository)
                session.add(job)
                session.commit()
    finally:
        with _submit_lock:
            _submitted_jobs.discard(job_id)


def enqueue_repository_analysis(
    project_id: int,
    targets: list[str] | None = None,
    idempotency_key: str = "automatic",
) -> dict[str, Any]:
    targets = targets or ["all"]
    with Session(engine) as session:
        repository = _latest_repository(session, project_id)
        if repository is None:
            raise ValueError("code_repository_not_found")
        if analysis_is_current(repository) and idempotency_key.startswith("automatic"):
            return {
                "job_id": None,
                "status": "ready",
                "targets": targets,
                "summary": repository.analysis_json.get("summary", {}),
            }
        existing = session.exec(
            select(RepositoryAnalysisJob)
            .where(
                RepositoryAnalysisJob.repository_id == (repository.id or 0),
                RepositoryAnalysisJob.repository_revision == repository.revision,
                RepositoryAnalysisJob.status.in_(["queued", "running"]),
            )
            .order_by(RepositoryAnalysisJob.created_at.desc())
        ).first()
        if existing is None:
            existing = RepositoryAnalysisJob(
                project_id=project_id,
                repository_id=repository.id or 0,
                repository_revision=repository.revision,
                targets_json=targets,
            )
            session.add(existing)
        repository.analysis_status = "queued"
        repository.analysis_error = None
        session.add(repository)
        session.commit()
        session.refresh(existing)
        job_id = existing.job_id
    _submit(job_id)
    return {"job_id": job_id, "status": "queued", "targets": targets}


def ensure_repository_analysis(project_id: int) -> dict[str, Any]:
    return enqueue_repository_analysis(project_id, ["all"], "automatic-cache-refresh")


def recover_repository_analysis() -> None:
    """Resume interrupted jobs and warm missing or stale caches at startup."""

    with Session(engine) as session:
        jobs = list(
            session.exec(
                select(RepositoryAnalysisJob).where(
                    RepositoryAnalysisJob.status.in_(["queued", "running"])
                )
            ).all()
        )
        for job in jobs:
            job.status = "queued"
            job.started_at = None
            session.add(job)
        session.commit()
        project_ids = {
            repository.project_id
            for repository in session.exec(select(CodeRepository)).all()
            if not analysis_is_current(repository)
        }
    for job in jobs:
        _submit(job.job_id)
    for project_id in project_ids:
        try:
            ensure_repository_analysis(project_id)
        except ValueError:
            continue


def run_repository_analysis(
    project_id: int,
    targets: list[str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Queue an approved Agent analysis request without blocking the Agent loop."""

    return enqueue_repository_analysis(project_id, targets, idempotency_key)
