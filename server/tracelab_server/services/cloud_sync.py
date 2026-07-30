from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from tracelab_server.api.routes.cloud_access import require_workspace_access
from tracelab_server.auth.dependencies import CurrentIdentity
from tracelab_server.core.config import settings
from tracelab_server.models.cloud_entities import (
    ArtifactVersion,
    AuditLog,
    BlobObject,
    BlobReference,
    CloudEntity,
    CloudProject,
    Device,
    DeviceProjectBinding,
    EntityTombstone,
    SyncEvent,
    SyncReceipt,
    Workspace,
)
from tracelab_server.models.entities import utc_now
from tracelab_server.schemas.cloud import SyncOperation, SyncOperationResult
from tracelab_server.services.sync_validation import validate_domain_operation

logger = logging.getLogger(__name__)

APPEND_ONLY_TYPES = {"agent_message", "agent_run_event"}
ARTIFACT_TYPES = {"paper_document", "code_repository", "code_edit", "artifact_version"}
PROJECT_FIELDS = {"name", "description", "agent_history_sync"}
MAX_EVENT_PAYLOAD_BYTES = 64 * 1024
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


def _project_blob_usage(session: Session, workspace_id: str, project_id: str) -> int:
    blob_ids = set(
        session.exec(
            select(BlobReference.blob_id).where(
                BlobReference.workspace_id == workspace_id,
                BlobReference.project_public_id == project_id,
                BlobReference.deleted_at.is_(None),
            )
        ).all()
    )
    return sum(
        blob.byte_size
        for blob_id in blob_ids
        if (blob := session.get(BlobObject, blob_id)) is not None and blob.status == "ready"
    )


