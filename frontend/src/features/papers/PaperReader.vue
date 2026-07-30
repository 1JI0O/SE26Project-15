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
        <div class="view-switch" role="group" aria-label="切换论文视图">
          <button
            type="button"
            :class="{ active: viewMode === 'markdown' }"
            @click="viewMode = 'markdown'"
          >
            Markdown
          </button>
          <button
            type="button"
            :class="{ active: viewMode === 'pdf' }"
            :disabled="!pdfUrl || annotation.pickingPaper"
            :title="pdfViewTitle"
            @click="viewMode = 'pdf'"
          >
            PDF 原件
          </button>
        </div>
        <div class="zoom-controls">
          <button aria-label="缩小论文" @click="zoom = Math.max(75, zoom - 10)">−</button>
          <button aria-label="重置论文缩放" @click="zoom = 100">{{ zoom }}%</button>
          <button aria-label="放大论文" @click="zoom = Math.min(150, zoom + 10)">＋</button>
        </div>
      </div>
      <PdfReader
        v-if="viewMode === 'pdf' && pdfUrl"
        ref="pdfReaderRef"
        :pdf-url="pdfUrl"
        :blocks="blocks"
        :trace-targets="traceTargets"
        :active-target-ids="activeTargetIds"
        :hover-target-ids="hoverTargetIds"
        :zoom="zoom"
        @trace-hover="(id: string) => emit('traceHover', id)"
        @trace-leave="emit('traceLeave')"
        @trace-pin="(id: string) => emit('tracePin', id)"
      />
      <div v-show="viewMode === 'markdown'" ref="scrollRef" class="paper-scroll">
        <article
          ref="markdownRef"
          :class="['markdown-body', { 'annotation-picking': annotation.pickingPaper }]"
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
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { getPaperAssetBlob, resolvePaperAssetUrl } from '@/api/paper-api'
import { useAnnotationStore } from '@/stores/annotation'
import { renderPaperMarkdown } from './markdown-renderer'
import PdfReader from './PdfReader.vue'
import {
  decoratePaperTargets,
  resolveBlockIdAt,
  resolveEventTargetId,
  resolveVisualBlock,
  setActivePaperTargets,
  type PaperMark,
} from './trace-decorations'
import type { WorkspacePaperBlock } from '@/types/papers'
import { resolveSinglePaperBlock } from '@/features/tracing/annotation-selection'

const annotation = useAnnotationStore()

const props = defineProps<{
  markdown: string
  assetBaseUrl: string
  pdfUrl?: string | null
  activeSectionId: string
  hasPaper: boolean
  loading: boolean
  error: string | null
  source: string
  parseStatus?: string
  blocks: WorkspacePaperBlock[]
  traceTargets?: PaperMark[]
  activeTargetIds?: Set<string>
  hoverTargetIds?: Set<string>
}>()

const emit = defineEmits<{
  selectSection: [sectionId: string]
  observeSection: [sectionId: string]
  retry: []
  traceHover: [targetId: string]
  traceLeave: []
  tracePin: [targetId: string]
}>()

const scrollRef = ref<HTMLElement | null>(null)
const markdownRef = ref<HTMLElement | null>(null)
const pdfReaderRef = ref<InstanceType<typeof PdfReader> | null>(null)
const zoom = ref(100)
type ViewMode = 'markdown' | 'pdf'
const viewMode = ref<ViewMode>('markdown')
const pdfViewTitle = computed(() => {
  if (annotation.pickingPaper) return '完成论文内容选择后可切换 PDF 原件'
  return props.pdfUrl ? '在原始 PDF 上查看高亮' : '原始 PDF 不可用，请重新上传论文'
})

