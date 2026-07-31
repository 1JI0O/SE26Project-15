"""Pluggable vector stores for the retrieval layer.

Two backends, one interface:

* :class:`SqliteExactStore` — the default. Persists base64 float32 vectors in ``rag_chunk``
  and ranks with an exact in-Python cosine scan. No optional dependencies.
* :class:`LanceDbStore` — optional LanceDB ANN index under ``data/rag-lancedb/``. Loaded only
  when ``rag_vector_store=lancedb`` and the ``rag`` extra is installed; otherwise the service
  surfaces ``rag_vector_deps_missing`` rather than crashing the agent.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from sqlmodel import Session, delete, select

from app.models.entities import RagChunk, utc_now
from app.services.rag.embeddings import cosine, decode_vector, encode_vector

logger = logging.getLogger(__name__)

TABLE_NAME = "chunks"


class VectorStoreError(RuntimeError):
    """Raised when a vector backend cannot complete a replace/query."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class VectorStore(Protocol):
    """Minimal persistence surface used by ``build_index`` / ``search``."""

    def replace(
        self,
        project_id: int,
        scope: str,
        source_key: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> None: ...

    def query(
        self,
        project_id: int,
        scope: str,
        source_key: str,
        vector: list[float],
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def delete_scope(self, project_id: int, scope: str) -> None: ...


def lancedb_available() -> bool:
    try:
        import lancedb  # noqa: F401
    except ImportError:
        return False
    return True


def default_lancedb_root() -> Path:
    """On-disk root for LanceDB tables: ``./data/rag-lancedb`` next to the SQLite DB."""

    from app.core.config import settings

    url = settings.database_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        # In-memory / relative ``./data/workbench.db`` → sibling ``rag-lancedb``.
        parent = db_path.parent
        if str(parent) not in {"", "."}:
            return parent / "rag-lancedb"
    return Path("data") / "rag-lancedb"


def _hit_from_parts(
    *,
    ref: str,
    text: str,
    score: float,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    preview = str(meta.get("preview") or text)[:1200]
    return {
        "ref": ref,
        "score": round(score, 4),
        "text": preview,
        **{key: value for key, value in meta.items() if key != "preview"},
    }


def _dedupe_hits(
    scored: list[tuple[float, str, str, Mapping[str, Any]]],
    limit: int,
) -> list[dict[str, Any]]:
    """One hit per ``ref``, highest score wins — mirrors the historical SQLite scan."""

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, ref, text, metadata in scored:
        if score <= 0 or ref in seen:
            continue
        seen.add(ref)
        items.append(_hit_from_parts(ref=ref, text=text, score=score, metadata=metadata))
        if len(items) >= max(1, limit):
            break
    return items


class SqliteExactStore:
    """Exact cosine scan over ``rag_chunk`` rows for one SQLModel session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(
        self,
        project_id: int,
        scope: str,
        source_key: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self.delete_scope(project_id, scope)
        for row in rows:
            vector = list(row["vector"])
            self._session.add(
                RagChunk(
                    project_id=project_id,
                    scope=scope,
                    source_key=source_key,
                    ref=str(row["ref"])[:500],
                    text=str(row["text"]),
                    embedding=encode_vector(vector),
                    dimensions=len(vector),
                    embedder=str(row.get("embedder") or "local")[:64],
                    token_count=len(str(row["text"])) // 4,
                    metadata_json=dict(row.get("metadata") or {}),
                    created_at=utc_now(),
                )
            )
        self._session.commit()

    def query(
        self,
        project_id: int,
        scope: str,
        source_key: str,
        vector: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = list(
            self._session.exec(
                select(RagChunk)
                .where(RagChunk.project_id == project_id)
                .where(RagChunk.scope == scope)
                .where(RagChunk.source_key == source_key)
            ).all()
        )
        scored: list[tuple[float, str, str, Mapping[str, Any]]] = []
        for row in rows:
            score = cosine(vector, decode_vector(row.embedding))
            scored.append((score, row.ref, row.text, row.metadata_json or {}))
        scored.sort(key=lambda item: item[0], reverse=True)
        return _dedupe_hits(scored, limit)

    def delete_scope(self, project_id: int, scope: str) -> None:
        self._session.exec(
            delete(RagChunk).where(RagChunk.project_id == project_id).where(RagChunk.scope == scope)
        )
        self._session.commit()


class LanceDbStore:
    """One LanceDB directory per ``(project_id, scope)``; table rewritten on every replace."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_lancedb_root()

    def _scope_dir(self, project_id: int, scope: str) -> Path:
        return self.root / str(project_id) / scope

    def _connect(self, project_id: int, scope: str) -> Any:
        try:
            import lancedb
        except ImportError as exc:
            raise VectorStoreError("rag_vector_deps_missing") from exc
        path = self._scope_dir(project_id, scope)
        path.mkdir(parents=True, exist_ok=True)
        return lancedb.connect(str(path))

    def replace(
        self,
        project_id: int,
        scope: str,
        source_key: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        if not rows:
            self.delete_scope(project_id, scope)
            return
        db = self._connect(project_id, scope)
        payload = [
            {
                "ref": str(row["ref"])[:500],
                "text": str(row["text"]),
                "vector": [float(value) for value in row["vector"]],
                "source_key": source_key,
                "metadata": dict(row.get("metadata") or {}),
            }
            for row in rows
        ]
        try:
            db.create_table(TABLE_NAME, data=payload, mode="overwrite")
        except Exception as exc:  # noqa: BLE001 - surface as a stable reason
            logger.warning("lancedb replace failed for %s/%s: %s", project_id, scope, exc)
            raise VectorStoreError("rag_vector_store_failed") from exc

    def query(
        self,
        project_id: int,
        scope: str,
        source_key: str,
        vector: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        path = self._scope_dir(project_id, scope)
        if not path.exists():
            return []
        db = self._connect(project_id, scope)
        try:
            names = set(db.table_names())
        except Exception as exc:  # noqa: BLE001
            raise VectorStoreError("rag_vector_store_failed") from exc
        if TABLE_NAME not in names:
            return []
        try:
            table = db.open_table(TABLE_NAME)
            # Over-fetch so overlapping windows of the same ``ref`` can be collapsed.
            fetch = max(limit * 4, limit, 16)
            escaped = source_key.replace("'", "''")
            raw = (
                table.search(vector)
                .metric("cosine")
                .where(f"source_key = '{escaped}'", prefilter=True)
                .limit(fetch)
                .to_list()
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("lancedb query failed for %s/%s: %s", project_id, scope, exc)
            raise VectorStoreError("rag_vector_store_failed") from exc

        scored: list[tuple[float, str, str, Mapping[str, Any]]] = []
        for item in raw:
            distance = float(item.get("_distance", 1.0))
            # Cosine distance ∈ [0, 2]; for L2-normalized vectors similarity ≈ 1 - distance.
            score = max(0.0, 1.0 - distance)
            metadata = item.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            scored.append(
                (score, str(item.get("ref") or ""), str(item.get("text") or ""), metadata)
            )
        scored.sort(key=lambda entry: entry[0], reverse=True)
        return _dedupe_hits(scored, limit)

    def delete_scope(self, project_id: int, scope: str) -> None:
        path = self._scope_dir(project_id, scope)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
