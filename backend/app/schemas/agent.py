from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class AgentContext(BaseModel):
    paper_block_id: str | None = Field(default=None, max_length=255)
    code_symbol_id: str | None = Field(default=None, max_length=500)
    graph_node_id: str | None = Field(default=None, max_length=255)


class AgentQueryRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    context: AgentContext = Field(default_factory=AgentContext)


class AgentCitation(BaseModel):
    side: str = Field(pattern="^(paper|code|trace|graph)$")
    ref: str = Field(min_length=1, max_length=500)
    quote: str = Field(default="", max_length=1000)


class AgentConfirmationRead(BaseModel):
    confirmation_id: str
    project_id: int
    tool_name: str
    parameter_summary: dict[str, object]
    status: ConfirmationStatus
    user_decision: str | None
    result: dict[str, object] | None
    error_summary: str | None
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None


class AgentQueryResponse(BaseModel):
    answer: str
    citations: list[AgentCitation] = Field(default_factory=list)
    degraded: bool = False
    degraded_reason: str | None = None
    confirmation: AgentConfirmationRead | None = None


class AgentDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")
