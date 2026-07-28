import { http } from '@/api/http'
import type {
  WorkspaceChangeSummary,
  WorkspaceConflictItem,
  WorkspaceReportCard,
} from '@/types/workspace'

export interface AnalysisRequest {
  mode: string
  targets: string[]
}

export interface AnalysisJob {
  project_id: string
  job_id: string
  status: string
  message: string
}

export async function startWorkspaceAnalysis(
  projectId: number | string,
  payload: AnalysisRequest,
): Promise<AnalysisJob> {
  const { data } = await http.post<AnalysisJob>(
    `/projects/${projectId}/workspace/analyze`,
    payload,
  )
  return data
}

export async function getWorkspaceConflicts(
  projectId: number | string,
): Promise<WorkspaceConflictItem[]> {
  const { data } = await http.get<WorkspaceConflictItem[]>(
    `/projects/${projectId}/workspace/conflicts`,
  )
  return data
}

export async function getWorkspaceChangeSummary(
  projectId: number | string,
): Promise<WorkspaceChangeSummary> {
  const { data } = await http.get<WorkspaceChangeSummary>(
    `/projects/${projectId}/workspace/change-summary`,
  )
  return data
}

export async function getWorkspaceReportSummary(
  projectId: number | string,
): Promise<WorkspaceReportCard[]> {
  const { data } = await http.get<WorkspaceReportCard[]>(
    `/projects/${projectId}/workspace/report-summary`,
  )
  return data
}
