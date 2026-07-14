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

export interface ProjectBatchDeleteResult {
  deleted_ids: number[]
  missing_ids: number[]
}
