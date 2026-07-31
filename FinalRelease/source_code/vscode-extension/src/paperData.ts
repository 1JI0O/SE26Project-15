import * as fs from 'node:fs'
import * as path from 'node:path'
import { tracelabPaths } from './workspaceStatus'

/** Paper artifacts + trace links, loaded once per change and cached by mtime. */
export interface PaperBlock {
  id: string
  text?: string
  kind?: string
  bbox?: number[]
  page?: number
  page_number?: number
  lines?: Array<{ text: string; bbox?: number[] }>
  page_size?: number[]
}

export interface TraceLink {
  id: string
  status: string
  source?: string
  relation_type?: string
  confidence?: number
  rationale?: string
  paper_target: { block_id: string; quote?: string; occurrence?: number; target_type?: string }
  code_target: {
    path: string
    line_start: number
    line_end: number
    quote?: string
    symbol_id?: string
  }
}

export interface PaperDocument {
  title: string
  markdown: string
  sections: Array<{ id: string; title: string; level: number }>
  blocks: PaperBlock[]
  source: string
}

/** Highlight box in page-relative (0..1) coordinates, ready for the webview. */
export interface HighlightRect {
  page: number
  left: number
  top: number
  width: number
  height: number
  precise: boolean
  linkId: string
  quote: string
  path: string
  lineStart: number
  lineEnd: number
  status: string
  pageAspect?: number
}

export interface PaperMark {
  linkId: string
  blockId: string
  quote: string
  status: string
  path: string
  lineStart: number
  lineEnd: number
}

function readJson<T>(target: string): T | undefined {
  try {
    return JSON.parse(fs.readFileSync(target, 'utf8')) as T
  } catch {
    return undefined
  }
}

function mtime(target: string): number {
  try {
    return fs.statSync(target).mtimeMs
  } catch {
    return 0
  }
}

/** Cheap change stamp over the artifacts a paper view depends on. */
export function paperStamp(workspace: string): string {
  const paths = tracelabPaths(workspace)
  return [
    mtime(paths.paperDocumentJson),
    mtime(paths.documentMd),
    mtime(paths.normalizedJson),
    mtime(paths.linksJson),
    mtime(paths.sourcePdf),
  ].join(':')
}

export function loadLinks(workspace: string): TraceLink[] {
  const paths = tracelabPaths(workspace)
  return readJson<{ links?: TraceLink[] }>(paths.linksJson)?.links ?? []
}

/**
 * Load the paper document. `document.md` is preferred as the Markdown source so
 * evidence snippets are cut from the same text the reader renders.
 */
export function loadPaperDocument(workspace: string): PaperDocument {
  const paths = tracelabPaths(workspace)
  const doc = readJson<Partial<PaperDocument>>(paths.paperDocumentJson)
  const normalized = readJson<{
    title?: string
    paragraphs?: Array<{ id: string; text?: string; page?: number }>
  }>(paths.normalizedJson)

  let markdown = ''
  try {
    markdown = fs.readFileSync(paths.documentMd, 'utf8')
  } catch {
    markdown = doc?.markdown ?? ''
  }
  if (!markdown) {
    markdown = doc?.markdown ?? ''
  }

  const blocks =
    doc?.blocks ??
    (normalized?.paragraphs ?? []).map((item) => ({
      id: String(item.id),
      text: item.text,
      page: item.page,
    }))

  return {
    title: doc?.title || normalized?.title || '论文',
    markdown,
    sections: doc?.sections ?? [],
    blocks,
    source: doc?.source || (markdown ? 'document.md' : 'missing'),
  }
}

/** Rewrite relative image links in the Markdown to webview URIs. */
export function resolveMarkdownAssets(
  workspace: string,
  markdown: string,
  toWebviewUri: (absolutePath: string) => string,
): string {
  const assetsRoot = tracelabPaths(workspace).assets
  return markdown.replace(
    /!\[([^\]]*)\]\((?!https?:|data:|blob:)([^)]+)\)/g,
    (_match, alt: string, src: string) => {
      const cleaned = src.replace(/^\.\//, '').split(/[?#]/)[0] ?? src
      const candidates = [
        path.join(assetsRoot, cleaned),
        path.join(assetsRoot, 'images', path.basename(cleaned)),
      ]
      for (const candidate of candidates) {
        try {
          if (fs.statSync(candidate).isFile()) {
            return `![${alt}](${toWebviewUri(candidate)})`
          }
        } catch {
          // try next candidate
        }
      }
      return `![${alt}](${src})`
    },
  )
}

