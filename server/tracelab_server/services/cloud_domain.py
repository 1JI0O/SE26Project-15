from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session, select

from tracelab_server.auth.dependencies import CurrentIdentity
from tracelab_server.models.cloud_entities import CloudProject, DeviceProjectBinding
from tracelab_server.schemas.cloud import SyncEntityType, SyncOperation
from tracelab_server.services.cloud_sync import apply_operation

SUPPORTED_ENTITY_TYPES = {
    "paper_document",
    "code_repository",
    "code_edit",
    "trace_link",
    "agent_conversation",
    "agent_message",
    "agent_run",
    "agent_run_event",
    "agent_memory",
}
REQUIRED_FIELDS = {
    "paper_document": {"filename", "blob_id"},
    "code_repository": {"filename", "blob_id"},
    "code_edit": {"path", "blob_id", "repository_public_id"},
    "trace_link": {"paper_ref", "code_ref", "status"},
    "agent_conversation": {"title"},
    "agent_message": {"conversation_public_id", "role"},
    "agent_run": {"conversation_public_id", "status"},
    "agent_run_event": {"run_public_id", "event_type"},
    "agent_memory": {"kind"},
}


def ensure_project_device_binding(
    session: Session,
    identity: CurrentIdentity,
    project: CloudProject,
) -> DeviceProjectBinding:
    binding = session.exec(
        select(DeviceProjectBinding).where(
            DeviceProjectBinding.device_id == identity.device_id,
            DeviceProjectBinding.project_public_id == project.public_id,
        )
    ).first()
    if binding is None:
        binding = DeviceProjectBinding(
            device_id=identity.device_id,
            workspace_id=project.workspace_id,
            project_public_id=project.public_id,
            sync_mode="cloud_enabled",
        )
        session.add(binding)
        session.commit()
    if binding.sync_mode != "cloud_enabled":
        raise HTTPException(status_code=409, detail="This device has paused project sync")
    return binding


def execute_cloud_entity_command(
    session: Session,
    identity: CurrentIdentity,
    project: CloudProject,
    entity_type: SyncEntityType,
    entity_public_id: str,
    operation: str,
    base_version: int,
    payload: dict,
    *,
    supersedes_operation_id: str | None = None,
):
    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported cloud entity type")
    ensure_project_device_binding(session, identity, project)
    command_payload = {**payload, "project_public_id": project.public_id}
    if operation == "upsert":
        missing = REQUIRED_FIELDS[entity_type] - command_payload.keys()
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required fields: {', '.join(sorted(missing))}",
            )
    return apply_operation(
        session,
        identity,
        SyncOperation(
            workspace_id=project.workspace_id,
            device_id=identity.device_id,
            client_operation_id=str(uuid4()),
            supersedes_operation_id=supersedes_operation_id,
            entity_type=entity_type,
            entity_public_id=entity_public_id,
            operation=operation,
            base_version=base_version,
            payload=command_payload,
        ),
    )
