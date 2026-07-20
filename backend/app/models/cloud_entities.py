from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Column, Text, UniqueConstraint
from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel

from app.models.entities import utc_now


def new_uuid() -> str:
    return str(uuid4())


cloud_registry = registry()


class CloudSQLModel(SQLModel, registry=cloud_registry):
    """Cloud-only ORM base with metadata isolated from Local SQLite."""


class UserAccount(CloudSQLModel, table=True):
    __tablename__ = "user_account"
    user_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    email_normalized: str = Field(index=True, unique=True, max_length=320)
    password_hash: str = Field(sa_column=Column(Text, nullable=False), repr=False)
    display_name: str = Field(default="", max_length=160)
    status: str = Field(default="active", max_length=24, index=True)
    email_verified_at: datetime | None = Field(default=None)
    is_platform_admin: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Device(CloudSQLModel, table=True):
    __tablename__ = "device"
    device_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    user_id: str = Field(foreign_key="user_account.user_id", index=True, max_length=36)
    name: str = Field(default="Unknown device", max_length=160)
    platform: str = Field(default="web", max_length=32)
    client_version: str = Field(default="", max_length=64)
    last_seen_at: datetime = Field(default_factory=utc_now, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class AuthSession(CloudSQLModel, table=True):
    __tablename__ = "auth_session"
    session_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    user_id: str = Field(foreign_key="user_account.user_id", index=True, max_length=36)
    device_id: str = Field(foreign_key="device.device_id", index=True, max_length=36)
    refresh_token_hash: str = Field(max_length=64, index=True, repr=False)
    previous_refresh_token_hash: str | None = Field(default=None, max_length=64, repr=False)
    expires_at: datetime = Field(index=True)
    revoked_at: datetime | None = Field(default=None, index=True)
    last_ip_hash: str = Field(default="", max_length=64)
    user_agent_summary: str = Field(default="", max_length=255)
    created_at: datetime = Field(default_factory=utc_now)


class Workspace(CloudSQLModel, table=True):
    __tablename__ = "workspace"
    workspace_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    name: str = Field(max_length=160)
    created_by: str = Field(foreign_key="user_account.user_id", index=True, max_length=36)
    plan: str = Field(default="free", max_length=32)
    storage_limit_bytes: int = Field(default=5 * 1024**3, ge=1, sa_type=BigInteger)
    workspace_seq: int = Field(default=0, ge=0, sa_type=BigInteger)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkspaceMember(CloudSQLModel, table=True):
    __tablename__ = "workspace_member"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)
    id: int | None = Field(default=None, primary_key=True)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    user_id: str = Field(foreign_key="user_account.user_id", index=True, max_length=36)
    role: str = Field(default="viewer", max_length=16, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class EmailToken(CloudSQLModel, table=True):
    __tablename__ = "email_token"
    token_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    user_id: str = Field(foreign_key="user_account.user_id", index=True, max_length=36)
    purpose: str = Field(max_length=32, index=True)
    token_hash: str = Field(max_length=64, unique=True, repr=False)
    expires_at: datetime = Field(index=True)
    used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class AuditLog(CloudSQLModel, table=True):
    __tablename__ = "audit_log"
    audit_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    actor_id: str | None = Field(default=None, index=True, max_length=36)
    workspace_id: str | None = Field(default=None, index=True, max_length=36)
    action: str = Field(index=True, max_length=96)
    target: str = Field(default="", max_length=255)
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AuthRateLimit(CloudSQLModel, table=True):
    __tablename__ = "auth_rate_limit"
    bucket_key: str = Field(primary_key=True, max_length=128)
    window_started_at: datetime = Field(default_factory=utc_now)
    attempt_count: int = Field(default=0, ge=0)


class CloudProject(CloudSQLModel, table=True):
    __tablename__ = "cloud_project"
    public_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    name: str = Field(max_length=160)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_by: str = Field(foreign_key="user_account.user_id", max_length=36)
    updated_by: str = Field(foreign_key="user_account.user_id", max_length=36)
    version: int = Field(default=1, ge=1)
    sync_mode: str = Field(default="cloud_enabled", max_length=24, index=True)
    agent_history_sync: bool = Field(default=True)
    deleted_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CloudEntity(CloudSQLModel, table=True):
    __tablename__ = "cloud_entity"
    __table_args__ = (
        UniqueConstraint("workspace_id", "entity_type", "public_id", name="uq_cloud_entity"),
    )
    id: int | None = Field(default=None, primary_key=True)
    public_id: str = Field(index=True, max_length=72)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    project_public_id: str | None = Field(default=None, index=True, max_length=36)
    entity_type: str = Field(index=True, max_length=64)
    version: int = Field(default=1, ge=1)
    created_by: str = Field(foreign_key="user_account.user_id", max_length=36)
    updated_by: str = Field(foreign_key="user_account.user_id", max_length=36)
    payload_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    deleted_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SyncEvent(CloudSQLModel, table=True):
    __tablename__ = "sync_event"
    __table_args__ = (
        UniqueConstraint("workspace_id", "workspace_seq", name="uq_sync_workspace_seq"),
    )
    event_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    workspace_seq: int = Field(index=True, ge=1, sa_type=BigInteger)
    entity_type: str = Field(max_length=64, index=True)
    entity_public_id: str = Field(max_length=72, index=True)
    operation: str = Field(max_length=16)
    entity_version: int = Field(ge=1)
    payload_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)


