<template>
  <article class="paper-panel">
    <div v-if="loading" class="state-placeholder">加载论文中...</div>
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
      <el-button size="small" @click="$emit('retry')">重试</el-button>
    </div>
    <div
      v-else-if="!hasPaper && (parseStatus === 'queued' || parseStatus === 'running')"
      class="state-placeholder"
    >
      <el-icon class="parsing-spin"><Loading /></el-icon>
      <span>正在解析论文…</span>
      <small>MinerU 正在提取正文、公式与图表，双栏长论文通常需要数分钟</small>
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
          @mouseover="onTraceOver"
          @mouseout="onTraceOut"
          @click="onTraceClick"
        />
      </div>
    </template>
  </article>
</template>

<script setup lang="ts">
import 'katex/dist/katex.min.css'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { getPaperAssetBlob, resolvePaperAssetUrl } from '@/api/paper-api'
import { renderPaperMarkdown } from './markdown-renderer'
import {
  decoratePaperTargets,
  setActivePaperTargets,
  type PaperMark,
} from './trace-decorations'
import type { WorkspacePaperBlock } from '@/types/papers'

const props = defineProps<{
  markdown: string
  assetBaseUrl: string
  activeSectionId: string
  hasPaper: boolean
  loading: boolean
  error: string | null
  source: string
  parseStatus?: string
  blocks: WorkspacePaperBlock[]
  traceTargets?: PaperMark[]
  activeTargetIds?: Set<string>
  revealActive?: boolean
}>()

const emit = defineEmits<{
  selectSection: [sectionId: string]
  retry: []
  traceHover: [targetId: string]
  traceLeave: []
  tracePin: [targetId: string]
}>()

const scrollRef = ref<HTMLElement | null>(null)
const markdownRef = ref<HTMLElement | null>(null)
const zoom = ref(100)
const desktopRuntime = '__TAURI_INTERNALS__' in window
const imageObjectUrls = new Set<string>()
let scrollFrame = 0
let suppressScrollTrackingUntil = 0
let highlightedElement: HTMLElement | null = null

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
      if (/^(?:data:image\/|blob:)/i.test(assetUrl)) return
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

function scrollToBlock(blockId: string, quote = ''): boolean {
  const root = scrollRef.value
  if (!root) return false
  const block = props.blocks.find((item) => item.id === blockId)
  // Prefer the injected block anchor (id or data-paper-block-id); fall back to fuzzy quote.
  let target =
    root.querySelector<HTMLElement>(`[data-paper-block-id="${CSS.escape(blockId)}"]`) ||
    (block?.anchor_resolved
      ? root.querySelector<HTMLElement>(`#${CSS.escape(block.render_anchor)}`)
      : null)
  if (!target && quote) {
    const needle = quote.replace(/\s+/g, ' ').trim().slice(0, 120)
    target = [...root.querySelectorAll<HTMLElement>('p, li, pre, blockquote, td')].find((item) =>
      item.textContent?.replace(/\s+/g, ' ').includes(needle),
    ) ?? null
  }
  if (!target) return false
  highlightedElement?.classList.remove('paper-block-highlight')
  const visualTarget = target.matches('span')
    ? target.closest<HTMLElement>('h1, h2, h3, h4, h5, h6, p, li, pre, blockquote, td')
      || target.nextElementSibling as HTMLElement | null
    : target
  highlightedElement = visualTarget || target
  highlightedElement.classList.add('paper-block-highlight')
  const top = target.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop
  // Suppress scroll-tracking for the duration of the smooth animation, otherwise the
  // intermediate scroll events flip the active section to section-1 and snap to the top.
  suppressScrollTrackingUntil = Date.now() + 900
  root.scrollTo({ top: Math.max(0, top - root.clientHeight * 0.2), behavior: 'smooth' })
  window.setTimeout(() => {
    highlightedElement?.classList.remove('paper-block-highlight')
    highlightedElement = null
  }, 1500)
  return true
}

function applyTraceDecorations(): void {
  const root = markdownRef.value
  if (!root) return
  decoratePaperTargets(root, props.traceTargets ?? [])
  setActivePaperTargets(root, props.activeTargetIds ?? new Set())
}

