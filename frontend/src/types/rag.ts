export type RagScope = 'paper' | 'code' | 'trace'
export type RagIndexStatus = 'pending' | 'building' | 'ready' | 'failed'

export interface RagScopeState {
  scope: RagScope
  status: RagIndexStatus
  chunk_count: number
  embedder: string
  model: string
  dimensions: number
  error: string | null
  built_at: string | null
}

export interface RagIndexStatusRead {
  enabled: boolean
  embedder: string
  model: string
  scopes: RagScopeState[]
}

export interface RagRebuildRequest {
  /** Omit to rebuild every scope. */
  scope?: RagScope
  /** Rebuild even when the stored generation already matches the source. */
  force?: boolean
}

export interface RagScopeResult {
  scope: string
  status: string
  chunk_count: number
  reused?: boolean
  reason?: string
}

export interface RagRebuildResult {
  results: RagScopeResult[]
}

/** One retrieval hit. Extra keys depend on the scope (page/section, path/lines, verdict). */
export interface RagSearchItem {
  ref: string
  score: number
  text: string
  [key: string]: unknown
}

export interface RagSearchResult {
  ok: boolean
  items: RagSearchItem[]
  query: string
  scope: string
  embedder: string
  reason: string | null
  searched: number
}
