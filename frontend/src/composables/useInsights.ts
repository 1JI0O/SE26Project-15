import { ref } from 'vue'

import {
  cancelAgentAnalysisJob,
  createAgentAnalysisJob,
  getAgentAnalysisArtifact,
  getAgentAnalysisJob,
  streamAgentAnalysisJob,
} from '@/api/agent-api'
import { extractErrorDetail } from '@/api/http'
import {
  getWorkspaceChangeSummary,
  getWorkspaceConflicts,
} from '@/api/workspace-api'
import type {
  ConflictAnalysisStep,
  ConflictReport,
  WorkspaceChangeSummary,
  WorkspaceConflictItem,
} from '@/types/workspace'

const EMPTY_SUMMARY: WorkspaceChangeSummary = {
  repository_revision: 0,
  analysis_status: 'missing',
  analysis_current: false,
  has_changes: false,
  changed_file_count: 0,
  changed_line_count: 0,
  latest_conflict_job_id: null,
  latest_conflict_artifact_id: null,
  analyzed_revision: null,
  report_stale: false,
}

function isConflictReport(payload: unknown): payload is ConflictReport {
  if (!payload || typeof payload !== 'object') return false
  const candidate = payload as Record<string, unknown>
  return (
    candidate.schema_version === 'conflict-agent-v1'
    && typeof candidate.repository_revision === 'number'
    && Array.isArray(candidate.items)
  )
}

function analysisErrorMessage(code: string): string {
  const labels: Record<string, string> = {
    no_code_changes: '当前没有相对导入版本的已保存修改',
    repository_analysis_pending: '代码静态分析尚未完成',
    repository_revision_changed: '分析期间代码再次发生修改，请重新开始',
    agent_not_configured: '尚未配置 Agent 分析模型',
    llm_not_configured: '尚未配置 Agent 分析模型',
    llm_disabled: 'Agent 与 LLM 辅助分析当前已关闭',
    conflict_output_must_be_chinese: 'Agent 返回了非中文报告，正在重试后仍未通过校验',
  }
  return labels[code] ?? code
}

function toolTitle(toolName: string): string {
  const labels: Record<string, string> = {
    get_conflict_context: '准备冲突分析上下文',
    list_changed_files: '收集代码修改',
    get_change_diff: '核对文件差异',
    get_change_impact: '分析代码影响范围',
    list_affected_traces: '查找受影响追溯',
    list_paper_blocks: '浏览论文结构',
    get_paper_block: '读取论文证据',
    list_repository_files: '浏览代码文件',
    list_code_symbols: '枚举代码符号',
    get_symbol_source: '读取代码符号',
    get_symbol_calls: '分析调用关系',
    search_repository_text: '检索代码',
    read_source_lines: '读取源码',
    get_analysis_artifact: '读取已有分析结果',
    publish_conflict_report: '生成冲突报告',
    validate_conflict_report: '校验并保存报告',
  }
  return labels[toolName] ?? '执行分析工具'
}

function toolFailureSummary(code: string, details = ''): string {
  if (
    code === 'invalid_tool_arguments'
    && details.includes('change_evidence')
    && details.includes('quote')
  ) {
    return '代码证据引文为空，Agent 将移除无内容的一侧后重试'
  }
  const labels: Record<string, string> = {
    invalid_tool_arguments: '参数未通过校验，Agent 将修正后重试',
    conflict_output_must_be_chinese: '报告语言未通过校验，Agent 将改写后重试',
    conflict_code_evidence_quote_invalid: '代码引文无法定位，Agent 将重新取证',
    conflict_paper_evidence_quote_invalid: '论文引文无法定位，Agent 将重新取证',
    repository_revision_changed: '代码版本已变化，本次分析无法继续',
  }
  return labels[code] ?? '本步骤未通过校验，Agent 将调整后重试'
}

