import { http } from '@/api/http'
import type { PaperDocument, WorkspacePaperPage } from '@/types/papers'

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

export async function getWorkspacePaperPages(
  projectId: number | string,
): Promise<WorkspacePaperPage[]> {
  const { data } = await http.get<WorkspacePaperPage[]>(
    `/projects/${projectId}/workspace/paper-pages`,
  )
  return data
}
