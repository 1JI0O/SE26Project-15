import { http } from '@/api/http'
import type {
  PaperDocument,
  PaperParseJob,
  PaperParseResult,
  WorkspacePaperPage,
} from '@/types/papers'

export async function uploadPaper(projectId: number, file: File): Promise<PaperDocument> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<PaperDocument>(`/projects/${projectId}/paper`, form)
  return data
}

export async function submitPaperParseJob(
  projectId: number,
  file: File,
): Promise<PaperParseJob> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<PaperParseJob>(`/projects/${projectId}/paper-jobs`, form)
  return data
}

export async function getPaperParseJob(
  projectId: number,
  jobId: string,
): Promise<PaperParseJob> {
  const { data } = await http.get<PaperParseJob>(
    `/projects/${projectId}/paper-jobs/${jobId}`,
  )
  return data
}

export async function getPaperParseResult(
  projectId: number,
  jobId: string,
): Promise<PaperParseResult> {
  const { data } = await http.get<PaperParseResult>(
    `/projects/${projectId}/paper-jobs/${jobId}/result`,
  )
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
