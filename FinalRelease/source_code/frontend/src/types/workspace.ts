export type TagType = 'success' | 'warning' | 'info' | 'primary' | 'danger'

export interface WorkspaceImportStep {
  index: string
  title: string
  description: string
  status: string
  tag_type: TagType
  action?: string
}

export interface WorkspaceConflictItem {
  id: string
  category: ConflictCategory
  severity: ConflictSeverity
  confidence: number
  level: string
  type: TagType
  title: string
  description: string
  affected_files: string[]
  status: string
}

export type ConflictSeverity = 'high' | 'medium' | 'low'
export type ConflictCategory =
  | 'paper_consistency'
  | 'behavior_regression'
  | 'trace_invalidation'
  | 'trace_coverage'
  | 'configuration_risk'

export type ConflictAnalysisStepStatus = 'running' | 'completed' | 'failed'

export interface ConflictAnalysisStep {
  step: number
  tool_name: string
  title: string
  summary: string
  status: ConflictAnalysisStepStatus
}

export interface WorkspaceChangeSummary {
  repository_revision: number
  analysis_status: string
  analysis_current: boolean
  has_changes: boolean
  changed_file_count: number
  changed_line_count: number
  latest_conflict_job_id: string | null
  latest_conflict_artifact_id: string | null
  analyzed_revision: number | null
  report_stale: boolean
}

export interface ConflictCodeEvidence {
  side: 'before' | 'after'
  path: string
  line_start: number
  line_end: number
  quote: string
}

export interface ConflictPaperEvidence {
  block_id: string
  quote: string
  span_id?: string
  char_start?: number
  char_end?: number
  quote_hash?: string
  page?: number | null
  association: 'trace' | 'inferred'
}

export interface ConflictTraceReference {
  trace_id: string
}

export interface ConflictReportItem {
  id: string
  category: ConflictCategory
  severity: ConflictSeverity
  confidence: number
  title: string
  description: string
  affected_files: string[]
  change_evidence: ConflictCodeEvidence[]
  affected_symbols: string[]
  callers: string[]
  graph_node_ids: string[]
  trace_refs: ConflictTraceReference[]
  paper_evidence: ConflictPaperEvidence[]
  recommendations: string[]
  verification_steps: string[]
}

export interface ConflictReport {
  schema_version: 'conflict-agent-v1'
  language?: 'zh-CN'
  repository_revision: number
  overall_risk: ConflictSeverity
  summary: {
    high: number
    medium: number
    low: number
    total: number
    changed_files: number
    changed_lines: number
  }
  items: ConflictReportItem[]
  unresolved: string[]
}

export interface WorkspaceReportCard {
  value: string
  title: string
  description: string
}
