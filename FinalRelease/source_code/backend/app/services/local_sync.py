from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from app.models.entities import (
    CodeRepository,
    CodeTarget,
    PaperDocument,
    PaperTarget,
    Project,
    TraceLink,
)
from app.models.sync import LocalSyncOutbox, LocalSyncState

# Canonical mirror of the cloud server's cloud_sync.FORBIDDEN_SYNC_KEYS
# (server/tracelab_server/services/cloud_sync.py). The server recursively rejects
# any sync push whose payload contains one of these keys (or a key ending in
# "_api_key") with HTTP 422. Agent operation payloads embed arbitrary runtime
# data (tool results, run-event payloads, message metadata) that can carry local
# paths / secrets, so we strip these keys client-side BEFORE they ever reach the
# outbox/push — both to unblock sync and to keep device-local secrets off the
# cloud. Keep this set in sync with the server definition; the drift test in
# backend/tests guards against regressions.
FORBIDDEN_SYNC_KEYS = {
    "storage_path",
    "absolute_path",
    "local_path",
    "api_key",
    "llm_api_key",
    "mineru_api_key",
    "refresh_token",
    "access_token",
    "secret",
    "_upload_content",
}


def scrub_forbidden_keys(value: Any) -> Any:
    """Recursively drop forbidden keys, returning a new structure.

    Mirrors the server's ``_validate_sync_payload`` rule (casefolded membership in
    ``FORBIDDEN_SYNC_KEYS`` or ``endswith("_api_key")``). Pure and non-mutating:
    it must not alter the ORM-derived dicts handed to ``record_local_operation``.
    """
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_SYNC_KEYS or normalized.endswith("_api_key"):
                continue
            cleaned[key] = scrub_forbidden_keys(child)
        return cleaned
    if isinstance(value, list):
        return [scrub_forbidden_keys(child) for child in value]
    return value


def _state(session: Session, project: Project) -> LocalSyncState | None:
    if not project.cloud_workspace_id:
        return None
    return session.get(LocalSyncState, project.cloud_workspace_id)


def record_local_operation(
    session: Session,
    project: Project,
    entity_type: str,
    entity_public_id: str,
    payload: dict[str, Any],
    *,
    operation: str = "upsert",
    base_version: int = 0,
) -> LocalSyncOutbox | None:
    if project.sync_mode != "cloud_enabled" or not project.cloud_workspace_id:
        return None
    state = _state(session, project)
    if state is None:
        return None
    item = LocalSyncOutbox(
        workspace_id=project.cloud_workspace_id,
        device_id=state.device_id,
        entity_type=entity_type,
        entity_public_id=entity_public_id,
        operation=operation,
        base_version=base_version,
        payload_json=scrub_forbidden_keys(payload),
    )
    session.add(item)
    return item


def project_payload(project: Project) -> dict[str, Any]:
    return {
        "name": project.name,
        "description": project.description,
        "agent_history_sync": project.agent_history_sync,
        "agent_deep_thinking": project.agent_deep_thinking,
    }


def paper_payload(project: Project, document: PaperDocument) -> dict[str, Any]:
    return {
        "project_public_id": project.public_id,
        "filename": document.filename,
        "title": document.title,
        "abstract": document.abstract,
        "parser": document.parser,
        "parser_version": document.parser_version,
        "content_hash": document.content_hash,
        "blob_id": document.blob_id,
        "requires_blob": document.blob_id is None,
    }


def repository_payload(project: Project, repository: CodeRepository) -> dict[str, Any]:
    # The locally generated flow diagram (tensor graph + architecture analysis) can be
    # hundreds of KB — far above the 64KB sync-event cap — so it travels as a
    # dedicated diagram blob rather than inline. ``requires_diagram_blob`` tells
    # the client to upload it and replace the marker with ``diagram_blob_id``.
    has_diagram = bool(
        (repository.tensor_graph_json or {}).get("nodes") or repository.analysis_json
    )
    return {
        "project_public_id": project.public_id,
        "filename": repository.filename,
        "revision": repository.revision,
        "blob_id": repository.blob_id,
        "requires_blob": repository.blob_id is None,
        "analysis_status": repository.analysis_status,
        "analysis_version": repository.analysis_version,
        "requires_diagram_blob": has_diagram,
    }


