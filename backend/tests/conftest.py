from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.db.session import get_session
from app.main import app
from app.services import analysis_jobs
from app.services.document_parsers import factory


@pytest.fixture(autouse=True)
def isolate_application_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    def session_override() -> Iterator[Session]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(analysis_jobs, "engine", test_engine)
    monkeypatch.setattr(factory, "engine", test_engine)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setenv("TRACELAB_PAPER_JOB_ROOT", str(tmp_path / "paper-jobs"))
    yield
    app.dependency_overrides.pop(get_session, None)
