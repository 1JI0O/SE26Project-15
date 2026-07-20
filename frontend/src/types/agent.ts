export interface AgentContext {
  paper_block_id?: string
  code_symbol_id?: string
  graph_node_id?: string
  file_path?: string
  line?: number
  trace_id?: string
  graph_root_symbol?: string
}

export type AgentAnalysisKind = 'architecture' | 'trace'

export interface AgentAnalysisJob {
  job_id: string
  project_id: number
  kind: AgentAnalysisKind
  status: 'queued' | 'running' | 'validating' | 'succeeded' | 'failed' | 'stale'
  paper_document_id: number | null
  code_repository_id: number
  code_revision: number
  root_symbol: string | null
  requested_depth: number
  run_id: string | null
  artifact_id: string | null
  progress: Record<string, unknown>
  error_code: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface AgentCitation {
  side: 'paper' | 'code' | 'trace' | 'graph' | 'memory' | 'project'
  ref: string
  quote: string
}

export type ConfirmationStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'expired'
  | 'executed'
  | 'failed'

export interface AgentConfirmation {
  confirmation_id: string
  project_id: number
  conversation_id: string | null
  run_id: string | null
  tool_name: string
  parameter_summary: Record<string, unknown>
  status: ConfirmationStatus
  user_decision: string | null
  result: Record<string, unknown> | null
  error_summary: string | null
  expires_at: string
  created_at: string
  decided_at: string | null
  executed_at: string | null
}

export interface AgentQueryResponse {
  answer: string
  citations: AgentCitation[]
  degraded: boolean
  degraded_reason: string | null
  confirmation: AgentConfirmation | null
}

export interface AgentConversation {
  conversation_id: string
  project_id: number
  title: string
  status: 'active' | 'archived'
  summary: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface AgentUiAction {
  type: 'open_code' | 'open_paper' | 'focus_architecture'
  path?: string
  line?: number
  block_id?: string
  quote?: string
  root_symbol?: string
  view?: 'architecture' | 'debug'
}

export interface AgentToolEvent {
  tool_name: string
  status: 'running' | 'succeeded' | 'failed' | 'pending_confirmation'
  summary: string
  result: Record<string, unknown> & { ui_action?: AgentUiAction }
}

export interface AgentMessage {
  message_id: string
  conversation_id: string
  project_id: number
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  citations: AgentCitation[]
  tool_events: AgentToolEvent[]
  degraded: boolean
  degraded_reason: string | null
  run_id: string | null
  confirmation: AgentConfirmation | null
  created_at: string
}

export interface AgentConversationDetail extends AgentConversation {
  messages: AgentMessage[]
}

export interface AgentTurnResponse {
  conversation: AgentConversation
  user_message: AgentMessage
  assistant_message: AgentMessage
  run_id: string
  status: string
  confirmation: AgentConfirmation | null
}

export interface AgentRunSubmission {
  conversation: AgentConversation
  user_message: AgentMessage
  run_id: string
  status: string
}

export interface AgentRunEvent {
  event_id: string
  run_id: string
  conversation_id: string
  project_id: number
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface AgentCapability {
  capability_id: string
  name: string
  title: string
  description: string
  kind: 'skill' | 'tool' | 'plugin'
  source: string
  version: string
  enabled: boolean
  trusted: boolean
  eligible: boolean
  read_only: boolean
  requires_confirmation: boolean
  reason: string | null
}

export interface AgentConversationDecisionResponse {
  confirmation: AgentConfirmation
  assistant_message: AgentMessage | null
  run_id: string | null
  status: string
}

export interface AgentMemory {
  memory_id: string
  project_id: number | null
  conversation_id: string | null
  scope: 'project' | 'global'
  kind: 'fact' | 'preference' | 'decision' | 'constraint' | 'summary'
  content: string
  importance: number
  source: Record<string, unknown>
  created_at: string
  updated_at: string
  last_used_at: string | null
}
