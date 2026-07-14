<template>
  <article class="trace-matrix">
    <header>
      <h2>双向追溯矩阵</h2>
      <p>论文段落、公式、图表与代码文件/符号的关联审阅队列。</p>
    </header>

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
      </div>
      <div v-for="row in rows" :key="`${row.paper}-${row.code}`" class="trace-row">
        <span>{{ row.paper }}</span>
        <span>{{ row.code }}</span>
        <span>{{ row.type }}</span>
        <el-progress :percentage="row.confidence" />
      </div>
      <el-empty v-if="!rows.length" description="上传论文和代码后可生成追溯候选" />
    </template>
  </article>
</template>

<script setup lang="ts">
import type { TraceRowView } from '@/composables/useTrace'

defineProps<{
  rows: TraceRowView[]
  loading: boolean
  error: string | null
}>()
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
  grid-template-columns: 1.2fr 1.4fr 0.7fr 1fr;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid #edf1f4;
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
