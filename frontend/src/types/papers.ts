export interface PaperDocument {
  id: number
  project_id: number
  filename: string
  title: string
  abstract: string
  sections: Array<Record<string, unknown>>
  paragraphs: Array<Record<string, unknown>>
  parser: string
  parser_version: string
  parse_status: string
  content_hash: string
  created_at: string
}

export interface PaperParseJob {
  id: string
  project_id: number
  filename: string
  parser: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  created_at: string
  updated_at: string
  external_task_id: string | null
  error: string | null
  cached: boolean
  document_id: number | null
}

export interface PaperParseResult {
  job: PaperParseJob
  document: PaperDocument
  parser: string
  parser_version: string
  pages: WorkspacePaperPage[]
}

export interface WorkspacePaperPage {
  page_number: number
  title: string
  body: string[]
  anchors: Array<Record<string, unknown>>
}
