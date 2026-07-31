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


class AgentAnalysisJobCreate(BaseModel):
    kind: str = Field(pattern="^(architecture|trace|conflict)$")
    paper_document_id: int | None = None
    code_repository_id: int | None = None
    root_symbol: str | None = Field(default=None, max_length=500)
    depth: int = Field(default=2, ge=1, le=3)
    force: bool = False


class AgentAnalysisJobRead(BaseModel):
    job_id: str
    project_id: int
    kind: str
    status: str
    paper_document_id: int | None
    code_repository_id: int
    code_revision: int
    root_symbol: str | None
    requested_depth: int
    run_id: str | None
    artifact_id: str | None
    progress: dict[str, object] = Field(default_factory=dict)
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AgentAnalysisDiagnosticsRead(BaseModel):
    """Full failure/progress detail for one analysis job, surfaced by the workbench debug mode.

    The normal job read only exposes a short ``error_code``; when debug mode is on the UI needs
    the underlying provider/tool failures and the last model steps to explain what actually broke.
    """

    job_id: str
    project_id: int
    kind: str
    status: str
    error_code: str | None
    progress: dict[str, object] = Field(default_factory=dict)
    run_id: str | None
    run_status: str | None
    degraded_reason: str | None
    provider_name: str | None
    model_name: str | None
    step_count: int
    published_link_count: int
    events: list[AgentRunEventRead] = Field(default_factory=list)
    steps: list[dict[str, object]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AgentQueueItemRead(BaseModel):
    id: str
    project_id: int
    project_name: str
    category: str
    kind: str
    status: str
    summary: str = ""
    model_name: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    stale: bool = False


class AgentQueueRead(BaseModel):
    items: list[AgentQueueItemRead] = Field(default_factory=list)
    active_count: int = 0
    stale_count: int = 0
    capacity: int = 0


class AgentAnalysisArtifactRead(BaseModel):
    artifact_id: str
    job_id: str
    project_id: int
    kind: str
    schema_version: str
    payload: dict[str, object]
    paper_document_id: int | None
    code_repository_id: int
    code_revision: int
    run_id: str
    model: dict[str, object]
    is_current: bool
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
