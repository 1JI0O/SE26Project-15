<template>
  <article class="trace-matrix">
    <header>
      <div>
        <h2>双向追溯矩阵</h2>
        <p>论文段落、公式、图表与代码文件/符号的关联审阅队列。点击任意行选中该关系并两侧联动定位。</p>
      </div>
      <div class="header-actions">
        <el-button
          v-if="generating"
          type="warning"
          plain
          :loading="cancelling"
          @click="$emit('cancel')"
        >
          {{ cancelling ? '正在中止…' : '中止追溯（保留已发现）' }}
        </el-button>
        <el-button type="primary" :loading="generating" @click="$emit('suggest')">
          {{ generating ? 'Agent 追溯中…' : hasGenerated ? '重新生成' : '生成追溯' }}
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="mode"
      :type="degraded ? 'warning' : 'success'"
      :closable="false"
      :title="degraded ? `${mode} · Agent 分析失败，已保留现有结果` : `${mode} · 分析完成`"
    />

    <div v-if="rows.length" class="trace-legend" aria-label="高亮图例">
      <span><i class="legend-dot legend-proposed" />候选（蓝）</span>
      <span><i class="legend-dot legend-accepted" />已接受（绿）</span>
      <span><i class="legend-dot legend-fanout" />一对多（紫）</span>
      <span><i class="legend-dot legend-fanin" />多对一（青）</span>
      <span><i class="legend-dot legend-active" />当前选中（黄）</span>
      <span><i class="legend-dot legend-hover" />悬停预览（浅黄）</span>
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
      <div v-if="proposedRows.length" class="batch-bar">
        <el-checkbox
          :model-value="allProposedSelected"
          :indeterminate="someProposedSelected && !allProposedSelected"
          @change="toggleSelectAll"
        >
          全选候选（{{ proposedRows.length }}）
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
        v-for="row in rows"
        :key="`${row.paper}-${row.code}`"
        :class="['trace-row', 'clickable', { selected: !!row.id && row.id === selectedId }]"
        @click="$emit('selectRow', row)"
        @mouseenter="$emit('hoverRow', row)"
        @mouseleave="$emit('leaveRow')"
      >
        <span class="check-cell" @click.stop>
          <el-checkbox
            v-if="row.id && row.status === 'proposed'"
            :model-value="selectedSet.has(row.id)"
            @change="toggleRow(row.id)"
          />
        </span>
        <span class="location-cell" :title="row.rationale">{{ row.paper }}</span>
        <span class="location-cell" :title="row.rationale">{{ row.code }}</span>
        <span>{{ row.type }} · {{ row.evidenceCount }} 证据</span>
        <el-progress :percentage="row.confidence" />
        <span class="trace-status">
          <el-tag :type="statusType(row.status)" effect="plain" size="small">
            {{ row.status }}
          </el-tag>
          <small>{{ row.source }}</small>
        </span>
        <span class="review-actions">
          <template v-if="row.id && row.status === 'proposed'">
            <el-button size="small" text type="danger" @click.stop="reviewOne(row.id, 'rejected')">
              拒绝
            </el-button>
            <el-button size="small" text type="success" @click.stop="reviewOne(row.id, 'accepted')">
              接受
            </el-button>
          </template>
          <small v-else>{{ row.uncertainty }}</small>
        </span>
      </div>
      <el-empty v-if="!rows.length" description="上传论文和代码后可生成追溯候选" />
    </template>
  </article>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TraceRowView } from '@/composables/useTrace'
import type { TraceStatus } from '@/types/tracing'

const props = withDefaults(
  defineProps<{
    rows: TraceRowView[]
    loading: boolean
    generating: boolean
    cancelling?: boolean
    error: string | null
    mode: string
    degraded: boolean
    hasGenerated?: boolean
    selectedId?: string | null
  }>(),
  { cancelling: false, hasGenerated: false, selectedId: null },
)

const emit = defineEmits<{
  suggest: []
  cancel: []
  review: [traceId: string, status: Extract<TraceStatus, 'accepted' | 'rejected'>]
  reviewBatch: [status: Extract<TraceStatus, 'accepted' | 'rejected'>, traceIds?: string[]]
  selectRow: [row: TraceRowView]
  hoverRow: [row: TraceRowView]
  leaveRow: []
}>()

// Ids checked for batch review. Kept in sync with the current proposed set so decided/removed
// rows never linger as phantom selections.
const selectedSet = ref<Set<string>>(new Set())

const proposedRows = computed(() =>
  props.rows.filter((row): row is TraceRowView & { id: string } =>
    Boolean(row.id) && row.status === 'proposed',
  ),
)
const selectedCount = computed(() => selectedSet.value.size)
const allProposedSelected = computed(
  () => proposedRows.value.length > 0 && proposedRows.value.every((row) => selectedSet.value.has(row.id)),
)
const someProposedSelected = computed(() =>
  proposedRows.value.some((row) => selectedSet.value.has(row.id)),
)

watch(proposedRows, (rows) => {
  const valid = new Set(rows.map((row) => row.id))
  const next = new Set<string>()
  for (const id of selectedSet.value) if (valid.has(id)) next.add(id)
  selectedSet.value = next
})

function toggleRow(id: string): void {
  const next = new Set(selectedSet.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedSet.value = next
}

function toggleSelectAll(checked: boolean | string | number): void {
  selectedSet.value = checked ? new Set(proposedRows.value.map((row) => row.id)) : new Set()
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

function reviewOne(traceId: string, status: Extract<TraceStatus, 'accepted' | 'rejected'>): void {
  emit('review', traceId, status)
  emit('leaveRow')
}

function statusType(status: TraceRowView['status']): 'success' | 'warning' | 'info' | 'danger' {
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

.header-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
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

@media (max-width: 820px) {
  .trace-row {
    grid-template-columns: 1fr;
  }
}
</style>
