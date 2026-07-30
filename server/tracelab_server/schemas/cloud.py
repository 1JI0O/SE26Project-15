from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, field_validator


def _uuid_string(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("must be a UUID") from exc


UuidStr = Annotated[str, AfterValidator(_uuid_string)]


class UserRead(BaseModel):
    user_id: UuidStr
    email: str
    display_name: str
    status: str
    email_verified: bool
    is_platform_admin: bool = False


class WorkspaceRead(BaseModel):
    workspace_id: UuidStr
    name: str
    role: str
    plan: str
    storage_limit_bytes: int
    workspace_seq: int


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(default="", max_length=160)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    client_kind: Literal["browser", "desktop"] = "browser"
    device_id: UuidStr | None = None
    device_name: str = Field(default="Unknown device", max_length=160)
    platform: str = Field(default="web", max_length=32)
    client_version: str = Field(default="", max_length=64)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None
    client_kind: Literal["browser", "desktop"] = "browser"


class AuthRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str | None = None
    refresh_token: str | None = None
    device_id: UuidStr | None = None
    user: UserRead
    default_workspace: WorkspaceRead | None = None


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=10, max_length=256)


class DeviceRead(BaseModel):
    device_id: UuidStr
    name: str
    platform: str
    client_version: str
    last_seen_at: datetime
    current: bool = False


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class WorkspaceMemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["owner", "editor", "viewer"] = "viewer"


class WorkspaceMemberPatch(BaseModel):
    role: Literal["owner", "editor", "viewer"]


class WorkspaceMemberRead(BaseModel):
    user_id: UuidStr
    email: str
    display_name: str
    role: str


class CloudProjectCreate(BaseModel):
    workspace_id: UuidStr
    public_id: UuidStr | None = None
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    agent_history_sync: bool = True


class CloudProjectPatch(BaseModel):
    base_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    agent_history_sync: bool | None = None


class CloudProjectRead(BaseModel):
    public_id: UuidStr
    workspace_id: UuidStr
    name: str
    description: str
    version: int
    sync_mode: str
    agent_history_sync: bool
    created_at: datetime
    updated_at: datetime


class DeviceProjectSyncPatch(BaseModel):
    sync_mode: Literal["cloud_enabled", "cloud_paused", "cloud_detached"]


class DeviceProjectSyncRead(BaseModel):
    project_public_id: UuidStr
    device_id: UuidStr
    sync_mode: Literal["cloud_enabled", "cloud_paused", "cloud_detached"]


class CloudEntityCommand(BaseModel):
    public_id: UuidStr | None = None
    base_version: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class ArtifactVersionSelect(BaseModel):
    base_version: int = Field(ge=1)
    version_id: UuidStr


SyncEntityType = Literal[
    "project",
    "paper_document",
    "code_repository",
    "code_edit",
    "paper_target",
    "code_target",
    "trace_link",
    "agent_conversation",
    "agent_message",
    "agent_run",
    "agent_run_event",
    "agent_memory",
]


class SyncOperation(BaseModel):
    workspace_id: UuidStr
    device_id: UuidStr
    client_operation_id: UuidStr
    supersedes_operation_id: UuidStr | None = None
    entity_type: SyncEntityType
    entity_public_id: UuidStr
    operation: Literal["upsert", "delete", "select_version"]
    base_version: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncPushRequest(BaseModel):
    operations: list[SyncOperation] = Field(min_length=1, max_length=100)


class SyncOperationResult(BaseModel):
    client_operation_id: UuidStr
    status: Literal["applied", "duplicate", "conflict"]
    entity_version: int | None = None
    workspace_seq: int | None = None
    remote: dict[str, Any] | None = None


class SyncPushRead(BaseModel):
    results: list[SyncOperationResult]


class SyncEventRead(BaseModel):
    event_id: str
    workspace_seq: int
    entity_type: str
    entity_public_id: str
    operation: str
    entity_version: int
    payload: dict[str, Any]
    created_at: datetime


class SyncPullRead(BaseModel):
    events: list[SyncEventRead]
    next_after: int
    has_more: bool


class SyncAckRequest(BaseModel):
    workspace_id: UuidStr
    device_id: UuidStr
    last_pulled_seq: int = Field(ge=0)


class BlobUploadInit(BaseModel):
    workspace_id: UuidStr
    project_public_id: UuidStr | None = None
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    mime_type: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=255)

    @field_validator("filename")
    @classmethod
    def filename_only(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("filename must not contain a path")
        return value


class BlobUploadInitRead(BaseModel):
    blob_id: str
    status: Literal["upload", "reuse"]
    chunk_size: int
    uploaded_bytes: int = 0


class BlobCompleteRead(BaseModel):
    blob_id: str
    status: str
    sha256: str
    byte_size: int


class AdminUserPatch(BaseModel):
    status: Literal["active", "disabled"] | None = None
    force_logout: bool = False


class AdminQuotaPatch(BaseModel):
    storage_limit_bytes: int = Field(ge=1)
