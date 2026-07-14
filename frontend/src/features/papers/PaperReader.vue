<template>
  <article class="paper-panel">
    <header class="panel-title">
      <div>
        <h2>论文原文</h2>
        <p>只读 PDF 页视图，支持段落、公式、图表锚点高亮，不提供内容编辑。</p>
      </div>
      <el-tag type="info" effect="plain">{{ filename || '未上传论文' }}</el-tag>
    </header>

    <!-- Loading state -->
    <div v-if="loading" class="state-placeholder">
      <el-icon class="is-loading" :size="24"><i class="el-icon-loading" /></el-icon>
      <span>加载论文中...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
      <el-button size="small" @click="$emit('retry')">重试</el-button>
    </div>

    <!-- Empty state -->
    <el-empty v-else-if="!hasPaper" description="请先上传论文 PDF" />

    <!-- Content -->
    <template v-else>
      <div class="pdf-toolbar">
        <span>第 {{ activePage }} / {{ pageNumbers.length || 1 }} 页</span>
        <div>
          <button>缩小</button>
          <button>100%</button>
          <button>放大</button>
        </div>
      </div>

      <div class="pdf-reader">
        <!-- Page rail -->
        <aside class="page-rail">
          <button
            v-for="page in pageNumbers"
            :key="page"
            :class="{ active: page === activePage }"
            @click="$emit('update:activePage', page)"
          >
            <span>Page</span>
            <strong>{{ page }}</strong>
          </button>
        </aside>

        <div class="paper-scroll">
          <div v-if="activeContent" class="paper-page" aria-label="只读论文预览">
            <div class="paper-meta">Page {{ activeContent.page_number }}</div>
            <h3>{{ activeContent.title }}</h3>
            <p v-if="activePage === 1 && abstract" class="paper-abstract">
              {{ abstract }}
            </p>
            <section
              v-for="(paragraph, index) in activeContent.body"
              :key="index"
              :class="['paper-section', { highlighted: activeBlockIndex === index }]"
              :ref="(el) => registerBlockRef(index, el as HTMLElement)"
              @click="$emit('selectBlock', index)"
            >
              <p>{{ paragraph }}</p>
            </section>
          </div>
          <el-empty v-else description="请先上传论文 PDF" />
        </div>
      </div>
    </template>
  </article>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { WorkspacePaperPage } from '@/types/papers'

defineProps<{
  filename: string
  abstract: string
  pageNumbers: number[]
  activePage: number
  activeContent: WorkspacePaperPage | undefined
  hasPaper: boolean
  loading: boolean
  error: string | null
  activeBlockIndex: number
}>()

defineEmits<{
  'update:activePage': [page: number]
  selectBlock: [index: number]
  retry: []
}>()

const blockRefs = ref<Map<number, HTMLElement>>(new Map())

function registerBlockRef(index: number, el: HTMLElement | null): void {
  if (el) {
    blockRefs.value.set(index, el)
  } else {
    blockRefs.value.delete(index)
  }
}

function scrollToBlock(index: number): void {
  const el = blockRefs.value.get(index)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

defineExpose({ scrollToBlock })
</script>

<style scoped>
.paper-panel {
  display: flex;
  height: var(--workspace-panel-height, 1040px);
  max-height: var(--workspace-panel-height, 1040px);
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.panel-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.panel-title h2 {
  margin: 0;
}

.panel-title p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.state-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px;
  color: #667789;
}

.state-error {
  color: #e15a4a;
}

.pdf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  color: #536475;
  font-size: 13px;
}

.pdf-toolbar div {
  display: inline-flex;
  gap: 6px;
}

.pdf-toolbar button {
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: #ffffff;
  color: #536475;
  cursor: pointer;
  font: inherit;
}

.pdf-reader {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.page-rail {
  display: grid;
  align-content: start;
  gap: 8px;
  overflow-y: auto;
  min-height: 0;
}

.page-rail button {
  display: grid;
  gap: 2px;
  padding: 8px;
  border: 1px solid #dce3ea;
  border-radius: 6px;
  background: #ffffff;
  color: #667789;
  cursor: pointer;
  font: inherit;
}

.page-rail button.active {
  border-color: #1f8f78;
  background: #e9f6f3;
  color: #1f8f78;
}

.page-rail span {
  font-size: 11px;
}

.paper-scroll {
  min-height: 0;
  overflow-y: auto;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.paper-page {
  min-height: 0;
  padding: 32px 36px;
  background: #ffffff;
  box-shadow: inset 0 0 0 1px #edf1f4;
}

.paper-meta {
  color: #8a97a5;
  font-size: 12px;
  text-transform: uppercase;
}

.paper-page h3 {
  margin: 12px 0 14px;
  color: #16232f;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 26px;
  line-height: 1.25;
}

.paper-abstract,
.paper-section p {
  color: #2d3b48;
  font-family: Georgia, "Times New Roman", serif;
  line-height: 1.8;
}

.paper-section {
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.paper-section:hover {
  background: rgba(31, 143, 120, 0.04);
}

.paper-section.highlighted {
  background: rgba(31, 143, 120, 0.1);
  border-left: 3px solid #1f8f78;
}

@media (max-width: 1180px) {
  .paper-panel {
    height: auto;
    max-height: none;
    min-height: 840px;
  }
}

@media (max-width: 820px) {
  .panel-title {
    align-items: stretch;
    flex-direction: column;
  }

  .paper-page {
    padding: 26px 22px;
  }
}
</style>
