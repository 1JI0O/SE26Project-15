<template>
  <article class="trace-matrix">
    <header>
      <div>
        <h2>双向追溯矩阵</h2>
        <p>论文段落、公式、图表与代码文件/符号的关联审阅队列。点击任意行选中该关系并两侧联动定位。</p>
      </div>
      <el-button
        type="primary"
        plain
        :icon="Plus"
        :disabled="annotation.active"
        @click="annotation.start()"
      >
        追加追溯关系
      </el-button>
    </header>

    <el-alert
      v-if="mode"
      :type="analysisAlertType"
      :closable="false"
      :title="analysisAlertTitle"
    />

    <div v-if="rows.length" class="trace-legend" aria-label="高亮图例">
      <strong>高亮含义</strong>
      <span title="Agent 生成、尚未审阅的关系"><i class="legend-dot legend-proposed" />候选（蓝）</span>
      <span title="你已确认的关系"><i class="legend-dot legend-accepted" />已接受（绿）</span>
      <span title="同一处论文内容对应多处代码：紫色下划线右上角的 ×N 表示对应的代码位置数量">
        <i class="legend-dot legend-fanout" />一对多（紫 ×N）
      </span>
      <span title="多处论文内容对应同一处代码：青色下划线右上角的 ×N 表示对应的论文片段数量">
        <i class="legend-dot legend-fanin" />多对一（青 ×N）
      </span>
      <span title="当前选中的那一条关系，两侧同时用黄色标出">
        <i class="legend-dot legend-active" />当前选中（黄）
      </span>
      <span title="鼠标悬停预览，不会移动视图"><i class="legend-dot legend-hover" />悬停预览（浅黄）</span>
      <small class="legend-note">
        一处内容对应多条关系时，点击默认跳转到相关度最高的一条；其余在右下角面板中以“另有 N 条”列出。
      </small>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="state-placeholder">
      <el-icon class="is-loading" :size="20"><i class="el-icon-loading" /></el-icon>
      <span>加载追溯矩阵...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
    </div>

    <!-- Content -->
    <template v-else>
      <div v-if="proposedGroups.length" class="batch-bar">
        <el-checkbox
          :model-value="allProposedSelected"
          :indeterminate="someProposedSelected && !allProposedSelected"
          @change="toggleSelectAll"
        >
          全选候选（{{ proposedGroups.length }}）
        </el-checkbox>
        <span class="batch-spacer" />
        <template v-if="selectedCount">
          <small class="batch-count">已选 {{ selectedCount }} 条</small>
          <el-button size="small" text type="danger" @click="emitBatch('rejected', true)">
            拒绝所选
          </el-button>
          <el-button size="small" text type="success" @click="emitBatch('accepted', true)">
            接受所选
          </el-button>
        </template>
        <template v-else>
          <el-button size="small" text type="danger" @click="emitBatch('rejected', false)">
            拒绝全部候选
          </el-button>
          <el-button size="small" text type="success" @click="emitBatch('accepted', false)">
            接受全部候选
          </el-button>
        </template>
      </div>
      <div class="trace-row trace-head">
        <span class="check-cell" />
        <span>论文位置</span>
        <span>代码位置</span>
        <span>关系</span>
        <span>置信度</span>
        <span>状态 / 来源</span>
        <span>审阅</span>
      </div>
      <div
        v-for="row in mergedRows"
        :key="row.key"
        :class="['trace-row', 'clickable', { selected: isRowSelected(row), fresh: isFreshRow(row) }]"
        @click="$emit('selectRow', row.top)"
        @mouseenter="$emit('hoverRow', row.top)"
        @mouseleave="$emit('leaveRow')"
      >
        <span class="check-cell" @click.stop>
          <el-checkbox
            v-if="row.proposedIds.length"
            :model-value="isGroupChecked(row)"
            @change="toggleRow(row)"
          />
        </span>
        <span class="location-cell" :title="row.top.rationale">{{ row.top.paper }}</span>
        <span class="location-cell" :title="row.top.rationale">{{ row.top.code }}</span>
        <span :title="row.relationTypes.join(' / ')">
          {{ row.relationTypes.join(' / ') }} · {{ row.evidenceCount }} 证据
          <em v-if="row.count > 1" class="merge-badge">×{{ row.count }}</em>
        </span>
        <el-progress :percentage="row.confidence" :color="confidenceColor(row.confidence)" />
        <span class="trace-status">
          <el-tag
            :type="statusType(row.status)"
            effect="plain"
            size="small"
            :title="row.statusSummary"
          >
            {{ row.status === 'mixed' ? '混合' : row.status }}
          </el-tag>
          <small>{{ row.top.source }}</small>
        </span>
        <span class="review-actions">
          <template v-if="row.proposedIds.length">
            <el-button size="small" text type="danger" @click.stop="reviewGroup(row, 'rejected')">
              拒绝
            </el-button>
            <el-button size="small" text type="success" @click.stop="reviewGroup(row, 'accepted')">
              接受
            </el-button>
          </template>
          <el-button
            v-if="row.decidedIds.length"
            size="small"
            text
            @click.stop="reviewGroup(row, 'proposed')"
          >
            撤回
          </el-button>
          <small v-if="!row.proposedIds.length && !row.decidedIds.length">
            {{ row.top.uncertainty }}
          </small>
        </span>
      </div>
      <el-empty v-if="!mergedRows.length" description="上传论文和代码后可生成追溯候选" />
    </template>
  </article>
