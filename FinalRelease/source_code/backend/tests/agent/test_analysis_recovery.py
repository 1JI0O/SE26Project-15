"""Startup recovery must tolerate the naive timestamps SQLite hands back.

Every timestamp is written as aware UTC, but SQLite has no timezone-aware type, so a row read
back after a restart carries a *naive* datetime. ``recover_analysis_jobs`` runs inside the
FastAPI lifespan, so a ``TypeError`` there does not degrade one feature — it aborts startup
("Application startup failed. Exiting.") and the whole desktop app refuses to launch.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.models.entities import AgentAnalysisJob, as_utc, utc_now
from app.services.agent import analysis_jobs


def _naive(delta_seconds: int) -> datetime:
    """A stored timestamp as SQLite returns it: UTC wall clock, no tzinfo."""

    return (datetime.now(UTC) - timedelta(seconds=delta_seconds)).replace(tzinfo=None)


def test_as_utc_normalizes_naive_and_preserves_aware() -> None:
    naive = datetime(2026, 7, 26, 14, 24, 8)
    assert as_utc(naive).tzinfo is UTC
    assert as_utc(naive) == naive.replace(tzinfo=UTC)
    aware = utc_now()
    assert as_utc(aware) is aware


def test_recover_analysis_jobs_handles_naive_timestamps(monkeypatch) -> None:
    """An interrupted job left by a previous process must not crash the lifespan hook."""

    submitted: list[str] = []
    monkeypatch.setattr(analysis_jobs, "_submit", submitted.append)

    with Session(analysis_jobs.engine) as session:
        fresh = AgentAnalysisJob(
            project_id=1,
            kind="trace",
            code_repository_id=1,
            code_revision=1,
            fingerprint="recover-fresh",
            status="running",
        )
        stale = AgentAnalysisJob(
            project_id=1,
            kind="trace",
            code_repository_id=1,
            code_revision=1,
            fingerprint="recover-stale",
            status="running",
        )
        session.add(fresh)
        session.add(stale)
        session.commit()
        # Overwrite through SQL so the values stay naive, exactly as a restart would read them.
        fresh.updated_at = _naive(30)
        stale.updated_at = _naive(3600)  # well past the 15-minute staleness cutoff
        session.add(fresh)
        session.add(stale)
        session.commit()
        fresh_id, stale_id = fresh.job_id, stale.job_id

    analysis_jobs.recover_analysis_jobs()

    with Session(analysis_jobs.engine) as session:
        rows = {
            job.job_id: job
            for job in session.exec(
                select(AgentAnalysisJob).where(
                    AgentAnalysisJob.job_id.in_([fresh_id, stale_id])
                )
            ).all()
        }
    # Recent job is requeued for another attempt; the long-idle one is retired, not resubmitted.
    assert rows[fresh_id].status == "queued"
    assert rows[stale_id].status == "failed"
    assert rows[stale_id].error_code == "analysis_stale_timeout"
    assert submitted == [fresh_id]
