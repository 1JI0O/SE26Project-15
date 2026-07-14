export interface WorkspaceTraceRow {
  paper_ref: string
  code_ref: string
  relation_type: string
  confidence: number
  rationale: string
}

export interface TraceLink {
  id: number
  project_id: number
  paper_ref: string
  code_ref: string
  relation_type: string
  confidence: number
  rationale: string
  created_at: string
}

export interface TraceLinkCreate {
  paper_ref: string
  code_ref: string
  relation_type: string
  confidence: number
  rationale: string
}

export type TraceLinkSuggestion = TraceLinkCreate
