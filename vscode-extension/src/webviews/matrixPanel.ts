import * as fs from 'node:fs'
import * as path from 'node:path'
import * as vscode from 'vscode'
import { CoreRunner } from '../coreRunner'
import { openWorkspaceCode } from '../openCode'
import { loadLinks, loadPaperDocument, paperStamp, type TraceLink } from '../paperData'
import { extractPaperMarkdownSnippet } from '../paperSnippet'
import { escapeHtml, shellAssets } from './shell'

type Filter = 'all' | 'proposed' | 'accepted' | 'rejected'
type ReviewStatus = 'accepted' | 'rejected' | 'proposed'

interface MatrixRow {
  id: string
  status: string
  source: string
  relationType: string
  confidence: number
  rationale: string
  blockId: string
  paperMarkdown: string
  targetType: string
  codePath: string
  lineStart: number
  lineEnd: number
  symbol: string
}

/**
 * Trace matrix, hosted in the bottom `tracelab-panel` next to the tensor view.
 *
 * Layout mirrors the desktop workbench: a fixed toolbar, an independently
 * scrolling list, and a docked relation preview (hover + pinned) rather than a
 * floating tooltip that overlapped the list.
 */
export class MatrixPanelProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'tracelab.matrix'
  private view?: vscode.WebviewView
  private filter: Filter = 'all'
  private agentLog: Array<{ step?: number; text: string }> = []
  private agentActivity = ''
  private agentRunning = false
  private sentStamp = ''

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly runner: CoreRunner,
    private readonly onLocatePaper: (linkId: string) => void,
  ) {}

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
    }
    webviewView.onDidDispose(() => {
      this.view = undefined
      this.sentStamp = ''
    })
    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible) this.refresh()
    })
    this.bind(webviewView.webview)
    webviewView.webview.html = this.renderShell(webviewView.webview)
  }

  /** Focus the bottom-panel tab (the desktop keeps matrix + flow side by side). */
  open(): void {
    void vscode.commands.executeCommand(`${MatrixPanelProvider.viewType}.focus`)
    this.view?.show?.(true)
    this.refresh()
  }

  setAgentState(state: { running?: boolean; activity?: string }): void {
    if (state.running != null) this.agentRunning = state.running
    if (state.activity != null) this.agentActivity = state.activity
    this.postAgent()
  }

  appendAgentLog(text: string, step?: number): void {
    if (!text.trim()) return
    this.agentLog.push({ step, text })
    if (this.agentLog.length > 60) this.agentLog = this.agentLog.slice(-60)
    this.postAgent()
  }

  clearAgentLog(): void {
    this.agentLog = []
    this.agentActivity = ''
    this.postAgent()
  }

  private postAgent(): void {
    void this.view?.webview.postMessage({
      type: 'agent',
      running: this.agentRunning,
      activity: this.agentActivity,
      log: this.agentLog,
    })
  }

  private bind(webview: vscode.Webview): void {
    webview.onDidReceiveMessage(async (message) => {
      const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      if (!root) return
      switch (message?.type) {
        case 'ready':
          this.sentStamp = ''
          this.postData(root)
          this.postAgent()
          return
        case 'filter':
          this.filter = (message.value as Filter) ?? 'all'
          void webview.postMessage({ type: 'filter', value: this.filter })
          return
        case 'openCode':
          await openWorkspaceCode(message.path, message.lineStart, message.lineEnd)
          return
        case 'locatePaper':
          this.onLocatePaper(String(message.linkId))
          return
        case 'review':
          await this.runner.review(root, message.linkId, message.status as ReviewStatus)
          this.refresh()
          return
        case 'reviewBatch':
          await this.runner.reviewBatch(root, message.status as ReviewStatus, {
            ids: message.ids,
            allProposed: Boolean(message.allProposed),
          })
          this.refresh()
          return
        case 'previewCode':
          void webview.postMessage({
            type: 'codePreview',
            linkId: message.linkId,
            snippet: readSnippet(root, message.path, message.lineStart, message.lineEnd),
          })
          return
        default:
      }
    })
  }

  refresh(): void {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!this.view || !root) return
    this.postData(root)
  }

  /** Rows go over postMessage so a review never reloads the webview. */
  private postData(root: string): void {
    const webview = this.view?.webview
    if (!webview) return
    const stamp = paperStamp(root)
    if (stamp === this.sentStamp) return
    this.sentStamp = stamp

    const markdown = loadPaperDocument(root).markdown
    const rows = loadLinks(root).map((link) => toRow(link, markdown))
    void webview.postMessage({ type: 'rows', rows, filter: this.filter })
  }

  private renderShell(webview: vscode.Webview): string {
    const { media, nonce, csp } = shellAssets(webview, this.extensionUri, { images: true })
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <link rel="stylesheet" href="${media('paper/katex.min.css')}" />
  <link rel="stylesheet" href="${media('ui.css')}" />
  <link rel="stylesheet" href="${media('matrix.css')}" />
</head>
<body class="tl-shell">
  <header class="tl-bar" id="toolbar">
    <select id="filter" title="按状态筛选">
      <option value="all">全部</option>
      <option value="proposed">待审</option>
      <option value="accepted">已接受</option>
      <option value="rejected">已拒绝</option>
    </select>
    <button class="tl-ghost" id="selectProposed">选中待审</button>
    <span class="tl-bar-group">
      <button class="tl-ghost" id="batchAccept">接受所选</button>
      <button class="tl-ghost" id="batchReject">拒绝所选</button>
      <button class="tl-ghost" id="batchReset">撤回所选</button>
    </span>
    <button class="tl-ghost" id="acceptAllProposed">接受全部待审</button>
    <span class="tl-bar-spacer"></span>
    <span class="tl-chip" id="countAll">0 条</span>
    <span class="tl-chip proposed" id="countProposed">待审 0</span>
    <span class="tl-chip accepted" id="countAccepted">已接受 0</span>
    <span class="tl-chip" id="countSelected" hidden>已选 0</span>
  </header>
  <div class="tl-split">
    <section class="tl-scroll" id="list" aria-label="追溯关系列表"></section>
    <aside class="tl-dock">
      <div class="tl-dock-scroll">
        <section class="tl-card" id="agentCard">
          <header class="tl-card-head">
            <span>Agent 分析</span>
            <span id="agentBadge" class="tl-chip">空闲</span>
          </header>
          <div class="tl-card-body">
            <div id="agentActivity" class="tl-agent-activity tl-muted">Agent 自主读取论文与代码证据</div>
            <div id="agentBar" class="tl-meter tl-meter-indeterminate tl-chip-accent" hidden><i></i></div>
            <ul id="agentLog" class="tl-log" hidden></ul>
          </div>
        </section>
        <section class="tl-card" id="previewCard">
          <header class="tl-card-head">
            <span>关系预览</span>
            <span class="tl-muted" id="previewHint">悬浮预览 / 已选中关系</span>
          </header>
          <div class="tl-card-body" id="previewBody">
            <div class="tl-empty">
              <strong>暂无预览关系</strong>
              <span>悬浮列表可临时预览，点击可固定关系。</span>
            </div>
          </div>
        </section>
      </div>
    </aside>
  </div>
  <script nonce="${nonce}" src="${media('paper/markdown-it.min.js')}"></script>
  <script nonce="${nonce}" src="${media('paper/katex.min.js')}"></script>
  <script nonce="${nonce}" src="${media('paper/purify.min.js')}"></script>
  <script nonce="${nonce}" src="${media('tl-markdown.js')}"></script>
  <script nonce="${nonce}" src="${media('matrix.js')}"></script>
</body>
</html>`
  }
}

function toRow(link: TraceLink, markdown: string): MatrixRow {
  return {
    id: link.id,
    status: link.status,
    source: link.source ?? '',
    relationType: link.relation_type ?? '',
    confidence: Math.round(Number(link.confidence ?? 0) * 100),
    rationale: link.rationale ?? '',
    blockId: link.paper_target.block_id,
    // Cut from `document.md` so `$…$` / `$$…$$` survive into the preview and
    // render as math instead of leaking raw TeX.
    paperMarkdown: extractPaperMarkdownSnippet(
      markdown,
      link.paper_target.block_id,
      link.paper_target.quote ?? '',
      link.paper_target.occurrence ?? 1,
    ),
    targetType: link.paper_target.target_type ?? '',
    codePath: link.code_target.path,
    lineStart: link.code_target.line_start,
    lineEnd: link.code_target.line_end,
    symbol: link.code_target.symbol_id ?? link.code_target.quote ?? '',
  }
}

function readSnippet(root: string, relPath: string, lineStart: number, lineEnd: number): string {
  try {
    const lines = fs.readFileSync(path.join(root, relPath), 'utf8').split(/\r?\n/)
    const from = Math.max(0, Math.max(1, lineStart) - 3)
    const to = Math.min(lines.length, Math.max(lineEnd, lineStart) + 3)
    return lines
      .slice(from, to)
      .map((line, index) => `${String(from + index + 1).padStart(4)}  ${line}`)
      .join('\n')
  } catch {
    return '(无法读取代码)'
  }
}
