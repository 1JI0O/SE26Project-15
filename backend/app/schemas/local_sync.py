from typing import Any, Literal

from pydantic import BaseModel, Field


class LocalSyncEnable(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    device_id: str = Field(min_length=36, max_length=36)
    agent_history_sync: bool = True


class LocalDeviceAdopt(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    device_id: str = Field(min_length=36, max_length=36)


class LocalSyncModePatch(BaseModel):
    sync_mode: Literal["cloud_enabled", "cloud_paused", "cloud_detached", "local_only"]


class LocalAgentHistoryPatch(BaseModel):
    enabled: bool


class LocalArtifactSelect(BaseModel):
    local_version_id: int = Field(gt=0)


class LocalSyncResult(BaseModel):
    client_operation_id: str
    status: Literal["applied", "duplicate", "conflict"]
    entity_version: int | None = None
    workspace_seq: int | None = None
    remote: dict[str, Any] | None = None


class LocalSyncResults(BaseModel):
    results: list[LocalSyncResult]


class RemoteSyncEvent(BaseModel):
    event_id: str
    workspace_seq: int = Field(ge=1)
    entity_type: str
    entity_public_id: str
    operation: str
    entity_version: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class RemoteSyncEvents(BaseModel):
    workspace_id: str
    device_id: str
    events: list[RemoteSyncEvent]


class LocalConflictResolve(BaseModel):
    resolution: Literal["keep_local", "use_remote", "keep_both"]
    merged_payload: dict[str, Any] | None = None


class LocalCloudProjectImport(BaseModel):
    workspace_id: str = Field(min_length=36, max_length=36)
    device_id: str = Field(min_length=36, max_length=36)
    public_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    version: int = Field(ge=1)
    agent_history_sync: bool = True


class LocalCloudEntityImport(BaseModel):
    entity_type: Literal[
        "paper_target",
        "code_target",
        "trace_link",
        "agent_conversation",
        "agent_message",
        "agent_run",
        "agent_run_event",
        "agent_memory",
    ]
    public_id: str = Field(min_length=1, max_length=72)
    version: int = Field(ge=1)
    payload: dict[str, Any]