def _find_forbidden_key(value: object) -> str | None:
    """Return the first forbidden key found (name only), or None. Never returns values."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_SYNC_KEYS or normalized.endswith("_api_key"):
                return str(key)
            nested = _find_forbidden_key(child)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _find_forbidden_key(child)
            if nested is not None:
                return nested
    return None


def _apply_blob_reference_change(
    session: Session,
    operation: SyncOperation,
    previous_payload: dict | None,
) -> None:
    old_blob_id = previous_payload.get("blob_id") if previous_payload else None
    new_blob_id = None if operation.operation == "delete" else operation.payload.get("blob_id")
    if old_blob_id == new_blob_id:
        return
    project_id = operation.payload.get("project_public_id") or (
        previous_payload.get("project_public_id") if previous_payload else None
    )
    if not isinstance(project_id, str):
        raise HTTPException(status_code=422, detail="project_public_id is required")
    if operation.operation == "delete" and operation.entity_type in ARTIFACT_TYPES:
        references = session.exec(
            select(BlobReference).where(
                BlobReference.workspace_id == operation.workspace_id,
                BlobReference.project_public_id == project_id,
                BlobReference.entity_type == operation.entity_type,
                BlobReference.entity_public_id == operation.entity_public_id,
                BlobReference.deleted_at.is_(None),
            )
        ).all()
        for reference in references:
            blob = session.get(BlobObject, reference.blob_id)
            if blob is not None:
                blob.reference_count = max(0, blob.reference_count - 1)
                session.add(blob)
            reference.deleted_at = utc_now()
            session.add(reference)
        versions = session.exec(
            select(ArtifactVersion).where(
                ArtifactVersion.workspace_id == operation.workspace_id,
                ArtifactVersion.entity_type == operation.entity_type,
                ArtifactVersion.entity_public_id == operation.entity_public_id,
                ArtifactVersion.deleted_at.is_(None),
            )
        ).all()
        for version in versions:
            version.is_current = False
            version.deleted_at = utc_now()
            session.add(version)
        return
    if new_blob_id is not None:
        if not isinstance(new_blob_id, str):
            raise HTTPException(status_code=422, detail="blob_id must be a UUID string")
        blob = session.get(BlobObject, new_blob_id)
        if blob is None or blob.workspace_id != operation.workspace_id or blob.status != "ready":
            raise HTTPException(status_code=409, detail="Blob is not ready in this workspace")
        existing_reference = session.exec(
            select(BlobReference).where(
                BlobReference.workspace_id == operation.workspace_id,
                BlobReference.project_public_id == project_id,
                BlobReference.entity_type == operation.entity_type,
                BlobReference.entity_public_id == operation.entity_public_id,
                BlobReference.blob_id == new_blob_id,
            )
        ).first()
        if existing_reference is None or existing_reference.deleted_at is not None:
            project_already_references_blob = session.exec(
                select(BlobReference.reference_id).where(
                    BlobReference.workspace_id == operation.workspace_id,
                    BlobReference.project_public_id == project_id,
                    BlobReference.blob_id == new_blob_id,
                    BlobReference.deleted_at.is_(None),
                )
            ).first()
            if (
                project_already_references_blob is None
                and _project_blob_usage(session, operation.workspace_id, project_id)
                + blob.byte_size
                > settings.cloud_project_quota_bytes
            ):
                raise HTTPException(status_code=413, detail="Project storage quota exceeded")
            blob.reference_count += 1
            session.add(blob)
            artifact = None
            if operation.entity_type in ARTIFACT_TYPES:
                previous_versions = session.exec(
                    select(ArtifactVersion).where(
                        ArtifactVersion.workspace_id == operation.workspace_id,
                        ArtifactVersion.entity_type == operation.entity_type,
                        ArtifactVersion.entity_public_id == operation.entity_public_id,
                        ArtifactVersion.deleted_at.is_(None),
                    )
                ).all()
                for version in previous_versions:
                    version.is_current = False
                    session.add(version)
                artifact = ArtifactVersion(
                    workspace_id=operation.workspace_id,
                    project_public_id=project_id,
                    entity_type=operation.entity_type,
                    entity_public_id=operation.entity_public_id,
                    version_number=max((row.version_number for row in previous_versions), default=0)
                    + 1,
                    blob_id=new_blob_id,
                    created_by=blob.created_by,
                    source_hash=blob.sha256,
                )
                session.add(artifact)
                session.flush()
                operation.payload["current_artifact_version_id"] = artifact.version_id
            if existing_reference is None:
                existing_reference = BlobReference(
                    workspace_id=operation.workspace_id,
                    project_public_id=project_id,
                    entity_type=operation.entity_type,
                    entity_public_id=operation.entity_public_id,
                    artifact_version_id=artifact.version_id if artifact else None,
                    blob_id=new_blob_id,
                )
            else:
                existing_reference.deleted_at = None
                existing_reference.artifact_version_id = artifact.version_id if artifact else None
            session.add(existing_reference)
    # Replacing an immutable artifact only switches the current pointer; the older
    # version and its blob reference remain available for conflict resolution/rollback.
    if isinstance(old_blob_id, str) and operation.entity_type not in ARTIFACT_TYPES:
        old_blob = session.get(BlobObject, old_blob_id)
        if old_blob is not None and old_blob.workspace_id == operation.workspace_id:
            old_blob.reference_count = max(0, old_blob.reference_count - 1)
            session.add(old_blob)
        old_reference = session.exec(
            select(BlobReference).where(
                BlobReference.workspace_id == operation.workspace_id,
                BlobReference.project_public_id == project_id,
                BlobReference.entity_type == operation.entity_type,
                BlobReference.entity_public_id == operation.entity_public_id,
                BlobReference.blob_id == old_blob_id,
                BlobReference.deleted_at.is_(None),
            )
        ).first()
        if old_reference is not None:
            old_reference.deleted_at = utc_now()
            session.add(old_reference)


def _lock_workspace(session: Session, workspace_id: str) -> Workspace:
    workspace = session.exec(
        select(Workspace).where(Workspace.workspace_id == workspace_id).with_for_update()
    ).one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _project_snapshot(project: CloudProject) -> dict:
    return {
        "public_id": project.public_id,
        "workspace_id": project.workspace_id,
        "name": project.name,
        "description": project.description,
        "sync_mode": project.sync_mode,
        "agent_history_sync": project.agent_history_sync,
        "version": project.version,
        "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
    }


def _entity_snapshot(entity: CloudEntity) -> dict:
    return {
        **entity.payload_json,
        "public_id": entity.public_id,
        "project_public_id": entity.project_public_id,
        "version": entity.version,
        "created_by": entity.created_by,
        "updated_by": entity.updated_by,
        "created_at": entity.created_at.isoformat(),
        "updated_at": entity.updated_at.isoformat(),
        "deleted_at": entity.deleted_at.isoformat() if entity.deleted_at else None,
    }


def _current(
    session: Session, operation: SyncOperation
) -> tuple[CloudProject | CloudEntity | None, dict | None]:
    if operation.entity_type == "project":
        item = session.get(CloudProject, operation.entity_public_id)
        if item is not None and item.workspace_id != operation.workspace_id:
            # public_id is globally unique; never treat a foreign-tenant project
            # as "missing" (that would attempt a conflicting create).
            raise HTTPException(
                status_code=409,
                detail="Project public_id belongs to another workspace",
            )
        return item, _project_snapshot(item) if item else None
    item = session.exec(
        select(CloudEntity).where(
            CloudEntity.workspace_id == operation.workspace_id,
            CloudEntity.entity_type == operation.entity_type,
            CloudEntity.public_id == operation.entity_public_id,
        )
    ).first()
    return item, _entity_snapshot(item) if item else None


def _validate_project_allows_push(
    session: Session, operation: SyncOperation, *, require_project_binding: bool
) -> CloudProject | None:
    if operation.entity_type == "project":
        existing = session.get(CloudProject, operation.entity_public_id)
        if existing is not None and require_project_binding:
            binding = session.exec(
                select(DeviceProjectBinding).where(
                    DeviceProjectBinding.device_id == operation.device_id,
                    DeviceProjectBinding.project_public_id == operation.entity_public_id,
                )
            ).first()
            if binding is None or binding.sync_mode != "cloud_enabled":
                raise HTTPException(status_code=409, detail="This device has paused project sync")
        return None
    project_id = operation.payload.get("project_public_id")
    if not isinstance(project_id, str):
        raise HTTPException(status_code=422, detail="project_public_id is required")
    project = session.get(CloudProject, project_id)
    if (
        project is None
        or project.workspace_id != operation.workspace_id
        or project.deleted_at is not None
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    binding = session.exec(
        select(DeviceProjectBinding).where(
            DeviceProjectBinding.device_id == operation.device_id,
            DeviceProjectBinding.project_public_id == project_id,
        )
    ).first()
    if binding is None or binding.sync_mode != "cloud_enabled":
        raise HTTPException(status_code=409, detail="This device is not enabled for project push")
    if operation.entity_type.startswith("agent_") and not project.agent_history_sync:
        raise HTTPException(status_code=409, detail="Agent history sync is disabled")
    return project


def apply_operation(
    session: Session,
    identity: CurrentIdentity,
    operation: SyncOperation,
    *,
    require_project_binding: bool = True,
) -> SyncOperationResult:
    if settings.cloud_require_email_verification and identity.user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Email verification required")
    require_workspace_access(session, identity, operation.workspace_id, "editor")
    if operation.entity_type == "project" and operation.operation == "delete":
        require_workspace_access(session, identity, operation.workspace_id, "owner")
    device = session.get(Device, operation.device_id)
    if (
        device is None
        or device.user_id != identity.user_id
        or device.device_id != identity.device_id
    ):
        raise HTTPException(status_code=403, detail="Invalid sync device")
    existing_receipt = session.exec(
        select(SyncReceipt).where(
            SyncReceipt.client_operation_id == operation.client_operation_id,
            SyncReceipt.device_id == operation.device_id,
        )
    ).first()
    if existing_receipt is not None:
        stored = existing_receipt.result_json
        return SyncOperationResult(
            client_operation_id=operation.client_operation_id,
            status="duplicate",
            entity_version=stored.get("entity_version"),
            workspace_seq=stored.get("workspace_seq"),
            remote=stored.get("remote"),
        )
    if operation.supersedes_operation_id is not None:
        superseded = session.exec(
            select(SyncReceipt).where(
                SyncReceipt.client_operation_id == operation.supersedes_operation_id,
                SyncReceipt.device_id == operation.device_id,
                SyncReceipt.workspace_id == operation.workspace_id,
            )
        ).first()
        if superseded is None or superseded.result_json.get("status") != "conflict":
            raise HTTPException(status_code=409, detail="supersedes_operation_id is not a conflict")
    if (
        len(json.dumps(operation.payload, ensure_ascii=False).encode("utf-8"))
        > MAX_EVENT_PAYLOAD_BYTES
    ):
        raise HTTPException(
            status_code=413, detail="Sync payload is too large; use a blob reference"
        )
    forbidden_key = _find_forbidden_key(operation.payload)
    if forbidden_key is not None:
        # Log the key NAME only (never its value — the value may be the secret
        # itself) so operators can trace which client op is being rejected.
        logger.warning(
            "sync push rejected: forbidden field %r in %s op (client_operation_id=%s)",
            forbidden_key,
            operation.entity_type,
            operation.client_operation_id,
        )
        raise HTTPException(status_code=422, detail="Payload contains a forbidden field")
    validate_domain_operation(operation)

    try:
        workspace = _lock_workspace(session, operation.workspace_id)
        item, snapshot = _current(session, operation)
        current_version = item.version if item else 0
        if current_version != operation.base_version:
            conflict_result = {
                "status": "conflict",
                "entity_version": current_version,
                "workspace_seq": None,
                "remote": snapshot,
            }
            session.add(
                SyncReceipt(
                    client_operation_id=operation.client_operation_id,
                    device_id=operation.device_id,
                    workspace_id=operation.workspace_id,
                    result_json=conflict_result,
                )
            )
            session.commit()
            return SyncOperationResult(
                client_operation_id=operation.client_operation_id,
                status="conflict",
                entity_version=current_version,
                remote=snapshot,
            )
        _validate_project_allows_push(
            session, operation, require_project_binding=require_project_binding
        )
        next_version = current_version + 1
        event_payload: dict = {}
        if operation.entity_type == "project":
            project = item if isinstance(item, CloudProject) else None
            if project is None:
                if operation.operation == "delete":
                    raise HTTPException(status_code=404, detail="Project not found")
                name = str(operation.payload.get("name", "")).strip()
                if not name:
                    raise HTTPException(status_code=422, detail="Project name is required")
                project = CloudProject(
                    public_id=operation.entity_public_id,
                    workspace_id=operation.workspace_id,
                    name=name,
                    description=str(operation.payload.get("description", "")),
                    created_by=identity.user_id,
                    updated_by=identity.user_id,
                    sync_mode="cloud_enabled",
                    agent_history_sync=bool(operation.payload.get("agent_history_sync", True)),
                )
            elif operation.operation == "upsert":
                for key, value in operation.payload.items():
                    if key not in PROJECT_FIELDS:
                        continue
                    setattr(project, key, value)
                project.version = next_version
                project.updated_by = identity.user_id
                project.updated_at = utc_now()
            if operation.operation == "delete":
                project.deleted_at = utc_now()
                project.sync_mode = "cloud_detached"
                project.version = next_version
                session.add(
                    EntityTombstone(
                        workspace_id=operation.workspace_id,
                        entity_type="project",
                        entity_public_id=project.public_id,
                        deleted_version=project.version,
                        expires_at=datetime.now(UTC)
                        + timedelta(days=settings.cloud_tombstone_days),
                    )
                )
            session.add(project)
            session.flush()
            binding = session.exec(
                select(DeviceProjectBinding).where(
                    DeviceProjectBinding.device_id == operation.device_id,
                    DeviceProjectBinding.project_public_id == project.public_id,
                )
            ).first()
            if binding is None and operation.operation != "delete":
                session.add(
                    DeviceProjectBinding(
                        device_id=operation.device_id,
                        workspace_id=operation.workspace_id,
                        project_public_id=project.public_id,
                        sync_mode="cloud_enabled",
                    )
                )
            next_version = project.version
            event_payload = _project_snapshot(project)
        else:
            entity = item if isinstance(item, CloudEntity) else None
            if operation.operation == "select_version":
                if entity is None:
                    raise HTTPException(status_code=404, detail="Artifact entity not found")
                version_id = operation.payload.get("version_id")
                artifact = session.get(ArtifactVersion, version_id)
                if (
                    artifact is None
                    or artifact.workspace_id != operation.workspace_id
                    or artifact.entity_type != operation.entity_type
                    or artifact.entity_public_id != operation.entity_public_id
                    or artifact.deleted_at is not None
                ):
                    raise HTTPException(status_code=404, detail="Artifact version not found")
                versions = session.exec(
                    select(ArtifactVersion).where(
                        ArtifactVersion.workspace_id == operation.workspace_id,
                        ArtifactVersion.entity_type == operation.entity_type,
                        ArtifactVersion.entity_public_id == operation.entity_public_id,
                        ArtifactVersion.deleted_at.is_(None),
                    )
                ).all()
                for version in versions:
                    version.is_current = version.version_id == artifact.version_id
                    session.add(version)
                entity.payload_json = {
                    **entity.payload_json,
                    "blob_id": artifact.blob_id,
                    "current_artifact_version_id": artifact.version_id,
                }
                entity.version = next_version
                entity.updated_by = identity.user_id
                entity.updated_at = utc_now()
                session.add(entity)
                session.flush()
                event_payload = _entity_snapshot(entity)
                next_version = entity.version
            elif operation.entity_type in APPEND_ONLY_TYPES and entity is not None:
                conflict_result = {
                    "status": "conflict",
                    "entity_version": entity.version,
                    "workspace_seq": None,
                    "remote": _entity_snapshot(entity),
                }
                session.add(
                    SyncReceipt(
                        client_operation_id=operation.client_operation_id,
                        device_id=operation.device_id,
                        workspace_id=operation.workspace_id,
                        result_json=conflict_result,
                    )
                )
                session.commit()
                return SyncOperationResult(
                    client_operation_id=operation.client_operation_id,
                    status="conflict",
                    entity_version=entity.version,
                    remote=_entity_snapshot(entity),
                )
            elif entity is None:
                if operation.operation == "delete":
                    raise HTTPException(status_code=404, detail="Entity not found")
                entity = CloudEntity(
                    public_id=operation.entity_public_id,
                    workspace_id=operation.workspace_id,
                    project_public_id=str(operation.payload["project_public_id"]),
                    entity_type=operation.entity_type,
                    created_by=identity.user_id,
                    updated_by=identity.user_id,
                    payload_json=operation.payload,
                )
            elif operation.operation == "upsert":
                _apply_blob_reference_change(session, operation, entity.payload_json)
                entity.payload_json = operation.payload
                entity.version = next_version
                entity.updated_by = identity.user_id
                entity.updated_at = utc_now()
            if operation.operation != "select_version" and entity.version == 1 and item is None:
                _apply_blob_reference_change(session, operation, None)
                entity.payload_json = operation.payload
            if operation.operation == "delete":
                _apply_blob_reference_change(session, operation, entity.payload_json)
                entity.payload_json = {
                    **entity.payload_json,
                    "_blob_reference_released": True,
                }
                entity.deleted_at = utc_now()
                entity.version = next_version
                entity.updated_by = identity.user_id
                entity.updated_at = utc_now()
                session.add(
                    EntityTombstone(
                        workspace_id=operation.workspace_id,
                        entity_type=operation.entity_type,
                        entity_public_id=entity.public_id,
                        deleted_version=entity.version,
                        expires_at=datetime.now(UTC)
                        + timedelta(days=settings.cloud_tombstone_days),
                    )
                )
            if operation.operation != "select_version":
                session.add(entity)
                session.flush()
                next_version = entity.version
                event_payload = _entity_snapshot(entity)

        workspace.workspace_seq += 1
        session.add(workspace)
        if (
            len(json.dumps(event_payload, ensure_ascii=False).encode("utf-8"))
            > MAX_EVENT_PAYLOAD_BYTES
        ):
            raise HTTPException(
                status_code=413,
                detail="Sync event is too large; move large content to a blob",
            )
        sync_event = SyncEvent(
            workspace_id=operation.workspace_id,
            workspace_seq=workspace.workspace_seq,
            entity_type=operation.entity_type,
            entity_public_id=operation.entity_public_id,
            operation=(
                "delete"
                if operation.operation == "delete" or event_payload.get("deleted_at")
                else operation.operation
            ),
            entity_version=next_version,
            payload_json=event_payload,
        )
        session.add(sync_event)
        result = {
            "status": "applied",
            "entity_version": next_version,
            "workspace_seq": workspace.workspace_seq,
            "remote": event_payload,
        }
        session.add(
            SyncReceipt(
                client_operation_id=operation.client_operation_id,
                device_id=operation.device_id,
                workspace_id=operation.workspace_id,
                result_json=result,
            )
        )
        session.add(
            AuditLog(
                actor_id=identity.user_id,
                workspace_id=operation.workspace_id,
                action="sync.write",
                target=f"{operation.entity_type}:{operation.entity_public_id}",
                metadata_json={"operation": operation.operation},
            )
        )
        session.commit()
        return SyncOperationResult(
            client_operation_id=operation.client_operation_id,
            status="applied",
            entity_version=next_version,
            workspace_seq=workspace.workspace_seq,
            remote=event_payload,
        )
    except Exception:
        session.rollback()
        raise
