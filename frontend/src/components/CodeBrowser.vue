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
      <el-tabs>
        <el-tab-pane label="文件树">
          <el-table :data="repository.file_tree" size="small" max-height="340">
            <el-table-column prop="path" label="路径" min-width="260" />
            <el-table-column prop="language" label="类型" width="100" />
            <el-table-column prop="size" label="大小" width="100" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="符号">
          <el-table :data="repository.symbols" size="small" max-height="340">
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column prop="type" label="类型" width="100" />
            <el-table-column prop="path" label="文件" min-width="220" />
            <el-table-column prop="line" label="行号" width="90" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="PyTorch 候选">
          <div class="candidate-list">
            <article v-for="candidate in repository.pytorch_candidates" :key="candidateKey(candidate)">
              <strong>{{ candidate.name }}</strong>
              <span>{{ candidate.path }}:{{ candidate.line }}</span>
              <p>{{ candidate.reason }}</p>
            </article>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>
  </section>
</template>

<script setup lang="ts">
import type { CodeRepository } from '@/types/api'

defineProps<{
  repository: CodeRepository | null
}>()

function candidateKey(candidate: Record<string, unknown>): string {
  return `${String(candidate.path)}:${String(candidate.name)}:${String(candidate.line)}`
}
</script>

<style scoped>
.panel {
  min-height: 520px;
  padding: 18px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: white;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.panel-header h2 {
  margin: 0;
  font-size: 18px;
}

.panel-header p {
  margin: 4px 0 0;
  color: #71808f;
}

.candidate-list {
  display: grid;
  gap: 10px;
  max-height: 340px;
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
</style>

