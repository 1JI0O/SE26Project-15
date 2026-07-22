/**
 * DOM decoration helpers for paper-side trace targets.
 *
 * Reuses the block anchors that the backend injects into the rendered markdown
 * (`<span id="paper-block-…" data-paper-block-id="…">`, see paper_markdown.inject_block_anchors)
 * to locate a block, then wraps the *occurrence*-th match of the target quote in a
 * `<mark data-trace-target>` so hover highlighting lands on the exact spot. When the quote
 * cannot be wrapped precisely (math, inline markup), it falls back to a block-level marker.
 */

export interface PaperMark {
  targetId: string
  blockId: string
  quote: string
  occurrence: number
  status: string
}

const MARK_SELECTOR = 'mark[data-trace-target]'
const BLOCK_CLASS = 'trace-block-target'

const normalize = (value: string): string => value.replace(/\s+/g, ' ').trim()

function blockElement(root: HTMLElement, blockId: string): HTMLElement | null {
  const anchor = root.querySelector<HTMLElement>(
    `[data-paper-block-id="${CSS.escape(blockId)}"]`,
  )
  if (!anchor) return null
  if (anchor.matches('span')) {
    const sibling = anchor.nextElementSibling as HTMLElement | null
    const container = anchor.closest<HTMLElement>('h1, h2, h3, h4, h5, h6, p, li, pre, blockquote, td')
    return container ?? sibling ?? (anchor.parentElement as HTMLElement | null)
  }
  return anchor
}

/** Wrap the occurrence-th raw match of `quote` inside `el`; returns the created mark or null. */
function wrapOccurrence(
  el: HTMLElement,
  quote: string,
  occurrence: number,
  targetId: string,
  status: string,
): HTMLElement | null {
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
  mark.dataset.traceTarget = targetId
  mark.className = `trace-mark trace-mark-${status}`
  try {
    range.surroundContents(mark)
  } catch {
    range.detach?.()
    return null
  }
  return mark
}

export function clearPaperDecorations(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>(MARK_SELECTOR).forEach((mark) => {
    const parent = mark.parentNode
    if (!parent) return
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark)
    parent.removeChild(mark)
  })
  root
    .querySelectorAll<HTMLElement>(`.${BLOCK_CLASS}`)
    .forEach((el) => el.classList.remove(BLOCK_CLASS, 'trace-block-proposed', 'trace-block-accepted'))
  root.normalize()
}

/** Decorate all paper targets; returns the map of targetId -> decorated elements. */
export function decoratePaperTargets(
  root: HTMLElement,
  targets: PaperMark[],
): Map<string, HTMLElement[]> {
  clearPaperDecorations(root)
  const decorated = new Map<string, HTMLElement[]>()
  for (const target of targets) {
    const block = blockElement(root, target.blockId)
    if (!block) continue
    const mark = wrapOccurrence(block, target.quote, target.occurrence, target.targetId, target.status)
    if (mark) {
      decorated.set(target.targetId, [...(decorated.get(target.targetId) ?? []), mark])
      continue
    }
    // Fallback: mark the whole block as a coarse target so it stays hoverable.
    if (block.dataset.traceTarget && block.dataset.traceTarget !== target.targetId) {
      // A block already claimed by another target keeps its first owner.
    } else {
      block.dataset.traceTarget = target.targetId
    }
    block.classList.add(BLOCK_CLASS, `trace-block-${target.status}`)
    decorated.set(target.targetId, [...(decorated.get(target.targetId) ?? []), block])
  }
  return decorated
}

export function setActivePaperTargets(root: HTMLElement, activeIds: Set<string>): void {
  root.querySelectorAll<HTMLElement>('[data-trace-target]').forEach((el) => {
    const id = el.dataset.traceTarget
    el.classList.toggle('trace-target-active', !!id && activeIds.has(id))
  })
}

export { normalize as normalizePaperQuote }
