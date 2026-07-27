<template>
  <section class="trace-preview" aria-label="关系预览">
    <header class="trace-preview-header">
      <strong>关系预览</strong>
      <span>悬浮预览 / 已选中关系</span>
    </header>

    <div class="trace-preview-content">
      <div v-if="!hoveredSummary && !selectedSummary" class="trace-preview-empty">
        <strong>暂无预览关系</strong>
        <span>悬浮矩阵行可临时预览，点击矩阵行可固定关系。</span>
      </div>

      <article v-if="hoveredSummary" class="trace-card trace-card-hover">
        <header class="trace-card-head">
          <span>悬浮预览</span>
          <span class="trace-card-badge">{{ hoveredSummary.relationType }}</span>
        </header>
        <div class="trace-card-body">
          <section class="trace-card-side">
            <span class="trace-card-side-label">论文</span>
            <div
              class="trace-card-quote"
              v-html="
                renderPaperEvidenceHtml(
                  paperMarkdown,
                  hoveredSummary.paper.blockId,
                  hoveredSummary.paper.quote,
                  hoveredSummary.paper.occurrence,
                )
              "
            />
            <div class="trace-card-meta">
              {{ hoveredSummary.paper.blockId }}
              <template v-if="hoveredSummary.paper.targetType">
                · {{ hoveredSummary.paper.targetType }}
              </template>
            </div>
          </section>
          <section class="trace-card-side">
            <span class="trace-card-side-label">代码</span>
            <div class="trace-card-quote">{{ hoveredSummary.code.symbol }}</div>
            <div class="trace-card-meta">
              {{ hoveredSummary.code.path }}
              <template v-if="hoveredSummary.code.line">
                :{{ hoveredSummary.code.line }}
              </template>
            </div>
          </section>
          <div class="trace-card-scores">
            <span>相关度 {{ hoveredSummary.relevance }}%</span>
            <span>置信 {{ hoveredSummary.confidence }}%</span>
          </div>
        </div>
      </article>

      <article v-if="selectedSummary" class="trace-card trace-card-selected">
        <header class="trace-card-head">
          <span>已选中关系</span>
          <span class="trace-card-actions">
            <span class="trace-card-badge">{{ selectedSummary.relationType }}</span>
            <button class="trace-card-unpin" title="取消固定 (Esc)" @click="emit('unselect')">
              取消固定
            </button>
          </span>
        </header>
        <div class="trace-card-body">
          <section class="trace-card-side">
            <span class="trace-card-side-label">论文</span>
            <div v-if="selectedPaperUnresolved" class="trace-card-unresolved">
              论文锚点不可用（后端未解析该块）
            </div>
            <template v-else>
              <div
                class="trace-card-quote"
                v-html="
                  renderPaperEvidenceHtml(
                    paperMarkdown,
                    selectedSummary.paper.blockId,
                    selectedSummary.paper.quote,
                    selectedSummary.paper.occurrence,
                  )
                "
              />
              <div class="trace-card-meta">
                {{ selectedSummary.paper.blockId }}
                <template v-if="selectedSummary.paper.targetType">
                  · {{ selectedSummary.paper.targetType }}
                </template>
              </div>
            </template>
          </section>
          <section class="trace-card-side">
            <span class="trace-card-side-label">代码</span>
            <div class="trace-card-quote">{{ selectedSummary.code.symbol }}</div>
            <div class="trace-card-meta">
              {{ selectedSummary.code.path }}
              <template v-if="selectedSummary.code.line">
                :{{ selectedSummary.code.line }}
              </template>
            </div>
          </section>
          <div class="trace-card-scores">
            <span>相关度 {{ selectedSummary.relevance }}%</span>
            <span>置信 {{ selectedSummary.confidence }}%</span>
          </div>
          <p v-if="selectedSummary.otherLinkCount" class="trace-card-more">
            另有 {{ selectedSummary.otherLinkCount }} 条更低相关度关系
          </p>
          <p
            v-if="selectedSummary.rationale"
            class="trace-card-rationale"
            v-html="renderTraceRichText(selectedSummary.rationale)"
          />
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { TraceLinkSummary } from '@/composables/useTraceIndex'
import {
  renderPaperEvidenceHtml,
  renderTraceRichText,
} from '@/features/papers/markdown-renderer'

defineProps<{
  hoveredSummary: TraceLinkSummary | null
  selectedSummary: TraceLinkSummary | null
  paperMarkdown: string
  selectedPaperUnresolved: boolean
}>()

const emit = defineEmits<{
  unselect: []
}>()
</script>

<style scoped>
.trace-preview {
  display: grid;
  height: 100%;
  min-width: 0;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
  background: #ffffff;
}

.trace-preview-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 12px;
  border-bottom: 1px solid #e6ebf0;
  background: #f8fafb;
}

.trace-preview-header strong {
  color: #26323d;
  font-size: 12px;
}

.trace-preview-header span {
  overflow: hidden;
  color: #7a8794;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-preview-content {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.trace-preview-empty {
  display: flex;
  min-height: 76px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 12px;
  color: #7a8794;
  text-align: center;
}

.trace-preview-empty strong {
  color: #55636f;
  font-size: 12px;
}

.trace-preview-empty span {
  font-size: 11px;
  line-height: 1.5;
}

.trace-card {
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid #cdd6df;
  border-radius: 7px;
  background: #ffffff;
}

.trace-card-hover {
  border-color: #e0d0a6;
  background: #fffdf8;
}

.trace-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid #e6ebf0;
  background: #f7f9fb;
  color: #26323d;
  font-size: 12px;
  font-weight: 600;
}

.trace-card-actions {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.trace-card-badge {
  padding: 0 7px;
  border-radius: 999px;
  background: #e6efff;
  color: #3061c2;
  font-size: 10px;
  font-weight: 600;
}

.trace-card-unpin {
  padding: 1px 7px;
  border: 1px solid #d8dee6;
  border-radius: 4px;
  background: #ffffff;
  color: #586675;
  cursor: pointer;
  font: inherit;
  font-size: 10px;
}

.trace-card-unpin:hover {
  border-color: #1f8f78;
  color: #176f60;
}

.trace-card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 9px 10px;
}

.trace-card-side {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.trace-card-side-label {
  color: #8a97a4;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.trace-card-quote {
  min-width: 0;
  overflow-x: auto;
  color: #1c2b38;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.trace-card-quote :deep(p),
.trace-card-quote :deep(.math-display),
.trace-card-rationale :deep(p),
.trace-card-rationale :deep(.math-display) {
  margin: 0;
}

.trace-card-quote :deep(p + p),
.trace-card-rationale :deep(p + p) {
  margin-top: 0.35em;
}

.trace-card-quote :deep(.math-display),
.trace-card-rationale :deep(.math-display) {
  margin: 0.25em 0;
  overflow-x: auto;
}

.trace-card-quote :deep(.katex),
.trace-card-rationale :deep(.katex) {
  font-size: 1.05em;
  font-weight: 400;
}

.trace-card-meta {
  color: #7a8794;
  font-size: 10px;
  overflow-wrap: anywhere;
}

.trace-card-scores {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: #55636f;
  font-size: 10px;
}

.trace-card-rationale {
  margin: 0;
  color: #6b7785;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.trace-card-unresolved {
  padding: 4px 6px;
  border-radius: 3px;
  background: rgba(182, 74, 60, 0.1);
  color: #b64a3c;
  font-size: 11px;
  line-height: 1.5;
}

.trace-card-more {
  margin: 0;
  color: #8a95a1;
  font-size: 10px;
}
</style>
