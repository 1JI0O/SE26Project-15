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

export interface WorkspacePaperSection {
  id: string
  title: string
  level: number
  page: number | null
}

export interface WorkspacePaperDocument {
  document_id: number
  filename: string
  title: string
  markdown: string
  sections: WorkspacePaperSection[]
  asset_base_url: string
  /** Original PDF endpoint, or null when the stored file is gone (markdown view only). */
  pdf_url: string | null
  parser: string
  parser_version: string
  source: 'mineru-markdown' | 'normalized-fallback'
  blocks: WorkspacePaperBlock[]
}

/** One text line of a block, with its box in the same normalized page space as `bbox`. */
export interface PaperBlockLine {
  text: string
  bbox: number[]
}

export interface WorkspacePaperBlock {
  id: string
  kind: string
  text: string
  page: number
  page_number?: number
  /**
   * Block box as `[x0, y0, x1, y1]`, each a 0-1 fraction of the page with a top-left
   * origin — multiply by a rendered page's width/height to get pixels.
   */
  bbox: number[] | null
  /**
   * Per-line boxes, present only for papers parsed with MinerU geometry capture.
   * Empty for older documents, which fall back to whole-block highlighting.
   */
  lines?: PaperBlockLine[]
  /**
   * Page size in PDF points that the boxes above were measured against, as
   * `[width, height]`. Lets the reader detect a page whose rendered shape disagrees
   * (rotation, or a MinerU/renderer mismatch) and suppress highlights rather than
   * draw them in the wrong place.
   */
  page_size?: number[] | null
  section_path: string[]
  render_anchor: string
  anchor_resolved: boolean
}
