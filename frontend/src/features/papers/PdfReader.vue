<template>
  <div class="pdf-reader">
    <div v-if="loading" class="state-placeholder">
      <el-icon class="pdf-spin"><Loading /></el-icon>
      <span>加载 PDF…</span>
    </div>
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
      <el-button size="small" @click="load">重试</el-button>
    </div>
    <div v-else ref="scrollRef" class="pdf-scroll">
      <div class="pdf-pages" :style="{ width: `${pageWidthPercent}%` }">
        <section
          v-for="page in pages"
          :key="page.number"
          :ref="(el) => registerPage(page.number, el as unknown as HTMLElement | null)"
          class="pdf-page"
          :data-page="page.number"
          :style="{ aspectRatio: `${page.width} / ${page.height}` }"
        >
          <canvas
            :ref="(el) => registerCanvas(page.number, el as unknown as HTMLCanvasElement | null)"
          />
          <!-- Rects are page fractions, so percentage positioning keeps them aligned at
               every zoom level without recomputing anything. -->
          <div class="pdf-highlight-layer">
            <button
              v-for="(rect, index) in highlightsByPage.get(page.number) ?? []"
              :key="`${rect.targetId}-${index}`"
              type="button"
              class="pdf-highlight"
              :class="[
                `pdf-highlight-${rect.status}`,
                {
                  'pdf-highlight-coarse': !rect.precise,
                  'pdf-highlight-active': activeTargetIds?.has(rect.targetId),
                  'pdf-highlight-hover': hoverTargetIds?.has(rect.targetId),
                },
              ]"
              :style="{
                left: `${rect.left * 100}%`,
                top: `${rect.top * 100}%`,
                width: `${rect.width * 100}%`,
                height: `${rect.height * 100}%`,
              }"
              :aria-label="`追溯高亮，第 ${page.number} 页`"
              @mouseenter="emit('traceHover', rect.targetId)"
              @mouseleave="emit('traceLeave')"
              @click="emit('tracePin', rect.targetId)"
            />
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
// Derived rather than imported: pdfjs-dist does not re-export RenderTask from its root
// type entry point across all 4.x releases.
type RenderTask = ReturnType<PDFPageProxy['render']>
// `?url` emits the worker as a local asset and lets pdf.js own the worker lifecycle
// (a shared `workerPort` would be torn down by the first document to be destroyed).
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { getPaperPdfData } from '@/api/paper-api'
import {
  buildHighlightRects,
  groupByPage,
  type HighlightRect,
  type PageAspects,
} from './pdf-highlights'
import type { PaperMark } from './trace-decorations'
import type { WorkspacePaperBlock } from '@/types/papers'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

/** Staged out of pdfjs-dist by scripts/copy-pdfjs-assets.mjs — never fetched from a CDN. */
const CMAP_URL = '/pdfjs/cmaps/'
const STANDARD_FONT_URL = '/pdfjs/standard_fonts/'

interface PageInfo {
  number: number
  /** Unscaled CSS pixel size, used only to reserve the right aspect ratio up front. */
  width: number
  height: number
}

const props = defineProps<{
  pdfUrl: string
  blocks: WorkspacePaperBlock[]
  traceTargets?: PaperMark[]
  activeTargetIds?: Set<string>
  hoverTargetIds?: Set<string>
  /** Percentage, shared with the markdown view's zoom control. */
  zoom?: number
}>()

const emit = defineEmits<{
  traceHover: [targetId: string]
  traceLeave: []
  tracePin: [targetId: string]
}>()

