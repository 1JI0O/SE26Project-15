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
    file_path: str | None = Field(default=None, max_length=1000)
    line: int | None = Field(default=None, ge=1)
    trace_id: str | None = Field(default=None, max_length=64)
    graph_root_symbol: str | None = Field(default=None, max_length=500)


class AgentQueryRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    context: AgentContext = Field(default_factory=AgentContext)


class AgentCitation(BaseModel):
    side: str = Field(pattern="^(paper|code|trace|graph|memory|project)$")
    ref: str = Field(min_length=1, max_length=500)
    quote: str = Field(default="", max_length=1000)


class AgentConfirmationRead(BaseModel):
    confirmation_id: str
    project_id: int
    conversation_id: str | None = None
    run_id: str | None = None
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


class AgentConversationCreate(BaseModel):
    title: str = Field(default="新对话", max_length=160)


class AgentConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class AgentConversationRead(BaseModel):
    conversation_id: str
    project_id: int
    title: str
    status: str
    summary: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class AgentToolEvent(BaseModel):
    tool_name: str
    status: str = Field(pattern="^(succeeded|failed|pending_confirmation)$")
    summary: str = ""
    result: dict[str, object] = Field(default_factory=dict)


class AgentMessageRead(BaseModel):
    message_id: str
    conversation_id: str
    project_id: int
    role: str = Field(pattern="^(user|assistant|tool|system)$")
    content: str
    citations: list[AgentCitation] = Field(default_factory=list)
    tool_events: list[AgentToolEvent] = Field(default_factory=list)
    degraded: bool = False
    degraded_reason: str | None = None
    run_id: str | None = None
    confirmation: AgentConfirmationRead | None = None
    created_at: datetime


class AgentConversationDetail(AgentConversationRead):
    messages: list[AgentMessageRead] = Field(default_factory=list)


class AgentTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    context: AgentContext = Field(default_factory=AgentContext)


class AgentTurnResponse(BaseModel):
    conversation: AgentConversationRead
    user_message: AgentMessageRead
    assistant_message: AgentMessageRead
    run_id: str
    status: str
    confirmation: AgentConfirmationRead | None = None


class AgentRunSubmission(BaseModel):
    conversation: AgentConversationRead
    user_message: AgentMessageRead
    run_id: str
    status: str = "queued"


class AgentRunEventRead(BaseModel):
    event_id: str
    run_id: str
    conversation_id: str
    project_id: int
    sequence: int
    event_type: str
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class AgentCapabilityRead(BaseModel):
    capability_id: str
    name: str
    title: str
    description: str
    kind: str = Field(pattern="^(skill|tool|plugin)$")
    source: str
    version: str
    enabled: bool
    trusted: bool
    eligible: bool
    read_only: bool = True
    requires_confirmation: bool = False
    reason: str | None = None


class AgentCapabilityUpdate(BaseModel):
    enabled: bool
    trusted: bool = False


class AgentConversationDecisionResponse(BaseModel):
    confirmation: AgentConfirmationRead
    assistant_message: AgentMessageRead | None = None
    run_id: str | None = None
    status: str


class AgentMemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    scope: str = Field(default="project", pattern="^(project|global)$")
    kind: str = Field(default="fact", pattern="^(fact|preference|decision|constraint|summary)$")
    importance: float = Field(default=0.6, ge=0, le=1)
    conversation_id: str | None = Field(default=None, max_length=72)


class AgentMemoryRead(BaseModel):
    memory_id: str
    project_id: int | None
    conversation_id: str | None
    scope: str
    kind: str
    content: str
    importance: float
    source: dict[str, object]
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
