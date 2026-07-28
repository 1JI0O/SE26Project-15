<template>
  <section class="conflict-panel">
    <header class="conflict-toolbar">
      <div>
        <div class="toolbar-title">
          <strong>修改冲突分析</strong>
          <el-tag v-if="summary.report_stale" size="small" type="warning">结果已过期</el-tag>
          <el-tag v-else-if="report" size="small" type="success">Revision {{ report.repository_revision }}</el-tag>
        </div>
        <p>
          对比导入原始版本与当前已保存代码，结合调用关系、论文和追溯证据判断风险。
        </p>
      </div>
      <div class="toolbar-actions">
        <el-button
          v-if="generating"
          type="warning"
          plain
          :loading="cancelling"
          @click="$emit('cancel')"
        >
          {{ cancelling ? '正在中止…' : '中止分析' }}
        </el-button>
        <el-button
          v-else
          type="primary"
          :disabled="loading || !summary.has_changes"
          @click="$emit('analyze')"
        >
          {{ report ? '重新分析' : '开始分析' }}
        </el-button>
      </div>
    </header>

    <div class="change-status">
      <span>当前 Revision {{ summary.repository_revision || '—' }}</span>
      <span>{{ summary.changed_file_count }} 个修改文件</span>
      <span>{{ summary.changed_line_count }} 行变更</span>
      <span v-if="!summary.analysis_current && summary.has_changes">
        静态分析：{{ analysisStatusLabel(summary.analysis_status) }}
      </span>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="panel-alert"
    />
    <section v-if="generating || analysisSteps.length" class="agent-process">
      <header class="process-heading">
        <div class="process-current">
          <span :class="['process-spinner', { completed: !generating }]">
            <el-icon v-if="generating" class="is-loading"><Loading /></el-icon>
            <span v-else>✓</span>
          </span>
          <div>
            <strong>{{ generating ? 'Agent 分析过程' : '最近一次分析过程' }}</strong>
            <p>{{ activity || progress || 'Agent 正在分析修改' }}</p>
          </div>
        </div>
        <span v-if="analysisStep" class="step-count">已执行 {{ analysisStep }} 步</span>
      </header>
      <div v-if="generating" class="process-bar"><i /></div>
      <div v-if="analysisSteps.length" class="process-tool-list">
        <article
          v-for="item in analysisSteps.slice().reverse()"
          :key="`${item.step}:${item.tool_name}`"
          :class="['process-tool', item.status]"
        >
          <span class="tool-status" />
          <div>
            <strong>{{ item.title }}</strong>
            <small>{{ item.summary }}</small>
          </div>
          <span class="tool-step">第 {{ item.step }} 步</span>
        </article>
      </div>
      <p v-else class="process-waiting">正在准备代码、论文与追溯上下文…</p>
    </section>

    <div v-if="report" class="risk-summary">
      <div><strong>{{ report.summary.total }}</strong><span>风险项</span></div>
      <div class="high"><strong>{{ report.summary.high }}</strong><span>高风险</span></div>
      <div class="medium"><strong>{{ report.summary.medium }}</strong><span>中风险</span></div>
      <div class="low"><strong>{{ report.summary.low }}</strong><span>低风险</span></div>
    </div>

    <el-empty
      v-if="!loading && !generating && !displayItems.length"
      :description="
        report
          ? 'Agent 未发现有证据支持的修改冲突'
          : summary.has_changes
            ? '尚未生成冲突分析结果'
            : '当前没有已保存的代码修改'
      "
    />

    <div v-else class="conflict-grid">
      <article v-for="item in displayItems" :key="item.id || item.title" class="conflict-card">
        <div class="card-heading">
          <el-tag :type="tagType(item.severity)" effect="plain">{{ severityLabel(item.severity) }}</el-tag>
          <span class="confidence">置信度 {{ Math.round(item.confidence * 100) }}%</span>
        </div>
        <h2>{{ item.title }}</h2>
        <p>{{ item.description }}</p>
        <div v-if="item.affected_files.length" class="affected-files">
          {{ item.affected_files.join('、') }}
        </div>
        <el-button
          text
          type="primary"
          :disabled="!reportItem(item.id)"
          @click="openDetail(item.id)"
        >
          查看影响范围
        </el-button>
      </article>
    </div>

    <el-drawer
      v-model="drawerVisible"
      title="冲突影响与证据"
      size="min(680px, 92vw)"
      append-to-body
    >
      <template v-if="selected">
        <div class="drawer-heading">
          <el-tag :type="tagType(selected.severity)">
            {{ severityLabel(selected.severity) }}
          </el-tag>
          <strong>{{ selected.title }}</strong>
        </div>
        <p class="drawer-description">{{ selected.description }}</p>

        <h3>代码修改证据</h3>
        <article
          v-for="evidence in selected.change_evidence"
          :key="`${evidence.side}:${evidence.path}:${evidence.line_start}`"
          class="evidence-block"
        >
          <div>
            <el-tag size="small" :type="evidence.side === 'before' ? 'info' : 'success'">
              {{ evidence.side === 'before' ? '修改前' : '修改后' }}
            </el-tag>
            <el-button
              v-if="evidence.side === 'after'"
              text
              type="primary"
              @click="$emit('open-code', evidence.path, evidence.line_start, evidence.line_end)"
            >
              {{ evidence.path }}:{{ evidence.line_start }}
            </el-button>
            <span v-else>{{ evidence.path }}:{{ evidence.line_start }}</span>
          </div>
          <pre>{{ evidence.quote }}</pre>
        </article>

        <template v-if="selected.paper_evidence.length">
          <h3>论文证据</h3>
          <article
            v-for="evidence in selected.paper_evidence"
            :key="`${evidence.block_id}:${evidence.quote}`"
            class="evidence-block"
          >
            <div>
              <el-tag v-if="evidence.association === 'inferred'" size="small" type="warning">
                推测关联
              </el-tag>
              <el-button
                text
                type="primary"
                @click="$emit('open-paper', evidence.block_id, evidence.quote)"
              >
                {{ evidence.block_id }}
              </el-button>
            </div>
            <p>{{ evidence.quote }}</p>
          </article>
        </template>

        <template v-if="selected.trace_refs.length">
          <h3>受影响追溯</h3>
          <el-button
            v-for="reference in selected.trace_refs"
            :key="reference.trace_id"
            text
            type="primary"
            @click="$emit('open-trace', reference.trace_id)"
          >
            {{ reference.trace_id }}
          </el-button>
        </template>

        <template v-if="selected.affected_symbols.length || selected.callers.length">
          <h3>影响范围</h3>
          <p v-if="selected.affected_symbols.length">
            受影响符号：{{ selected.affected_symbols.join('、') }}
          </p>
          <p v-if="selected.callers.length">调用者：{{ selected.callers.join('、') }}</p>
        </template>

        <template v-if="selected.recommendations.length">
          <h3>建议</h3>
          <ul><li v-for="item in selected.recommendations" :key="item">{{ item }}</li></ul>
        </template>
        <template v-if="selected.verification_steps.length">
          <h3>验证步骤</h3>
          <ol><li v-for="item in selected.verification_steps" :key="item">{{ item }}</li></ol>
        </template>
      </template>
    </el-drawer>
  </section>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

