export interface AgentContext {
  paper_block_id?: string
  code_symbol_id?: string
  graph_node_id?: string
}

export interface AgentCitation {
  side: 'paper' | 'code' | 'trace' | 'graph'
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
