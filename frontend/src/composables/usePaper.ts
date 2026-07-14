import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { isAxiosError } from 'axios'
import {
  getPaper,
  getPaperParseJob,
  getPaperParseResult,
  getWorkspacePaperPages,
  submitPaperParseJob,
} from '@/api/paper-api'
import type { PaperParseJob, WorkspacePaperPage } from '@/types/papers'

const POLL_INTERVAL_MS = 800
const PARSE_TIMEOUT_MS = 10 * 60 * 1000

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function isNotFound(error: unknown): boolean {
  return isAxiosError(error) && error.response?.status === 404
}

export function usePaper(projectId: () => number) {
  const paperPageData = ref<WorkspacePaperPage[]>([])
  const paperFilename = ref('')
  const paperAbstract = ref('')
  const parserName = ref('')
  const parseStatus = ref<PaperParseJob['status'] | 'idle'>('idle')
  const activePaperPage = ref(1)
  const uploading = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const paperPageNumbers = computed(() => paperPageData.value.map((p) => p.page_number))
  const activePaperContent = computed(() =>
    paperPageData.value.find((p) => p.page_number === activePaperPage.value),
  )
  const hasPaper = computed(() => paperPageData.value.length > 0)

  async function loadPaperPages(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [pages, document] = await Promise.all([
        getWorkspacePaperPages(projectId()),
        getPaper(projectId()),
      ])
      paperPageData.value = pages
      paperFilename.value = document.filename
      paperAbstract.value = document.abstract
      parserName.value = document.parser
      parseStatus.value = 'succeeded'
      activePaperPage.value = pages[0]?.page_number ?? 1
    } catch (cause) {
      paperPageData.value = []
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
      const job = await getPaperParseJob(projectId(), jobId)
      parseStatus.value = job.status
      if (job.status === 'succeeded' || job.status === 'failed') return job
      await sleep(POLL_INTERVAL_MS)
    }
    throw new Error('论文解析等待超时')
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
      paperPageData.value = result.pages
      paperFilename.value = result.document.filename
      paperAbstract.value = result.document.abstract
      parserName.value = `${result.parser} ${result.parser_version}`.trim()
      activePaperPage.value = result.pages[0]?.page_number ?? 1
      ElMessage.success(completed.cached ? '论文解析完成（命中缓存）' : '论文解析完成')
      return true
    } catch (cause) {
      parseStatus.value = 'failed'
      error.value = cause instanceof Error ? cause.message : '论文上传失败'
      ElMessage.error(error.value)
      return false
    } finally {
      uploading.value = false
    }
  }

  return {
    paperPageData,
    paperFilename,
    paperAbstract,
    parserName,
    parseStatus,
    activePaperPage,
    uploading,
    loading,
    error,
    paperPageNumbers,
    activePaperContent,
    hasPaper,
    loadPaperPages,
    handleUpload,
  }
}
