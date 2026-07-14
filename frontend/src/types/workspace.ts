export type TagType = 'success' | 'warning' | 'info' | 'primary' | 'danger'

export interface WorkspaceImportStep {
  index: string
  title: string
  description: string
  status: string
  tag_type: TagType
  action?: string
}
