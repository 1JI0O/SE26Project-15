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

export interface WorkspacePaperPage {
  page_number: number
  title: string
  body: string[]
  anchors: Array<Record<string, unknown>>
}

export type TagType = 'success' | 'warning' | 'info' | 'primary' | 'danger'

export interface WorkspaceImportStep {
  index: string
  title: string
  description: string
  status: string
  tag_type: TagType
  action?: string
}

export interface WorkspaceTraceRow {
  paper_ref: string
  code_ref: string
  relation_type: string
  confidence: number
  rationale: string
}

export interface WorkspaceCodeTreeNode {
  name: string
  path: string
  kind: 'folder' | 'file'
  meta: string
  children: WorkspaceCodeTreeNode[]
}

export interface WorkspaceCodeFile {
  path: string
  name: string
  badge: string
  status: string
  status_type: string
  symbol: string
  paper_ref: string
  content: string
  linked_lines: number[]
}

export interface WorkspaceTensorFlow {
  project_id: string
  renderer: 'trace-svg'
  nodes: Array<{
    id: string
    label: string
    kind: string
    description: string
    source_path: string
    line_start: number
    line_end: number
    tensor_shape: string
    x: number
    y: number
    width: number
    height: number
  }>
  edges: Array<{
    id: string
    source: string
    target: string
    label: string
    points: number[][]
  }>
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
