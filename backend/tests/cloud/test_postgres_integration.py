import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect
from sqlmodel import Session, create_engine, select

from app.db.migration_runner import upgrade_cloud_database
from app.models.cloud_entities import BackgroundJob, UserAccount, Workspace

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL", "")
if os.getenv("CI") and not POSTGRES_URL:
    raise RuntimeError("CI requires TEST_POSTGRES_URL; PostgreSQL tests may not be skipped")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")


def test_real_postgres_migration_sequence_lock_and_skip_locked() -> None:
    engine = create_engine(POSTGRES_URL)
    upgrade_cloud_database(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"user_account", "workspace", "sync_event", "blob_object", "background_job"} <= tables
    assert "project" not in tables

    with Session(engine) as session:
        user = UserAccount(email_normalized="postgres@example.com", password_hash="fixture")
        session.add(user)
        session.flush()
        workspace = Workspace(name="postgres", created_by=user.user_id)
        session.add(workspace)
        session.add(BackgroundJob(job_type="fixture", idempotency_key="postgres-lock-a"))
        session.add(BackgroundJob(job_type="fixture", idempotency_key="postgres-lock-b"))
        session.commit()
        workspace_id = workspace.workspace_id

    def increment_sequence() -> None:
        with Session(engine) as session:
            workspace = session.exec(
                select(Workspace).where(Workspace.workspace_id == workspace_id).with_for_update()
            ).one()
            workspace.workspace_seq += 1
            session.add(workspace)
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: increment_sequence(), range(2)))
    with Session(engine) as session:
        assert session.get(Workspace, workspace_id).workspace_seq == 2

    first = Session(engine)
    second = Session(engine)
    try:
        first_job = first.exec(
            select(BackgroundJob)
            .where(BackgroundJob.job_type == "fixture")
            .order_by(BackgroundJob.idempotency_key)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).one()
        second_job = second.exec(
            select(BackgroundJob)
            .where(BackgroundJob.job_type == "fixture")
            .order_by(BackgroundJob.idempotency_key)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).one()
        assert first_job.job_id != second_job.job_id
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