import type {
  ConflictAnalysisStep,
  ConflictReport,
  ConflictReportItem,
  ConflictSeverity,
  WorkspaceChangeSummary,
  WorkspaceConflictItem,
} from '@/types/workspace'

const props = defineProps<{
  items: WorkspaceConflictItem[]
  summary: WorkspaceChangeSummary
  report: ConflictReport | null
  loading: boolean
  generating: boolean
  cancelling: boolean
  progress: string
  activity: string
  analysisStep: number
  analysisSteps: ConflictAnalysisStep[]
  error: string | null
}>()

defineEmits<{
  analyze: []
  cancel: []
  'open-code': [path: string, line: number, endLine: number]
  'open-paper': [blockId: string, quote: string]
  'open-trace': [traceId: string]
}>()

const drawerVisible = ref(false)
const selected = ref<ConflictReportItem | null>(null)

const displayItems = computed<WorkspaceConflictItem[]>(() => {
  if (!props.report) return props.items
  return props.report.items.map((item) => ({
    id: item.id,
    category: item.category,
    severity: item.severity,
    confidence: item.confidence,
    level: severityLabel(item.severity),
    type: tagType(item.severity),
    title: item.title,
    description: item.description,
    affected_files: item.affected_files,
    status: props.summary.report_stale ? 'stale' : 'ready',
  }))
})

function tagType(severity: ConflictSeverity): 'danger' | 'warning' | 'info' {
  if (severity === 'high') return 'danger'
  if (severity === 'medium') return 'warning'
  return 'info'
}

function severityLabel(severity: ConflictSeverity): string {
  if (severity === 'high') return '高风险'
  if (severity === 'medium') return '中风险'
  return '低风险'
}

function analysisStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    missing: '尚未开始',
    pending: '等待中',
    running: '进行中',
    ready: '已完成',
    stale: '需要更新',
    failed: '失败',
  }
  return labels[status] ?? status
}

function reportItem(id: string): ConflictReportItem | null {
  return props.report?.items.find((item) => item.id === id) ?? null
}

function openDetail(id: string): void {
  const item = reportItem(id)
  if (!item) return
  selected.value = item
  drawerVisible.value = true
}
</script>

