<template>
  <section class="panel">
    <header class="panel-header">
      <div>
        <h2>论文阅读区</h2>
        <p v-if="paper">{{ paper.filename }}</p>
        <p v-else>等待上传论文 PDF</p>
      </div>
      <el-tag v-if="paper" type="success">{{ paper.paragraphs.length }} 段</el-tag>
    </header>

    <el-empty v-if="!paper" description="暂无论文解析结果" />
    <template v-else>
      <h3 class="paper-title">{{ paper.title || '未识别标题' }}</h3>
      <div class="abstract">
        <strong>摘要</strong>
        <p>{{ paper.abstract || '未识别摘要，后续可接入更强的版面解析。' }}</p>
      </div>
      <el-tabs>
        <el-tab-pane label="章节">
          <el-table :data="paper.sections" size="small" max-height="260">
            <el-table-column prop="title" label="标题" min-width="220" />
            <el-table-column prop="page" label="页码" width="90" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="段落">
          <div class="paragraph-list">
            <article v-for="paragraph in visibleParagraphs" :key="String(paragraph.id)">
              <span>{{ paragraph.id }}</span>
              <p>{{ paragraph.text }}</p>
            </article>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { PaperDocument } from '@/types/api'

const props = defineProps<{
  paper: PaperDocument | null
}>()

const visibleParagraphs = computed(() => props.paper?.paragraphs.slice(0, 20) ?? [])
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

.paper-title {
  margin: 0 0 12px;
  line-height: 1.35;
}

.abstract {
  margin-bottom: 12px;
  padding: 12px;
  border-left: 4px solid #1f8f78;
  background: #f0faf7;
}

.abstract p {
  margin: 6px 0 0;
  line-height: 1.7;
}

.paragraph-list {
  display: grid;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
}

.paragraph-list article {
  padding: 10px 12px;
  border: 1px solid #e4e9ee;
  border-radius: 6px;
  background: #fbfcfd;
}

.paragraph-list span {
  color: #1f8f78;
  font-size: 12px;
  font-weight: 700;
}

.paragraph-list p {
  margin: 4px 0 0;
  line-height: 1.65;
}
</style>

