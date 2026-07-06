<template>
  <div class="workspace-page">
    <section class="workspace-title">
      <div>
        <el-button text @click="$router.push('/')">返回项目列表</el-button>
        <h1>{{ project?.name ?? '项目工作台' }}</h1>
        <p>{{ project?.description || '上传论文与代码包后即可查看解析结果。' }}</p>
      </div>
      <el-tag type="info">Project #{{ projectId }}</el-tag>
    </section>

    <UploadPanel :project-id="projectId" @uploaded="refreshArtifacts" />

    <section class="split-view">
      <PaperReader :paper="paper" />
      <CodeBrowser :repository="repository" />
    </section>

    <TraceResultPanel
      :links="links"
      :loading="suggesting"
      :suggestions="suggestions"
      @suggest="suggest"
    />
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getCode, getPaper, getProject, listTraceLinks, suggestTraceLinks } from '@/api/projects'
import CodeBrowser from '@/components/CodeBrowser.vue'
import PaperReader from '@/components/PaperReader.vue'
import TraceResultPanel from '@/components/TraceResultPanel.vue'
import UploadPanel from '@/components/UploadPanel.vue'
import type { CodeRepository, PaperDocument, Project, TraceLink, TraceLinkSuggestion } from '@/types/api'

const route = useRoute()
const projectId = computed(() => Number(route.params.id)).value

const project = ref<Project | null>(null)
const paper = ref<PaperDocument | null>(null)
const repository = ref<CodeRepository | null>(null)
const links = ref<TraceLink[]>([])
const suggestions = ref<TraceLinkSuggestion[]>([])
const suggesting = ref(false)

onMounted(async () => {
  project.value = await getProject(projectId)
  await refreshArtifacts()
})

async function refreshArtifacts() {
  const [paperResult, codeResult, traceResult] = await Promise.allSettled([
    getPaper(projectId),
    getCode(projectId),
    listTraceLinks(projectId),
  ])
  paper.value = paperResult.status === 'fulfilled' ? paperResult.value : null
  repository.value = codeResult.status === 'fulfilled' ? codeResult.value : null
  links.value = traceResult.status === 'fulfilled' ? traceResult.value : []
}

async function suggest() {
  suggesting.value = true
  try {
    suggestions.value = await suggestTraceLinks(projectId)
    if (suggestions.value.length === 0) {
      ElMessage.info('暂无候选追溯关系')
    }
  } catch {
    ElMessage.warning('请先上传论文 PDF 和代码 ZIP')
  } finally {
    suggesting.value = false
  }
}
</script>

<style scoped>
.workspace-page {
  display: grid;
  gap: 18px;
}

.workspace-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: white;
}

.workspace-title h1 {
  margin: 4px 0 6px;
  font-size: 24px;
}

.workspace-title p {
  margin: 0;
  color: #667789;
}

.split-view {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}

@media (max-width: 1080px) {
  .split-view {
    grid-template-columns: 1fr;
  }
}
</style>

