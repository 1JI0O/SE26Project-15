/**
 * Resolve trace targets to rectangles on the original PDF.
 *
 * The markdown reader locates a target by searching the rendered DOM for its quote. That
 * is impossible on a PDF page — there is no DOM to search — so placement is done purely
 * from geometry MinerU recorded at parse time:
 *
 * - every block carries a `bbox` (0-1 of the page, top-left origin), always present;
 * - blocks parsed with geometry capture also carry per-line `bbox`es.
 *
 * A quote is matched against the block's line texts to find which lines it covers, giving
 * a highlight close to a real hand-drawn one. When a paper was parsed before geometry
 * capture existed, or the quote cannot be matched (maths, table markup, MinerU text drift),
 * the whole block box is highlighted instead — coarser, but never wrong about *which*
 * block, which matters more than tightness.
 */

import type { PaperBlockLine, WorkspacePaperBlock } from '@/types/papers'
import type { PaperMark } from './trace-decorations'

/** A rectangle to paint, in 0-1 page fractions with a top-left origin. */
export interface HighlightRect {
  targetId: string
  page: number
  status: string
  /** True when the rect came from line boxes; false when it is the coarse block box. */
  precise: boolean
  left: number
  top: number
  width: number
  height: number
}

/**
 * Comparison key mirroring the backend's `geometry.text_key`.
 *
 * Keeping only letters/digits/CJK discards exactly the characters that differ between a
 * quote taken from MinerU's markdown (`$x$`, escaped LaTeX, collapsed whitespace) and the
 * raw span text recorded in the PDF's line boxes.
 */
export function textKey(value: string): string {
  return value.toLowerCase().replace(/[^0-9a-z一-鿿]+/g, '')
}

/** Ignore matches this short — a few characters would land almost anywhere. */
const MIN_QUOTE_KEY = 8

function isBox(bbox: number[] | null | undefined): bbox is number[] {
  return Array.isArray(bbox) && bbox.length === 4 && bbox.every((n) => Number.isFinite(n))
}

function toRect(
  bbox: number[],
  target: PaperMark,
  page: number,
  precise: boolean,
): HighlightRect | null {
  const [x0, y0, x1, y1] = bbox
  const left = Math.min(x0, x1)
  const top = Math.min(y0, y1)
  const width = Math.abs(x1 - x0)
  const height = Math.abs(y1 - y0)
  // A degenerate box would render as an invisible sliver; treat it as unusable so the
  // caller can fall back rather than silently drawing nothing.
  if (width <= 0 || height <= 0) return null
  return { targetId: target.targetId, page, status: target.status, precise, left, top, width, height }
}

/**
 * Indices of the lines covered by `quote`.
 *
 * Line keys are concatenated into one string per block, remembering which line each
 * character came from, so a quote spanning a line break resolves to every line it touches.
 * Returns an empty array when the quote cannot be located.
 */
export function linesForQuote(
  lines: PaperBlockLine[],
  quote: string,
  occurrence = 1,
): number[] {
  const needle = textKey(quote)
  if (needle.length < MIN_QUOTE_KEY) return []

  let joined = ''
  const owner: number[] = []
  lines.forEach((line, index) => {
    const key = textKey(line.text ?? '')
    joined += key
    for (let i = 0; i < key.length; i += 1) owner.push(index)
  })
  if (!joined) return []

  // Walk to the requested (1-based) occurrence within this block, matching how the
  // markdown decorator counts in `wrapOccurrence`. Falls back to the last one found when
  // the block holds fewer repeats than the anchor claimed.
  let at = joined.indexOf(needle)
  if (at < 0) return []
  for (let n = 1; n < occurrence; n += 1) {
    const next = joined.indexOf(needle, at + 1)
    if (next < 0) break
    at = next
  }

  const covered = new Set<number>()
  for (let i = at; i < at + needle.length && i < owner.length; i += 1) covered.add(owner[i])
  return [...covered].sort((a, b) => a - b)
}

/**
 * Merge rects that sit on the same text line into one.
 *
 * MinerU sometimes splits a visual line into several boxes; painting each separately shows
 * seams through the highlight. Boxes whose vertical spans overlap by most of their height
 * are treated as one line and unioned.
 */
