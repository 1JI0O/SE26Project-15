export type AgentThinkingMode = '' | 'enabled' | 'disabled'
export type MinerUProvider = 'local' | 'official'

export interface AgentIntegrationSettings {
  enabled: boolean
  base_url: string
  model: string
  thinking_mode: AgentThinkingMode
  timeout_seconds: number
  api_key_configured: boolean
}

export interface MinerUIntegrationSettings {
  provider: MinerUProvider
  local_url: string
  backend: string
  language: string
  parse_method: string
  official_api_url: string
  official_api_model: string
  api_token_configured: boolean
  ocr: boolean
  formula_enable: boolean
  table_enable: boolean
  request_timeout_seconds: number
  request_retries: number
  task_timeout_seconds: number
  poll_interval_seconds: number
}

export interface IntegrationSettings {
  agent: AgentIntegrationSettings
  mineru: MinerUIntegrationSettings
  source: 'environment' | 'application'
  updated_at: string | null
}

export interface IntegrationSettingsUpdate {
  agent: Omit<AgentIntegrationSettings, 'api_key_configured'> & {
    api_key?: string
    clear_api_key: boolean
  }
  mineru: Omit<MinerUIntegrationSettings, 'api_token_configured'> & {
    official_api_token?: string
    clear_api_token: boolean
  }
}
