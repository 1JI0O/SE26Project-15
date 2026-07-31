import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.db.session import get_session
from app.main import app
from app.services import analysis_jobs, cloud_import
from app.services.agent import analysis_jobs as agent_analysis_jobs
from app.services.agent import conversations
from app.services.document_parsers import factory
from app.services.tracing import coordinator


def _configure_sqlite_connection(dbapi_connection, _record) -> None:  # noqa: ANN001
    """Mirror the production WAL/busy-timeout pragmas so concurrency behaves the same.

    ``synchronous`` is relaxed further than production: durability is irrelevant for a database
    that lives in ``tmp_path`` for one test, and fsync per commit would dominate the runtime.
    """

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def _drain_background_jobs(timeout: float = 15.0) -> None:
    """Wait for background analysis workers to finish before the fixture tears down.

    Both job modules resolve their module-level ``engine`` at *execution* time, and this
    fixture rebinds that global per test. A worker that outlives its own test therefore binds
    to the next test's engine — and because every test session shares ONE SQLite connection
    (``sqlite://`` + ``StaticPool``), its commits and rollbacks interleave with the request
    thread's transaction on that same connection. That is what produced the flaky
    "Could not refresh instance '<CodeRepository>'" on repository upload: the row had just been
    committed, then a leaked worker's rollback discarded it before ``session.refresh``.

    Draining keeps each test's background work inside its own fixture scope. It also stops a
    leaked worker from writing to the developer's real database once the patch is reverted.
    """

    tracked = (
        (analysis_jobs._submit_lock, analysis_jobs._submitted_jobs),
        (agent_analysis_jobs._lock, agent_analysis_jobs._submitted),
        (cloud_import._submit_lock, cloud_import._submitted),
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outstanding = 0
        for lock, submitted in tracked:
            with lock:
                outstanding += len(submitted)
        if not outstanding:
            return
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def isolate_application_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    # A file database with per-connection pooling, matching production. The previous
    # ``sqlite://`` + ``StaticPool`` setup gave every session in every thread the SAME DBAPI
    # connection, so a background worker shared transaction state with the request thread: it
    # could read rows the request had not committed yet, or lose rows the request had just
    # committed. That produced two unrelated-looking flakes — "Could not refresh instance
    # <CodeRepository>" on upload, and agent runs that never emitted message.completed.
    db_path = tmp_path / "workbench-test.db"
    test_engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(test_engine, "connect", _configure_sqlite_connection)
    SQLModel.metadata.create_all(test_engine)

    def session_override() -> Iterator[Session]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(analysis_jobs, "engine", test_engine)
    monkeypatch.setattr(cloud_import, "engine", test_engine)
    monkeypatch.setattr(conversations, "engine", test_engine)
    monkeypatch.setattr(agent_analysis_jobs, "engine", test_engine)
    monkeypatch.setattr(factory, "engine", test_engine)
    # The auto-trace coordinator runs from upload/parse completion hooks; without this it would
    # open sessions against the real application database during tests.
    monkeypatch.setattr(coordinator, "engine", test_engine)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    # The developer's root .env may intentionally enable a real LLM. Tests must
    # never call it or vary with workstation secrets.
    monkeypatch.setattr(settings, "tracelab_llm_enabled", False)
    monkeypatch.setattr(settings, "tracelab_llm_base_url", "")
    monkeypatch.setattr(settings, "tracelab_llm_model", "")
    monkeypatch.setenv("TRACELAB_PAPER_JOB_ROOT", str(tmp_path / "paper-jobs"))
    yield
    # Runs while the engine patches are still active (this fixture finalizes before monkeypatch).
    _drain_background_jobs()
    app.dependency_overrides.pop(get_session, None)
    test_engine.dispose()
