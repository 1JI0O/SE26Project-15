/**
 * DOM decoration helpers for paper-side trace targets.
 *
 * Reuses the block anchors that the backend injects into the rendered markdown
 * (`<span id="paper-block-…" data-paper-block-id="…">`, see paper_markdown.inject_block_anchors)
 * to locate a block, then wraps the *occurrence*-th match of the target quote in a
 * `<mark data-trace-target>` so hover highlighting lands on the exact spot. When the quote
 * cannot be wrapped precisely (math, inline markup), it falls back to a block-level marker.
 */

import type { TraceMultiplicity } from '@/composables/useTraceIndex'

export interface PaperMark {
  targetId: string
  blockId: string
  quote: string
  occurrence: number
  status: string
  targetType?: string
  multiplicity?: TraceMultiplicity
  fanoutCount?: number
}

const MARK_SELECTOR = 'mark[data-trace-target]'
const BLOCK_CLASS = 'trace-block-target'

const FORMULA_TARGET_TYPES = new Set([
  'formula',
  'equation',
  'equation_interline',
  'equation_inline',
  'equation_display',
  'table',
  'figure',
])

/** Rendered block elements whose whole box should be highlighted (formulas/tables/images). */
const VISUAL_BLOCK_SELECTOR = '.math-display, .table-scroll, table, pre, img, blockquote'

const normalize = (value: string): string => value.replace(/\s+/g, ' ').trim()

