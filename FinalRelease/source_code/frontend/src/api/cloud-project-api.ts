import { cloudHttp } from '@/api/http'
import type { CloudProject } from '@/types/cloud'

export async function listCloudProjects(workspaceId?: string): Promise<CloudProject[]> {
  const { data } = await cloudHttp.get<CloudProject[]>('/projects', {
    params: workspaceId ? { workspace_id: workspaceId } : undefined,
  })
  return data
}

export async function createCloudProject(payload: {
  workspace_id: string
  name: string
  description: string
  agent_history_sync: boolean
}): Promise<CloudProject> {
  const { data } = await cloudHttp.post<CloudProject>('/projects', payload)
  return data
}

export async function getCloudProject(projectId: string): Promise<CloudProject> {
  const { data } = await cloudHttp.get<CloudProject>(`/projects/${projectId}`)
  return data
}

export async function deleteCloudProject(project: CloudProject): Promise<void> {
  await cloudHttp.delete(`/projects/${project.public_id}`, {
    params: { base_version: project.version },
  })
}
