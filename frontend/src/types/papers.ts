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

export interface WorkspacePaperPage {
  page_number: number
  title: string
  body: string[]
  anchors: Array<Record<string, unknown>>
}
