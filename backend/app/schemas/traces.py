from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TraceLinkCreate(BaseModel):
    paper_ref: str = Field(min_length=1, max_length=255)
    code_ref: str = Field(min_length=1, max_length=255)
    relation_type: str = Field(default="implements", max_length=64)
    confidence: float = Field(default=0.5, ge=0, le=1)
    rationale: str = ""


class TraceLinkRead(BaseModel):
    id: int
    project_id: int
    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: float
    rationale: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TraceLinkSuggestion(BaseModel):
    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: float
    rationale: str


class WorkspaceTraceRow(BaseModel):
    paper_ref: str
    code_ref: str
    relation_type: str
    confidence: int = Field(ge=0, le=100)
    rationale: str