const desktopRuntime = '__TAURI_INTERNALS__' in window
const imageObjectUrls = new Set<string>()
// While a programmatic block/target jump is animating we must fully own the scroll: the section
// observer's highlight updates are harmless (they never scroll), but a TOC re-scroll must not snap
// over the jump. blockJumpActive gates scrollToSection. Settle is detected by watching scrollTop.
let blockJumpActive = false
let settleTimer = 0
let settleRaf = 0
let highlightTimer = 0
let highlightedElement: HTMLElement | null = null
const TEMP_HIGHLIGHT_MS = 3200
// Debounce hover so crossing glyph boundaries inside one mark doesn't flicker the trace box.
let lastHoveredTargetId: string | null = null
let hoverLeaveTimer = 0
// Observes which heading is at the top of the viewport (TOC highlight only, never scrolls).
let sectionObserver: IntersectionObserver | null = null
const headingVisibility = new Map<string, number>()

// Hold scroll-tracking suppression open until the smooth scroll actually stops (scrollTop
// stable for a few frames), instead of a fixed 900ms that can expire mid-animation.
function holdSuppressionUntilSettled(onSettled?: () => void): void {
  blockJumpActive = true
  window.clearTimeout(settleTimer)
  window.cancelAnimationFrame(settleRaf)
  const root = scrollRef.value
  if (!root) {
    blockJumpActive = false
    onSettled?.()
    return
  }
  let last = root.scrollTop
  let stableFrames = 0
  const finish = (): void => {
    window.cancelAnimationFrame(settleRaf)
    blockJumpActive = false
    onSettled?.()
  }
  const tick = (): void => {
    const current = root.scrollTop
    if (Math.abs(current - last) < 1) {
      stableFrames += 1
    } else {
      stableFrames = 0
    }
    last = current
    if (stableFrames >= 4) {
      finish()
      return
    }
    settleRaf = window.requestAnimationFrame(tick)
  }
  settleRaf = window.requestAnimationFrame(tick)
  // Hard safety cap: never stay locked longer than 2.5s.
  settleTimer = window.setTimeout(finish, 2500)
}

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
  // A trace/target jump owns the scroll; don't let a TOC re-scroll snap over it.
  if (blockJumpActive) return
  const root = scrollRef.value
  const section = root?.querySelector<HTMLElement>(`#${CSS.escape(sectionId)}`)
  if (!root || !section) return
  const top =
    section.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop - 18
  holdSuppressionUntilSettled()
  root.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
}

function clearTempHighlight(): void {
  window.clearTimeout(highlightTimer)
  highlightedElement?.classList.remove('paper-block-highlight')
  highlightedElement = null
}

function scheduleTempHighlight(el: HTMLElement): void {
  clearTempHighlight()
  highlightedElement = el
  highlightedElement.classList.add('paper-block-highlight')
  holdSuppressionUntilSettled(() => {
    highlightTimer = window.setTimeout(() => {
      highlightedElement?.classList.remove('paper-block-highlight')
      highlightedElement = null
    }, TEMP_HIGHLIGHT_MS)
  })
}

/** Scroll `el` to the vertical centre of the reading pane, using the pane's own scroll box.
 * `scrollIntoView({block:'center'})` walks every scrollable ancestor and could nudge the whole
 * workbench, so the offset is computed against `.paper-scroll` directly. */
function centerInPane(el: HTMLElement): void {
  const root = scrollRef.value
  if (!root) return
  const rootBox = root.getBoundingClientRect()
  const elBox = el.getBoundingClientRect()
  const offset = elBox.top - rootBox.top + root.scrollTop
  const top = offset - Math.max(0, (root.clientHeight - elBox.height) / 2)
  root.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
}

