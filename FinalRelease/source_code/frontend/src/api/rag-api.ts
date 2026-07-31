import { http } from '@/api/http'
import type {
  RagIndexStatusRead,
  RagRebuildRequest,
  RagRebuildResult,
  RagScope,
  RagSearchResult,
} from '@/types/rag'

export async function getRagStatus(projectId: number): Promise<RagIndexStatusRead> {
  const { data } = await http.get<RagIndexStatusRead>(`/projects/${projectId}/rag/status`)
  return data
}

/**
 * Rebuild retrieval indexes. Runs server-side inline, so allow a generous timeout: a large
 * repository re-embedded through a remote provider takes longer than the default.
 */
export async function rebuildRagIndex(
  projectId: number,
  payload: RagRebuildRequest = {},
  timeoutMs = 180_000,
): Promise<RagRebuildResult> {
  const { data } = await http.post<RagRebuildResult>(
    `/projects/${projectId}/rag/rebuild`,
    payload,
    { timeout: timeoutMs },
  )
  return data
}

export async function searchRagIndex(
  projectId: number,
  query: string,
  scope: RagScope = 'paper',
  limit = 5,
): Promise<RagSearchResult> {
  const { data } = await http.get<RagSearchResult>(`/projects/${projectId}/rag/search`, {
    params: { query, scope, limit },
  })
  return data
}
