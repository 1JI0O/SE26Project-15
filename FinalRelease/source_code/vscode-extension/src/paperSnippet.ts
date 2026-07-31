/**
 * Extract paper evidence snippets from MinerU markdown (desktop paper-snippet.ts port).
 * Block quotes often omit `$` delimiters; document markdown keeps `$…$` / `$$…$$`.
 */

const ANCHOR_RE = /<span\b[^>]*\bdata-paper-block-id="([^"]+)"[^>]*><\/span>\n?/g
const MAX_SNIPPET_CHARS = 800

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function matchKey(value: string): string {
  return value.replace(/\$+/g, '').replace(/\s+/g, ' ').trim()
}

function buildMatchIndex(source: string): { key: string; offsets: number[] } {
  const chars: string[] = []
  const offsets: number[] = []
  let prevSpace = false
  for (let index = 0; index < source.length; index += 1) {
    const ch = source[index]!
    if (ch === '$') continue
    if (/\s/.test(ch)) {
      if (prevSpace) continue
      chars.push(' ')
      offsets.push(index)
      prevSpace = true
      continue
    }
    chars.push(ch)
    offsets.push(index)
    prevSpace = false
  }
  offsets.push(source.length)
  return { key: chars.join(''), offsets }
}

/** Offsets of unescaped single `$` (positions inside `$$` are reported once, as pairs). */
interface MathSpan {
  open: number
  close: number
  display: boolean
}

function mathSpans(source: string): MathSpan[] {
  const spans: MathSpan[] = []
  let index = 0
  while (index < source.length) {
    if (source[index] !== '$' || (index > 0 && source[index - 1] === '\\')) {
      index += 1
      continue
    }
    const display = source[index + 1] === '$'
    const delimiter = display ? '$$' : '$'
    let search = index + delimiter.length
    let close = -1
    while (search < source.length) {
      const at = source.indexOf(delimiter, search)
      if (at < 0) break
      if (source[at - 1] === '\\') {
        search = at + 1
        continue
      }
      // A bare `$` never spans a blank line — that is prose, not math.
      if (!display && /\n\s*\n/.test(source.slice(index, at))) break
      close = at
      break
    }
    if (close < 0) {
      index += delimiter.length
      continue
    }
    spans.push({ open: index, close: close + delimiter.length, display })
    index = close + delimiter.length
  }
  return spans
}

/**
 * Grow `[start, end)` to whole math delimiters.
 *
 * Block quotes usually drop the `$` markers, so a match can start *inside* an
 * inline or display formula. Snapping to the enclosing span keeps the snippet
 * renderable — an unbalanced `$` used to leak raw TeX into the matrix preview.
 */
function expandToMathDelimiters(source: string, start: number, end: number): [number, number] {
  let from = start
  let to = end
  for (const span of mathSpans(source)) {
    if (span.open < to && span.close > from) {
      from = Math.min(from, span.open)
      to = Math.max(to, span.close)
    }
  }
  return [from, to]
}

/** Last resort: drop a stray `$` the slice could not pair up. */
function balanceMathDelimiters(snippet: string): string {
  let out = snippet
  for (let guard = 0; guard < 4; guard += 1) {
    const markers = out.match(/(?<!\\)\$\$?/g) ?? []
    if (markers.length % 2 === 0) return out
    if (/(?<!\\)\$\$?\s*$/.test(out)) {
      out = out.replace(/(?<!\\)\$\$?\s*$/, '').trimEnd()
      continue
    }
    if (/^\s*\$\$?/.test(out)) {
      out = out.replace(/^\s*\$\$?/, '').trimStart()
      continue
    }
    return out
  }
  return out
}

function findQuoteSpan(
  region: string,
  quote: string,
  occurrence: number,
): [number, number] | null {
  const needle = matchKey(quote)
  if (!needle || occurrence < 1) return null
  const { key, offsets } = buildMatchIndex(region)
  let from = 0
  let hitStart = -1
  let hitEnd = -1
  for (let n = 0; n < occurrence; n += 1) {
    const at = key.indexOf(needle, from)
    if (at < 0) return null
    hitStart = offsets[at]!
    hitEnd = offsets[Math.min(at + needle.length, offsets.length - 1)]!
    from = at + Math.max(needle.length, 1)
  }
  if (hitStart < 0) return null
  return expandToMathDelimiters(region, hitStart, hitEnd)
}

export function blockMarkdownRegion(markdown: string, blockId: string): string | null {
  if (!markdown || !blockId) return null
  const exact = new RegExp(
    `<span\\b[^>]*\\bdata-paper-block-id="${escapeRegExp(blockId)}"[^>]*><\\/span>\\n?`,
  )
  const match = exact.exec(markdown)
  if (!match || match.index == null) return null
  const start = match.index + match[0].length
  ANCHOR_RE.lastIndex = start
  const next = ANCHOR_RE.exec(markdown)
  const end = next ? next.index : markdown.length
  return markdown.slice(start, end).trim()
}

export function extractPaperMarkdownSnippet(
  markdown: string,
  blockId: string,
  quote = '',
  occurrence = 1,
): string {
  const region = blockMarkdownRegion(markdown, blockId)
  if (region) {
    if (quote.trim()) {
      const span = findQuoteSpan(region, quote, occurrence)
      if (span) {
        const [from, to] = span
        return balanceMathDelimiters(region.slice(from, to).trim())
      }
    }
    if (region.length <= MAX_SNIPPET_CHARS) return region
    return balanceMathDelimiters(`${region.slice(0, MAX_SNIPPET_CHARS).trimEnd()}`) + '…'
  }
  if (quote.trim() && markdown) {
    const span = findQuoteSpan(markdown, quote, occurrence)
    if (span) {
      const [from, to] = span
      return balanceMathDelimiters(markdown.slice(from, to).trim())
    }
  }
  return quote.trim()
}
