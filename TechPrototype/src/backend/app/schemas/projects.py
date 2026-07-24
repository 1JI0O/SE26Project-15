from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None


class ProjectRead(BaseModel):
    id: int
    public_id: str
    name: str
    description: str
    version: int
    sync_mode: str
    agent_history_sync: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectBatchDeleteRequest(BaseModel):
    project_ids: list[int] = Field(min_length=1, max_length=100)


class ProjectBatchDeleteRead(BaseModel):
    deleted_ids: list[int]
    missing_ids: list[int]
