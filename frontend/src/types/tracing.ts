export type TraceStatus = 'proposed' | 'accepted' | 'rejected' | 'stale'

export type TraceRelationType =
  | 'implements'
  | 'describes'
  | 'motivates'
  | 'evaluates'
  | 'defines'
  | 'computes'
  | 'calls'
  | 'tests'
  | 'related'

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
  // Fragment-level anchoring (V1) used for precise hover highlighting.
  target_id?: string
  target_type?: string
  role?: string
  occurrence?: number
  char_start?: number | null
  char_end?: number | null
  column_start?: number | null
  column_end?: number | null
  match_line_start?: number | null
  match_line_end?: number | null
  quote_hash?: string
  code_quote_hash?: string
  salience?: number | null
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
  relevance: number
  static_confidence: number
  llm_confidence: number | null
  source: string
  paper_target_id?: string | null
  code_target_id?: string | null
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
