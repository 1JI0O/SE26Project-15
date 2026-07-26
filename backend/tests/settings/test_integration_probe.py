from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.routes.integration_settings import router
from app.db.session import get_session
from app.services import integration_probe


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


def _response(status: int, payload: Any, url: str = "https://api.example.com/v1") -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", url))


def test_agent_probe_reports_success_with_the_served_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        seen["json"] = kwargs["json"]
        return _response(
            200, {"choices": [{"message": {"content": "pong"}}]}
        )

    monkeypatch.setattr(integration_probe.httpx, "post", fake_post)
    with _client() as client:
        result = client.post(
            "/api/v1/settings/integrations/probe",
            json={
                "target": "agent",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-test",
                "model": "example-chat",
            },
        )

    assert result.status_code == 200
    body = result.json()
    assert body["ok"] is True
    assert body["code"] == "ok"
    # The probe must exercise the real completion endpoint with the given credentials.
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["json"]["model"] == "example-chat"


def test_agent_probe_surfaces_the_providers_own_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return _response(401, {"error": {"message": "Invalid API key provided"}})

    monkeypatch.setattr(integration_probe.httpx, "post", fake_post)
    with _client() as client:
        result = client.post(
            "/api/v1/settings/integrations/probe",
            json={
                "target": "agent",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-wrong",
                "model": "example-chat",
            },
        )

    # A rejected key is a probe result, not an API error — the caller still gets 200.
    assert result.status_code == 200
    body = result.json()
    assert body["ok"] is False
    assert body["code"] == "unauthorized"
    assert "Invalid API key provided" in body["detail"]


def test_agent_probe_reports_transport_failure_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(integration_probe.httpx, "post", fake_post)
    with _client() as client:
        result = client.post(
            "/api/v1/settings/integrations/probe",
            json={
                "target": "agent",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-test",
                "model": "example-chat",
            },
        )

    body = result.json()
    assert result.status_code == 200
    assert body["ok"] is False
    assert body["code"] == "transport_error"
    assert "connection refused" in body["detail"]


def test_agent_probe_without_a_stored_or_supplied_key_fails_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> httpx.Response:
        raise AssertionError("probe must not issue a request without a key")

    monkeypatch.setattr(integration_probe.httpx, "post", fail)
    with _client() as client:
        result = client.post(
            "/api/v1/settings/integrations/probe",
            json={
                "target": "agent",
                "base_url": "https://api.example.com/v1",
                "model": "example-chat",
            },
        )

    assert result.json()["code"] == "missing_api_key"


def test_mineru_local_probe_hits_health(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        seen["url"] = url
        return httpx.Response(
            200, json={"version": "2.0"}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(integration_probe.httpx, "get", fake_get)
    with _client() as client:
        result = client.post(
            "/api/v1/settings/integrations/probe",
            json={
                "target": "mineru",
                "mineru_provider": "local",
                "base_url": "http://127.0.0.1:8001",
            },
        )

    assert result.json()["ok"] is True
    assert seen["url"] == "http://127.0.0.1:8001/health"


def test_mineru_official_probe_flags_a_rejected_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            401, text="token expired", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(integration_probe.httpx, "get", fake_get)
    with _client() as client:
        result = client.post(
            "/api/v1/settings/integrations/probe",
            json={
                "target": "mineru",
                "mineru_provider": "official",
                "base_url": "https://mineru.net/api/v4",
                "api_key": "bad-token",
            },
        )

    body = result.json()
    assert body["ok"] is False
    assert body["code"] == "unauthorized"


def test_mineru_official_probe_treats_a_missing_batch_as_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The probe batch id never exists; anything other than an auth rejection proves the
    # endpoint accepted our token, which is all we set out to learn.
    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": -60012, "msg": "task not found"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(integration_probe.httpx, "get", fake_get)
    with _client() as client:
        result = client.post(
            "/api/v1/settings/integrations/probe",
            json={
                "target": "mineru",
                "mineru_provider": "official",
                "base_url": "https://mineru.net/api/v4",
                "api_key": "good-token",
            },
        )

    assert result.json()["ok"] is True


def test_probe_reuses_the_stored_secret_when_none_is_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen["headers"] = kwargs["headers"]
        return _response(200, {"choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr(integration_probe.httpx, "post", fake_post)
    with _client() as client:
        client.put(
            "/api/v1/settings/integrations",
            json={
                "agent": {
                    "enabled": True,
                    "base_url": "https://api.example.com/v1",
                    "model": "example-chat",
                    "api_key": "stored-secret",
                    "thinking_mode": "",
                    "timeout_seconds": 30,
                    "clear_api_key": False,
                },
                "mineru": {
                    "provider": "local",
                    "local_url": "http://127.0.0.1:8001",
                    "backend": "pipeline",
                    "language": "ch",
                    "parse_method": "auto",
                    "official_api_url": "https://mineru.net/api/v4",
                    "official_api_model": "vlm",
                    "ocr": True,
                    "formula_enable": True,
                    "table_enable": True,
                    "request_timeout_seconds": 60,
                    "request_retries": 3,
                    "task_timeout_seconds": 600,
                    "poll_interval_seconds": 2,
                    "clear_api_token": False,
                },
            },
        )
        result = client.post(
            "/api/v1/settings/integrations/probe", json={"target": "agent"}
        )

    assert result.json()["ok"] is True
    assert seen["headers"]["Authorization"] == "Bearer stored-secret"
