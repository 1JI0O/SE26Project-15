export interface CloudUser {
  user_id: string
  email: string
  display_name: string
  status: string
  email_verified: boolean
  is_platform_admin: boolean
}

export interface CloudWorkspace {
  workspace_id: string
  name: string
  role: 'owner' | 'editor' | 'viewer'
  plan: string
  storage_limit_bytes: number
  workspace_seq: number
}

export interface CloudAuthResponse {
  access_token: string
  expires_in: number
  csrf_token: string | null
  refresh_token: string | null
  device_id: string | null
  user: CloudUser
  default_workspace: CloudWorkspace | null
}

export interface CloudProject {
  public_id: string
  workspace_id: string
  name: string
  description: string
  version: number
  sync_mode: 'cloud_enabled' | 'cloud_paused' | 'cloud_detached'
  agent_history_sync: boolean
  created_at: string
  updated_at: string
}

export interface SyncOperation {
  workspace_id: string
  device_id: string
  client_operation_id: string
  supersedes_operation_id?: string | null
  entity_type: string
  entity_public_id: string
  operation: 'upsert' | 'delete' | 'select_version'
  base_version: number
  payload: Record<string, unknown>
}

export type CloudEntityType =
  | 'paper_document'
  | 'code_repository'
  | 'code_edit'
  | 'paper_target'
  | 'code_target'
  | 'trace_link'
  | 'agent_conversation'
  | 'agent_message'
  | 'agent_run'
  | 'agent_run_event'
  | 'agent_memory'

export interface CloudDomainEntity {
  public_id: string
  project_public_id: string
  entity_type: CloudEntityType | string
  version: number
  payload: Record<string, unknown>
  deleted_at: string | null
  updated_at: string
}

export interface ArtifactVersion {
  version_id: string
  entity_type: string
  entity_public_id: string
  version_number: number
  blob_id: string
  is_current: boolean
  source_hash: string
  created_at: string
}

export interface SyncEvent {
  event_id: string
  workspace_seq: number
  entity_type: string
  entity_public_id: string
  operation: string
  entity_version: number
  payload: Record<string, unknown>
  created_at: string
}
