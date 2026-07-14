import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getWorkspaceTraceMatrix,
  listTraceLinks,
  suggestTraceLinks,
  updateTraceStatus,
} from '@/api/trace-api'
import type { TraceLink, TraceStatus, WorkspaceTraceRow } from '@/types/tracing'

export interface TraceRowView {
  id?: string
  paper: string
  code: string
  type: string
  confidence: number
  rationale: string
  source: string
  status: TraceStatus | 'preview'
  evidenceCount: number
  uncertainty: string
}

function fromTraceLink(link: TraceLink): TraceRowView {
  return {
    id: link.id,
    paper: link.paper_block_id,
    code: link.code_symbol_id,
    type: link.relation_type,
    confidence: Math.round(link.confidence * 100),
    rationale: link.rationale,
    source: link.source,
    status: link.status,
    evidenceCount: link.evidence.length,
    uncertainty: link.uncertainty.level,
  }
}

function fromWorkspaceRow(row: WorkspaceTraceRow): TraceRowView {
  return {
    paper: row.paper_ref,
    code: row.code_ref,
    type: row.relation_type,
    confidence: row.confidence,
    rationale: row.rationale,
    source: 'preview',
    status: 'preview',
    evidenceCount: 0,
    uncertainty: 'unknown',
  }
}

export function useTrace(projectId: () => number) {
  const traceRows = ref<TraceRowView[]>([])
  const loading = ref(false)
  const generating = ref(false)
  const error = ref<string | null>(null)
  const mode = ref('')
  const degraded = ref(false)
  const degradedReason = ref<string | null>(null)

  async function loadTraceRows(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const links = await listTraceLinks(projectId())
      if (links.length) {
        traceRows.value = links.map(fromTraceLink)
      } else {
        const rows = await getWorkspaceTraceMatrix(projectId())
        traceRows.value = rows.map(fromWorkspaceRow)
      }
    } catch (cause) {
      traceRows.value = []
      error.value = '追溯矩阵加载失败'
      console.error(cause)
    } finally {
      loading.value = false
    }
  }

  async function generateSuggestions(useLlm = true): Promise<void> {
    generating.value = true
    error.value = null
    try {
      const response = await suggestTraceLinks(projectId(), useLlm)
      mode.value = response.mode
      degraded.value = response.degraded
      degradedReason.value = response.degraded_reason
      traceRows.value = response.items.map(fromTraceLink)
      ElMessage.success(`已生成 ${response.items.length} 条追溯候选`)
    } catch (cause) {
      ElMessage.error('生成追溯候选失败，请确认论文和代码均已导入')
      console.error(cause)
    } finally {
      generating.value = false
    }
  }

  async function reviewTrace(
    traceId: string,
    status: Extract<TraceStatus, 'accepted' | 'rejected'>,
  ): Promise<void> {
    try {
      const updated = await updateTraceStatus(projectId(), traceId, status)
      const index = traceRows.value.findIndex((row) => row.id === traceId)
      if (index >= 0) traceRows.value[index] = fromTraceLink(updated)
      ElMessage.success(status === 'accepted' ? '追溯关系已接受' : '追溯关系已拒绝')
    } catch (cause) {
      ElMessage.error('追溯审阅状态更新失败')
      console.error(cause)
    }
  }

  return {
    traceRows,
    loading,
    generating,
    error,
    mode,
    degraded,
    degradedReason,
    loadTraceRows,
    generateSuggestions,
    reviewTrace,
  }
}
