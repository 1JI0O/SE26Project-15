<template>
  <article class="paper-panel">
    <div v-if="loading" class="state-placeholder">加载论文中...</div>
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
      <el-button size="small" @click="$emit('retry')">重试</el-button>
    </div>
    <el-empty v-else-if="!hasPaper" description="请先上传论文 PDF" />
    <template v-else>
      <div class="markdown-toolbar">
        <span>{{ source === 'mineru-markdown' ? 'MinerU 结构化 Markdown' : '结构化文本兼容模式' }}</span>
        <div class="zoom-controls">
          <button aria-label="缩小论文" @click="zoom = Math.max(75, zoom - 10)">−</button>
          <button aria-label="重置论文缩放" @click="zoom = 100">{{ zoom }}%</button>
          <button aria-label="放大论文" @click="zoom = Math.min(150, zoom + 10)">＋</button>
        </div>
      </div>
      <div ref="scrollRef" class="paper-scroll" @scroll="updateActiveSection">
        <article
          ref="markdownRef"
          class="markdown-body"
          :style="{ fontSize: `${zoom}%` }"
          aria-label="只读论文 Markdown"
          v-html="renderedMarkdown"
        />
      </div>
    </template>
  </article>
</template>

<script setup lang="ts">
import 'katex/dist/katex.min.css'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { getPaperAssetBlob, resolvePaperAssetUrl } from '@/api/paper-api'
import { renderPaperMarkdown } from './markdown-renderer'

const props = defineProps<{
  markdown: string
  assetBaseUrl: string
  activeSectionId: string
  hasPaper: boolean
  loading: boolean
  error: string | null
  source: string
}>()

const emit = defineEmits<{
  selectSection: [sectionId: string]
  retry: []
}>()

const scrollRef = ref<HTMLElement | null>(null)
const markdownRef = ref<HTMLElement | null>(null)
const zoom = ref(100)
const desktopRuntime = '__TAURI_INTERNALS__' in window
const imageObjectUrls = new Set<string>()
let scrollFrame = 0
let suppressScrollTrackingUntil = 0

const renderedMarkdown = computed(() =>
  renderPaperMarkdown(props.markdown, (path) => resolvePaperAssetUrl(props.assetBaseUrl, path)),
)

function revokeImageObjectUrls(): void {
  for (const objectUrl of imageObjectUrls) URL.revokeObjectURL(objectUrl)
  imageObjectUrls.clear()
}

async function hydrateDesktopImages(): Promise<void> {
  if (!desktopRuntime) return
  const root = markdownRef.value
  if (!root) return
  revokeImageObjectUrls()
  const images = [...root.querySelectorAll<HTMLImageElement>('img[data-paper-asset-url]')]
  await Promise.all(
    images.map(async (image) => {
      const assetUrl = image.dataset.paperAssetUrl
      if (!assetUrl) return
      try {
        const blob = await getPaperAssetBlob(assetUrl)
        if (!root.contains(image)) return
        const objectUrl = URL.createObjectURL(blob)
        imageObjectUrls.add(objectUrl)
        image.src = objectUrl
      } catch {
        image.classList.add('image-load-error')
      }
    }),
  )
}

function scrollToSection(sectionId: string): void {
  const root = scrollRef.value
  const section = root?.querySelector<HTMLElement>(`#${CSS.escape(sectionId)}`)
  if (!root || !section) return
  const top =
    sectionId === 'section-1'
      ? 0
      : section.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - 18
  suppressScrollTrackingUntil = Date.now() + 150
  root.scrollTo({ top, behavior: 'auto' })
}

function updateActiveSection(): void {
  if (Date.now() < suppressScrollTrackingUntil) return
  window.cancelAnimationFrame(scrollFrame)
  scrollFrame = window.requestAnimationFrame(() => {
    const root = scrollRef.value
    if (!root) return
    const headings = [...root.querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]')]
    const active = headings.reduce<HTMLElement | null>((current, heading) => {
      return heading.offsetTop <= root.scrollTop + 70 ? heading : current
    }, headings[0] ?? null)
    if (active?.id && active.id !== props.activeSectionId) emit('selectSection', active.id)
  })
}

watch(
  () => props.activeSectionId,
  async (sectionId, previous) => {
    if (!sectionId || sectionId === previous) return
    await nextTick()
    scrollToSection(sectionId)
  },
)

watch(
  () => props.markdown,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: 0 })
    await hydrateDesktopImages()
  },
  { immediate: true },
)

onBeforeUnmount(revokeImageObjectUrls)

defineExpose({ scrollToSection })
</script>

<style scoped>
.paper-panel {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #ffffff;
}

.state-placeholder {
  display: grid;
  min-height: 220px;
  flex: 1;
  place-content: center;
  gap: 10px;
  color: #6b7785;
  font-size: 12px;
  text-align: center;
}

.state-error {
  color: #b64a3c;
}

.markdown-toolbar {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 8px 0 11px;
  border-bottom: 1px solid #d8dee6;
  background: #f8fafb;
  color: #71808e;
  font-size: 10px;
}

.zoom-controls {
  display: flex;
  gap: 2px;
}

.zoom-controls button {
  min-width: 27px;
  height: 23px;
  padding: 0 5px;
  border: 1px solid #d8dee6;
  border-radius: 3px;
  background: #ffffff;
  color: #586675;
  cursor: pointer;
  font: inherit;
}

.paper-scroll {
  min-height: 0;
  flex: 1;
  overflow: auto;
  background: #eef1f4;
}

.markdown-body {
  width: min(100%, 920px);
  min-height: 100%;
  margin: 0 auto;
  padding: 34px clamp(24px, 5%, 62px) 80px;
  overflow-wrap: anywhere;
  background: #ffffff;
  color: #26323d;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 100%;
  line-height: 1.72;
  box-sizing: border-box;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  scroll-margin-top: 20px;
  color: #15232f;
  line-height: 1.3;
}

.markdown-body :deep(h1) {
  margin: 0 0 24px;
  font-size: 1.8em;
}

.markdown-body :deep(h2) {
  margin: 34px 0 14px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e1e6eb;
  font-size: 1.35em;
}

.markdown-body :deep(h3) {
  margin: 26px 0 10px;
  font-size: 1.14em;
}

.markdown-body :deep(p) {
  margin: 0 0 1em;
}

.markdown-body :deep(img) {
  display: block;
  max-width: 100%;
  max-height: 68vh;
  margin: 20px auto 8px;
  object-fit: contain;
}

.markdown-body :deep(.table-scroll) {
  max-width: 100%;
  margin: 18px 0;
  overflow-x: auto;
}

.markdown-body :deep(table) {
  width: max-content;
  min-width: 100%;
  margin: 0;
  border-collapse: collapse;
  table-layout: auto;
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 0.76em;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 6px 8px;
  border: 1px solid #cfd7df;
  overflow-wrap: anywhere;
  vertical-align: top;
}

.markdown-body :deep(.math-display) {
  max-width: 100%;
  margin: 18px 0;
  overflow-x: auto;
  overflow-y: hidden;
  text-align: center;
}

.markdown-body :deep(pre) {
  max-width: 100%;
  padding: 12px;
  overflow: auto;
  background: #f4f6f8;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 0.82em;
}

.markdown-body :deep(a) {
  color: #147866;
}
</style>
