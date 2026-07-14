<template>
  <el-drawer
    :model-value="visible"
    title="追溯证据详情"
    direction="rtl"
    size="480px"
    @close="$emit('close')"
  >
    <div v-if="!row" class="empty-state">
      <el-empty description="请选择一条追溯记录查看证据" />
    </div>

    <div v-else class="evidence-content">
      <!-- Confidence -->
      <section class="evidence-section">
        <h4>置信度</h4>
        <div class="confidence-bar">
          <el-progress
            :percentage="row.confidence"
            :color="confidenceColor"
            :stroke-width="20"
            :text-inside="true"
          />
        </div>
      </section>

      <!-- Paper side evidence -->
      <section class="evidence-section">
        <h4>论文侧证据</h4>
        <div class="evidence-card paper-side">
          <div class="evidence-label">论文位置</div>
          <div class="evidence-value">{{ row.paper }}</div>
        </div>
      </section>

      <!-- Code side evidence -->
      <section class="evidence-section">
        <h4>代码侧证据</h4>
        <div class="evidence-card code-side">
          <div class="evidence-label">代码位置</div>
          <div class="evidence-value">{{ row.code }}</div>
        </div>
      </section>

      <!-- Relation -->
      <section class="evidence-section">
        <h4>关系类型</h4>
        <el-tag type="info" effect="plain">{{ row.type }}</el-tag>
      </section>

      <!-- Rationale -->
      <section v-if="row.rationale" class="evidence-section">
        <h4>判定依据</h4>
        <p class="rationale-text">{{ row.rationale }}</p>
      </section>

      <!-- Actions -->
      <section class="evidence-actions">
        <el-button type="primary" @click="$emit('confirm', row)">
          确认追溯关系
        </el-button>
        <el-button @click="$emit('reject', row)">
          驳回
        </el-button>
      </section>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TraceRowView } from '@/composables/useTrace'

const props = defineProps<{
  visible: boolean
  row: TraceRowView | null
}>()

defineEmits<{
  close: []
  confirm: [row: TraceRowView]
  reject: [row: TraceRowView]
}>()

const confidenceColor = computed(() => {
  if (!props.row) return '#9aa7b4'
  if (props.row.confidence >= 80) return '#1f8f78'
  if (props.row.confidence >= 50) return '#d97706'
  return '#e15a4a'
})
</script>

<style scoped>
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.evidence-content {
  display: grid;
  gap: 20px;
}

.evidence-section h4 {
  margin: 0 0 10px;
  color: #16232f;
  font-size: 14px;
}

.confidence-bar {
  max-width: 320px;
}

.evidence-card {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #edf1f4;
}

.evidence-card.paper-side {
  border-left: 3px solid #2563eb;
}

.evidence-card.code-side {
  border-left: 3px solid #1f8f78;
}

.evidence-label {
  color: #667789;
  font-size: 12px;
  margin-bottom: 4px;
}

.evidence-value {
  color: #16232f;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  word-break: break-all;
}

.rationale-text {
  margin: 0;
  color: #2d3b48;
  line-height: 1.7;
  font-size: 14px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
}

.evidence-actions {
  display: flex;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid #edf1f4;
}
</style>