class SyncReceipt(CloudSQLModel, table=True):
    __tablename__ = "sync_receipt"
    __table_args__ = (
        UniqueConstraint("client_operation_id", "device_id", name="uq_sync_receipt_operation"),
    )
    receipt_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    client_operation_id: str = Field(index=True, max_length=72)
    device_id: str = Field(foreign_key="device.device_id", index=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    result_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class SyncDeviceCursor(CloudSQLModel, table=True):
    __tablename__ = "sync_device_cursor"
    __table_args__ = (UniqueConstraint("device_id", "workspace_id", name="uq_sync_device_cursor"),)
    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(foreign_key="device.device_id", index=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    last_pulled_seq: int = Field(default=0, ge=0, sa_type=BigInteger)
    updated_at: datetime = Field(default_factory=utc_now)


class EntityTombstone(CloudSQLModel, table=True):
    __tablename__ = "entity_tombstone"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "entity_type", "entity_public_id", name="uq_entity_tombstone"
        ),
    )
    tombstone_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    entity_type: str = Field(max_length=64, index=True)
    entity_public_id: str = Field(max_length=72, index=True)
    deleted_version: int = Field(ge=1)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)


class BlobObject(CloudSQLModel, table=True):
    __tablename__ = "blob_object"
    __table_args__ = (UniqueConstraint("workspace_id", "sha256", name="uq_blob_workspace_hash"),)
    blob_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    project_public_id: str | None = Field(default=None, index=True, max_length=36)
    content_id: str | None = Field(
        default=None,
        foreign_key="blob_content.content_id",
        index=True,
        max_length=36,
    )
    sha256: str = Field(index=True, max_length=64)
    byte_size: int = Field(ge=0, sa_type=BigInteger)
    mime_type: str = Field(max_length=160)
    filename: str = Field(default="upload.bin", max_length=255)
    storage_key: str = Field(default="", max_length=255)
    status: str = Field(default="uploading", max_length=24, index=True)
    created_by: str = Field(foreign_key="user_account.user_id", max_length=36)
    reference_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class BlobContent(CloudSQLModel, table=True):
    """Physical, globally deduplicated content. Never exposed as an authorization handle."""

    __tablename__ = "blob_content"
    content_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    sha256: str = Field(unique=True, index=True, max_length=64)
    byte_size: int = Field(ge=0, sa_type=BigInteger)
    mime_type: str = Field(max_length=160)
    storage_key: str = Field(max_length=255)
    physical_ref_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactVersion(CloudSQLModel, table=True):
    __tablename__ = "artifact_version"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "entity_type",
            "entity_public_id",
            "version_number",
            name="uq_artifact_version_number",
        ),
    )
    version_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    project_public_id: str = Field(index=True, max_length=36)
    entity_type: str = Field(index=True, max_length=64)
    entity_public_id: str = Field(index=True, max_length=36)
    version_number: int = Field(default=1, ge=1)
    blob_id: str = Field(foreign_key="blob_object.blob_id", index=True, max_length=36)
    created_by: str = Field(foreign_key="user_account.user_id", max_length=36)
    is_current: bool = Field(default=True, index=True)
    source_hash: str = Field(default="", max_length=64)
    created_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = Field(default=None, index=True)


