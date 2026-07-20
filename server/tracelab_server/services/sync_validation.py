from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException

from tracelab_server.schemas.cloud import SyncOperation

REQUIRED_UPSERT_FIELDS = {
    "paper_document": {"filename"},
    "code_repository": {"filename"},
    "code_edit": {"path", "repository_public_id", "blob_id"},
    "trace_link": {"paper_ref", "code_ref", "status"},
    "agent_conversation": {"title"},
    "agent_message": {"conversation_public_id", "role"},
    "agent_run": {"conversation_public_id", "status"},
    "agent_run_event": {"run_public_id", "event_type"},
    "agent_memory": {"kind"},
}
ALLOWED_TRACE_STATUSES = {"pending", "accepted", "rejected", "stale"}
ALLOWED_MESSAGE_ROLES = {"user", "assistant", "system", "tool"}


def _require_uuid(value: object, field: str) -> None:
    try:
        UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be a UUID") from exc


def validate_domain_operation(operation: SyncOperation) -> None:
    """Validate the bounded sync envelope before touching the generic replica table."""
    if operation.entity_type == "project" or operation.operation != "upsert":
        return
    required = REQUIRED_UPSERT_FIELDS[operation.entity_type]
    missing = sorted(field for field in required if operation.payload.get(field) is None)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required fields: {', '.join(missing)}",
        )
    _require_uuid(operation.payload.get("project_public_id"), "project_public_id")
    if "blob_id" in operation.payload and operation.payload["blob_id"] is not None:
        _require_uuid(operation.payload["blob_id"], "blob_id")
    if operation.entity_type == "trace_link":
        status = operation.payload.get("status")
        if status not in ALLOWED_TRACE_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid TraceLink status")
    if operation.entity_type == "agent_message":
        role = operation.payload.get("role")
        if role not in ALLOWED_MESSAGE_ROLES:
            raise HTTPException(status_code=422, detail="Invalid Agent message role")
