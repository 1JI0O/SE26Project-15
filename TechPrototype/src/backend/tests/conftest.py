from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.db.session import get_session
from app.main import app
from app.services import analysis_jobs
from app.services.agent import analysis_jobs as agent_analysis_jobs
from app.services.agent import conversations
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
    monkeypatch.setattr(conversations, "engine", test_engine)
    monkeypatch.setattr(agent_analysis_jobs, "engine", test_engine)
    monkeypatch.setattr(factory, "engine", test_engine)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    # The developer's root .env may intentionally enable a real LLM. Tests must
    # never call it or vary with workstation secrets.
    monkeypatch.setattr(settings, "tracelab_llm_enabled", False)
    monkeypatch.setattr(settings, "tracelab_llm_base_url", "")
    monkeypatch.setattr(settings, "tracelab_llm_model", "")
    monkeypatch.setenv("TRACELAB_PAPER_JOB_ROOT", str(tmp_path / "paper-jobs"))
    yield
    app.dependency_overrides.pop(get_session, None)
