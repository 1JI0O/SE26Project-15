<template>
  <section class="panel">
    <header class="panel-header">
      <div>
        <h2>代码浏览区</h2>
        <p v-if="repository">{{ repository.filename }}</p>
        <p v-else>等待上传代码 ZIP</p>
      </div>
      <el-tag v-if="repository" type="success">{{ repository.symbols.length }} 个符号</el-tag>
    </header>

    <el-empty v-if="!repository" description="暂无代码分析结果" />
    <template v-else>
      <div class="analysis-summary">
        <div v-for="item in summaryItems" :key="item.label" class="summary-card">
          <strong>{{ item.value }}</strong>
          <span>{{ item.label }}</span>
        </div>
      </div>

      <el-tabs class="code-tabs">
        <el-tab-pane label="文件树">
          <el-empty
            v-if="repository.file_tree.length === 0"
            class="empty-inline"
            description="未发现可分析文件"
          />
          <el-table v-else :data="repository.file_tree" size="small" height="300">
            <el-table-column prop="path" label="路径" min-width="260" />
            <el-table-column prop="language" label="类型" width="100" />
            <el-table-column label="大小" width="110">
              <template #default="{ row }">{{ formatSize(row.size) }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="符号">
          <el-empty
            v-if="repository.symbols.length === 0"
            class="empty-inline"
            description="未识别到类或函数"
          />
          <el-table v-else :data="repository.symbols" size="small" height="300">
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column prop="type" label="类型" width="100" />
            <el-table-column prop="path" label="文件" min-width="220" />
            <el-table-column prop="line" label="行号" width="90" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="导入关系">
          <el-empty
            v-if="repository.imports.length === 0"
            class="empty-inline"
            description="未识别到 import 语句"
          />
          <el-table v-else :data="repository.imports" size="small" height="300">
            <el-table-column prop="name" label="导入对象" min-width="220" />
            <el-table-column prop="path" label="文件" min-width="220" />
            <el-table-column prop="line" label="行号" width="90" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="PyTorch 候选">
          <el-empty
            v-if="repository.pytorch_candidates.length === 0"
            class="empty-inline"
            description="未发现 PyTorch 模型候选"
          />
          <div v-else class="candidate-list">
            <article v-for="candidate in repository.pytorch_candidates" :key="candidateKey(candidate)">
              <strong>{{ candidate.name }}</strong>
              <span>{{ candidate.path }}:{{ candidate.line }}</span>
              <p>{{ candidate.reason }}</p>
            </article>
          </div>
        </el-tab-pane>
      </el-tabs>

      <p class="filter-note">已按压缩包内 .gitignore 和 macOS 元数据规则过滤无关文件。</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { CodeRepository } from '@/types/api'

const props = defineProps<{
  repository: CodeRepository | null
}>()

const repository = computed(() => props.repository)
const summaryItems = computed(() => [
  { label: '文件', value: repository.value?.file_tree.length ?? 0 },
  { label: '符号', value: repository.value?.symbols.length ?? 0 },
  { label: '导入', value: repository.value?.imports.length ?? 0 },
  { label: 'PyTorch 候选', value: repository.value?.pytorch_candidates.length ?? 0 },
])

function candidateKey(candidate: Record<string, unknown>): string {
  return `${String(candidate.path)}:${String(candidate.name)}:${String(candidate.line)}`
}

function formatSize(value: unknown): string {
  const size = Number(value)
  if (!Number.isFinite(size)) {
    return '-'
  }
  if (size < 1024) {
    return `${size} B`
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>

<style scoped>
.panel {
  min-height: 520px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: white;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.panel-header h2 {
  margin: 0;
  font-size: 18px;
}

.panel-header p {
  margin: 4px 0 0;
  color: #71808f;
}

.analysis-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.summary-card {
  padding: 10px 12px;
  border: 1px solid #e4e9ee;
  border-radius: 6px;
  background: #f8fafc;
}

.summary-card strong,
.summary-card span {
  display: block;
}

.summary-card strong {
  color: #1f8f78;
  font-size: 20px;
}

.summary-card span {
  margin-top: 2px;
  color: #667789;
  font-size: 12px;
}

.code-tabs {
  flex: 1;
  min-height: 0;
}

.empty-inline {
  min-height: 300px;
  border: 1px dashed #dce3ea;
  border-radius: 6px;
  background: #fbfcfd;
}

.candidate-list {
  display: grid;
  gap: 10px;
  max-height: 300px;
  overflow: auto;
}

.candidate-list article {
  padding: 12px;
  border: 1px solid #e4e9ee;
  border-radius: 6px;
  background: #fbfcfd;
}

.candidate-list strong,
.candidate-list span {
  display: block;
}

.candidate-list span {
  margin-top: 4px;
  color: #71808f;
  font-size: 12px;
}

.candidate-list p {
  margin: 8px 0 0;
  line-height: 1.5;
}

.filter-note {
  margin: 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f0faf7;
  color: #536475;
  font-size: 12px;
}

@media (max-width: 780px) {
  .analysis-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
