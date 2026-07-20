import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getWorkspaceTraceMatrix,
  listTraceLinks,
  updateTraceStatus,
} from '@/api/trace-api'
import {
  createAgentAnalysisJob,
  getAgentAnalysisJob,
  streamAgentAnalysisJob,
} from '@/api/agent-api'
import type { TraceEvidence, TraceLink, TraceStatus, WorkspaceTraceRow } from '@/types/tracing'

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
  evidence: TraceEvidence[]
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
    evidence: link.evidence,
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
    evidence: [],
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
  const analysisProgress = ref('')

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

  async function runAnalysis(kind: 'architecture' | 'trace'): Promise<void> {
    const submitted = await createAgentAnalysisJob(projectId(), { kind, depth: 2 })
    analysisProgress.value = String(submitted.progress.message || '等待 Agent 分析')
    if (!['succeeded', 'failed'].includes(submitted.status)) {
      await streamAgentAnalysisJob(projectId(), submitted.job_id, (event) => {
        const message = event.payload.message
        if (typeof message === 'string') analysisProgress.value = message
      })
    }
    const completed = await getAgentAnalysisJob(projectId(), submitted.job_id)
    if (completed.status !== 'succeeded') {
      throw new Error(completed.error_code || `${kind}_analysis_failed`)
    }
  }

  async function generateSuggestions(): Promise<void> {
    generating.value = true
    error.value = null
    try {
      await runAnalysis('architecture')
      await runAnalysis('trace')
      mode.value = 'agent'
      degraded.value = false
      degradedReason.value = null
      await loadTraceRows()
      ElMessage.success(`Agent 已生成 ${traceRows.value.length} 条追溯候选`)
    } catch (cause) {
      degraded.value = true
      degradedReason.value = cause instanceof Error ? cause.message : 'agent_analysis_failed'
      ElMessage.error('Agent 分析失败，已保留现有追溯结果')
      console.error(cause)
    } finally {
      generating.value = false
      analysisProgress.value = ''
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
    analysisProgress,
    loadTraceRows,
    generateSuggestions,
    reviewTrace,
  }
}
