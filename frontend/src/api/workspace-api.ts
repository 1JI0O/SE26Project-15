import { http } from '@/api/http'

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
