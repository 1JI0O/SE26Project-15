/**
 * Extract paper evidence snippets from the served MinerU markdown source.
 *
 * Block ``text`` / agent quotes often store raw TeX without `$` delimiters, while the
 * document markdown keeps `$…$` / `$$…$$`. Hover/selected boxes must render the latter.
 */

const ANCHOR_RE = /<span\b[^>]*\bdata-paper-block-id="([^"]+)"[^>]*><\/span>\n?/g
const MAX_SNIPPET_CHARS = 800

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Collapse whitespace and drop `$` so block.text quotes can match markdown with delimiters. */
function matchKey(value: string): string {
  return value.replace(/\$+/g, '').replace(/\s+/g, ' ').trim()
}

/**
 * Build a whitespace+$–insensitive index of `source`, mapping each kept char back to an
 * original offset (plus a sentinel end offset).
 */
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

/** Expand [start, end) so a hit inside `$…$` / `$$…$$` includes the delimiters. */
function expandToMathDelimiters(source: string, start: number, end: number): [number, number] {
  let from = start
  let to = end

  // Prefer enclosing display math.
  const before = source.slice(0, start)
  const displayOpen = before.lastIndexOf('$$')
  if (displayOpen >= 0) {
    const displayClose = source.indexOf('$$', end)
    const between = source.slice(displayOpen + 2, start)
    // Only treat as enclosing when no other $$ sits between open and the match.
    if (displayClose >= end && !between.includes('$$')) {
      return [displayOpen, displayClose + 2]
    }
  }

  let left = from - 1
  while (left >= 0 && /\s/.test(source[left]!)) left -= 1
  if (left >= 0 && source[left] === '$') {
    from = left >= 1 && source[left - 1] === '$' ? left - 1 : left
  }

  let right = to
  while (right < source.length && /\s/.test(source[right]!)) right += 1
  if (right < source.length && source[right] === '$') {
    to = right + 1 < source.length && source[right + 1] === '$' ? right + 2 : right + 1
  }

  return [from, to]
}

/**
 * Locate the occurrence-th quote inside a markdown region, ignoring `$` and whitespace drift.
 * Returns [start, end) in region coordinates, expanded to math delimiters when applicable.
 */
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

/** Markdown body for one paper block: between its injected anchor and the next block anchor. */
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

/**
 * Slice the markdown source that corresponds to a paper evidence quote.
 * Falls back to the whole block region, then to the raw quote.
 */
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
        return region.slice(from, to).trim()
      }
    }
    // Equation / short blocks: show the whole region (still has $$ delimiters).
    if (region.length <= MAX_SNIPPET_CHARS) return region
    return `${region.slice(0, MAX_SNIPPET_CHARS).trimEnd()}…`
  }

  // No anchor (compat / unresolved): still try a document-wide fuzzy quote match.
  if (quote.trim() && markdown) {
    const span = findQuoteSpan(markdown, quote, occurrence)
    if (span) {
      const [from, to] = span
      return markdown.slice(from, to).trim()
    }
  }

  return quote.trim()
}
