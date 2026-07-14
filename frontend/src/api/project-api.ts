import { http } from '@/api/http'
import type {
  Project,
  ProjectBatchDeleteResult,
  ProjectCreate,
} from '@/types/projects'

export async function listProjects(): Promise<Project[]> {
  const { data } = await http.get<Project[]>('/projects')
  return data
}

export async function createProject(payload: ProjectCreate): Promise<Project> {
  const { data } = await http.post<Project>('/projects', payload)
  return data
}

export async function getProject(projectId: number): Promise<Project> {
  const { data } = await http.get<Project>(`/projects/${projectId}`)
  return data
}

export async function deleteProjects(
  projectIds: number[],
): Promise<ProjectBatchDeleteResult> {
  const { data } = await http.post<ProjectBatchDeleteResult>(
    '/projects/batch-delete',
    { project_ids: projectIds },
  )
  return data
}
