export interface Project {
  id: number
  public_id: string
  name: string
  description: string
  version: number
  sync_mode: 'local_only' | 'cloud_enabled' | 'cloud_paused' | 'cloud_detached'
  agent_history_sync: boolean
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