function revealActiveTarget(): void {
  const root = scrollRef.value
  const body = markdownRef.value
  if (!root || !body || !props.revealActive) return
  const active = body.querySelector<HTMLElement>('[data-trace-target].trace-target-active')
  if (!active) return
  const top = active.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop
  suppressScrollTrackingUntil = Date.now() + 900
  root.scrollTo({ top: Math.max(0, top - root.clientHeight * 0.35), behavior: 'smooth' })
}

function traceTargetId(event: Event): string | null {
  const el = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-trace-target]')
  return el?.dataset.traceTarget ?? null
}

function onTraceOver(event: MouseEvent): void {
  const id = traceTargetId(event)
  if (id) emit('traceHover', id)
}

function onTraceOut(event: MouseEvent): void {
  if (traceTargetId(event)) emit('traceLeave')
}

function onTraceClick(event: MouseEvent): void {
  const id = traceTargetId(event)
  if (id) emit('tracePin', id)
}

function updateActiveSection(): void {
  if (Date.now() < suppressScrollTrackingUntil) return
  window.cancelAnimationFrame(scrollFrame)
  scrollFrame = window.requestAnimationFrame(() => {
    const root = scrollRef.value
    if (!root) return
    const headings = [...root.querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]')]
    // Start from null (NOT headings[0]); otherwise any sample above the first heading — which
    // every smooth programmatic jump passes through — would emit section-1 and snap to the top.
    const active = headings.reduce<HTMLElement | null>((current, heading) => {
      return heading.offsetTop <= root.scrollTop + 70 ? heading : current
    }, null)
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
    applyTraceDecorations()
  },
  { immediate: true },
)

watch(
  () => props.traceTargets,
  async () => {
    await nextTick()
    applyTraceDecorations()
  },
  { deep: true },
)

watch(
  () => props.activeTargetIds,
  async () => {
    const root = markdownRef.value
    if (root) setActivePaperTargets(root, props.activeTargetIds ?? new Set())
    await nextTick()
    revealActiveTarget()
  },
  { deep: true },
)

onBeforeUnmount(revokeImageObjectUrls)

defineExpose({ scrollToSection, scrollToBlock })
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

.state-placeholder small {
  color: #9aa5b1;
  font-size: 11px;
}

.parsing-spin {
  font-size: 22px;
  color: #5885ff;
  animation: paper-parsing-spin 1s linear infinite;
}

@keyframes paper-parsing-spin {
  to {
    transform: rotate(360deg);
  }
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

.markdown-body :deep(.paper-block-highlight) {
  background: #fff2b8;
  outline: 2px solid #e6b94f;
  outline-offset: 3px;
  transition: background 180ms ease;
}

/* Resting decoration for traceable paper fragments. */
.markdown-body :deep(.trace-mark) {
  border-radius: 2px;
  cursor: pointer;
  transition: background 140ms ease, box-shadow 140ms ease;
}

.markdown-body :deep(.trace-mark-proposed) {
  background: rgba(88, 133, 255, 0.16);
  box-shadow: inset 0 -2px 0 rgba(88, 133, 255, 0.45);
  color: inherit;
}

.markdown-body :deep(.trace-mark-accepted) {
  background: rgba(46, 168, 118, 0.2);
  box-shadow: inset 0 -2px 0 rgba(46, 168, 118, 0.6);
  color: inherit;
}

.markdown-body :deep(.trace-block-target) {
  cursor: pointer;
  border-left: 3px solid rgba(88, 133, 255, 0.5);
  background: rgba(88, 133, 255, 0.1);
  border-radius: 2px;
  padding-left: 8px;
  margin-left: -11px;
  transition: background 140ms ease;
}

.markdown-body :deep(.trace-block-accepted) {
  border-left-color: rgba(46, 168, 118, 0.65);
  background: rgba(46, 168, 118, 0.12);
}

.markdown-body :deep(.trace-target-active) {
  background: #ffe8a3 !important;
  box-shadow: inset 0 -2px 0 #e0a83a, 0 0 0 2px rgba(224, 168, 58, 0.4) !important;
  border-left-color: #e0a83a !important;
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
