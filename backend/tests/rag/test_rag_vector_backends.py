"""LanceDB store, LangChain embedder, and missing-deps resolution coverage."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from app.models.entities import IntegrationConfig, Project, RagChunk
from app.services.rag import embeddings, service
from app.services.rag.embeddings import LangChainRemoteEmbedder, LocalHashingEmbedder
from app.services.rag.vector_store import LanceDbStore, SqliteExactStore, lancedb_available

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _skip_without_lancedb() -> None:
    if not lancedb_available():
        pytest.skip("optional rag extra (lancedb) not installed")


def _skip_without_langchain() -> None:
    if not embeddings.langchain_available():
        pytest.skip("optional rag extra (langchain-openai) not installed")


def test_langchain_remote_embedder_normalizes_and_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    _skip_without_langchain()

    class _FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            self.calls: list[list[str]] = []

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(list(texts))
            # Unnormalized vectors — the adapter must L2-normalize.
            return [[3.0, 4.0] for _ in texts]

    fake = _FakeClient()
    monkeypatch.setattr(
        "langchain_openai.OpenAIEmbeddings",
        lambda **kwargs: fake,
    )
    embedder = LangChainRemoteEmbedder(
        "https://embedding.example/v1",
        "secret",
        "embed-v1",
        timeout_seconds=9.0,
        dimensions=2,
    )
    vectors = embedder.embed(["alpha", "beta"])
    assert fake.calls == [["alpha", "beta"]]
    assert vectors[0] == pytest.approx([0.6, 0.8])
    assert vectors[1] == pytest.approx([0.6, 0.8])
    assert embedder.dimensions == 2
    assert embedder.embed([]) == []


def test_langchain_remote_embedder_maps_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_without_langchain()

    class _Boom:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("401 unauthorized from provider")

    monkeypatch.setattr(
        "langchain_openai.OpenAIEmbeddings",
        lambda **_kwargs: _Boom(),
    )
    embedder = LangChainRemoteEmbedder("https://example/v1", "k", "m")
    with pytest.raises(embeddings.EmbeddingError) as caught:
        embedder.embed(["q"])
    assert caught.value.reason == "embedding_unauthorized"


def test_lancedb_store_replace_query_dedupes_refs(tmp_path: Path) -> None:
    _skip_without_lancedb()
    store = LanceDbStore(root=tmp_path / "lance")
    store.replace(
        7,
        "paper",
        "gen-1",
        [
            {
                "ref": "a",
                "text": "focal loss primary",
                "vector": [1.0, 0.0],
                "metadata": {"preview": "primary", "page": 1},
            },
            {
                "ref": "a",
                "text": "focal loss window",
                "vector": [0.95, 0.05],
                "metadata": {"preview": "window", "page": 1},
            },
            {
                "ref": "b",
                "text": "attention",
                "vector": [0.2, 0.8],
                "metadata": {"preview": "attn", "page": 2},
            },
        ],
    )
    hits = store.query(7, "paper", "gen-1", [1.0, 0.0], limit=5)
    assert [item["ref"] for item in hits] == ["a", "b"]
    assert hits[0]["text"] == "primary"
    assert hits[0]["score"] >= hits[1]["score"]
    assert hits[0]["page"] == 1

    # Wrong generation key → empty.
    assert store.query(7, "paper", "other", [1.0, 0.0], limit=3) == []
    store.delete_scope(7, "paper")
    assert store.query(7, "paper", "gen-1", [1.0, 0.0], limit=3) == []


def test_resolve_vector_store_reports_missing_lancedb_deps(
    rag_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rag_session.add(IntegrationConfig(id=1, rag_vector_store="lancedb"))
    rag_session.commit()
    monkeypatch.setattr(service, "lancedb_available", lambda: False)

    with pytest.raises(service.RagUnavailable) as caught:
        service.resolve_vector_store(rag_session)
    assert caught.value.reason == "rag_vector_deps_missing"

    result = service.search(rag_session, 1, "paper", "anything", auto_build=False)
    assert result == {"ok": False, "reason": "rag_vector_deps_missing", "items": []}


def test_resolve_vector_store_missing_deps_during_build(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_with_paper(rag_session)
    rag_session.add(IntegrationConfig(id=1, rag_vector_store="lancedb"))
    rag_session.commit()
    monkeypatch.setattr(service, "lancedb_available", lambda: False)

    built = service.build_index(rag_session, project.id or 0, "paper")
    assert built["status"] == "disabled"
    assert built["reason"] == "rag_vector_deps_missing"

    searched = service.search(rag_session, project.id or 0, "paper", "focal loss")
    assert searched == {
        "ok": False,
        "reason": "rag_vector_deps_missing",
        "items": [],
    }


def test_resolve_embedder_falls_back_to_httpx_without_langchain(
    rag_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rag_session.add(
        IntegrationConfig(
            id=1,
            rag_embedder="remote",
            rag_base_url="https://embedding.example/v1",
            rag_api_key="secret",
            rag_model="embedding-model",
        )
    )
    rag_session.commit()
    monkeypatch.setattr(service, "langchain_available", lambda: False)

    embedder = service.resolve_embedder(rag_session)
    assert embedder.name == "remote"
    assert type(embedder).__name__ == "RemoteEmbedder"


def test_lancedb_build_and_search_does_not_write_sqlite_embeddings(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skip_without_lancedb()
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    rag_session.add(IntegrationConfig(id=1, rag_vector_store="lancedb", rag_embedder="local"))
    rag_session.commit()

    store = LanceDbStore(root=tmp_path / "lance-index")
    monkeypatch.setattr(service, "resolve_vector_store", lambda _session: store)

    built = service.build_index(rag_session, project_id, "paper")
    assert built["status"] == "ready"
    assert built["chunk_count"] > 0
    assert rag_session.exec(select(RagChunk)).all() == []

    result = service.search(rag_session, project_id, "paper", "focal loss down-weight")
    assert result["ok"] is True
    assert result["items"]
    assert result["items"][0]["ref"]


def test_sqlite_store_roundtrip(rag_session: Session) -> None:
    project = Project(name="store")
    rag_session.add(project)
    rag_session.commit()
    rag_session.refresh(project)
    store = SqliteExactStore(rag_session)
    store.replace(
        project.id or 0,
        "paper",
        "k",
        [
            {
                "ref": "r1",
                "text": "alpha",
                "vector": LocalHashingEmbedder(64).embed(["alpha"])[0],
                "metadata": {"preview": "alpha"},
                "embedder": "local",
            }
        ],
    )
    query = LocalHashingEmbedder(64).embed(["alpha"])[0]
    hits = store.query(project.id or 0, "paper", "k", query, limit=1)
    assert hits[0]["ref"] == "r1"
    store.delete_scope(project.id or 0, "paper")
    assert store.query(project.id or 0, "paper", "k", query, limit=1) == []