export function useInsights(projectId: () => number) {
  const conflictItems = ref<WorkspaceConflictItem[]>([])
  const changeSummary = ref<WorkspaceChangeSummary>({ ...EMPTY_SUMMARY })
  const report = ref<ConflictReport | null>(null)
  const loading = ref(false)
  const generating = ref(false)
  const cancelling = ref(false)
  const progress = ref('')
  const analysisActivity = ref('')
  const analysisStep = ref(0)
  const analysisBudget = ref(0)
  const analysisSteps = ref<ConflictAnalysisStep[]>([])
  const error = ref<string | null>(null)
  const currentJobId = ref<string | null>(null)
  let cancellationRequested = false

  function upsertAnalysisStep(step: ConflictAnalysisStep): void {
    const existing = analysisSteps.value.findIndex(
      (item) => item.step === step.step && item.tool_name === step.tool_name,
    )
    if (existing >= 0) {
      analysisSteps.value[existing] = step
      analysisSteps.value = [...analysisSteps.value]
      return
    }
    analysisSteps.value = [...analysisSteps.value.slice(-19), step]
  }

  function completeRunningSteps(): void {
    analysisSteps.value = analysisSteps.value.map((item) =>
      item.status === 'running'
        ? { ...item, status: 'completed', summary: '已完成' }
        : item,
    )
  }

  async function loadChangeSummary(): Promise<WorkspaceChangeSummary> {
    const summary = await getWorkspaceChangeSummary(projectId())
    changeSummary.value = summary
    return summary
  }

  async function loadLatestArtifact(summary: WorkspaceChangeSummary): Promise<void> {
    if (!summary.latest_conflict_job_id) {
      report.value = null
      return
    }
    try {
      const artifact = await getAgentAnalysisArtifact(
        projectId(),
        summary.latest_conflict_job_id,
      )
      report.value = isConflictReport(artifact.payload) ? artifact.payload : null
    } catch {
      report.value = null
    }
  }

  async function loadInsights(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [summary, items] = await Promise.all([
        loadChangeSummary(),
        getWorkspaceConflicts(projectId()),
      ])
      conflictItems.value = items
      await loadLatestArtifact(summary)
    } catch (cause) {
      error.value = extractErrorDetail(cause) || '冲突分析状态加载失败'
    } finally {
      loading.value = false
    }
  }

  async function waitForStaticAnalysis(): Promise<WorkspaceChangeSummary> {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (cancellationRequested) throw new Error('analysis_cancelled')
      const summary = await loadChangeSummary()
      if (!summary.has_changes) throw new Error('no_code_changes')
      if (summary.analysis_current) return summary
      if (summary.analysis_status === 'failed') {
        throw new Error('repository_analysis_failed')
      }
      progress.value = '等待当前代码版本的静态分析完成'
      analysisActivity.value = progress.value
      await new Promise((resolve) => window.setTimeout(resolve, 1500))
    }
    throw new Error('repository_analysis_timeout')
  }

  async function runAnalysis(): Promise<boolean> {
    generating.value = true
    cancelling.value = false
    cancellationRequested = false
    error.value = null
    progress.value = '检查已保存代码修改'
    analysisActivity.value = progress.value
    analysisStep.value = 0
    analysisBudget.value = 0
    analysisSteps.value = []
    try {
      await waitForStaticAnalysis()
      const submitted = await createAgentAnalysisJob(projectId(), {
        kind: 'conflict',
        force: true,
      })
      currentJobId.value = submitted.job_id
      progress.value = String(submitted.progress.message || '等待 Agent 分析')
      analysisActivity.value = progress.value
      if (!['succeeded', 'failed', 'stale'].includes(submitted.status)) {
        await streamAgentAnalysisJob(projectId(), submitted.job_id, (event) => {
          const payload = event.payload as Record<string, unknown>
          const message = payload.activity ?? payload.message
          const step = typeof payload.step === 'number' ? payload.step : analysisStep.value
          const budget = typeof payload.budget === 'number' ? payload.budget : analysisBudget.value
          const toolName = typeof payload.tool_name === 'string' ? payload.tool_name : ''
          if (typeof payload.step === 'number') analysisStep.value = payload.step
          if (typeof payload.budget === 'number') analysisBudget.value = payload.budget
          if (typeof message === 'string' && message) {
            progress.value = message
            analysisActivity.value = message
          }
          if (event.event_type === 'analysis.started') {
            analysisActivity.value = 'Agent 已启动，正在规划取证步骤'
            progress.value = analysisActivity.value
          } else if (event.event_type === 'analysis.tool.started' && toolName) {
            const activity = typeof message === 'string' && message
              ? message
              : toolTitle(toolName)
            upsertAnalysisStep({
              step,
              tool_name: toolName,
              title: toolTitle(toolName),
              summary: activity,
              status: 'running',
            })
          } else if (event.event_type === 'analysis.tool.completed' && toolName) {
            upsertAnalysisStep({
              step,
              tool_name: toolName,
              title: toolTitle(toolName),
              summary: payload.reused
                ? '已复用前一步取得的证据'
                : payload.prefetched && typeof message === 'string'
                  ? message
                  : '已完成',
              status: 'completed',
            })
          } else if (event.event_type === 'analysis.tool.failed' && toolName) {
            const code = String(payload.code ?? 'analysis_step_failed')
            const details = String(payload.details ?? '')
            upsertAnalysisStep({
              step,
              tool_name: toolName,
              title: toolTitle(toolName),
              summary: toolFailureSummary(code, details),
              status: 'failed',
            })
          }
          if (event.event_type === 'analysis.validating') {
            progress.value = '正在校验并保存冲突证据'
            analysisActivity.value = progress.value
            completeRunningSteps()
            upsertAnalysisStep({
              step: Math.max(analysisStep.value + 1, 1),
              tool_name: 'validate_conflict_report',
              title: toolTitle('validate_conflict_report'),
              summary: '正在核对报告内容、代码行号和论文原文',
              status: 'running',
            })
          } else if (event.event_type === 'analysis.completed') {
            completeRunningSteps()
            analysisActivity.value = cancellationRequested ? '分析已中止' : '冲突分析完成'
          }
        })
      }
      const completed = await getAgentAnalysisJob(projectId(), submitted.job_id)
      if (
        cancellationRequested
        || completed.progress.code === 'analysis_cancelled'
      ) {
        progress.value = '分析已中止'
        analysisActivity.value = progress.value
        return false
      }
      if (completed.status !== 'succeeded') {
        throw new Error(completed.error_code || 'conflict_analysis_failed')
      }
      const artifact = await getAgentAnalysisArtifact(projectId(), submitted.job_id)
      if (!isConflictReport(artifact.payload)) throw new Error('conflict_report_invalid')
      report.value = artifact.payload
      conflictItems.value = await getWorkspaceConflicts(projectId())
      await loadChangeSummary()
      progress.value = '冲突分析完成'
      analysisActivity.value = progress.value
      return true
    } catch (cause) {
      const detail = extractErrorDetail(cause)
      const code = detail || (cause instanceof Error ? cause.message : 'conflict_analysis_failed')
      if (code === 'analysis_cancelled') {
        progress.value = '分析已中止'
        analysisActivity.value = progress.value
        return false
      }
      error.value = analysisErrorMessage(code)
      return false
    } finally {
      generating.value = false
      cancelling.value = false
      currentJobId.value = null
    }
  }

  async function cancelAnalysis(): Promise<boolean> {
    if (!generating.value || cancelling.value) return false
    cancellationRequested = true
    cancelling.value = true
    progress.value = '正在中止分析'
    analysisActivity.value = progress.value
    const runningStep = [...analysisSteps.value]
      .reverse()
      .find((item) => item.status === 'running')
    if (runningStep) {
      upsertAnalysisStep({
        ...runningStep,
        summary: '正在等待当前步骤安全停止',
      })
    }
    const jobId = currentJobId.value
    if (!jobId) return true
    try {
      await cancelAgentAnalysisJob(projectId(), jobId)
      return true
    } catch (cause) {
      cancellationRequested = false
      cancelling.value = false
      error.value = extractErrorDetail(cause) || '中止分析失败'
      return false
    }
  }

  return {
    conflictItems,
    changeSummary,
    report,
    loading,
    generating,
    cancelling,
    progress,
    analysisActivity,
    analysisStep,
    analysisBudget,
    analysisSteps,
    error,
    currentJobId,
    loadInsights,
    runAnalysis,
    cancelAnalysis,
  }
}
