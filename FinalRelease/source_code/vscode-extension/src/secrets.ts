import * as vscode from 'vscode'

const MINERU_TOKEN = 'tracelab.mineru.token'
const LLM_API_KEY = 'tracelab.llm.apiKey'

function isPlaceholderSecret(value: string): boolean {
  const trimmed = value.trim()
  return !trimmed || trimmed.includes('•••')
}

export class SecretStore {
  constructor(private readonly secrets: vscode.SecretStorage) {}

  async getMineruToken(): Promise<string> {
    return (await this.secrets.get(MINERU_TOKEN)) ?? ''
  }

  /** Store only when value is a real new token. Empty / placeholder never deletes. */
  async setMineruToken(value: string): Promise<void> {
    if (isPlaceholderSecret(value)) {
      return
    }
    await this.secrets.store(MINERU_TOKEN, value.trim())
  }

  async clearMineruToken(): Promise<void> {
    await this.secrets.delete(MINERU_TOKEN)
  }

  async getLlmApiKey(): Promise<string> {
    return (await this.secrets.get(LLM_API_KEY)) ?? ''
  }

  /** Store only when value is a real new key. Empty / placeholder never deletes. */
  async setLlmApiKey(value: string): Promise<void> {
    if (isPlaceholderSecret(value)) {
      return
    }
    await this.secrets.store(LLM_API_KEY, value.trim())
  }

  async clearLlmApiKey(): Promise<void> {
    await this.secrets.delete(LLM_API_KEY)
  }
}

export interface TraceLabSettingsSnapshot {
  mineru: {
    enabled: boolean
    provider: string
    base_url: string
    api_token: string
    model: string
    language: string
    request_timeout_seconds: number
    task_timeout_seconds: number
  }
  llm: {
    enabled: boolean
    base_url: string
    model: string
    thinking_mode: string
    timeout_seconds: number
    api_key: string
  }
}

export async function runtimeConfig(secrets: SecretStore): Promise<TraceLabSettingsSnapshot> {
  const cfg = vscode.workspace.getConfiguration('tracelab')
  const mineruToken = await secrets.getMineruToken()
  const llmKey = await secrets.getLlmApiKey()
  const provider = cfg.get<string>('mineru.provider', 'official')
  const mineruBaseUrl =
    cfg.get<string>('mineru.baseUrl') ||
    (provider === 'official' ? 'https://mineru.net/api/v4' : 'http://127.0.0.1:8001')
  const mineruEnabled =
    provider === 'official' ? Boolean(mineruToken.trim()) : Boolean(mineruBaseUrl.trim())

  return {
    mineru: {
      enabled: mineruEnabled,
      provider,
      base_url: mineruBaseUrl,
      api_token: mineruToken,
      model: cfg.get<string>('mineru.model', 'vlm'),
      language: cfg.get<string>('mineru.language', 'en'),
      request_timeout_seconds: cfg.get<number>('mineru.requestTimeoutSeconds', 120),
      task_timeout_seconds: cfg.get<number>('mineru.taskTimeoutSeconds', 1800),
    },
    llm: {
      enabled: Boolean(llmKey.trim()),
      base_url: cfg.get<string>('llm.baseUrl', 'https://api.deepseek.com/v1'),
      model: cfg.get<string>('llm.model', 'deepseek-chat'),
      thinking_mode: cfg.get<string>('llm.thinkingMode', ''),
      timeout_seconds: cfg.get<number>('llm.timeoutSeconds', 120),
      api_key: llmKey,
    },
  }
}

export async function publicSettingsView(secrets: SecretStore): Promise<Record<string, unknown>> {
  const full = await runtimeConfig(secrets)
  return {
    mineru: {
      ...full.mineru,
      api_token: '',
      has_token: Boolean(full.mineru.api_token),
    },
    llm: {
      ...full.llm,
      api_key: '',
      has_key: Boolean(full.llm.api_key),
    },
  }
}
