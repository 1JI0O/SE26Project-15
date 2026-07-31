"""Startup recovery must not read ORM attributes after its session closes.

``recover_repository_analysis`` runs inside the FastAPI lifespan, so an exception there
does not degrade one feature -- it aborts startup ("Application startup failed. Exiting.")
and the backend never serves a request. Because the trigger is a leftover ``queued`` or
``running`` row, an unclean shutdown would leave the process permanently unstartable with
no way for a user to recover on their own.

Found by the stress-test round documented in ``docs/stress-test-report.md`` (D1).
"""

from sqlmodel import Session, select

from app.models.entities import RepositoryAnalysisJob
from app.services import analysis_jobs


def test_recover_repository_analysis_submits_interrupted_jobs(monkeypatch) -> None:
    """A job left behind by a killed process is requeued and handed to the executor.

    Regression guard: the ids must be read while the session is still open. ``commit()``
    expires every attribute, so reading ``job.job_id`` afterwards raises
    ``DetachedInstanceError`` instead of submitting anything.
    """

    submitted: list[str] = []
    monkeypatch.setattr(analysis_jobs, "_submit", submitted.append)

    with Session(analysis_jobs.engine) as session:
        interrupted = RepositoryAnalysisJob(
            project_id=1,
            repository_id=1,
            repository_revision=1,
            status="running",
            targets_json=["all"],
        )
        pending = RepositoryAnalysisJob(
            project_id=1,
            repository_id=1,
            repository_revision=1,
            status="queued",
            targets_json=["all"],
        )
        session.add(interrupted)
        session.add(pending)
        session.commit()
        job_ids = [interrupted.job_id, pending.job_id]

    analysis_jobs.recover_repository_analysis()

    with Session(analysis_jobs.engine) as session:
        rows = {
            job.job_id: job
            for job in session.exec(
                select(RepositoryAnalysisJob).where(RepositoryAnalysisJob.job_id.in_(job_ids))
            ).all()
        }

    # Both are reset to queued with started_at cleared, then submitted for another attempt.
    for job_id in job_ids:
        assert rows[job_id].status == "queued"
        assert rows[job_id].started_at is None
    assert sorted(submitted) == sorted(job_ids)


def test_recover_repository_analysis_is_a_noop_without_leftover_jobs(monkeypatch) -> None:
    """The clean-shutdown path must stay quiet: nothing queued means nothing submitted."""

    submitted: list[str] = []
    monkeypatch.setattr(analysis_jobs, "_submit", submitted.append)

    with Session(analysis_jobs.engine) as session:
        leftover = session.exec(
            select(RepositoryAnalysisJob).where(
                RepositoryAnalysisJob.status.in_(["queued", "running"])
            )
        ).all()
        assert not leftover, "fixture database should start with no pending analysis jobs"

    analysis_jobs.recover_repository_analysis()

    assert submitted == []
