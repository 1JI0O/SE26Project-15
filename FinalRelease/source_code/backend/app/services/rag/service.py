"""Index build + search for the three retrieval scopes.

Scopes and what invalidates them:

* ``paper`` — keyed by the paper's ``content_hash``. Rebuilt when a new paper is parsed.
* ``code``  — keyed by ``{repository_id}:{analysis_revision}``. Rebuilt when analysis lands.
* ``trace`` — keyed by a digest of reviewed link ids, so accepting or rejecting a link
  invalidates it without a version counter.

Everything degrades to "no results" rather than raising: retrieval is an accelerator layered
on top of the existing exhaustive read tools, so a missing index, a failed embedder, or a
disabled feature must never break parsing, tracing, or chat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any

from sqlmodel import Session, select

from app.models.entities import (
    CodeRepository,
    PaperDocument,
    RagIndexState,
    TraceLink,
    utc_now,
)
from app.services.rag.chunking import code_chunks, paper_chunks, trace_chunks
from app.services.rag.embeddings import (
    Embedder,
    EmbeddingError,
    LangChainRemoteEmbedder,
    LocalHashingEmbedder,
    RemoteEmbedder,
    langchain_available,
)
from app.services.rag.vector_store import (
    LanceDbStore,
    SqliteExactStore,
    VectorStore,
    VectorStoreError,
    lancedb_available,
)

logger = logging.getLogger(__name__)

SCOPES = ("paper", "code", "trace")
REVIEWED_STATUSES = ("accepted", "rejected")
# Cap per scope. Keeps a pathological repository (50k symbols) from turning one index build
# into a multi-minute embedding job or a hundred-megabyte table.
MAX_CHUNKS = {"paper": 4000, "code": 6000, "trace": 2000}
# Serialize builds per (project, scope): the same build can be triggered from the paper hook,
# the analysis hook, and a tool call at once, and duplicating the embedding work is pure waste.
_build_locks: dict[tuple[int, str], threading.Lock] = {}
_locks_guard = threading.Lock()


def _build_lock(project_id: int, scope: str) -> threading.Lock:
    key = (project_id, scope)
    with _locks_guard:
        lock = _build_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _build_locks[key] = lock
        return lock


class RagUnavailable(RuntimeError):
    """Retrieval cannot run; ``reason`` is a stable machine code for the caller."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def rag_settings(session: Session) -> dict[str, Any]:
    from app.services.integration_settings import get_effective_integration_config

    config, _ = get_effective_integration_config(session)
    vector_store = str(getattr(config, "rag_vector_store", "sqlite") or "sqlite")
    if vector_store not in {"sqlite", "lancedb"}:
        vector_store = "sqlite"
    return {
        "enabled": bool(getattr(config, "rag_enabled", True)),
        "embedder": str(getattr(config, "rag_embedder", "local") or "local"),
        "base_url": str(getattr(config, "rag_base_url", "") or ""),
        "api_key": str(getattr(config, "rag_api_key", "") or ""),
        "model": str(getattr(config, "rag_model", "") or ""),
        "dimensions": int(getattr(config, "rag_dimensions", 512) or 512),
        "timeout_seconds": float(getattr(config, "rag_timeout_seconds", 30.0) or 30.0),
        "vector_store": vector_store,
    }


def resolve_embedder(session: Session) -> Embedder:
    """Pick the configured embedder, falling back to local when remote is incomplete.

    A half-configured remote embedder (URL but no key) silently falling back to local is the
    right call here: an unusable index is worse than a lexical one, and the settings dialog
    already surfaces configuration state.

    When ``embedder=remote`` is fully configured, prefer LangChain's OpenAI-compatible client
    if the optional ``rag`` extra is installed; otherwise keep the httpx :class:`RemoteEmbedder`.
    """

    config = rag_settings(session)
    if not config["enabled"]:
        raise RagUnavailable("rag_disabled")
    remote_ready = all(config[key] for key in ("base_url", "api_key", "model"))
    if config["embedder"] == "remote" and remote_ready:
        dimensions = config["dimensions"] if config["dimensions"] != 512 else 0
        if langchain_available():
            return LangChainRemoteEmbedder(
                config["base_url"],
                config["api_key"],
                config["model"],
                config["timeout_seconds"],
                dimensions,
            )
        return RemoteEmbedder(
            config["base_url"],
            config["api_key"],
            config["model"],
            config["timeout_seconds"],
            dimensions,
        )
    return LocalHashingEmbedder(config["dimensions"])


