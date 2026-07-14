import { http } from '@/api/http'
import type {
  TraceLink,
  TraceLinkCreate,
  TraceStatus,
  TraceSuggestionResponse,
  WorkspaceTraceRow,
} from '@/types/tracing'

export async function listTraceLinks(projectId: number): Promise<TraceLink[]> {
  const { data } = await http.get<TraceLink[]>(`/projects/${projectId}/trace-links`)
  return data
}

export async function createTraceLink(
  projectId: number,
  payload: TraceLinkCreate,
): Promise<TraceLink> {
  const { data } = await http.post<TraceLink>(`/projects/${projectId}/trace-links`, payload)
  return data
}

export async function suggestTraceLinks(
  projectId: number,
  useLlm = true,
): Promise<TraceSuggestionResponse> {
  const { data } = await http.post<TraceSuggestionResponse>(
    `/projects/${projectId}/trace-links/suggest`,
    { use_llm: useLlm },
  )
  return data
}

export async function updateTraceStatus(
  projectId: number,
  traceId: string,
  status: Extract<TraceStatus, 'accepted' | 'rejected'>,
): Promise<TraceLink> {
  const { data } = await http.patch<TraceLink>(
    `/projects/${projectId}/trace-links/${traceId}/status`,
    { status },
  )
  return data
}

export async function getWorkspaceTraceMatrix(
  projectId: number | string,
): Promise<WorkspaceTraceRow[]> {
  const { data } = await http.get<WorkspaceTraceRow[]>(
    `/projects/${projectId}/workspace/trace-matrix`,
  )
  return data
}
