import { http } from '@/api/http'
import type {
  TraceLink,
  TraceLinkCreate,
  TraceLinkSuggestion,
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

export async function suggestTraceLinks(projectId: number): Promise<TraceLinkSuggestion[]> {
  const { data } = await http.post<TraceLinkSuggestion[]>(
    `/projects/${projectId}/trace-links/suggest`,
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
