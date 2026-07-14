import { ref } from 'vue'
import { getWorkspaceTraceMatrix } from '@/api/trace-api'
import type { WorkspaceTraceRow } from '@/types/tracing'

export interface TraceRowView {
  paper: string
  code: string
  type: string
  confidence: number
  rationale: string
}

export function useTrace(projectId: () => number) {
  const traceRows = ref<TraceRowView[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadTraceRows(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const rows = await getWorkspaceTraceMatrix(projectId())
      traceRows.value = rows.map((row: WorkspaceTraceRow) => ({
        paper: row.paper_ref,
        code: row.code_ref,
        type: row.relation_type,
        confidence: row.confidence,
        rationale: row.rationale,
      }))
    } catch {
      traceRows.value = []
      error.value = '追溯矩阵加载失败'
    } finally {
      loading.value = false
    }
  }

  return {
    traceRows,
    loading,
    error,
    loadTraceRows,
  }
}