</template>

<script setup lang="ts">
import { Plus } from '@element-plus/icons-vue'
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import type { TraceRowView } from '@/composables/useTrace'
import type { TraceStatus } from '@/types/tracing'
import { useAnnotationStore } from '@/stores/annotation'
import { confidenceColor } from './confidence'

const annotation = useAnnotationStore()

const freshTraceIds = ref<Set<string>>(new Set())

const props = withDefaults(
  defineProps<{
    rows: TraceRowView[]
    loading: boolean
    error: string | null
    mode: string
    degraded: boolean
    analyzing?: boolean
    publishedCount?: number
    selectedId?: string | null
  }>(),
  { analyzing: false, publishedCount: 0, selectedId: null },
)

const emit = defineEmits<{
  review: [traceId: string, status: Extract<TraceStatus, 'accepted' | 'rejected'>]
  reviewBatch: [
    status: Extract<TraceStatus, 'accepted' | 'rejected' | 'proposed'>,
    traceIds?: string[],
  ]
  selectRow: [row: TraceRowView]
  hoverRow: [row: TraceRowView]
  leaveRow: []
}>()

// One merged row per paper×code pair: the same pair may carry several relations (different
// relation_type links); the matrix shows the highest-confidence one and reviews the whole group.
interface MergedTraceRow {
  key: string
  top: TraceRowView
  ids: string[]
  proposedIds: string[]
  // Accepted/rejected links in the group — the ones a "撤回" reverts to proposed.
  decidedIds: string[]
  relationTypes: string[]
  count: number
  confidence: number
  status: TraceRowView['status'] | 'mixed'
  statusSummary: string
  evidenceCount: number
}

const mergedRows = computed<MergedTraceRow[]>(() => {
  const groups = new Map<string, TraceRowView[]>()
  for (const row of props.rows) {
    const key = `${row.paper}|${row.code}`
    const list = groups.get(key)
    if (list) list.push(row)
    else groups.set(key, [row])
  }
  const merged: MergedTraceRow[] = []
  for (const [key, group] of groups) {
    const sorted = [...group].sort((a, b) => b.confidence - a.confidence)
    const top = sorted[0]
    const relationTypes: string[] = []
    const statusCounts = new Map<string, number>()
    for (const row of sorted) {
      if (!relationTypes.includes(row.type)) relationTypes.push(row.type)
      statusCounts.set(row.status, (statusCounts.get(row.status) ?? 0) + 1)
    }
    merged.push({
      key,
      top,
      ids: sorted.map((row) => row.id).filter((id): id is string => Boolean(id)),
      proposedIds: sorted
        .filter((row): row is TraceRowView & { id: string } =>
          Boolean(row.id) && row.status === 'proposed',
        )
        .map((row) => row.id),
      decidedIds: sorted
        .filter((row): row is TraceRowView & { id: string } =>
          Boolean(row.id) && (row.status === 'accepted' || row.status === 'rejected'),
        )
        .map((row) => row.id),
      relationTypes,
      count: sorted.length,
      confidence: top.confidence,
      status: statusCounts.size === 1 ? top.status : 'mixed',
      statusSummary: Array.from(statusCounts, ([status, count]) => `${status} ${count}`).join(' · '),
      evidenceCount: sorted.reduce((sum, row) => sum + row.evidenceCount, 0),
    })
  }
  return merged
})

// Ids checked for batch review. Kept in sync with the current proposed set so decided/removed
// rows never linger as phantom selections. Checking a merged row checks its whole group.
const selectedSet = ref<Set<string>>(new Set())

const proposedGroups = computed(() => mergedRows.value.filter((row) => row.proposedIds.length))
const allProposedIds = computed(() => proposedGroups.value.flatMap((row) => row.proposedIds))
const selectedCount = computed(() => selectedSet.value.size)
const allProposedSelected = computed(
  () =>
    allProposedIds.value.length > 0 &&
    allProposedIds.value.every((id) => selectedSet.value.has(id)),
)
const someProposedSelected = computed(() =>
  allProposedIds.value.some((id) => selectedSet.value.has(id)),
)

const analysisAlertType = computed(() => {
  if (props.degraded) return 'warning'
  if (props.analyzing) return 'info'
  return 'success'
})

const analysisAlertTitle = computed(() => {
  if (props.degraded) return `${props.mode} · Agent 分析失败，已保留现有结果`
  if (props.analyzing) return `${props.mode} · Agent 分析中，已发布 ${props.publishedCount} 条关系`
  return `${props.mode} · 分析完成`
})

watch(allProposedIds, (ids) => {
  const valid = new Set(ids)
  const next = new Set<string>()
  for (const id of selectedSet.value) if (valid.has(id)) next.add(id)
  selectedSet.value = next
})

