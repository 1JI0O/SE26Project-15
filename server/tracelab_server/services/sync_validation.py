from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException

from tracelab_server.schemas.cloud import SyncOperation

logger = logging.getLogger(__name__)

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
# Mirror of the shared TraceStatus contract: {proposed, accepted, rejected, stale}.
# "proposed" is the initial status of a freshly generated link.
# "pending" is retained only for backward compatibility with any older data.
ALLOWED_TRACE_STATUSES = {"proposed", "pending", "accepted", "rejected", "stale"}
ALLOWED_MESSAGE_ROLES = {"user", "assistant", "system", "tool"}


def _reject(operation: SyncOperation, detail: str) -> HTTPException:
    """Log a bounded-envelope rejection (no payload values) and build the 422."""
    logger.warning(
        "sync push rejected: %s (%s op, client_operation_id=%s)",
        detail,
        operation.entity_type,
        operation.client_operation_id,
    )
    return HTTPException(status_code=422, detail=detail)


def _require_uuid(operation: SyncOperation, value: object, field: str) -> None:
    try:
        UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _reject(operation, f"{field} must be a UUID") from exc


def validate_domain_operation(operation: SyncOperation) -> None:
    """Validate the bounded sync envelope before touching the generic replica table."""
    if operation.entity_type == "project" or operation.operation != "upsert":
        return
    required = REQUIRED_UPSERT_FIELDS[operation.entity_type]
    missing = sorted(field for field in required if operation.payload.get(field) is None)
    if missing:
        raise _reject(operation, f"Missing required fields: {', '.join(missing)}")
    _require_uuid(operation, operation.payload.get("project_public_id"), "project_public_id")
    if "blob_id" in operation.payload and operation.payload["blob_id"] is not None:
        _require_uuid(operation, operation.payload["blob_id"], "blob_id")
    if operation.entity_type == "trace_link":
        status = operation.payload.get("status")
        if status not in ALLOWED_TRACE_STATUSES:
            raise _reject(operation, "Invalid TraceLink status")
    if operation.entity_type == "agent_message":
        role = operation.payload.get("role")
        if role not in ALLOWED_MESSAGE_ROLES:
            raise _reject(operation, "Invalid Agent message role")