function scrollToBlock(blockId: string, quote = '', paperTargetId: string | null = null): boolean {
  // In PDF mode the markdown DOM is hidden, so anchor/quote lookups are meaningless —
  // reveal the target by its recorded page geometry instead.
  if (viewMode.value === 'pdf') {
    const reader = pdfReaderRef.value
    if (!reader) return false
    if (paperTargetId && reader.scrollToTarget(paperTargetId)) return true
    const block = props.blocks.find((item) => item.id === blockId)
    const page = block?.page_number ?? block?.page
    return page ? reader.scrollToPage(page) : false
  }

  const root = scrollRef.value
  if (!root) return false

  // Prefer the persistent trace mark for this target — lands on the exact underlined fragment.
  if (paperTargetId) {
    const escaped = CSS.escape(paperTargetId)
    const mark =
      root.querySelector<HTMLElement>(`[data-trace-target="${escaped}"]`) ??
      // Blocks shared by several relations list every id; the primary attribute holds only one.
      root.querySelector<HTMLElement>(`[data-trace-targets~="${escaped}"]`) ??
      [...root.querySelectorAll<HTMLElement>('[data-trace-targets]')].find((el) =>
        (el.getAttribute('data-trace-targets') ?? '').split(',').includes(paperTargetId),
      ) ??
      null
    if (mark) {
      centerInPane(mark)
      scheduleTempHighlight(mark)
      return true
    }
  }

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
  // Resolve the element that visually represents the block: for a math block the anchor is an
  // empty <span> inside an empty <p>, so highlight the following .math-display instead of the
  // zero-height wrapper (which showed as a thin strip on top).
  const visualTarget = target.matches('span') ? resolveVisualBlock(target) : target
  const anchorForScroll = visualTarget || target
  centerInPane(anchorForScroll)
  scheduleTempHighlight(anchorForScroll)
  return true
}

// Targets the backend never anchored and quote-search couldn't place either. Exposed so the fixed
// box can show "论文锚点不可用" instead of a silent blank.
const markdownUnresolvedTargetIds = ref<Set<string>>(new Set())

// The two views fail independently: markdown resolution depends on DOM anchors, PDF
// resolution on recorded geometry. Report whichever view the user is actually looking at,
// so the message matches what they can see.
const unresolvedTargetIds = computed<Set<string>>(() =>
  viewMode.value === 'pdf'
    ? (pdfReaderRef.value?.unresolvedTargetIds ?? new Set<string>())
    : markdownUnresolvedTargetIds.value,
)

function applyTraceDecorations(): void {
  const root = markdownRef.value
  if (!root) return
  const { unresolved } = decoratePaperTargets(root, props.traceTargets ?? [])
  markdownUnresolvedTargetIds.value = unresolved
  setActivePaperTargets(root, props.activeTargetIds ?? new Set(), props.hoverTargetIds ?? new Set())
}

function traceTargetId(event: Event): string | null {
  const el = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-trace-target]')
  if (!el) return null
  // A shared block backs several relations; keep the current selection sticky so clicking the
  // same formula twice doesn't hop to a different relation.
  return resolveEventTargetId(el, props.activeTargetIds ?? new Set())
}

function onTraceOver(event: MouseEvent): void {
  const id = traceTargetId(event)
  window.clearTimeout(hoverLeaveTimer)
  if (!id) return
  if (id === lastHoveredTargetId) return
  lastHoveredTargetId = id
  emit('traceHover', id)
}

function onTraceOut(event: MouseEvent): void {
  const id = traceTargetId(event)
  if (!id) return
  window.clearTimeout(hoverLeaveTimer)
  hoverLeaveTimer = window.setTimeout(() => {
    lastHoveredTargetId = null
    emit('traceLeave')
  }, 60)
}