function isBlockLevelTarget(targetType?: string, quote?: string): boolean {
  if (targetType && FORMULA_TARGET_TYPES.has(targetType)) return true
  if (!quote) return false
  return /[$\\]|\\begin\{/.test(quote)
}

function multiplicityClasses(multiplicity?: TraceMultiplicity): string[] {
  if (!multiplicity || multiplicity === '1_to_1') return []
  return [`trace-mark-${multiplicity}`, `trace-block-${multiplicity}`]
}

function appendFanoutBadge(el: HTMLElement, fanoutCount?: number, multiplicity?: TraceMultiplicity): void {
  if (!fanoutCount || fanoutCount <= 1) return
  const badge = document.createElement('sup')
  badge.className = 'trace-mark-badge'
  if (multiplicity === 'n_to_1') badge.classList.add('trace-mark-badge-fanin')
  else if (multiplicity === 'n_to_n') badge.classList.add('trace-mark-badge-both')
  badge.textContent = `×${fanoutCount}`
  el.appendChild(badge)
}

/** True when an element carries no meaningful text of its own (e.g. the empty `<p>` that
 * wraps a lone anchor span above a `$$…$$` block). */
function isEmptyContainer(el: HTMLElement): boolean {
  return normalize(el.textContent ?? '').length === 0
}

/**
 * From the injected anchor span, resolve the element that should actually be highlighted /
 * scrolled to. The backend places `<span data-paper-block-id></span>` on its own line above a
 * `$$…$$` block; markdown-it wraps that lone inline span in an empty `<p>`, so the real formula
 * (`.math-display`) is the NEXT element sibling. Highlighting the empty `<p>` would only paint a
 * thin strip on top — so when the resolved container is empty, hop to the following visual block.
 */
export function resolveVisualBlock(anchor: HTMLElement): HTMLElement {
  const container =
    anchor.closest<HTMLElement>('h1, h2, h3, h4, h5, h6, p, li, pre, blockquote, td') ?? anchor
  if (!isEmptyContainer(container)) return container
  // Empty wrapper: look for the meaningful block that follows it.
  let sibling = container.nextElementSibling as HTMLElement | null
  while (sibling && isEmptyContainer(sibling) && !sibling.matches(VISUAL_BLOCK_SELECTOR)) {
    sibling = sibling.nextElementSibling as HTMLElement | null
  }
  if (sibling && (sibling.matches(VISUAL_BLOCK_SELECTOR) || !isEmptyContainer(sibling))) {
    return sibling
  }
  return container
}

/** Walk up to `maxSteps` following siblings to find a visual block (formula/table). */
function findNearbyVisualBlock(start: HTMLElement, maxSteps = 3): HTMLElement | null {
  let sibling = start.nextElementSibling as HTMLElement | null
  for (let step = 0; step < maxSteps && sibling; step += 1) {
    if (sibling.matches(VISUAL_BLOCK_SELECTOR)) return sibling
    if (!isEmptyContainer(sibling) && !sibling.matches('p')) return sibling
    sibling = sibling.nextElementSibling as HTMLElement | null
  }
  return null
}

function blockElement(root: HTMLElement, blockId: string, targetType?: string): HTMLElement | null {
  const anchor = root.querySelector<HTMLElement>(
    `[data-paper-block-id="${CSS.escape(blockId)}"]`,
  )
  if (!anchor) return null
  let resolved: HTMLElement
  if (anchor.matches('span')) {
    resolved = resolveVisualBlock(anchor)
  } else {
    resolved = anchor
  }
  if (isBlockLevelTarget(targetType) && !resolved.matches(VISUAL_BLOCK_SELECTOR)) {
    const nearby = findNearbyVisualBlock(resolved)
    if (nearby) return nearby
  }
  return resolved
}

/** Wrap the occurrence-th raw match of `quote` inside `el`; returns the created mark or null. */
function wrapOccurrence(
  el: HTMLElement,
  quote: string,
  occurrence: number,
  target: PaperMark,
): HTMLElement | null {
  if (isBlockLevelTarget(target.targetType, quote)) return null

  const raw = el.textContent ?? ''
  // The rendered DOM shows KaTeX glyphs, not `$…$` source, so a quote containing math rarely
  // matches verbatim. Try the full quote first, then its leading plain-text run (up to the first
  // math/backslash), so mixed "text $x$ …" quotes still get a precise partial highlight. Pure-math
  // quotes fall through to the caller's block-level fallback.
  const plainLead = quote.split(/[$\\]/, 1)[0].trim()
  const candidates = [quote.trim(), plainLead].filter((c) => c.length >= 6)
  let needle = ''
  let index = -1
  for (const candidate of candidates) {
    let idx = -1
    for (let i = 0; i < occurrence; i += 1) {
      idx = raw.indexOf(candidate, idx + 1)
      if (idx < 0) break
    }
    if (idx >= 0) {
      needle = candidate
      index = idx
      break
    }
  }
  if (index < 0 || !needle) return null
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  let consumed = 0
  let startNode: Text | null = null
  let startOffset = 0
  let endNode: Text | null = null
  let endOffset = 0
  const end = index + needle.length
  let node = walker.nextNode() as Text | null
  while (node) {
    const length = node.data.length
    if (!startNode && consumed + length > index) {
      startNode = node
      startOffset = index - consumed
    }
    if (startNode && consumed + length >= end) {
      endNode = node
      endOffset = end - consumed
      break
    }
    consumed += length
    node = walker.nextNode() as Text | null
  }
  if (!startNode || !endNode) return null
  const range = document.createRange()
  range.setStart(startNode, startOffset)
  range.setEnd(endNode, endOffset)
  const mark = document.createElement('mark')
  mark.dataset.traceTarget = target.targetId
  if (target.fanoutCount && target.fanoutCount > 1) {
    mark.dataset.fanout = String(target.fanoutCount)
  }
  mark.className = [
    'trace-mark',
    `trace-mark-${target.status}`,
    ...multiplicityClasses(target.multiplicity),
  ].join(' ')
  try {
    range.surroundContents(mark)
  } catch {
    range.detach?.()
    return null
  }
  appendFanoutBadge(mark, target.fanoutCount, target.multiplicity)
  return mark
}

export function clearPaperDecorations(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>(MARK_SELECTOR).forEach((mark) => {
    const parent = mark.parentNode
    if (!parent) return
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark)
    parent.removeChild(mark)
  })
  root.querySelectorAll<HTMLElement>(`.${BLOCK_CLASS}, [data-trace-target]`).forEach((el) => {
    el.classList.remove(
      BLOCK_CLASS,
      'trace-block-proposed',
      'trace-block-accepted',
      'trace-block-1_to_n',
      'trace-block-n_to_1',
      'trace-block-n_to_n',
    )
    if (el.dataset.traceTarget && el.matches(`.${BLOCK_CLASS}, .math-display, .table-scroll`)) {
      delete el.dataset.traceTarget
      delete el.dataset.fanout
    }
    el.querySelectorAll('.trace-mark-badge').forEach((badge) => badge.remove())
  })
  root.normalize()
}