function mergeAdjacent(rects: HighlightRect[]): HighlightRect[] {
  if (rects.length < 2) return rects
  const sorted = [...rects].sort((a, b) => a.top - b.top || a.left - b.left)
  const merged: HighlightRect[] = []
  for (const rect of sorted) {
    const previous = merged[merged.length - 1]
    if (previous && previous.page === rect.page) {
      const overlap =
        Math.min(previous.top + previous.height, rect.top + rect.height) -
        Math.max(previous.top, rect.top)
      if (overlap > Math.min(previous.height, rect.height) * 0.5) {
        const left = Math.min(previous.left, rect.left)
        const top = Math.min(previous.top, rect.top)
        previous.width = Math.max(previous.left + previous.width, rect.left + rect.width) - left
        previous.height = Math.max(previous.top + previous.height, rect.top + rect.height) - top
        previous.left = left
        previous.top = top
        continue
      }
    }
    merged.push({ ...rect })
  }
  return merged
}

/**
 * Aspect ratios of the pages the renderer actually produced, keyed by page number.
 * Supplying this lets `buildHighlightRects` reject geometry measured against a
 * differently-shaped page.
 */
export type PageAspects = Map<number, number>

/** Allowed disagreement between MinerU's page shape and the rendered one. */
const ASPECT_TOLERANCE = 0.02

/**
 * True when the block's recorded page shape matches the page we rendered.
 *
 * A rotated page (`/Rotate 90`) comes out of pdf.js with its width and height swapped.
 * MinerU's boxes were measured against the unrotated box, so every rect would be
 * transposed — visibly wrong, and wrong silently. Rather than guess at a rotation the
 * pipeline never recorded, mismatched pages drop their highlights and are reported as
 * unresolved. Blocks with no recorded page size (parsed before geometry capture) are
 * trusted, since block boxes are axis-normalized and were never page-shape dependent.
 */
function pageShapeAgrees(block: WorkspacePaperBlock, page: number, aspects?: PageAspects): boolean {
  const size = block.page_size
  const rendered = aspects?.get(page)
  if (!rendered || !Array.isArray(size) || size.length !== 2) return true
  const [width, height] = size
  if (!(width > 0) || !(height > 0)) return true
  return Math.abs(width / height - rendered) <= ASPECT_TOLERANCE
}

/**
 * Build every highlight rect for the given targets.
 *
 * Targets whose block is unknown, or which have no usable geometry at all, are reported in
 * `unresolved` so the view can say so explicitly instead of showing nothing.
 */
export function buildHighlightRects(
  targets: PaperMark[],
  blocks: WorkspacePaperBlock[],
  pageAspects?: PageAspects,
): { rects: HighlightRect[]; unresolved: Set<string> } {
  const byId = new Map(blocks.map((block) => [block.id, block]))
  const rects: HighlightRect[] = []
  const unresolved = new Set<string>()

  for (const target of targets) {
    const block = byId.get(target.blockId)
    if (!block) {
      unresolved.add(target.targetId)
      continue
    }
    const page = block.page_number ?? block.page
    if (!Number.isFinite(page) || page < 1) {
      unresolved.add(target.targetId)
      continue
    }
    if (!pageShapeAgrees(block, page, pageAspects)) {
      unresolved.add(target.targetId)
      continue
    }

    const lines = block.lines ?? []
    const covered = lines.length ? linesForQuote(lines, target.quote, target.occurrence) : []
    const lineRects = covered
      .map((index) => lines[index])
      .filter((line): line is PaperBlockLine => isBox(line?.bbox))
      .map((line) => toRect(line.bbox, target, page, true))
      .filter((rect): rect is HighlightRect => rect !== null)

    if (lineRects.length) {
      rects.push(...mergeAdjacent(lineRects))
      continue
    }
    // Fallback: the block's own box. Coarser, but it always points at the right block.
    if (isBox(block.bbox)) {
      const rect = toRect(block.bbox, target, page, false)
      if (rect) {
        rects.push(rect)
        continue
      }
    }
    unresolved.add(target.targetId)
  }
  return { rects, unresolved }
}

/** Group rects by page so each rendered page only paints its own overlay. */
export function groupByPage(rects: HighlightRect[]): Map<number, HighlightRect[]> {
  const grouped = new Map<number, HighlightRect[]>()
  for (const rect of rects) {
    const list = grouped.get(rect.page)
    if (list) list.push(rect)
    else grouped.set(rect.page, [rect])
  }
  return grouped
}
