export interface Project {
  id: number
  name: string
  description: string
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  name: string
  description: string
}

export interface PaperDocument {
  id: number
  project_id: number
  filename: string
  title: string
  abstract: string
  sections: Array<Record<string, unknown>>
  paragraphs: Array<Record<string, unknown>>
  created_at: string
}

export interface CodeRepository {
  id: number
  project_id: number
  filename: string
  file_tree: Array<Record<string, unknown>>
  symbols: Array<Record<string, unknown>>
  imports: Array<Record<string, unknown>>
  pytorch_candidates: Array<Record<string, unknown>>
  created_at: string
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

export type TraceLinkSuggestion = Omit<TraceLinkCreate, never>