function isRowSelected(row: MergedTraceRow): boolean {
  return Boolean(props.selectedId && row.ids.includes(props.selectedId))
}

function isFreshRow(row: MergedTraceRow): boolean {
  return row.ids.some((id) => freshTraceIds.value.has(id))
}

function handleNewTraceLink(event: Event): void {
  const customEvent = event as CustomEvent
  const { traceId } = customEvent.detail
  if (traceId) {
    freshTraceIds.value.add(traceId)

    // Remove highlight after 3 seconds
    setTimeout(() => {
      freshTraceIds.value.delete(traceId)
    }, 3000)

    // Emit event to parent to refresh trace data
    // The parent (ProjectWorkspaceView) should call trace.refresh()
  }
}

onMounted(() => {
  window.addEventListener('trace-link-created', handleNewTraceLink)
})

onUnmounted(() => {
  window.removeEventListener('trace-link-created', handleNewTraceLink)
})

function isGroupChecked(row: MergedTraceRow): boolean {
  return row.proposedIds.every((id) => selectedSet.value.has(id))
}

function toggleRow(row: MergedTraceRow): void {
  const next = new Set(selectedSet.value)
  if (isGroupChecked(row)) for (const id of row.proposedIds) next.delete(id)
  else for (const id of row.proposedIds) next.add(id)
  selectedSet.value = next
}

function toggleSelectAll(checked: boolean | string | number): void {
  selectedSet.value = checked ? new Set(allProposedIds.value) : new Set()
}

function emitBatch(
  status: Extract<TraceStatus, 'accepted' | 'rejected'>,
  useSelection: boolean,
): void {
  const ids = useSelection ? Array.from(selectedSet.value) : undefined
  emit('reviewBatch', status, ids)
  selectedSet.value = new Set()
  emit('leaveRow')
}

function reviewGroup(
  row: MergedTraceRow,
  status: Extract<TraceStatus, 'accepted' | 'rejected' | 'proposed'>,
): void {
  // 'proposed' undoes the group's decisions; the other two review its pending links.
  emit('reviewBatch', status, status === 'proposed' ? row.decidedIds : row.proposedIds)
  emit('leaveRow')
}

function statusType(status: MergedTraceRow['status']): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'accepted') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'proposed') return 'warning'
  return 'info'
}
</script>

<style scoped>
.trace-matrix {
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  padding: 16px;
}

.trace-matrix h2 {
  margin: 0;
}

.trace-matrix p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.location-cell {
  min-width: 0;
  overflow: hidden;
  color: #176b87;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-matrix header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 8px;
  border-radius: 6px;
  background: #f4f8fb;
}

.batch-spacer {
  flex: 1;
}

.batch-count {
  color: #667789;
}

.trace-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f8fafb;
  color: #667789;
  font-size: 11px;
}

.trace-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.trace-legend strong {
  color: #55636f;
}

.legend-note {
  flex-basis: 100%;
  color: #8a95a1;
  line-height: 1.6;
}

.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-proposed {
  background: rgba(88, 133, 255, 0.55);
}

.legend-accepted {
  background: rgba(46, 168, 118, 0.65);
}

.legend-fanout {
  background: rgba(139, 92, 246, 0.65);
}

.legend-fanin {
  background: rgba(8, 145, 178, 0.65);
}

.legend-active {
  background: #e0a83a;
}

.legend-hover {
  background: rgba(224, 168, 58, 0.35);
  border: 1px solid rgba(224, 168, 58, 0.55);
}

.state-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: #667789;
  font-size: 13px;
}

.state-error {
  color: #e15a4a;
}

.trace-row {
  display: grid;
  grid-template-columns: 28px minmax(120px, 1.1fr) minmax(150px, 1.3fr) 0.8fr 0.9fr 0.8fr 0.8fr;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid #edf1f4;
}

.check-cell {
  display: flex;
  align-items: center;
  justify-content: center;
}

.trace-row > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-status,
.review-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}

.merge-badge {
  padding: 0 5px;
  border-radius: 8px;
  background: rgba(139, 92, 246, 0.14);
  color: #8b5cf6;
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
}

.trace-status small,
.review-actions small {
  color: #667789;
}

.trace-row.clickable {
  cursor: pointer;
  border-radius: 6px;
  padding: 12px 8px;
  transition: background 0.15s ease;
}

.trace-row.clickable:hover {
  background: #f0faf7;
}

.trace-row.clickable.selected {
  background: #fff5df;
  box-shadow: inset 3px 0 0 #e0a83a;
}

.trace-head {
  margin-top: 12px;
  color: #667789;
  font-size: 12px;
  font-weight: 700;
  cursor: default;
}

.trace-head:hover {
  background: transparent;
}

/* Fresh trace link animation */
@keyframes flash-yellow {
  0% {
    background-color: #fdf6ec;
  }
  50% {
    background-color: #f5daa5;
  }
  100% {
    background-color: transparent;
  }
}

.trace-row.fresh {
  animation: flash-yellow 3s ease-out;
}

@media (max-width: 820px) {
  .trace-row {
    grid-template-columns: 1fr;
  }
}
</style>
