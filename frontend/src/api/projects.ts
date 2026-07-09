import { http } from '@/api/http'
import type {
  CodeRepository,
  PaperDocument,
  Project,
  ProjectCreate,
  TraceLink,
  TraceLinkCreate,
  TraceLinkSuggestion,
  WorkspaceCodeFile,
  WorkspaceCodeTreeNode,
  WorkspaceTensorFlow,
} from '@/types/api'

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

export async function uploadPaper(projectId: number, file: File): Promise<PaperDocument> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<PaperDocument>(`/projects/${projectId}/paper`, form)
  return data
}

export async function getPaper(projectId: number): Promise<PaperDocument> {
  const { data } = await http.get<PaperDocument>(`/projects/${projectId}/paper`)
  return data
}

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
