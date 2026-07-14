<template>
  <article class="trace-matrix">
    <header>
      <div>
        <h2>双向追溯矩阵</h2>
        <p>论文段落、公式、图表与代码文件/符号的关联审阅队列。</p>
      </div>
      <el-button type="primary" :loading="generating" @click="$emit('suggest')">
        生成候选
      </el-button>
    </header>

    <el-alert
      v-if="mode"
      :type="degraded ? 'warning' : 'success'"
      :closable="false"
      :title="degraded ? `${mode} · LLM 降级，已保留静态分析结果` : `${mode} · 候选生成完成`"
    />

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
      <div class="trace-row trace-head">
        <span>论文位置</span>
        <span>代码位置</span>
        <span>关系</span>
        <span>置信度</span>
        <span>状态 / 来源</span>
        <span>审阅</span>
      </div>
      <div v-for="row in rows" :key="`${row.paper}-${row.code}`" class="trace-row">
        <span :title="row.rationale">{{ row.paper }}</span>
        <span :title="row.rationale">{{ row.code }}</span>
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
            <el-button size="small" text type="danger" @click="$emit('review', row.id, 'rejected')">
              拒绝
            </el-button>
            <el-button size="small" text type="success" @click="$emit('review', row.id, 'accepted')">
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
import type { TraceRowView } from '@/composables/useTrace'
import type { TraceStatus } from '@/types/tracing'

defineProps<{
  rows: TraceRowView[]
  loading: boolean
  generating: boolean
  error: string | null
  mode: string
  degraded: boolean
}>()

defineEmits<{
  suggest: []
  review: [traceId: string, status: Extract<TraceStatus, 'accepted' | 'rejected'>]
}>()

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

.trace-matrix header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
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
  grid-template-columns: minmax(120px, 1.1fr) minmax(150px, 1.3fr) 0.8fr 0.9fr 0.8fr 0.8fr;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid #edf1f4;
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

.trace-head {
  margin-top: 12px;
  color: #667789;
  font-size: 12px;
  font-weight: 700;
}

@media (max-width: 820px) {
  .trace-row {
    grid-template-columns: 1fr;
  }
}
</style>