const scrollRef = ref<HTMLElement | null>(null)
const pages = ref<PageInfo[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const pageElements = new Map<number, HTMLElement>()
const canvasElements = new Map<number, HTMLCanvasElement>()
const renderTasks = new Map<number, RenderTask>()
const renderedAtWidth = new Map<number, number>()
let document_: PDFDocumentProxy | null = null
let observer: IntersectionObserver | null = null
// Guards against a slow load finishing after the user switched papers.
let loadToken = 0

// Matches the markdown view's 75-150 range; above 100% the pane scrolls horizontally.
const pageWidthPercent = computed(() => Math.max(30, Math.min(150, props.zoom ?? 100)))

// Shape of each page as pdf.js actually laid it out, so geometry measured against a
// differently-shaped page (a rotated one) is discarded instead of drawn askew.
const pageAspects = computed<PageAspects>(
  () => new Map(pages.value.map((page) => [page.number, page.width / page.height])),
)

const highlights = computed<{ rects: HighlightRect[]; unresolved: Set<string> }>(() =>
  buildHighlightRects(props.traceTargets ?? [], props.blocks, pageAspects.value),
)
const highlightsByPage = computed(() => groupByPage(highlights.value.rects))
const unresolvedTargetIds = computed(() => highlights.value.unresolved)

function registerPage(number: number, el: HTMLElement | null): void {
  if (el) {
    pageElements.set(number, el)
    observer?.observe(el)
  } else {
    const existing = pageElements.get(number)
    if (existing) observer?.unobserve(existing)
    pageElements.delete(number)
  }
}

function registerCanvas(number: number, el: HTMLCanvasElement | null): void {
  if (el) canvasElements.set(number, el)
  else canvasElements.delete(number)
}

function cancelRender(pageNumber: number): void {
  const task = renderTasks.get(pageNumber)
  if (!task) return
  task.cancel()
  renderTasks.delete(pageNumber)
}

/**
 * Draw one page at the size it currently occupies.
 *
 * Rendering is keyed on the element's CSS width so a zoom change re-renders at the new
 * resolution instead of upscaling a stale bitmap, while scrolling past an already-drawn
 * page at the same width is a no-op.
 */
async function renderPage(pageNumber: number): Promise<void> {
  const doc = document_
  const canvas = canvasElements.get(pageNumber)
  const host = pageElements.get(pageNumber)
  if (!doc || !canvas || !host) return

  const cssWidth = host.clientWidth
  if (cssWidth <= 0) return
  if (renderedAtWidth.get(pageNumber) === cssWidth) return

  const token = loadToken
  let page: PDFPageProxy
  try {
    page = await doc.getPage(pageNumber)
  } catch {
    return
  }
  if (token !== loadToken) return

  const unscaled = page.getViewport({ scale: 1 })
  // Cap the backing store so a high-DPI display does not allocate huge canvases for a
  // 30-page paper; 2x is already beyond what the eye resolves at reading size.
  const ratio = Math.min(window.devicePixelRatio || 1, 2)
  const viewport = page.getViewport({ scale: (cssWidth / unscaled.width) * ratio })
  const context = canvas.getContext('2d')
  if (!context) return

  cancelRender(pageNumber)
  canvas.width = Math.floor(viewport.width)
  canvas.height = Math.floor(viewport.height)

  const task = page.render({ canvasContext: context, viewport })
  renderTasks.set(pageNumber, task)
  try {
    await task.promise
    if (token === loadToken) renderedAtWidth.set(pageNumber, cssWidth)
  } catch {
    // A cancelled render (zoom change, unmount) is expected; leave the page unmarked so
    // it is drawn again next time it becomes visible.
  } finally {
    // Only clear our own entry: a concurrent call for this page may have cancelled this
    // task and registered its own, and deleting that would leave it untrackable.
    if (renderTasks.get(pageNumber) === task) renderTasks.delete(pageNumber)
  }
}

function setupObserver(): void {
  observer?.disconnect()
  const root = scrollRef.value
  if (!root) return
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const pageNumber = Number((entry.target as HTMLElement).dataset.page)
        if (Number.isFinite(pageNumber)) void renderPage(pageNumber)
      }
    },
    // Pre-render roughly a screen ahead so scrolling rarely lands on a blank page.
    { root, rootMargin: '250% 0px' },
  )
  for (const element of pageElements.values()) observer.observe(element)
}

function teardown(): void {
  observer?.disconnect()
  observer = null
  for (const pageNumber of [...renderTasks.keys()]) cancelRender(pageNumber)
  renderedAtWidth.clear()
  void document_?.destroy()
  document_ = null
}

async function load(): Promise<void> {
  if (!props.pdfUrl) return
  loadToken += 1
  const token = loadToken
  teardown()
  pages.value = []
  loading.value = true
  error.value = null
  try {
    const data = await getPaperPdfData(props.pdfUrl)
    if (token !== loadToken) return
    const doc = await pdfjsLib.getDocument({
      data: new Uint8Array(data),
      cMapUrl: CMAP_URL,
      cMapPacked: true,
      standardFontDataUrl: STANDARD_FONT_URL,
    }).promise
    if (token !== loadToken) {
      void doc.destroy()
      return
    }
    document_ = doc
    // Read every page's size up front so each placeholder reserves the correct aspect
    // ratio; without it the scroll height jumps around as pages render in.
    const infos: PageInfo[] = []
    for (let number = 1; number <= doc.numPages; number += 1) {
      const page = await doc.getPage(number)
      if (token !== loadToken) return
      const viewport = page.getViewport({ scale: 1 })
      infos.push({ number, width: viewport.width, height: viewport.height })
    }
    pages.value = infos
    // Drop the loading state BEFORE waiting for the DOM: the page list sits inside the
    // `v-else` branch, so while `loading` is true `scrollRef` is null and no page element
    // has registered itself — building the observer here would silently observe nothing
    // and every page would stay blank.
    loading.value = false
    await nextTick()
    setupObserver()
  } catch {
    if (token === loadToken) {
      error.value = 'PDF 加载失败，可尝试重新解析论文'
      loading.value = false
    }
  }
}

