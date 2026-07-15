export interface AgentContext {
  paper_block_id?: string
  code_symbol_id?: string
  graph_node_id?: string
  file_path?: string
  line?: number
  trace_id?: string
  graph_root_symbol?: string
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
  type: 'open_code' | 'focus_architecture'
  path?: string
  line?: number
  root_symbol?: string
  view?: 'architecture' | 'debug'
}

export interface AgentToolEvent {
  tool_name: string
  status: 'succeeded' | 'failed' | 'pending_confirmation'
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
