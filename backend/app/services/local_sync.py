from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from app.models.cloud_entities import LocalSyncOutbox, LocalSyncState
from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink


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
        payload_json=payload,
    )
    session.add(item)
    return item


def project_payload(project: Project) -> dict[str, Any]:
    return {
        "name": project.name,
        "description": project.description,
        "agent_history_sync": project.agent_history_sync,
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
    return {
        "project_public_id": project.public_id,
        "filename": repository.filename,
        "revision": repository.revision,
        "blob_id": repository.blob_id,
        "requires_blob": repository.blob_id is None,
    }


def trace_payload(project: Project, link: TraceLink) -> dict[str, Any]:
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
    }


def agent_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= 32 * 1024:
        return payload
    return {
        "summary": "large local run event omitted from sync",
        "keys": sorted(str(key) for key in payload)[:50],
        "truncated": True,
    }