def trace_payload(project: Project, link: TraceLink, *, session: Session) -> dict[str, Any]:
    """Serialize a TraceLink for sync, including its scoring and provenance.

    The original payload carried only the eight fields the first sync release knew about.
    Everything the agentic deep-tracing work added — relevance, the confidence split,
    uncertainty, model info, score basis and provenance — was silently dropped, so a
    downloaded relation arrived with ``relevance=0`` and ``source="static"`` and the
    workbench ranked and labelled it wrong.

    Target references travel as **public ids**: ``paper_target_id`` / ``code_target_id``
    hold device-local primary keys (``ptarget-<hex>``) that mean nothing on another
    install. The importer maps them back through the target's public id.
    """

    return {
        "project_public_id": project.public_id,
        "trace_id": link.trace_id,
        "paper_ref": link.paper_ref,
        "code_ref": link.code_ref,
        "code_revision": link.code_revision,
        "relation_type": link.relation_type,
        "confidence": link.confidence,
        "evidence": link.evidence_json,
        "rationale": link.rationale,
        "status": link.status,
        "relevance": link.relevance,
        "source": link.source,
        "static_confidence": link.static_confidence,
        "llm_confidence": link.llm_confidence,
        "uncertainty": link.uncertainty_json,
        "model_info": link.model_info_json,
        "score_basis": link.score_basis_json,
        "provenance": link.provenance_json,
        "stale_reason": link.stale_reason,
        "supersedes_trace_id": link.supersedes_trace_id,
        "fingerprint": link.fingerprint,
        # Opaque origin provenance. The artifact chain (job/run/artifact) is not synced, and
        # SQLite foreign keys are not enforced, so this is carried for traceability only —
        # nothing joins on it.
        "artifact_id": link.artifact_id,
        "paper_target_public_id": _target_public_id(session, PaperTarget, link.paper_target_id),
        "code_target_public_id": _target_public_id(session, CodeTarget, link.code_target_id),
        # Which paper/repository this relation belongs to. Without these the importer left
        # both foreign keys null and could only guess "the latest one in the project".
        "paper_document_public_id": _row_public_id(session, PaperDocument, link.paper_document_id),
        "code_repository_public_id": _row_public_id(
            session, CodeRepository, link.code_repository_id
        ),
    }


def _row_public_id(session: Session, model: Any, row_id: int | None) -> str | None:
    if row_id is None:
        return None
    row = session.get(model, row_id)
    return row.public_id if row is not None else None


def _target_public_id(session: Session, model: Any, target_id: str | None) -> str | None:
    if not target_id:
        return None
    row = session.get(model, target_id)
    return row.public_id if row is not None else None


def paper_target_payload(
    project: Project, target: PaperTarget, *, session: Session
) -> dict[str, Any]:
    """Serialize a paper anchor. Identity is the fingerprint, not the local target_id.

    ``block_id`` is only a navigation hint (MinerU block ids drift across re-parses), so the
    importer re-anchors on section_path + quote + occurrence + quote_hash.
    """

    return {
        "project_public_id": project.public_id,
        "paper_document_public_id": _row_public_id(
            session, PaperDocument, target.paper_document_id
        ),
        "target_type": target.target_type,
        "block_id": target.block_id,
        "section_path": target.section_path_json,
        "quote": target.quote,
        "occurrence": target.occurrence,
        "char_start": target.char_start,
        "char_end": target.char_end,
        "quote_hash": target.quote_hash,
        "bbox": target.bbox_json,
        "asset_path": target.asset_path,
        "salience": target.salience,
        "salience_reason": target.salience_reason,
        "anchor_status": target.anchor_status,
        "fingerprint": target.fingerprint,
        "artifact_id": target.artifact_id,
    }


def code_target_payload(
    project: Project, target: CodeTarget, *, session: Session
) -> dict[str, Any]:
    """Serialize a code anchor. Line numbers are a search window, not identity."""

    return {
        "project_public_id": project.public_id,
        "code_repository_public_id": _row_public_id(
            session, CodeRepository, target.code_repository_id
        ),
        "code_revision": target.code_revision,
        "path": target.path,
        "symbol_id": target.symbol_id,
        "line_start": target.line_start,
        "line_end": target.line_end,
        "column_start": target.column_start,
        "column_end": target.column_end,
        "quote": target.quote,
        "occurrence": target.occurrence,
        "code_quote_hash": target.code_quote_hash,
        "role": target.role,
        "salience": target.salience,
        "salience_reason": target.salience_reason,
        "anchor_status": target.anchor_status,
        "fingerprint": target.fingerprint,
        "artifact_id": target.artifact_id,
    }


def agent_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= 32 * 1024:
        return payload
    return {
        "summary": "large local run event omitted from sync",
        "keys": sorted(str(key) for key in payload)[:50],
        "truncated": True,
    }
