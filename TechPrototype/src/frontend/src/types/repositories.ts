export interface CodeRepository {
  id: number
  project_id: number
  filename: string
  file_tree: Array<Record<string, unknown>>
  symbols: Array<Record<string, unknown>>
  imports: Array<Record<string, unknown>>
  calls: Array<Record<string, unknown>>
  pytorch_candidates: Array<Record<string, unknown>>
  tensor_graph: TensorGraph | null
  summary: RepositorySummary | null
  revision: number
  created_at: string
}

export interface RepositorySummary {
  file_count: number
  python_file_count: number
  symbol_count: number
  call_count: number
  ignored_count: number
  total_bytes: number
}

export interface TensorGraph {
  nodes: Array<Record<string, unknown>>
  edges: Array<Record<string, unknown>>
  entry_symbols: string[]
  shape_status: string
  shape_reason: string | null
}

export interface CodeAnalysis {
  symbols: Array<Record<string, unknown>>
  imports: Array<Record<string, unknown>>
  calls: Array<Record<string, unknown>>
  pytorch_candidates: Array<Record<string, unknown>>
  tensor_graph: TensorGraph
  summary: RepositorySummary
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
  renderer: string
  view: 'architecture' | 'debug'
  root_symbol: string | null
  root_label: string | null
  available_roots: Array<{
    symbol_id: string
    label: string
    source_path: string
    score: number
  }>
  analysis_status: 'missing' | 'pending' | 'queued' | 'running' | 'ready' | 'failed' | 'stale'
  analysis_revision: number
  repository_revision: number
  stale: boolean
  nodes: Array<{
    id: string
    label: string
    kind: string
    description: string
    source_path: string
    line_start: number
    line_end: number
    tensor_shape: string | Array<number | null> | null
    shape_reason: string | null
    op: string
    symbol_id: string
    component_symbol_id: string | null
    expandable: boolean
    external: boolean
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
    kind: string
    points: number[][]
  }>
}
