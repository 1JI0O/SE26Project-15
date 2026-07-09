<template>
  <section class="trace-panel">
    <header class="trace-header">
      <div>
        <h2>追溯结果面板</h2>
        <p>保存的关系与候选建议分开展示，便于人工确认。</p>
      </div>
      <el-button :loading="loading" type="primary" @click="$emit('suggest')">生成候选</el-button>
    </header>

    <el-row :gutter="16">
      <el-col :lg="12" :md="24">
        <h3>候选建议</h3>
        <el-empty v-if="suggestions.length === 0" description="暂无候选建议" />
        <div v-else class="trace-list">
          <article v-for="item in suggestions" :key="`${item.paper_ref}-${item.code_ref}`">
            <div class="trace-line">
              <strong>{{ item.paper_ref }}</strong>
              <span>{{ item.relation_type }}</span>
              <strong>{{ item.code_ref }}</strong>
            </div>
            <p>{{ item.rationale }}</p>
            <el-progress :percentage="Math.round(item.confidence * 100)" />
          </article>
        </div>
      </el-col>
      <el-col :lg="12" :md="24">
        <h3>已保存关系</h3>
        <el-empty v-if="links.length === 0" description="暂无已保存追溯关系" />
        <div v-else class="trace-list">
          <article v-for="item in links" :key="item.id">
            <div class="trace-line">
              <strong>{{ item.paper_ref }}</strong>
              <span>{{ item.relation_type }}</span>
              <strong>{{ item.code_ref }}</strong>
            </div>
            <p>{{ item.rationale }}</p>
            <el-progress :percentage="Math.round(item.confidence * 100)" status="success" />
          </article>
        </div>
      </el-col>
    </el-row>
  </section>
</template>

<script setup lang="ts">
import type { TraceLink, TraceLinkSuggestion } from '@/types/api'

defineProps<{
  suggestions: TraceLinkSuggestion[]
  links: TraceLink[]
  loading: boolean
}>()

defineEmits<{
  suggest: []
}>()
</script>

<style scoped>
.trace-panel {
  padding: 18px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: white;
}

.trace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.trace-header h2,
h3 {
  margin: 0;
}

.trace-header p {
  margin: 4px 0 0;
  color: #71808f;
}

h3 {
  margin-bottom: 10px;
  font-size: 15px;
}

.trace-list {
  display: grid;
  gap: 10px;
}

.trace-list article {
  padding: 12px;
  border: 1px solid #e4e9ee;
  border-radius: 6px;
  background: #fbfcfd;
}

.trace-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.trace-line span {
  padding: 2px 8px;
  border-radius: 999px;
  background: #e8f4f1;
  color: #1f8f78;
  font-size: 12px;
}

.trace-list p {
  margin: 8px 0;
  color: #536475;
  line-height: 1.55;
}
</style>

