import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  batchUpdateTraceStatus,
  getWorkspaceTraceMatrix,
  listTraceLinks,
  updateTraceStatus,
} from '@/api/trace-api'
import {
  cancelAgentAnalysisJob,
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
  // Raw links power the bidirectional hover index (fragment anchoring + relevance).
  const traceLinks = ref<TraceLink[]>([])
  const loading = ref(false)
  const generating = ref(false)
  const error = ref<string | null>(null)
  const mode = ref('')
  const degraded = ref(false)
  const degradedReason = ref<string | null>(null)
  const analysisProgress = ref('')
  const analysisActivity = ref('')
  const analysisStep = ref(0)
  const analysisBudget = ref(0)
  const analysisLog = ref<string[]>([])
  // Id of the in-flight analysis job, so the user can interrupt it and keep partial results.
  const currentJobId = ref<string | null>(null)
  const cancelling = ref(false)
  let cancelledRun = false

  async function loadTraceRows(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const links = await listTraceLinks(projectId())
      if (links.length) {
        traceLinks.value = links
        traceRows.value = links.map(fromTraceLink)
      } else {
        traceLinks.value = []
        const rows = await getWorkspaceTraceMatrix(projectId())
        traceRows.value = rows.map(fromWorkspaceRow)
      }
    } catch (cause) {
      traceLinks.value = []
      traceRows.value = []
      error.value = '追溯矩阵加载失败'
      console.error(cause)
    } finally {
      loading.value = false
    }
  }

  function pushLog(entry: string): void {
    analysisLog.value = [...analysisLog.value.slice(-15), entry]
  }

  // Progressive render: pull the links published so far and swap them in as batches arrive,
  // instead of waiting for the whole run to finish. Guarded so overlapping events don't race.
  let mergingLinks = false
  async function mergePublishedLinks(): Promise<void> {
    if (mergingLinks) return
    mergingLinks = true
    try {
      const links = await listTraceLinks(projectId())
      if (links.length) {
        traceLinks.value = links
        traceRows.value = links.map(fromTraceLink)
        mode.value = 'agent'
      }
    } catch (cause) {
      console.warn('progressive trace merge failed', cause)
    } finally {
      mergingLinks = false
    }
  }

  async function runAnalysis(kind: 'architecture' | 'trace', force = false): Promise<void> {
    const submitted = await createAgentAnalysisJob(projectId(), { kind, depth: 2, force })
    currentJobId.value = submitted.job_id
    analysisProgress.value = String(submitted.progress.message || '等待 Agent 分析')
    analysisActivity.value = analysisProgress.value
    analysisLog.value = []
    if (submitted.status === 'queued') {
      analysisActivity.value = '排队等待 Agent 分析（可能有其他任务占用分析线程）'
      analysisProgress.value = analysisActivity.value
      pushLog(analysisActivity.value)
    }
    if (!['succeeded', 'failed'].includes(submitted.status)) {
      await streamAgentAnalysisJob(projectId(), submitted.job_id, (event) => {
        const p = event.payload as Record<string, unknown>
        const activity = (p.activity ?? p.message) as string | undefined
        if (typeof p.step === 'number') analysisStep.value = p.step
        if (typeof p.budget === 'number') analysisBudget.value = p.budget
        if (typeof activity === 'string' && activity) {
          analysisActivity.value = activity
          analysisProgress.value = activity
        }
        if (event.event_type === 'analysis.progress' && typeof activity === 'string') {
          // Queued jobs have no run events yet; progress comes from job.progress_json.
          return
        }
        if (event.event_type === 'analysis.tool.started' && typeof activity === 'string') {
          pushLog(`#${analysisStep.value} ${activity}`)
        } else if (event.event_type === 'analysis.tool.failed') {
          pushLog(`⚠ ${String(p.code ?? '重试')}`)
        } else if (event.event_type === 'analysis.published') {
          const total = Number(p.total_links ?? 0)
          pushLog(`✓ 新增 ${Number(p.new_links ?? 0)} 条（累计 ${total}）`)
          void mergePublishedLinks() // render progressively as batches land
        } else if (event.event_type === 'analysis.completed') {
          pushLog('✓ 追溯完成')
        } else if (event.event_type === 'analysis.validating') {
          analysisActivity.value = '正在校验并保存证据'
        } else if (event.event_type === 'analysis.started') {
          analysisActivity.value = 'Agent 正在检查证据'
          analysisProgress.value = analysisActivity.value
          pushLog('开始分析')
        }
      })
    }
    const completed = await getAgentAnalysisJob(projectId(), submitted.job_id)
    if (completed.status !== 'succeeded') {
      throw new Error(completed.error_code || `${kind}_analysis_failed`)
    }
  }

  async function generateSuggestions(force = false): Promise<void> {
    generating.value = true
    cancelling.value = false
    cancelledRun = false
    error.value = null
    if (force) {
      traceLinks.value = []
      traceRows.value = []
      mode.value = ''
      degraded.value = false
      degradedReason.value = null
      analysisLog.value = []
      analysisProgress.value = ''
      analysisActivity.value = ''
      analysisStep.value = 0
    }
    try {
      // Always force a fresh job on explicit user click. Reusing a stuck
      // queued/running fingerprint made the UI freeze on「等待 Agent 分析」.
      await runAnalysis('trace', true)
      mode.value = 'agent'
      degraded.value = false
      degradedReason.value = null
      await loadTraceRows()
      if (cancelledRun) {
        ElMessage.success(`已中止追溯，保留 ${traceRows.value.length} 条已发现关系`)
      } else {
        ElMessage.success(`Agent 已生成 ${traceRows.value.length} 条追溯候选`)
      }
    } catch (cause) {
      degraded.value = true
      degradedReason.value = cause instanceof Error ? cause.message : 'agent_analysis_failed'
      ElMessage.error('Agent 追溯失败，已保留现有追溯结果')
      console.error(cause)
    } finally {
      generating.value = false
      cancelling.value = false
      currentJobId.value = null
      analysisProgress.value = ''
    }
  }

  // Interrupt the running trace early. Already-published links are kept; the backend
  // finalizes the job as succeeded so loadTraceRows renders whatever was found.
  async function cancelAnalysis(): Promise<void> {
    const jobId = currentJobId.value
    if (!jobId || cancelling.value) return
    cancelling.value = true
    cancelledRun = true
    analysisActivity.value = '正在中止追溯（保留已发现的关系）'
    pushLog('⏹ 中止追溯，保留已发现的关系')
    try {
      await cancelAgentAnalysisJob(projectId(), jobId)
    } catch (cause) {
      cancelling.value = false
      cancelledRun = false
      ElMessage.error('中止追溯失败')
      console.error(cause)
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
      const linkIndex = traceLinks.value.findIndex((link) => link.id === traceId)
      if (linkIndex >= 0) traceLinks.value[linkIndex] = updated
      ElMessage.success(status === 'accepted' ? '追溯关系已接受' : '追溯关系已拒绝')
    } catch (cause) {
      ElMessage.error('追溯审阅状态更新失败')
      console.error(cause)
    }
  }

  // Accept/reject many proposed links at once. Pass explicit ids for a selection, or omit
  // them to review every currently-proposed link in the project.
  async function reviewBatch(
    status: Extract<TraceStatus, 'accepted' | 'rejected'>,
    traceIds?: string[],
  ): Promise<void> {
    try {
      const result = await batchUpdateTraceStatus(projectId(), status, traceIds)
      const updatedById = new Map(result.updated.map((link) => [link.id, link]))
      traceRows.value = traceRows.value.map((row) =>
        row.id && updatedById.has(row.id) ? fromTraceLink(updatedById.get(row.id)!) : row,
      )
      traceLinks.value = traceLinks.value.map((link) =>
        updatedById.has(link.id) ? updatedById.get(link.id)! : link,
      )
      if (result.updated_count) {
        ElMessage.success(
          `${status === 'accepted' ? '已接受' : '已拒绝'} ${result.updated_count} 条追溯关系`,
        )
      } else {
        ElMessage.info('没有可审阅的候选关系')
      }
    } catch (cause) {
      ElMessage.error('批量审阅失败')
      console.error(cause)
    }
  }

  return {
    traceRows,
    traceLinks,
    loading,
    generating,
    cancelling,
    error,
    mode,
    degraded,
    degradedReason,
    analysisProgress,
    analysisActivity,
    analysisStep,
    analysisBudget,
    analysisLog,
    currentJobId,
    loadTraceRows,
    generateSuggestions,
    cancelAnalysis,
    reviewTrace,
    reviewBatch,
  }
}