/** Scroll a page to the top of the pane, leaving a little breathing room. */
function scrollToPage(pageNumber: number, offsetFraction = 0): boolean {
  const root = scrollRef.value
  const element = pageElements.get(pageNumber)
  if (!root || !element) return false
  const top =
    element.getBoundingClientRect().top -
    root.getBoundingClientRect().top +
    root.scrollTop +
    element.clientHeight * offsetFraction -
    root.clientHeight * 0.3
  root.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  return true
}

/** Reveal a trace target; returns false when it has no geometry to scroll to. */
function scrollToTarget(targetId: string): boolean {
  const rect = highlights.value.rects.find((item) => item.targetId === targetId)
  if (!rect) return false
  return scrollToPage(rect.page, rect.top)
}

watch(() => props.pdfUrl, load, { immediate: true })

watch(
  () => props.zoom,
  async () => {
    // Width changed, so every drawn bitmap is now the wrong resolution.
    renderedAtWidth.clear()
    await nextTick()
    for (const [pageNumber, element] of pageElements) {
      const box = element.getBoundingClientRect()
      const root = scrollRef.value?.getBoundingClientRect()
      if (!root) continue
      if (box.bottom > root.top && box.top < root.bottom) void renderPage(pageNumber)
    }
  },
)

onBeforeUnmount(teardown)

defineExpose({ scrollToPage, scrollToTarget, unresolvedTargetIds })
</script>

<style scoped>
.pdf-reader {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
}

.state-placeholder {
  display: grid;
  min-height: 220px;
  flex: 1;
  place-content: center;
  justify-items: center;
  gap: 10px;
  color: #6b7785;
  font-size: 12px;
  text-align: center;
}

.state-error {
  color: #b64a3c;
}

.pdf-spin {
  font-size: 22px;
  color: #5885ff;
  animation: pdf-spin 1s linear infinite;
}

@keyframes pdf-spin {
  to {
    transform: rotate(360deg);
  }
}

.pdf-scroll {
  min-height: 0;
  flex: 1;
  overflow: auto;
  background: #eef1f4;
}

.pdf-pages {
  margin: 0 auto;
  padding: 18px 0 60px;
}

.pdf-page {
  position: relative;
  margin: 0 auto 16px;
  background: #ffffff;
  box-shadow: 0 1px 4px rgba(21, 35, 47, 0.16);
}

.pdf-page canvas {
  display: block;
  width: 100%;
  height: 100%;
}

.pdf-highlight-layer {
  position: absolute;
  inset: 0;
}

.pdf-highlight {
  position: absolute;
  padding: 0;
  border: 0;
  border-radius: 2px;
  background: rgba(88, 133, 255, 0.26);
  box-shadow: inset 0 -2px 0 rgba(88, 133, 255, 0.6);
  cursor: pointer;
  /* Multiply keeps the glyphs underneath legible instead of washing them out. */
  mix-blend-mode: multiply;
  transition: background 140ms ease, box-shadow 140ms ease;
}

.pdf-highlight-accepted {
  background: rgba(46, 168, 118, 0.28);
  box-shadow: inset 0 -2px 0 rgba(46, 168, 118, 0.7);
}

/* Block-level fallback: no line boxes, so the whole block is tinted. Drawn weaker and
   outlined so it reads as "somewhere in here" rather than a precise quote. */
.pdf-highlight-coarse {
  background: rgba(88, 133, 255, 0.13);
  outline: 1px dashed rgba(88, 133, 255, 0.5);
  outline-offset: 1px;
  box-shadow: none;
}

.pdf-highlight-accepted.pdf-highlight-coarse {
  background: rgba(46, 168, 118, 0.14);
  outline-color: rgba(46, 168, 118, 0.55);
}

.pdf-highlight-hover {
  background: rgba(224, 168, 58, 0.3);
}

.pdf-highlight-active {
  background: rgba(255, 205, 90, 0.55);
  outline: 2px solid #e0a83a;
  outline-offset: 1px;
  box-shadow: inset 0 -2px 0 #e0a83a;
}
</style>