def resolve_vector_store(session: Session) -> VectorStore:
    """Return the configured vector backend, or raise with a stable reason code."""

    config = rag_settings(session)
    if config["vector_store"] == "lancedb":
        if not lancedb_available():
            raise RagUnavailable("rag_vector_deps_missing")
        return LanceDbStore()
    return SqliteExactStore(session)


def _latest_paper(session: Session, project_id: int) -> PaperDocument | None:
    return session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()


def _latest_repository(session: Session, project_id: int) -> CodeRepository | None:
    return session.exec(
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    ).first()


def _reviewed_links(session: Session, project_id: int) -> list[TraceLink]:
    return list(
        session.exec(
            select(TraceLink)
            .where(TraceLink.project_id == project_id)
            .where(TraceLink.status.in_(REVIEWED_STATUSES))
            .order_by(TraceLink.updated_at.desc())
        ).all()
    )


def _source_key(session: Session, project_id: int, scope: str) -> tuple[str, Any]:
    """Current generation key for a scope, plus the source object the chunker needs."""

    if scope == "paper":
        paper = _latest_paper(session, project_id)
        if paper is None or paper.parse_status != "succeeded":
            return "", None
        key = paper.content_hash or f"paper:{paper.id}:{paper.created_at.isoformat()}"
        return key[:128], paper
    if scope == "code":
        repository = _latest_repository(session, project_id)
        if repository is None or repository.analysis_status != "succeeded":
            return "", None
        return f"{repository.id}:{repository.analysis_revision}", repository
    links = _reviewed_links(session, project_id)
    if not links:
        return "", []
    digest = hashlib.blake2b(
        "\x00".join(f"{link.trace_id}:{link.status}" for link in links).encode(),
        digest_size=16,
    ).hexdigest()
    return digest, links


def _state(session: Session, project_id: int, scope: str) -> RagIndexState:
    state = session.exec(
        select(RagIndexState)
        .where(RagIndexState.project_id == project_id)
        .where(RagIndexState.scope == scope)
    ).first()
    if state is None:
        state = RagIndexState(project_id=project_id, scope=scope)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def _source_reader(repository: CodeRepository) -> Any:
    from app.services.agent.analysis_tools import _read_file

    def read(path: str, line_start: int, line_end: int) -> str:
        lines = _read_file(repository, path).splitlines()
        end = min(len(lines), max(line_start, line_end))
        return "\n".join(lines[max(0, line_start - 1) : end])[:1600]

    return read


def _collect_chunks(scope: str, source: Any) -> list[dict[str, Any]]:
    if scope == "paper":
        return paper_chunks(source)
    if scope == "code":
        return code_chunks(source, _source_reader(source))
    return trace_chunks(source)


def _clear_scope_stores(session: Session, project_id: int, scope: str) -> None:
    """Drop both backends for a scope so a switch cannot leave a stale generation behind."""

    SqliteExactStore(session).delete_scope(project_id, scope)
    if lancedb_available():
        try:
            LanceDbStore().delete_scope(project_id, scope)
        except Exception:  # noqa: BLE001 - clearing is best-effort
            logger.exception("rag lance clear failed for project %s scope %s", project_id, scope)