function onTraceClick(event: MouseEvent): void {
  // Guided annotation, paper step only: resolve the pick to a real MinerU block id.
  if (annotation.pickingPaper) {
    const root = markdownRef.value
    const selection = window.getSelection()
    const dragged = Boolean(selection && !selection.isCollapsed && selection.toString().trim())
    const range = dragged ? selection!.getRangeAt(0) : null
    const blockId = root
      ? range
        ? resolveSinglePaperBlock(range.startContainer, range.endContainer, (container) =>
            resolveBlockIdAt(root, container),
          )
        : resolveBlockIdAt(root, event.target as Node | null)
      : null
    if (blockId) {
      // Show back the whole block, not just the dragged span: the relation is stored against
      // the block, so previewing the drag would promise finer granularity than exists.
      const anchor = root?.querySelector<HTMLElement>(
        `[data-paper-block-id="${CSS.escape(blockId)}"]`,
      )
      const block = anchor?.matches('span') ? resolveVisualBlock(anchor) : anchor
      const blockText = (block?.textContent ?? '').replace(/\s+/g, ' ').trim()
      annotation.pickPaper({
        ref: blockId,
        preview: blockText.slice(0, 400),
      })
      selection?.removeAllRanges()
      return
    }
    // Nothing resolvable under the pointer: say so instead of leaving the user guessing.
    ElMessage.warning('这里没有可锚定的论文块，请选择正文段落、公式或图表')
    return
  }

  // Normal mode: pin trace target
  const id = traceTargetId(event)
  if (id) emit('tracePin', id)
}

// One-way section observation: whenever the set of visible headings changes, report the topmost
// visible one as the observed section for the TOC to highlight. This NEVER scrolls — decoupling
// "what section am I looking at" (observe) from "where the user asked to go" (jump) is what stops
// the wheel-scroll-jumps-randomly loop the previous @scroll handler caused.
function reportObservedSection(): void {
  const root = scrollRef.value
  if (!root) return
  const headings = [...root.querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]')]
  // Prefer the last heading whose top is at/above the tracking line; fall back to the first
  // heading still intersecting, so a section taller than the viewport keeps its own highlight.
  const rootTop = root.getBoundingClientRect().top
  let candidate: HTMLElement | null = null
  for (const heading of headings) {
    if (heading.getBoundingClientRect().top - rootTop <= 80) candidate = heading
    else break
  }
  if (!candidate) {
    candidate = headings.find((h) => (headingVisibility.get(h.id) ?? 0) > 0) ?? null
  }
  if (candidate?.id) emit('observeSection', candidate.id)
}

function setupSectionObserver(): void {
  teardownSectionObserver()
  const root = scrollRef.value
  const body = markdownRef.value
  if (!root || !body) return
  headingVisibility.clear()
  sectionObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).id
        if (id) headingVisibility.set(id, entry.intersectionRatio)
      }
      reportObservedSection()
    },
    { root, threshold: [0, 1], rootMargin: '-72px 0px -70% 0px' },
  )
  body
    .querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]')
    .forEach((heading) => sectionObserver?.observe(heading))
}

function teardownSectionObserver(): void {
  sectionObserver?.disconnect()
  sectionObserver = null
}

// A paper without a retained PDF (older upload, file removed) must not strand the user in
// an empty PDF pane.
watch(
  () => props.pdfUrl,
  (url) => {
    if (!url && viewMode.value === 'pdf') viewMode.value = 'markdown'
  },
)

watch(
  () => annotation.pickingPaper,
  (picking) => {
    if (picking) viewMode.value = 'markdown'
  },
)

