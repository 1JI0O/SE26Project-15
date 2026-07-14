import { http } from '@/api/http'
import type {
  CodeRepository,
  WorkspaceCodeFile,
  WorkspaceCodeTreeNode,
  WorkspaceTensorFlow,
} from '@/types/repositories'

export async function uploadCode(projectId: number, file: File): Promise<CodeRepository> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<CodeRepository>(`/projects/${projectId}/code`, form)
  return data
}

export async function getCode(projectId: number): Promise<CodeRepository> {
  const { data } = await http.get<CodeRepository>(`/projects/${projectId}/code`)
  return data
}

export async function getWorkspaceCodeTree(
  projectId: number | string,
): Promise<WorkspaceCodeTreeNode[]> {
  const { data } = await http.get<WorkspaceCodeTreeNode[]>(
    `/projects/${projectId}/workspace/code-tree`,
  )
  return data
}

export async function getWorkspaceCodeFile(
  projectId: number | string,
  filePath: string,
): Promise<WorkspaceCodeFile> {
  const { data } = await http.get<WorkspaceCodeFile>(
    `/projects/${projectId}/workspace/code-files/${filePath}`,
  )
  return data
}

export async function saveWorkspaceCodeFile(
  projectId: number | string,
  filePath: string,
  content: string,
): Promise<{ status: string; message: string }> {
  const { data } = await http.put<{ status: string; message: string }>(
    `/projects/${projectId}/workspace/code-files/${filePath}`,
    { content },
  )
  return data
}

export async function getWorkspaceTensorFlow(
  projectId: number | string,
): Promise<WorkspaceTensorFlow> {
  const { data } = await http.get<WorkspaceTensorFlow>(
    `/projects/${projectId}/workspace/tensor-flow`,
  )
  return data
}
