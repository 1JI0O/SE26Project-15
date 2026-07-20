export type TraceStatus = 'proposed' | 'accepted' | 'rejected' | 'stale'

export interface WorkspaceTraceRow {
  paper_ref: string
  code_ref: string
  relation_type: string
  confidence: number
  rationale: string
}

export interface TraceEvidence {
  side: 'paper' | 'code'
  ref: string
  quote: string
  path?: string
  line_start?: number
  line_end?: number
}

export interface TraceLink {
  id: string
  project_id: number
  paper_document_id: number | null
  paper_block_id: string
  code_repository_id: number | null
  code_revision: number
  code_symbol_id: string
  relation_type: string
  confidence: number
  static_confidence: number
  llm_confidence: number | null
  source: string
  evidence: TraceEvidence[]
  rationale: string
  uncertainty: { level: 'low' | 'medium' | 'high'; reasons: string[] }
  model: { provider: string; name: string; prompt_version: string } | null
  status: TraceStatus
  stale_reason: string | null
  created_at: string
  updated_at: string
}

export interface TraceLinkCreate {
  paper_ref: string
  code_ref: string
  relation_type: string
  confidence: number
  rationale: string
  evidence: TraceEvidence[]
}

export interface TraceSuggestionResponse {
  mode: 'static' | 'static+llm' | 'agent'
  degraded: boolean
  degraded_reason: string | null
  items: TraceLink[]
}

export type TraceLinkSuggestion = TraceLink