class BlobReference(CloudSQLModel, table=True):
    __tablename__ = "blob_reference"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "project_public_id",
            "entity_type",
            "entity_public_id",
            "blob_id",
            name="uq_blob_reference_target",
        ),
    )
    reference_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    project_public_id: str = Field(index=True, max_length=36)
    entity_type: str = Field(index=True, max_length=64)
    entity_public_id: str = Field(index=True, max_length=36)
    artifact_version_id: str | None = Field(
        default=None, foreign_key="artifact_version.version_id", index=True, max_length=36
    )
    blob_id: str = Field(foreign_key="blob_object.blob_id", index=True, max_length=36)
    purpose: str = Field(default="source", max_length=32)
    created_at: datetime = Field(default_factory=utc_now)
    deleted_at: datetime | None = Field(default=None, index=True)


class UploadSession(CloudSQLModel, table=True):
    __tablename__ = "upload_session"
    session_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    blob_id: str = Field(foreign_key="blob_object.blob_id", unique=True, index=True, max_length=36)
    uploaded_bytes: int = Field(default=0, ge=0, sa_type=BigInteger)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)


class DeviceProjectBinding(CloudSQLModel, table=True):
    """Per-device sync state; cloud project lifecycle remains globally active/deleting."""

    __tablename__ = "device_project_binding"
    __table_args__ = (
        UniqueConstraint("device_id", "project_public_id", name="uq_device_project_binding"),
    )
    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(foreign_key="device.device_id", index=True, max_length=36)
    workspace_id: str = Field(foreign_key="workspace.workspace_id", index=True, max_length=36)
    project_public_id: str = Field(index=True, max_length=36)
    sync_mode: str = Field(default="cloud_enabled", index=True, max_length=24)
    updated_at: datetime = Field(default_factory=utc_now)


class BackgroundJob(CloudSQLModel, table=True):
    __tablename__ = "background_job"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_background_job_idempotency"),)
    job_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    workspace_id: str | None = Field(default=None, index=True, max_length=36)
    job_type: str = Field(max_length=64, index=True)
    idempotency_key: str = Field(max_length=160)
    payload_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    status: str = Field(default="queued", max_length=24, index=True)
    attempt_count: int = Field(default=0, ge=0)
    available_at: datetime = Field(default_factory=utc_now, index=True)
    lease_expires_at: datetime | None = Field(default=None, index=True)
    last_error: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = Field(default=None)


class LocalSyncOutbox(SQLModel, table=True):
    __tablename__ = "local_sync_outbox"
    client_operation_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=72)
    supersedes_operation_id: str | None = Field(default=None, index=True, max_length=72)
    workspace_id: str = Field(index=True, max_length=36)
    device_id: str = Field(index=True, max_length=36)
    entity_type: str = Field(max_length=64)
    entity_public_id: str = Field(max_length=72)
    operation: str = Field(max_length=16)
    base_version: int = Field(default=0, ge=0)
    payload_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    status: str = Field(default="pending", max_length=24, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class LocalSyncState(SQLModel, table=True):
    __tablename__ = "local_sync_state"
    workspace_id: str = Field(primary_key=True, max_length=36)
    device_id: str = Field(max_length=36)
    last_pulled_seq: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class LocalSyncInbox(SQLModel, table=True):
    __tablename__ = "local_sync_inbox"
    event_id: str = Field(primary_key=True, max_length=36)
    workspace_id: str = Field(index=True, max_length=36)
    workspace_seq: int = Field(index=True, ge=1)
    entity_type: str = Field(max_length=64)
    entity_public_id: str = Field(max_length=72)
    operation: str = Field(max_length=16)
    entity_version: int = Field(ge=1)
    payload_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    applied_at: datetime = Field(default_factory=utc_now)


class LocalSyncConflict(SQLModel, table=True):
    __tablename__ = "local_sync_conflict"
    conflict_id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
    client_operation_id: str = Field(index=True, max_length=72)
    workspace_id: str = Field(index=True, max_length=36)
    entity_type: str = Field(max_length=64)
    entity_public_id: str = Field(max_length=72)
    local_payload_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    remote_payload_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="unresolved", max_length=24, index=True)
    created_at: datetime = Field(default_factory=utc_now)
