import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getWorkspacePaperPages, uploadPaper } from '@/api/paper-api'
import type { WorkspacePaperPage } from '@/types/papers'

export function usePaper(projectId: () => number) {
  const paperPageData = ref<WorkspacePaperPage[]>([])
  const paperFilename = ref('')
  const paperAbstract = ref('')
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
      const pages = await getWorkspacePaperPages(projectId())
      paperPageData.value = pages
      paperFilename.value = pages.length > 0 ? 'paper.pdf' : ''
      activePaperPage.value = pages[0]?.page_number ?? 1
      if (pages[0]?.body?.length) {
        paperAbstract.value = pages[0].body[0].slice(0, 500)
      }
    } catch {
      paperPageData.value = []
      paperFilename.value = ''
      paperAbstract.value = ''
      error.value = '论文数据加载失败'
    } finally {
      loading.value = false
    }
  }

  async function handleUpload(file: File): Promise<boolean> {
    uploading.value = true
    try {
      const paper = await uploadPaper(projectId(), file)
      paperFilename.value = paper.filename
      paperAbstract.value = paper.abstract
      await loadPaperPages()
      ElMessage.success('论文上传并解析完成')
      return true
    } catch (e) {
      ElMessage.error('论文上传失败')
      console.error(e)
      return false
    } finally {
      uploading.value = false
    }
  }

  return {
    paperPageData,
    paperFilename,
    paperAbstract,
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
