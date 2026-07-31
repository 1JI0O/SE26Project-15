"""Boundary and failure-path coverage for the RAG service and HTTP facade."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import rag as rag_routes
from app.main import app
from app.models.entities import (
    IntegrationConfig,
    PaperDocument,
    Project,
    RagChunk,
)
from app.services.rag import service
from app.services.rag.embeddings import (
    EmbeddingError,
    LangChainRemoteEmbedder,
    RemoteEmbedder,
    encode_vector,
    langchain_available,
)

client = TestClient(app)


class _StaticEmbedder:
    name = "test"
    model = "test-vector"
    dimensions = 2

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _FailingEmbedder(_StaticEmbedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("embedding_test_failure")


def _project(session: Session, name: str = "Boundary project") -> Project:
    project = Project(name=name)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _api_project(name: str) -> int:
    response = client.post("/api/v1/projects", json={"name": name, "description": ""})
    assert response.status_code == 201
    return int(response.json()["id"])


def test_rag_unavailable_exposes_a_stable_reason() -> None:
    error = service.RagUnavailable("rag_disabled")
    assert str(error) == "rag_disabled"
    assert error.reason == "rag_disabled"


def test_build_and_search_reject_invalid_input_before_touching_storage(
    rag_session: Session,
) -> None:
    with pytest.raises(service.RagUnavailable, match="rag_unknown_scope") as caught:
        service.build_index(rag_session, 1, "invalid")
    assert caught.value.reason == "rag_unknown_scope"

    assert service.search(rag_session, 1, "invalid", "query") == {
        "ok": False,
        "reason": "rag_unknown_scope",
        "items": [],
    }
    assert service.search(rag_session, 1, "paper", "  \t\n") == {
        "ok": False,
        "reason": "rag_empty_query",
        "items": [],
    }


def test_resolve_embedder_rejects_disabled_rag(rag_session: Session) -> None:
    rag_session.add(IntegrationConfig(id=1, rag_enabled=False))
    rag_session.commit()

    with pytest.raises(service.RagUnavailable) as caught:
        service.resolve_embedder(rag_session)
    assert caught.value.reason == "rag_disabled"


@pytest.mark.parametrize("dimensions, expected", [(512, 0), (1024, 1024)])
def test_resolve_embedder_builds_configured_remote_provider(
    rag_session: Session,
    dimensions: int,
    expected: int,
) -> None:
    rag_session.add(
        IntegrationConfig(
            id=1,
            rag_embedder="remote",
            rag_base_url="https://embedding.example/v1/",
            rag_api_key="secret",
            rag_model="embedding-model",
            rag_dimensions=dimensions,
            rag_timeout_seconds=12.5,
        )
    )
    rag_session.commit()

    embedder = service.resolve_embedder(rag_session)
    # Prefer LangChain when the optional ``rag`` extra is installed; otherwise httpx.
    assert isinstance(embedder, (LangChainRemoteEmbedder, RemoteEmbedder))
    if langchain_available():
        assert isinstance(embedder, LangChainRemoteEmbedder)
    else:
        assert isinstance(embedder, RemoteEmbedder)
    assert embedder.base_url == "https://embedding.example/v1"
    assert embedder.model == "embedding-model"
    assert embedder.dimensions == expected


def test_incomplete_remote_configuration_falls_back_to_local(rag_session: Session) -> None:
    rag_session.add(
        IntegrationConfig(
            id=1,
            rag_embedder="remote",
            rag_base_url="https://embedding.example/v1",
            rag_api_key="",
            rag_model="embedding-model",
            rag_dimensions=256,
        )
    )
    rag_session.commit()

    embedder = service.resolve_embedder(rag_session)
    assert embedder.name == "local"
    assert embedder.dimensions == 256


def test_build_drops_stale_chunks_when_the_source_becomes_unavailable(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    assert service.build_index(rag_session, project_id, "paper")["chunk_count"] == 3

    paper = rag_session.exec(select(PaperDocument)).one()
    paper.parse_status = "failed"
    rag_session.add(paper)
    rag_session.commit()

    result = service.build_index(rag_session, project_id, "paper")
    assert result == {"scope": "paper", "status": "pending", "chunk_count": 0}
    assert rag_session.exec(select(RagChunk)).all() == []
    state = service._state(rag_session, project_id, "paper")
    assert state.source_key == ""
    assert state.chunk_count == 0


def test_build_reports_disabled_if_embedder_resolution_becomes_unavailable(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_with_paper(rag_session)

    def unavailable(_session: Session) -> Any:
        raise service.RagUnavailable("rag_disabled_during_build")

    monkeypatch.setattr(service, "resolve_embedder", unavailable)
    assert service.build_index(rag_session, project.id or 0, "paper") == {
        "scope": "paper",
        "status": "disabled",
        "chunk_count": 0,
        "reason": "rag_disabled_during_build",
    }


def test_build_records_a_ready_empty_generation(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_with_paper(rag_session)
    monkeypatch.setattr(service, "_collect_chunks", lambda _scope, _source: [])
    monkeypatch.setattr(service, "resolve_embedder", lambda _session: _StaticEmbedder())

    result = service.build_index(rag_session, project.id or 0, "paper")
    assert result == {"scope": "paper", "status": "ready", "chunk_count": 0}
    state = service._state(rag_session, project.id or 0, "paper")
    assert (state.status, state.source_key, state.embedder, state.model) == (
        "ready",
        "hash-v1",
        "test",
        "test-vector",
    )
    assert state.built_at is not None


def test_build_persists_embedding_failure_and_search_surfaces_it(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    monkeypatch.setattr(service, "resolve_embedder", lambda _session: _FailingEmbedder())

    result = service.build_index(rag_session, project_id, "paper")
    assert result == {
        "scope": "paper",
        "status": "failed",
        "chunk_count": 0,
        "reason": "embedding_test_failure",
    }
    state = service._state(rag_session, project_id, "paper")
    assert state.status == "failed"
    assert state.error == "embedding_test_failure"
    assert service.search(rag_session, project_id, "paper", "query", auto_build=False) == {
        "ok": False,
        "reason": "embedding_test_failure",
        "items": [],
    }


def test_search_uses_default_reason_for_failed_state_without_an_error(
    rag_session: Session,
) -> None:
    project = _project(rag_session)
    state = service._state(rag_session, project.id or 0, "paper")
    state.status = "failed"
    state.error = None
    rag_session.add(state)
    rag_session.commit()

    assert service.search(
        rag_session, project.id or 0, "paper", "query", auto_build=False
    )["reason"] == "rag_index_failed"


@pytest.mark.parametrize(
    "error, reason",
    [
        (service.RagUnavailable("rag_runtime_unavailable"), "rag_runtime_unavailable"),
        (EmbeddingError("embedding_query_failure"), "embedding_query_failure"),
    ],
)
def test_search_degrades_when_query_embedding_fails(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    reason: str,
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    service.build_index(rag_session, project_id, "paper")

    def unavailable(_session: Session) -> Any:
        raise error

    monkeypatch.setattr(service, "resolve_embedder", unavailable)
    result = service.search(rag_session, project_id, "paper", "query", auto_build=False)
    assert result == {"ok": False, "reason": reason, "items": []}


def test_search_deduplicates_overlapping_chunks_with_the_same_ref(
    rag_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(rag_session)
    project_id = project.id or 0
    state = service._state(rag_session, project_id, "paper")
    state.status = "ready"
    state.source_key = "generation"
    state.chunk_count = 2
    rag_session.add(state)
    rag_session.add_all(
        [
            RagChunk(
                project_id=project_id,
                scope="paper",
                source_key="generation",
                ref="same-ref",
                text="full first text",
                embedding=encode_vector([1.0, 0.0]),
                dimensions=2,
                metadata_json={"preview": "first preview", "page": 1},
            ),
            RagChunk(
                project_id=project_id,
                scope="paper",
                source_key="generation",
                ref="same-ref",
                text="duplicate text",
                embedding=encode_vector([0.5, 0.0]),
                dimensions=2,
                metadata_json={"preview": "duplicate preview", "page": 2},
            ),
        ]
    )
    rag_session.commit()
    monkeypatch.setattr(service, "resolve_embedder", lambda _session: _StaticEmbedder())

    result = service.search(
        rag_session, project_id, "paper", "query", limit=2, auto_build=False
    )
    assert result["ok"] is True
    assert result["searched"] == 2
    assert result["items"] == [
        {"ref": "same-ref", "score": 1.0, "text": "first preview", "page": 1}
    ]


def test_refresh_skips_builds_when_disabled(
    rag_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.db.session as db_session

    rag_session.add(IntegrationConfig(id=1, rag_enabled=False))
    rag_session.commit()
    monkeypatch.setattr(db_session, "engine", rag_session.get_bind())
    calls: list[str] = []
    monkeypatch.setattr(
        service,
        "build_index",
        lambda _session, _project_id, scope: calls.append(scope),
    )

    service.refresh_project_indexes(1)
    assert calls == []


def test_refresh_continues_after_one_scope_fails(
    rag_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import app.db.session as db_session

    monkeypatch.setattr(db_session, "engine", rag_session.get_bind())
    calls: list[str] = []

    def build(_session: Session, _project_id: int, scope: str) -> None:
        calls.append(scope)
        if scope == "paper":
            raise RuntimeError("paper build failed")

    monkeypatch.setattr(service, "build_index", build)
    service.refresh_project_indexes(1, ("paper", "code"))

    assert calls == ["paper", "code"]
    assert "rag paper index build failed" in caplog.text


def test_refresh_swallows_session_setup_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenSession:
        def __init__(self, _engine: Any) -> None:
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "Session", BrokenSession)
    service.refresh_project_indexes(7)
    assert "rag index refresh failed for project 7" in caplog.text


def test_invalidate_is_advisory_when_storage_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenSession:
        def exec(self, _statement: Any) -> Any:
            raise RuntimeError("database unavailable")

    service.invalidate(BrokenSession(), 9, "trace")  # type: ignore[arg-type]
    assert "rag invalidate failed for project 9 scope trace" in caplog.text


def test_rag_api_returns_404_for_an_unknown_project() -> None:
    assert client.get("/api/v1/projects/99999999/rag/status").status_code == 404
    assert client.post("/api/v1/projects/99999999/rag/rebuild", json={}).status_code == 404
    assert client.get(
        "/api/v1/projects/99999999/rag/search", params={"query": "x"}
    ).status_code == 404


@pytest.mark.parametrize(
    "path, params",
    [
        ("search", {"query": ""}),
        ("search", {"query": "x" * 1001}),
        ("search", {"query": "x", "limit": 0}),
        ("search", {"query": "x", "limit": 21}),
    ],
)
def test_rag_search_api_validates_query_and_limit(path: str, params: dict[str, Any]) -> None:
    project_id = _api_project(f"RAG validation {len(params)} {len(str(params))}")
    response = client.get(f"/api/v1/projects/{project_id}/rag/{path}", params=params)
    assert response.status_code == 422


def test_rag_rebuild_api_forwards_single_scope_and_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = _api_project("RAG forced single rebuild")
    calls: list[tuple[int, str, bool]] = []

    def build(_session: Session, called_project_id: int, scope: str, *, force: bool) -> dict:
        calls.append((called_project_id, scope, force))
        return {"scope": scope, "status": "ready", "chunk_count": 4, "reused": False}

    monkeypatch.setattr(rag_routes, "build_index", build)
    response = client.post(
        f"/api/v1/projects/{project_id}/rag/rebuild",
        json={"scope": "code", "force": True},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"scope": "code", "status": "ready", "chunk_count": 4, "reused": False}
    ]
    assert calls == [(project_id, "code", True)]


def test_rag_search_api_forwards_valid_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = _api_project("RAG search forwarding")
    calls: list[tuple[int, str, str, int]] = []

    def search(
        _session: Session,
        called_project_id: int,
        scope: str,
        query: str,
        *,
        limit: int,
    ) -> dict:
        calls.append((called_project_id, scope, query, limit))
        return {
            "ok": True,
            "query": query,
            "scope": scope,
            "embedder": "test:model",
            "items": [{"ref": "symbol", "score": 1.0, "text": "match"}],
            "searched": 1,
        }

    monkeypatch.setattr(rag_routes, "search", search)
    response = client.get(
        f"/api/v1/projects/{project_id}/rag/search",
        params={"query": "focal loss", "scope": "code", "limit": 7},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["ref"] == "symbol"
    assert calls == [(project_id, "code", "focal loss", 7)]


def test_rag_rebuild_api_rejects_an_invalid_scope() -> None:
    project_id = _api_project("RAG invalid rebuild scope")
    response = client.post(
        f"/api/v1/projects/{project_id}/rag/rebuild",
        json={"scope": "invalid"},
    )
    assert response.status_code == 422
