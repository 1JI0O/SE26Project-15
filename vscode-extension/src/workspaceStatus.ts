import * as fs from 'node:fs'
import * as path from 'node:path'

/**
 * In-process mirror of `tracelab status` (see `tracelab_core/cli.py:cmd_status`).
 *
 * The CLI reads the very same `.tracelab/` files, but going through `uv run`
 * costs a process spawn (~350ms) per call — and the sidebar posts state on every
 * Agent progress event. Reading the files here keeps the UI responsive and stops
 * a long trace run from starving the extension host (which also serves webview
 * resources, i.e. the PDF).
 */
export interface WorkspaceStatus {
  ok: true
  tracelab_root: string
  paper_ready: boolean
  analysis_ready: boolean
  has_pdf: boolean
  has_markdown: boolean
  links_total: number
  links_proposed: number
  links_accepted: number
  links_rejected: number
  tensor_nodes: number
  paper_title: string
}

interface LinksFile {
  links?: Array<{ status?: string }>
}

function exists(target: string): boolean {
  try {
    return fs.statSync(target).isFile()
  } catch {
    return false
  }
}

function readJson<T>(target: string): T | undefined {
  try {
    return JSON.parse(fs.readFileSync(target, 'utf8')) as T
  } catch {
    return undefined
  }
}

export function tracelabPaths(workspace: string) {
  const root = path.join(workspace, '.tracelab')
  const parsed = path.join(root, 'papers', 'parsed')
  return {
    root,
    parsed,
    sourcePdf: path.join(root, 'papers', 'source.pdf'),
    normalizedJson: path.join(parsed, 'normalized.json'),
    paperDocumentJson: path.join(parsed, 'paper_document.json'),
    documentMd: path.join(parsed, 'document.md'),
    assets: path.join(parsed, 'assets'),
    symbolsJson: path.join(root, 'analysis', 'symbols.json'),
    tensorGraphJson: path.join(root, 'analysis', 'tensor_graph.json'),
    linksJson: path.join(root, 'traces', 'links.json'),
  }
}

export function readWorkspaceStatus(workspace: string): WorkspaceStatus {
  const paths = tracelabPaths(workspace)
  const links = readJson<LinksFile>(paths.linksJson)?.links ?? []
  let proposed = 0
  let accepted = 0
  let rejected = 0
  for (const link of links) {
    if (link.status === 'proposed') proposed += 1
    else if (link.status === 'accepted') accepted += 1
    else if (link.status === 'rejected') rejected += 1
  }
  const hasMarkdown = exists(paths.documentMd)
  return {
    ok: true,
    tracelab_root: paths.root,
    paper_ready:
      exists(paths.normalizedJson) || exists(paths.paperDocumentJson) || hasMarkdown,
    analysis_ready: exists(paths.symbolsJson),
    has_pdf: exists(paths.sourcePdf),
    has_markdown: hasMarkdown,
    links_total: links.length,
    links_proposed: proposed,
    links_accepted: accepted,
    links_rejected: rejected,
    tensor_nodes:
      readJson<{ nodes?: unknown[] }>(paths.tensorGraphJson)?.nodes?.length ?? 0,
    paper_title:
      readJson<{ title?: string }>(paths.paperDocumentJson)?.title ??
      readJson<{ title?: string }>(paths.normalizedJson)?.title ??
      '',
  }
}
