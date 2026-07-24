from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.routes.integration_settings import router
from app.db.session import get_session


def _client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    return TestClient(app)


def _payload(agent_key: str | None = None, mineru_token: str | None = None) -> dict:
    agent = {
        "enabled": True,
        "base_url": "https://api.example.com/v1/",
        "model": "example-chat",
        "thinking_mode": "disabled",
        "timeout_seconds": 30,
        "clear_api_key": False,
    }
    mineru = {
        "provider": "official",
        "local_url": "http://127.0.0.1:8001/",
        "backend": "pipeline",
        "language": "ch",
        "parse_method": "auto",
        "official_api_url": "https://mineru.net/api/v4/",
        "official_api_model": "vlm",
        "ocr": True,
        "formula_enable": True,
        "table_enable": True,
        "request_timeout_seconds": 60,
        "request_retries": 3,
        "task_timeout_seconds": 600,
        "poll_interval_seconds": 2,
        "clear_api_token": False,
    }
    if agent_key is not None:
        agent["api_key"] = agent_key
    if mineru_token is not None:
        mineru["official_api_token"] = mineru_token
    return {"agent": agent, "mineru": mineru}


def test_settings_are_saved_without_returning_secrets() -> None:
    with _client() as client:
        saved = client.put(
            "/api/v1/settings/integrations",
            json=_payload("agent-secret", "mineru-secret"),
        )
        read = client.get("/api/v1/settings/integrations")

    assert saved.status_code == 200
    assert saved.json()["source"] == "application"
    assert saved.json()["agent"]["api_key_configured"] is True
    assert saved.json()["mineru"]["api_token_configured"] is True
    assert "agent-secret" not in saved.text
    assert "mineru-secret" not in saved.text
    assert read.json()["agent"]["base_url"] == "https://api.example.com/v1"


def test_blank_secret_preserves_it_and_clear_flag_removes_it() -> None:
    with _client() as client:
        client.put(
            "/api/v1/settings/integrations",
            json=_payload("agent-secret", "mineru-secret"),
        )
        preserved = client.put("/api/v1/settings/integrations", json=_payload())
        clear_payload = _payload()
        clear_payload["agent"]["clear_api_key"] = True
        clear_payload["mineru"]["clear_api_token"] = True
        cleared = client.put("/api/v1/settings/integrations", json=clear_payload)

    assert preserved.json()["agent"]["api_key_configured"] is True
    assert preserved.json()["mineru"]["api_token_configured"] is True
    assert cleared.json()["agent"]["api_key_configured"] is False
    assert cleared.json()["mineru"]["api_token_configured"] is False