export function toMarks(links: TraceLink[]): PaperMark[] {
  return links.map((link) => ({
    linkId: link.id,
    blockId: link.paper_target.block_id,
    quote: link.paper_target.quote ?? '',
    status: link.status,
    path: link.code_target.path,
    lineStart: link.code_target.line_start,
    lineEnd: link.code_target.line_end,
  }))
}

function textKey(value: unknown): string {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[^0-9a-z一-鿿]+/g, '')
}

/** Indices of the block lines covered by `quote`, matched on normalized text. */
function linesForQuote(lines: Array<{ text?: string }>, quote: string): number[] {
  const needle = textKey(quote)
  if (needle.length < 8) return []
  let joined = ''
  const owner: number[] = []
  lines.forEach((line, index) => {
    const key = textKey(line.text)
    joined += key
    for (let i = 0; i < key.length; i += 1) owner.push(index)
  })
  const at = joined.indexOf(needle)
  if (at < 0) return []
  const covered = new Set<number>()
  for (let i = at; i < at + needle.length && i < owner.length; i += 1) {
    covered.add(owner[i]!)
  }
  return [...covered].sort((a, b) => a - b)
}

/**
 * Pre-compute PDF highlight boxes on the host, grouped by page.
 *
 * This used to run in the webview over the full `blocks` array (with every line
 * bbox inlined into the HTML), which is the bulk of the paper payload and was
 * recomputed on every page render.
 */
export function computeHighlightRects(
  blocks: PaperBlock[],
  links: TraceLink[],
): Record<number, HighlightRect[]> {
  const byId = new Map(blocks.map((block) => [block.id, block]))
  const out: Record<number, HighlightRect[]> = {}
  const push = (rect: HighlightRect) => {
    ;(out[rect.page] ??= []).push(rect)
  }

  for (const link of links) {
    const block = byId.get(link.paper_target.block_id)
    if (!block) continue
    const page = Number(block.page ?? block.page_number ?? 1)
    if (!Number.isFinite(page) || page < 1) continue
    const size = Array.isArray(block.page_size) ? block.page_size : undefined
    const pageAspect =
      size && size.length === 2 && size[0]! > 0 && size[1]! > 0
        ? size[0]! / size[1]!
        : undefined
    const base = {
      page,
      precise: true,
      linkId: link.id,
      quote: link.paper_target.quote ?? '',
      path: link.code_target.path,
      lineStart: link.code_target.line_start,
      lineEnd: link.code_target.line_end,
      status: link.status,
      pageAspect,
    }

    const lines = Array.isArray(block.lines) ? block.lines : []
    let used = false
    for (const index of lines.length ? linesForQuote(lines, base.quote) : []) {
      const bbox = lines[index]?.bbox
      if (!Array.isArray(bbox) || bbox.length !== 4) continue
      const [x0, y0, x1, y1] = bbox as [number, number, number, number]
      const width = Math.abs(x1 - x0)
      const height = Math.abs(y1 - y0)
      if (width <= 0 || height <= 0) continue
      push({ ...base, left: Math.min(x0, x1), top: Math.min(y0, y1), width, height })
      used = true
    }
    if (used) continue

    const bbox = block.bbox
    if (Array.isArray(bbox) && bbox.length === 4) {
      const [x0, y0, x1, y1] = bbox as [number, number, number, number]
      const width = Math.abs(x1 - x0)
      const height = Math.abs(y1 - y0)
      if (width > 0 && height > 0) {
        push({
          ...base,
          precise: false,
          left: Math.min(x0, x1),
          top: Math.min(y0, y1),
          width,
          height,
        })
      }
    }
  }
  return out
}