<style scoped>
.conflict-panel { min-height: 100%; background: #f8fafc; }
.conflict-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
  padding: 14px 16px; border-bottom: 1px solid #dce3ea; background: #fff;
}
.toolbar-title { display: flex; align-items: center; gap: 10px; font-size: 15px; }
.conflict-toolbar p { margin: 4px 0 0; color: #667789; font-size: 12px; }
.toolbar-actions { display: flex; flex: 0 0 auto; align-items: center; }
.change-status {
  display: flex; flex-wrap: wrap; gap: 18px; padding: 9px 16px;
  border-bottom: 1px solid #e5eaf0; color: #64748b; font-size: 12px;
}
.panel-alert { margin: 12px 16px 0; width: auto; }
.agent-process {
  margin: 12px 16px 0; overflow: hidden; border: 1px solid #d7e2ea;
  border-radius: 8px; background: #fff;
}
.process-heading {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 12px; background: #f5f8fb;
}
.process-current { display: flex; min-width: 0; align-items: center; gap: 9px; }
.process-current > div { min-width: 0; }
.process-current strong { color: #30404f; font-size: 12px; }
.process-current p {
  margin: 2px 0 0; overflow: hidden; color: #607285; font-size: 11px;
  text-overflow: ellipsis; white-space: nowrap;
}
.process-spinner {
  display: grid; width: 24px; height: 24px; flex: 0 0 auto; place-items: center;
  border-radius: 50%; background: #e4efff; color: #3476b8;
}
.process-spinner.completed { background: #e3f3ed; color: #24765f; font-weight: 700; }
.step-count {
  flex: 0 0 auto; padding: 3px 7px; border-radius: 10px;
  background: #e8eef4; color: #657587; font-size: 10px;
}
.process-bar {
  position: relative; height: 3px; overflow: hidden; background: #e8edf2;
}
.process-bar i {
  position: absolute; top: 0; left: -35%; width: 35%; height: 100%;
  background: #2c8b76; animation: conflict-agent-slide 1.1s ease-in-out infinite;
}
@keyframes conflict-agent-slide {
  from { left: -35%; }
  to { left: 100%; }
}
.process-tool-list {
  display: grid; max-height: 190px; gap: 5px; padding: 8px; overflow-y: auto;
}
.process-tool {
  display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; gap: 7px;
  align-items: center; padding: 6px 7px; border: 1px solid #e0e6eb;
  border-radius: 4px; background: #fff;
}
.tool-status {
  width: 7px; height: 7px; border-radius: 50%; background: #23876f;
}
.process-tool.running .tool-status {
  background: #4f85b5; animation: conflict-agent-pulse 1.2s ease-in-out infinite;
}
.process-tool.failed .tool-status { background: #c45b4b; }
@keyframes conflict-agent-pulse {
  50% { opacity: .35; transform: scale(.75); }
}
.process-tool > div { display: grid; min-width: 0; }
.process-tool strong,
.process-tool small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.process-tool strong { color: #334252; font-size: 11px; }
.process-tool small { color: #74808c; font-size: 10px; }
.tool-step { color: #8a96a2; font-size: 9px; }
.process-waiting { margin: 0; padding: 9px 12px; color: #718096; font-size: 11px; }
.risk-summary { display: grid; grid-template-columns: repeat(4, minmax(100px, 1fr)); gap: 10px; padding: 14px 16px 0; }
.risk-summary div { display: flex; align-items: baseline; gap: 7px; padding: 10px 12px; border: 1px solid #dce3ea; border-radius: 7px; background: #fff; }
.risk-summary strong { font-size: 21px; }
.risk-summary span { color: #64748b; font-size: 12px; }
.risk-summary .high strong { color: #c2413b; }
.risk-summary .medium strong { color: #b7791f; }
.risk-summary .low strong { color: #397b68; }
.conflict-grid {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px; padding: 16px;
}
.conflict-card {
  display: flex; min-width: 0; flex-direction: column; gap: 10px; padding: 14px;
  border: 1px solid #dce3ea; border-radius: 8px; background: #fff;
}
.card-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.confidence { color: #7b8794; font-size: 11px; }
.conflict-card h2 { margin: 0; font-size: 14px; }
.conflict-card p { flex: 1; margin: 0; color: #667789; line-height: 1.55; }
.affected-files { overflow: hidden; color: #526579; font: 11px/1.4 monospace; text-overflow: ellipsis; white-space: nowrap; }
.conflict-card .el-button { align-self: flex-start; margin-left: -8px; }
.drawer-heading { display: flex; align-items: center; gap: 10px; }
.drawer-description { color: #526579; line-height: 1.7; }
.evidence-block { margin-bottom: 12px; padding: 12px; border: 1px solid #e1e7ed; border-radius: 7px; background: #f8fafc; }
.evidence-block > div { display: flex; align-items: center; gap: 8px; }
.evidence-block pre { max-height: 260px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
.evidence-block p { margin-bottom: 0; line-height: 1.65; }
h3 { margin: 22px 0 10px; font-size: 14px; }
li { margin: 6px 0; line-height: 1.5; }
@media (max-width: 900px) {
  .conflict-grid { grid-template-columns: 1fr; }
  .risk-summary { grid-template-columns: repeat(2, 1fr); }
}
</style>
