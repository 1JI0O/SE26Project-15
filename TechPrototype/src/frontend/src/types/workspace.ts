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
  level: string
  type: TagType
  title: string
  description: string
  affected_files: string[]
  status: string
}

export interface WorkspaceReportCard {
  value: string
  title: string
  description: string
}