watch(
  () => props.activeSectionId,
  async (sectionId, previous) => {
    if (!sectionId || sectionId === previous) return
    // A trace/target jump owns the scroll; the TOC highlight can move but must not re-scroll.
    if (blockJumpActive) return
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
    setupSectionObserver()
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

// Selection/hover change only refreshes decorations (strong vs weak highlight). It never scrolls —
// the one-time reveal scroll lives in the parent's selectedLinkId watch (scrollToBlock), so hover
// can't move the pane.
watch(
  () => props.activeTargetIds,
  () => {
    const root = markdownRef.value
    if (root) {
      setActivePaperTargets(
        root,
        props.activeTargetIds ?? new Set(),
        props.hoverTargetIds ?? new Set(),
      )
    }
  },
  { deep: true },
)

watch(
  () => props.hoverTargetIds,
  () => {
    const root = markdownRef.value
    if (root) {
      setActivePaperTargets(
        root,
        props.activeTargetIds ?? new Set(),
        props.hoverTargetIds ?? new Set(),
      )
    }
  },
  { deep: true },
)

// Mark the block picked for the guided flow. It stays marked past the confirm step so the user
// keeps seeing their paper choice while selecting code and filling the form.
watch(
  () => annotation.paperPick?.ref ?? null,
  (pickedRef) => {
    const root = markdownRef.value
    if (!root) return

    root.querySelectorAll('.annotation-selected').forEach((el) => {
      el.classList.remove('annotation-selected')
    })
    if (!pickedRef) return

    // The id lives on a zero-width injected span, so mark the visual block it belongs to —
    // styling the span itself would be invisible.
    const anchor = root.querySelector<HTMLElement>(
      `[data-paper-block-id="${CSS.escape(pickedRef)}"]`,
    )
    if (!anchor) return
    const block = anchor.matches('span') ? resolveVisualBlock(anchor) : anchor
    block.classList.add('annotation-selected')
    block.scrollIntoView({ behavior: 'smooth', block: 'center' })
  },
)

onBeforeUnmount(() => {
  revokeImageObjectUrls()
  teardownSectionObserver()
  window.clearTimeout(settleTimer)
  window.clearTimeout(highlightTimer)
  window.clearTimeout(hoverLeaveTimer)
  window.cancelAnimationFrame(settleRaf)
})

defineExpose({ scrollToSection, scrollToBlock, unresolvedTargetIds })
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
  justify-items: center;
  gap: 10px;
  color: #6b7785;
  font-size: 12px;
  text-align: center;
}

.parsing-spin {
  display: block;
  margin: 0 auto;
  font-size: 22px;
  color: #5885ff;
  animation: paper-parsing-spin 1s linear infinite;
}

.state-error {
  color: #b64a3c;
}

.state-placeholder small {
  color: #9aa5b1;
  font-size: 11px;
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

.view-switch {
  display: flex;
  flex: none;
  gap: 2px;
}

.view-switch button {
  height: 23px;
  padding: 0 9px;
  border: 1px solid #d8dee6;
  border-radius: 3px;
  background: #ffffff;
  color: #586675;
  cursor: pointer;
  font: inherit;
}

.view-switch button.active {
  border-color: #5885ff;
  background: #eef3ff;
  color: #2a52c4;
}

.view-switch button:disabled {
  color: #b3bcc6;
  cursor: not-allowed;
}

.zoom-controls {
  display: flex;
  flex: none;
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

/* One-to-many: one paper fragment maps to multiple code locations. */
.markdown-body :deep(.trace-mark-1_to_n),
.markdown-body :deep(.trace-block-1_to_n) {
  box-shadow: inset 0 -2px 0 rgba(139, 92, 246, 0.65);
}

.markdown-body :deep(.trace-mark-1_to_n:not(.trace-mark-proposed):not(.trace-mark-accepted)) {
  background: rgba(139, 92, 246, 0.12);
}

/* Many-to-one: multiple paper fragments share one code location. */
.markdown-body :deep(.trace-mark-n_to_1),
.markdown-body :deep(.trace-block-n_to_1) {
  box-shadow: inset 0 -2px 0 rgba(8, 145, 178, 0.65);
}

.markdown-body :deep(.trace-mark-n_to_1:not(.trace-mark-proposed):not(.trace-mark-accepted)) {
  background: rgba(8, 145, 178, 0.12);
}

/* Many-to-many: both fanout and fanin. */
.markdown-body :deep(.trace-mark-n_to_n),
.markdown-body :deep(.trace-block-n_to_n) {
  box-shadow: inset 0 -2px 0 rgba(139, 92, 246, 0.65), inset 0 -4px 0 rgba(8, 145, 178, 0.45);
}

.markdown-body :deep(.trace-mark-badge) {
  margin-left: 2px;
  padding: 0 3px;
  border-radius: 8px;
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
  font-size: 9px;
  font-weight: 700;
  line-height: 1.2;
  vertical-align: super;
}

.markdown-body :deep(.trace-mark-badge-fanin) {
  background: rgba(8, 145, 178, 0.15);
  color: #0891b2;
}

.markdown-body :deep(.trace-mark-badge-both) {
  background: rgba(139, 92, 246, 0.12);
  color: #7c3aed;
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

/* Weak highlight for the relation currently under the pointer (preview only, not selected). */
.markdown-body :deep(.trace-target-hover) {
  background: rgba(224, 168, 58, 0.18);
  box-shadow: 0 0 0 1px rgba(224, 168, 58, 0.5);
}

/* When the traceable block is a formula/table/etc., the whole block box gets the highlight.
   KaTeX renders on a light background, so the coarse base tint is nearly invisible — give the
   formula its own clearly-visible resting tint + outline so traced formulas are legible unselected. */
.markdown-body :deep(.math-display.trace-block-target) {
  display: block;
  padding: 6px 10px;
  border-radius: 4px;
  margin-left: 0;
  border-left: 0;
  background: rgba(88, 133, 255, 0.14);
  outline: 1px solid rgba(88, 133, 255, 0.4);
  outline-offset: 1px;
}

.markdown-body :deep(.math-display.trace-block-accepted) {
  background: rgba(46, 168, 118, 0.16);
  outline-color: rgba(46, 168, 118, 0.5);
}

.markdown-body :deep(.math-display.trace-block-1_to_n) {
  outline-color: rgba(139, 92, 246, 0.55);
  background: rgba(139, 92, 246, 0.12);
}

.markdown-body :deep(.math-display.trace-block-n_to_1) {
  outline-color: rgba(8, 145, 178, 0.55);
  background: rgba(8, 145, 178, 0.12);
}

.markdown-body :deep(.math-display.trace-block-n_to_n) {
  outline-color: rgba(139, 92, 246, 0.55);
  background: rgba(139, 92, 246, 0.1);
}

.markdown-body :deep(.math-display.paper-block-highlight) {
  display: block;
  padding: 6px 10px;
  border-radius: 4px;
  margin-left: 0;
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

/* Annotation mode styles */
/* Annotation mode. The block id sits on a zero-width injected span, so these target the
   rendered blocks themselves — styling the anchor span would be invisible. */
.markdown-body.annotation-picking :deep(p),
.markdown-body.annotation-picking :deep(li),
.markdown-body.annotation-picking :deep(h1),
.markdown-body.annotation-picking :deep(h2),
.markdown-body.annotation-picking :deep(h3),
.markdown-body.annotation-picking :deep(h4),
.markdown-body.annotation-picking :deep(blockquote),
.markdown-body.annotation-picking :deep(pre),
.markdown-body.annotation-picking :deep(table),
.markdown-body.annotation-picking :deep(.math-display) {
  cursor: text;
  transition: outline-color 0.15s ease, background 0.15s ease;
  outline: 2px dashed transparent;
  outline-offset: 2px;
}

.markdown-body.annotation-picking :deep(p:hover),
.markdown-body.annotation-picking :deep(li:hover),
.markdown-body.annotation-picking :deep(h1:hover),
.markdown-body.annotation-picking :deep(h2:hover),
.markdown-body.annotation-picking :deep(h3:hover),
.markdown-body.annotation-picking :deep(h4:hover),
.markdown-body.annotation-picking :deep(blockquote:hover),
.markdown-body.annotation-picking :deep(pre:hover),
.markdown-body.annotation-picking :deep(table:hover),
.markdown-body.annotation-picking :deep(.math-display:hover) {
  outline-color: #409eff;
  background: rgba(64, 158, 255, 0.05);
}

/* Survives leaving the pane, so the picked block stays visible while the dialog is open. */
.markdown-body :deep(.annotation-selected) {
  outline: 3px solid #67c23a !important;
  outline-offset: 2px;
  background: rgba(103, 194, 58, 0.12) !important;
}

.markdown-body.annotation-picking :deep(::selection) {
  background: rgba(64, 158, 255, 0.3);
}
</style>