/** Locate a visual block by fuzzy-matching its quote text, used when the backend never resolved
 * an anchor for the target's block id (anchor_resolved=false → no `data-paper-block-id` in DOM).
 * Scans normalized text of candidate blocks so a target still lands somewhere visible. */
function findBlockByQuote(root: HTMLElement, quote: string, targetType?: string): HTMLElement | null {
  const needle = normalize(quote).slice(0, 120)
  if (needle.length < 12 && !isBlockLevelTarget(targetType, quote)) return null
  const candidates = root.querySelectorAll<HTMLElement>('p, li, td, blockquote, .math-display')
  for (const el of candidates) {
    if (isBlockLevelTarget(targetType, quote) && el.matches('.math-display, .table-scroll')) {
      if (needle.length >= 12 && normalize(el.textContent ?? '').includes(needle)) return el
      if (isBlockLevelTarget(targetType)) continue
    }
    if (normalize(el.textContent ?? '').includes(needle)) {
      const resolved = el.matches('span') ? resolveVisualBlock(el) : el
      if (isBlockLevelTarget(targetType) && !resolved.matches(VISUAL_BLOCK_SELECTOR)) {
        return findNearbyVisualBlock(resolved) ?? resolved
      }
      return resolved
    }
  }
  if (isBlockLevelTarget(targetType, quote)) {
    return root.querySelector<HTMLElement>('.math-display')
  }
  return null
}

function applyBlockFallback(block: HTMLElement, target: PaperMark): void {
  if (block.dataset.traceTarget && block.dataset.traceTarget !== target.targetId) {
    // A block already claimed by another target keeps its first owner.
  } else {
    block.dataset.traceTarget = target.targetId
    if (target.fanoutCount && target.fanoutCount > 1) {
      block.dataset.fanout = String(target.fanoutCount)
    }
  }
  block.classList.add(BLOCK_CLASS, `trace-block-${target.status}`, ...multiplicityClasses(target.multiplicity))
}

/**
 * Decorate all paper targets. Returns `{ decorated, unresolved }` where `unresolved` is the set of
 * targetIds that could not be located in the DOM at all (neither anchor nor quote), so the view can
 * surface "论文锚点不可用" instead of a silent blank.
 */
export function decoratePaperTargets(
  root: HTMLElement,
  targets: PaperMark[],
): { decorated: Map<string, HTMLElement[]>; unresolved: Set<string> } {
  clearPaperDecorations(root)
  const decorated = new Map<string, HTMLElement[]>()
  const unresolved = new Set<string>()
  for (const target of targets) {
    // Prefer the injected anchor; when the backend never resolved it, fall back to quote search.
    const block =
      blockElement(root, target.blockId, target.targetType) ??
      findBlockByQuote(root, target.quote, target.targetType)
    if (!block) {
      unresolved.add(target.targetId)
      continue
    }
    const mark = wrapOccurrence(block, target.quote, target.occurrence, target)
    if (mark) {
      decorated.set(target.targetId, [...(decorated.get(target.targetId) ?? []), mark])
      continue
    }
    // Fallback: mark the whole block as a coarse target so it stays hoverable.
    applyBlockFallback(block, target)
    decorated.set(target.targetId, [...(decorated.get(target.targetId) ?? []), block])
  }
  return { decorated, unresolved }
}

export function setActivePaperTargets(
  root: HTMLElement,
  activeIds: Set<string>,
  hoverIds: Set<string> = new Set(),
): void {
  root.querySelectorAll<HTMLElement>('[data-trace-target]').forEach((el) => {
    const id = el.dataset.traceTarget
    const isActive = !!id && activeIds.has(id)
    el.classList.toggle('trace-target-active', isActive)
    // Weak hover highlight only when it isn't already the strong (selected) one.
    el.classList.toggle('trace-target-hover', !isActive && !!id && hoverIds.has(id))
  })
}

export { normalize as normalizePaperQuote }
