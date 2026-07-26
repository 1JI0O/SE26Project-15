import { http } from '@/api/http'
import type {
  PaperDocument,
  PaperParseJob,
  PaperParseResult,
  WorkspacePaperDocument,
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

export async function getWorkspacePaperDocument(
  projectId: number,
): Promise<WorkspacePaperDocument> {
  const { data } = await http.get<WorkspacePaperDocument>(
    `/projects/${projectId}/workspace/paper-document`,
  )
  return data
}

/**
 * Fetch the original PDF as bytes for pdf.js.
 *
 * Routed through the shared axios client rather than handed to pdf.js as a URL so it
 * inherits the configured base URL and interceptors, and so the desktop shell (which
 * talks to a sidecar on a different port) resolves it the same way as every other call.
 */
export async function getPaperPdfData(pdfUrl: string): Promise<ArrayBuffer> {
  const { data } = await http.get<ArrayBuffer>(pdfUrl, { responseType: 'arraybuffer' })
  return data
}

export function resolvePaperAssetUrl(assetBaseUrl: string, assetPath: string): string {
  if (/^(?:data:image\/|blob:)/i.test(assetPath)) return assetPath
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(assetPath)) return ''
  const normalizedPath = assetPath.replace(/^\.\//, '').replace(/^\//, '')
  const apiBase = String(http.defaults.baseURL || '').replace(/\/$/, '')
  const assetBase = assetBaseUrl.replace(/\/$/, '')
  return `${apiBase}${assetBase}/${normalizedPath}`
}

export async function getPaperAssetBlob(assetUrl: string): Promise<Blob> {
  const apiBase = String(http.defaults.baseURL || '').replace(/\/$/, '')
  if (/^https?:/i.test(assetUrl) && !assetUrl.startsWith(`${apiBase}/`)) {
    throw new Error('paper_asset_url_not_allowed')
  }
  const { data } = await http.get<Blob>(assetUrl, { responseType: 'blob' })
  return data
}
