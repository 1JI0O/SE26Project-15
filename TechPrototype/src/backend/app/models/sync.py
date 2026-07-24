from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.models.entities import utc_now


def new_uuid() -> str:
    return str(uuid4())


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
