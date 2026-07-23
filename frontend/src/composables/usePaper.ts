import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { isAxiosError } from 'axios'
import {
  getPaper,
  getPaperParseJob,
  getPaperParseResult,
  getWorkspacePaperDocument,
  submitPaperParseJob,
} from '@/api/paper-api'
import type { PaperParseJob, WorkspacePaperDocument } from '@/types/papers'

const POLL_INTERVAL_MS = 800
const PARSE_TIMEOUT_MS = 10 * 60 * 1000

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function isNotFound(error: unknown): boolean {
  return isAxiosError(error) && error.response?.status === 404
}

export function usePaper(projectId: () => number) {
  const paperDocument = ref<WorkspacePaperDocument | null>(null)
  const paperFilename = ref('')
  const paperAbstract = ref('')
  const parserName = ref('')
  const parseStatus = ref<PaperParseJob['status'] | 'idle'>('idle')
  // `activeSectionId` = explicit user jump intent (TOC click) — the only thing allowed to scroll.
  // `observedSectionId` = section currently scrolled into view (IntersectionObserver), for TOC
  // highlight only; it never drives a scroll, so wheel scrolling can't fight a jump.
  const activeSectionId = ref('')
  const observedSectionId = ref('')
  const uploading = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  // Set on unmount so an in-flight parse poll stops instead of hitting /projects/NaN/... (422)
  // once the route id becomes undefined after navigating away from the workbench.
  let cancelled = false

  const paperSections = computed(() => paperDocument.value?.sections ?? [])
  const hasPaper = computed(() => Boolean(paperDocument.value?.markdown))

  async function loadPaperPages(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [structuredDocument, document] = await Promise.all([
        getWorkspacePaperDocument(projectId()),
        getPaper(projectId()),
      ])
      paperDocument.value = structuredDocument
      paperFilename.value = document.filename
      paperAbstract.value = document.abstract
      parserName.value = `${document.parser} ${document.parser_version}`.trim()
      parseStatus.value = 'succeeded'
      activeSectionId.value = structuredDocument.sections[0]?.id ?? ''
    } catch (cause) {
      paperDocument.value = null
      paperFilename.value = ''
      paperAbstract.value = ''
      parserName.value = ''
      if (!isNotFound(cause)) error.value = '论文数据加载失败'
    } finally {
      loading.value = false
    }
  }

  async function waitForJob(jobId: string): Promise<PaperParseJob> {
    const deadline = Date.now() + PARSE_TIMEOUT_MS
    while (Date.now() < deadline) {
      const pid = projectId()
      // Stop cleanly if the composable was torn down or the route id is gone (navigation),
      // rather than polling /projects/NaN/paper-jobs/... which the backend rejects with 422.
      if (cancelled || !Number.isFinite(pid)) throw new Error('parse_poll_cancelled')
      const job = await getPaperParseJob(pid, jobId)
      parseStatus.value = job.status
      if (job.status === 'succeeded' || job.status === 'failed') return job
      await sleep(POLL_INTERVAL_MS)
    }
    throw new Error('论文解析等待超时')
  }

  function cancelPolling(): void {
    cancelled = true
  }

  function selectSection(sectionId: string): void {
    activeSectionId.value = sectionId
  }

  function observeSection(sectionId: string): void {
    observedSectionId.value = sectionId
  }

  async function handleUpload(file: File): Promise<boolean> {
    uploading.value = true
    error.value = null
    paperFilename.value = file.name
    try {
      const submitted = await submitPaperParseJob(projectId(), file)
      parseStatus.value = submitted.status
      parserName.value = submitted.parser
      const completed = await waitForJob(submitted.id)
      if (completed.status === 'failed') {
        throw new Error(completed.error || '论文解析失败')
      }
      const result = await getPaperParseResult(projectId(), submitted.id)
      paperFilename.value = result.document.filename
      paperAbstract.value = result.document.abstract
      parserName.value = `${result.parser} ${result.parser_version}`.trim()
      paperDocument.value = await getWorkspacePaperDocument(projectId())
      activeSectionId.value = paperDocument.value.sections[0]?.id ?? ''
      ElMessage.success(completed.cached ? '论文解析完成（命中缓存）' : '论文解析完成')
      return true
    } catch (cause) {
      if (cancelled || (cause instanceof Error && cause.message === 'parse_poll_cancelled')) {
        return false // navigated away mid-parse; not a real failure, stay silent
      }
      parseStatus.value = 'failed'
      error.value = cause instanceof Error ? cause.message : '论文上传失败'
      ElMessage.error(error.value)
      return false
    } finally {
      uploading.value = false
    }
  }

  return {
    paperDocument,
    paperFilename,
    paperAbstract,
    parserName,
    parseStatus,
    activeSectionId,
    observedSectionId,
    uploading,
    loading,
    error,
    paperSections,
    hasPaper,
    loadPaperPages,
    handleUpload,
    selectSection,
    observeSection,
    cancelPolling,
  }
}