def build_index(
    session: Session,
    project_id: int,
    scope: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Embed and persist every chunk for one scope. Idempotent and safe to call often."""

    if scope not in SCOPES:
        raise RagUnavailable("rag_unknown_scope")
    settings_snapshot = rag_settings(session)
    if not settings_snapshot["enabled"]:
        return {"scope": scope, "status": "disabled", "chunk_count": 0}

    with _build_lock(project_id, scope):
        source_key, source = _source_key(session, project_id, scope)
        state = _state(session, project_id, scope)
        if not source_key:
            # Source not ready (or no reviewed traces yet). Drop any stale generation so a
            # search cannot answer from an index whose source has gone away.
            if state.chunk_count:
                _clear_scope_stores(session, project_id, scope)
                state.chunk_count = 0
            state.status = "pending"
            state.source_key = ""
            state.updated_at = utc_now()
            session.add(state)
            session.commit()
            return {"scope": scope, "status": "pending", "chunk_count": 0}

        try:
            embedder = resolve_embedder(session)
            store = resolve_vector_store(session)
        except RagUnavailable as exc:
            return {"scope": scope, "status": "disabled", "chunk_count": 0, "reason": exc.reason}

        current = (
            state.status == "ready"
            and state.source_key == source_key
            and state.embedder == embedder.name
            and state.model == embedder.model
            and state.chunk_count > 0
        )
        if current and not force:
            return {
                "scope": scope,
                "status": "ready",
                "chunk_count": state.chunk_count,
                "reused": True,
            }

        chunks = _collect_chunks(scope, source)[: MAX_CHUNKS[scope]]
        if not chunks:
            store.delete_scope(project_id, scope)
            # Avoid leaving the alternate backend with a previous generation.
            if settings_snapshot["vector_store"] == "lancedb":
                SqliteExactStore(session).delete_scope(project_id, scope)
            elif lancedb_available():
                LanceDbStore().delete_scope(project_id, scope)
            state.status = "ready"
            state.source_key = source_key
            state.chunk_count = 0
            state.embedder = embedder.name
            state.model = embedder.model
            state.error = None
            state.built_at = utc_now()
            state.updated_at = utc_now()
            session.add(state)
            session.commit()
            return {"scope": scope, "status": "ready", "chunk_count": 0}

        state.status = "building"
        state.updated_at = utc_now()
        session.add(state)
        session.commit()

        try:
            vectors = embedder.embed([chunk["text"] for chunk in chunks])
        except EmbeddingError as exc:
            state.status = "failed"
            state.error = exc.reason[:500]
            state.updated_at = utc_now()
            session.add(state)
            session.commit()
            logger.warning("rag %s index failed for project %s: %s", scope, project_id, exc.reason)
            return {"scope": scope, "status": "failed", "chunk_count": 0, "reason": exc.reason}

        rows = [
            {
                "ref": chunk["ref"],
                "text": chunk["text"],
                "vector": vector,
                "metadata": chunk.get("metadata", {}),
                "embedder": embedder.name,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            # LanceDB path must not duplicate embeddings into SQLite; clear the other backend.
            if settings_snapshot["vector_store"] == "lancedb":
                SqliteExactStore(session).delete_scope(project_id, scope)
            elif lancedb_available():
                LanceDbStore().delete_scope(project_id, scope)
            store.replace(project_id, scope, source_key, rows)
        except VectorStoreError as exc:
            state.status = "failed"
            state.error = exc.reason[:500]
            state.updated_at = utc_now()
            session.add(state)
            session.commit()
            logger.warning(
                "rag %s store failed for project %s: %s", scope, project_id, exc.reason
            )
            return {"scope": scope, "status": "failed", "chunk_count": 0, "reason": exc.reason}

        dimensions = len(vectors[0]) if vectors else 0
        state.status = "ready"
        state.source_key = source_key
        state.embedder = embedder.name
        state.model = embedder.model
        state.dimensions = dimensions
        state.chunk_count = len(chunks)
        state.error = None
        state.built_at = utc_now()
        state.updated_at = utc_now()
        session.add(state)
        session.commit()
        return {"scope": scope, "status": "ready", "chunk_count": len(chunks)}


def search(
    session: Session,
    project_id: int,
    scope: str,
    query: str,
    *,
    limit: int = 5,
    auto_build: bool = True,
) -> dict[str, Any]:
    """Cosine-rank chunks in one scope against ``query``.

    Returns ``{"ok": bool, "items": [...]}``. ``ok=False`` carries a ``reason`` instead of
    raising so agent tool wrappers can hand the model an actionable message.
    """

    if scope not in SCOPES:
        return {"ok": False, "reason": "rag_unknown_scope", "items": []}
    query = query.strip()
    if not query:
        return {"ok": False, "reason": "rag_empty_query", "items": []}
    if not rag_settings(session)["enabled"]:
        return {"ok": False, "reason": "rag_disabled", "items": []}

    try:
        # Surface configuration/deps failures before treating an empty index as "no corpus".
        resolve_vector_store(session)
    except RagUnavailable as exc:
        return {"ok": False, "reason": exc.reason, "items": []}

    state = _state(session, project_id, scope)
    if auto_build and state.status != "ready":
        built = build_index(session, project_id, scope)
        if built.get("reason") and built.get("status") in {"disabled", "failed"}:
            return {"ok": False, "reason": str(built["reason"]), "items": []}
        state = _state(session, project_id, scope)
    if state.status == "failed":
        return {"ok": False, "reason": state.error or "rag_index_failed", "items": []}
    if state.status != "ready" or state.chunk_count == 0:
        return {"ok": False, "reason": "rag_index_empty", "items": []}

    try:
        embedder = resolve_embedder(session)
        store = resolve_vector_store(session)
        query_vector = embedder.embed([query])[0]
        items = store.query(project_id, scope, state.source_key, query_vector, limit)
    except (RagUnavailable, EmbeddingError, VectorStoreError) as exc:
        return {"ok": False, "reason": getattr(exc, "reason", "rag_unavailable"), "items": []}

    return {
        "ok": True,
        "query": query,
        "scope": scope,
        "embedder": f"{embedder.name}:{embedder.model}",
        "items": items,
        "searched": state.chunk_count,
    }


def index_status(session: Session, project_id: int) -> dict[str, Any]:
    config = rag_settings(session)
    scopes: list[dict[str, Any]] = []
    for scope in SCOPES:
        state = _state(session, project_id, scope)
        scopes.append(
            {
                "scope": scope,
                "status": state.status,
                "chunk_count": state.chunk_count,
                "embedder": state.embedder,
                "model": state.model,
                "dimensions": state.dimensions,
                "error": state.error,
                "built_at": state.built_at,
            }
        )
    return {
        "enabled": config["enabled"],
        "embedder": config["embedder"],
        "model": config["model"] if config["embedder"] == "remote" else "local-hashing",
        "vector_store": config["vector_store"],
        "scopes": scopes,
    }


def refresh_project_indexes(project_id: int, scopes: tuple[str, ...] = SCOPES) -> None:
    """Best-effort background rebuild for completion hooks. Never raises.

    Opens its own session against the module-level engine, mirroring the other background
    hooks in this codebase (and letting tests rebind ``engine`` the same way).
    """

    from app.db.session import engine

    try:
        with Session(engine) as session:
            if not rag_settings(session)["enabled"]:
                return
            for scope in scopes:
                try:
                    build_index(session, project_id, scope)
                except Exception:  # noqa: BLE001 - a hook must not break its caller
                    logger.exception("rag %s index build failed for project %s", scope, project_id)
    except Exception:  # noqa: BLE001
        logger.exception("rag index refresh failed for project %s", project_id)


def invalidate(session: Session, project_id: int, scope: str) -> None:
    """Mark a scope stale so the next search rebuilds it."""

    try:
        state = _state(session, project_id, scope)
        state.status = "pending"
        state.updated_at = utc_now()
        session.add(state)
        session.commit()
    except Exception:  # noqa: BLE001 - invalidation is advisory
        logger.exception("rag invalidate failed for project %s scope %s", project_id, scope)


def trace_examples(
    session: Session,
    project_id: int,
    query: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Recall reviewed trace cases similar to ``query`` for few-shot prompting."""

    result = search(session, project_id, "trace", query, limit=limit)
    if not result.get("ok"):
        return []
    return [
        {
            "status": item.get("status"),
            "relation_type": item.get("relation_type"),
            "paper_quote": item.get("paper_quote", ""),
            "code_ref": item.get("code_ref", ""),
            "code_quote": item.get("code_quote", ""),
            "rationale": item.get("rationale", ""),
            "score": item.get("score"),
        }
        for item in result.get("items", [])
    ]
