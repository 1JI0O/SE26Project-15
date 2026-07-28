import * as fs from 'node:fs'
import * as path from 'node:path'
import * as vscode from 'vscode'
import { CoreRunner } from '../coreRunner'
import { openWorkspaceCode } from '../openCode'
import { extractPaperMarkdownSnippet } from '../paperSnippet'

interface TraceLink {
  id: string
  status: string
  source?: string
  relation_type: string
  confidence: number
  rationale: string
  paper_target: { block_id: string; quote: string }
  code_target: {
    path: string
    line_start: number
    line_end: number
    quote: string
    symbol_id?: string
  }
}

export class MatrixPanelProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'tracelab.matrix'
  private panel?: vscode.WebviewPanel
  private view?: vscode.WebviewView
  private filter: 'all' | 'proposed' | 'accepted' | 'rejected' = 'all'

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly runner: CoreRunner,
    private readonly onLocatePaper: (linkId: string) => void,
  ) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this.view = webviewView
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.extensionUri, 'media'),
        ...(vscode.workspace.workspaceFolders?.map((f) => f.uri) ?? []),
      ],
    }
    this.bind(webviewView.webview)
    this.refresh()
  }

  open(): void {
    // Prefer bottom panel tab (alongside Tensor Flow), not an editor column.
    void vscode.commands.executeCommand('workbench.view.extension.tracelab-panel')
    void vscode.commands.executeCommand(`${MatrixPanelProvider.viewType}.focus`)
    if (this.view) {
      this.view.show?.(true)
      this.refresh()
      return
    }
    // Fallback editor panel if bottom view not yet resolved.
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside)
      this.refresh()
      return
    }
    this.panel = vscode.window.createWebviewPanel(
      'tracelab.matrixEditor',
      'TraceLab 追溯矩阵',
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(this.extensionUri, 'media'),
          ...(vscode.workspace.workspaceFolders?.map((f) => f.uri) ?? []),
        ],
      },
    )
    this.panel.onDidDispose(() => {
      this.panel = undefined
    })
    this.bind(this.panel.webview)
    this.refresh()
  }

  private bind(webview: vscode.Webview): void {
    webview.onDidReceiveMessage(async (message) => {
      const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      if (!root) {
        return
      }
      if (message.type === 'review') {
        await this.runner.review(root, message.linkId, message.status)
        this.refresh()
      }
      if (message.type === 'reviewBatch') {
        await this.runner.reviewBatch(root, message.status, {
          ids: message.ids,
          allProposed: Boolean(message.allProposed),
        })
        this.refresh()
      }
      if (message.type === 'openCode') {
        await openWorkspaceCode(message.path, message.lineStart, message.lineEnd)
      }
      if (message.type === 'locatePaper') {
        this.onLocatePaper(String(message.linkId))
      }
      if (message.type === 'filter') {
        this.filter = message.value
        this.refresh()
      }
      if (message.type === 'previewCode') {
        const snippet = readSnippet(root, message.path, message.lineStart, message.lineEnd)
        const target = this.view?.webview ?? this.panel?.webview
        void target?.postMessage({ type: 'codePreview', linkId: message.linkId, snippet })
      }
    })
  }

  refresh(): void {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!root) {
      return
    }
    const html = this.buildHtml(root)
    if (this.view) {
      this.view.webview.html = html
    }
    if (this.panel) {
      this.panel.webview.html = html
    }
  }

  private loadMarkdown(root: string): string {
    const tracelab = this.runner.tracelabRoot(root)
    const mdPath = path.join(tracelab, 'papers', 'parsed', 'document.md')
    if (fs.existsSync(mdPath)) {
      return fs.readFileSync(mdPath, 'utf8')
    }
    const doc = this.runner.readJsonFile<{ markdown?: string }>(
      path.join(tracelab, 'papers', 'parsed', 'paper_document.json'),
    )
    return doc?.markdown || ''
  }

  private buildHtml(root: string): string {
    const webview = this.view?.webview ?? this.panel?.webview
    if (!webview) {
      return '<!DOCTYPE html><html><body>加载中…</body></html>'
    }
    const linksPath = path.join(this.runner.tracelabRoot(root), 'traces', 'links.json')
    const payload = this.runner.readJsonFile<{ links: TraceLink[] }>(linksPath)
    let links = payload?.links ?? []
    if (this.filter !== 'all') {
      links = links.filter((item) => item.status === this.filter)
    }
    const markdown = this.loadMarkdown(root)
    const media = (rel: string) =>
      webview
        .asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', ...rel.split('/')))
        .toString()

    const rows = links
      .map((link) => {
        const snippet = extractPaperMarkdownSnippet(
          markdown,
          link.paper_target.block_id,
          link.paper_target.quote || '',
        )
        return `
      <article class="row" data-id="${escapeHtml(link.id)}"
        data-path="${escapeHtml(link.code_target.path)}"
        data-ls="${link.code_target.line_start}"
        data-le="${link.code_target.line_end}"
        data-paper-md="${escapeAttr(snippet)}">
        <header>
          <input type="checkbox" class="pick" />
          <span class="status ${escapeHtml(link.status)}">${escapeHtml(link.status)}</span>
          <span class="src">${escapeHtml(link.source ?? '')}</span>
          <strong>${escapeHtml(link.relation_type)}</strong>
          <span class="conf">${(Number(link.confidence || 0) * 100).toFixed(0)}%</span>
        </header>
        <div class="paper md-snip"></div>
        <p class="code">${escapeHtml(link.code_target.path)}:${link.code_target.line_start}</p>
        <p class="why">${escapeHtml(link.rationale || '')}</p>
        <div class="actions">
          <button data-action="open">打开代码</button>
          <button data-action="paper">定位论文</button>
          <button data-action="accept">接受</button>
          <button data-action="reject">拒绝</button>
          <button data-action="reset">重置</button>
        </div>
      </article>`
      })
      .join('')

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource};" />
  <link rel="stylesheet" href="${media('paper/katex.min.css')}" />
  <style>
    html, body { height: 100%; margin: 0; }
    body {
      font: 12px/1.4 var(--vscode-font-family); color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      display: grid; grid-template-rows: auto 1fr; overflow: hidden;
    }
    .toolbar {
      display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
      padding: 8px 10px; border-bottom: 1px solid var(--vscode-widget-border);
      background: var(--vscode-editor-background); z-index: 5;
    }
    .list { overflow: auto; padding: 10px; }
    button { cursor: pointer; }
    .row { border: 1px solid var(--vscode-widget-border); border-radius: 6px; padding: 8px; margin-bottom: 8px; }
    .row:hover { border-color: var(--vscode-focusBorder); }
    header { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .status.proposed { color: #cca700; } .status.accepted { color: #3ba55d; } .status.rejected { color: #f04747; }
    .src { opacity: .7; font-size: 11px; }
    .md-snip { margin: 6px 0; max-height: 8em; overflow: auto; }
    .md-snip .math-display { margin: 4px 0; overflow-x: auto; }
    .md-snip .katex { font-size: 1em; }
    #hover {
      display: none; position: fixed; z-index: 20; max-width: 420px; padding: 8px;
      background: var(--vscode-editorWidget-background); border: 1px solid var(--vscode-widget-border);
      box-shadow: 0 4px 16px rgba(0,0,0,.25); white-space: pre-wrap; max-height: 40vh; overflow: auto;
    }
  </style>
</head>
<body>
  <div class="toolbar">
    <select id="filter">
      <option value="all"${this.filter === 'all' ? ' selected' : ''}>全部</option>
      <option value="proposed"${this.filter === 'proposed' ? ' selected' : ''}>待审</option>
      <option value="accepted"${this.filter === 'accepted' ? ' selected' : ''}>已接受</option>
      <option value="rejected"${this.filter === 'rejected' ? ' selected' : ''}>已拒绝</option>
    </select>
    <button id="selectProposed">选中待审</button>
    <button id="batchAccept">接受所选</button>
    <button id="batchReject">拒绝所选</button>
    <button id="batchReset">重置所选</button>
    <button id="acceptAllProposed">接受全部待审</button>
    <span>显示 ${links.length} 条</span>
  </div>
  <div class="list">
    ${rows || '<p>暂无追溯。请先配置 LLM 并运行「生成追溯」。</p>'}
  </div>
  <div id="hover"></div>
  <script src="${media('paper/markdown-it.min.js')}"></script>
  <script src="${media('paper/katex.min.js')}"></script>
  <script src="${media('paper/purify.min.js')}"></script>
  <script>
    const vscode = acquireVsCodeApi();
    const hover = document.getElementById('hover');

    function renderEvidence(src) {
      const md = window.markdownit({ html: true, linkify: false });
      md.inline.ruler.before('escape', 'math_inline', (state, silent) => {
        const start = state.pos;
        if (state.src[start] !== '$' || state.src[start + 1] === '$') return false;
        let end = start + 1;
        while ((end = state.src.indexOf('$', end)) !== -1) {
          if (state.src[end - 1] !== '\\\\') break;
          end += 1;
        }
        if (end === -1) return false;
        if (!silent) {
          const token = state.push('math_inline', 'math', 0);
          token.content = state.src.slice(start + 1, end);
        }
        state.pos = end + 1;
        return true;
      });
      md.block.ruler.before('fence', 'math_block', (state, startLine, endLine, silent) => {
        let pos = state.bMarks[startLine] + state.tShift[startLine];
        let max = state.eMarks[startLine];
        const opening = state.src.slice(pos, max).trim();
        if (!opening.startsWith('$$')) return false;
        let content = opening.slice(2);
        let nextLine = startLine;
        if (content.endsWith('$$') && content.length > 2) content = content.slice(0, -2);
        else {
          const chunks = [content];
          let closed = false;
          while (++nextLine < endLine) {
            const lineStart = state.bMarks[nextLine] + state.tShift[nextLine];
            const lineEnd = state.eMarks[nextLine];
            const line = state.src.slice(lineStart, lineEnd);
            if (line.trim().endsWith('$$')) { chunks.push(line.replace(/\\$\\$\\s*$/, '')); closed = true; break; }
            chunks.push(line);
          }
          if (!closed) return false;
          content = chunks.join('\\n');
        }
        if (!silent) {
          const token = state.push('math_block', 'math', 0);
          token.block = true;
          token.content = content.trim();
          token.map = [startLine, nextLine + 1];
        }
        state.line = nextLine + 1;
        return true;
      }, { alt: ['paragraph', 'reference', 'blockquote', 'list'] });
      md.renderer.rules.math_inline = (tokens, idx) =>
        katex.renderToString(tokens[idx].content, { throwOnError: false, displayMode: false });
      md.renderer.rules.math_block = (tokens, idx) =>
        '<div class="math-display">' + katex.renderToString(tokens[idx].content, { throwOnError: false, displayMode: true }) + '</div>';
      return DOMPurify.sanitize(md.render(src || ''), { ADD_ATTR: ['id', 'data-paper-block-id'] });
    }

    document.querySelectorAll('.row').forEach((row) => {
      const snip = row.querySelector('.md-snip');
      if (snip) snip.innerHTML = renderEvidence(row.getAttribute('data-paper-md') || '');
    });

    document.getElementById('filter').onchange = (e) => vscode.postMessage({ type: 'filter', value: e.target.value });
    document.getElementById('selectProposed').onclick = () => {
      document.querySelectorAll('.row').forEach((row) => {
        const box = row.querySelector('.pick');
        box.checked = row.querySelector('.status')?.textContent === 'proposed';
      });
    };
    function selectedIds() {
      return [...document.querySelectorAll('.row')].filter((r) => r.querySelector('.pick')?.checked).map((r) => r.dataset.id);
    }
    document.getElementById('batchAccept').onclick = () => vscode.postMessage({ type: 'reviewBatch', status: 'accepted', ids: selectedIds() });
    document.getElementById('batchReject').onclick = () => vscode.postMessage({ type: 'reviewBatch', status: 'rejected', ids: selectedIds() });
    document.getElementById('batchReset').onclick = () => vscode.postMessage({ type: 'reviewBatch', status: 'proposed', ids: selectedIds() });
    document.getElementById('acceptAllProposed').onclick = () => vscode.postMessage({ type: 'reviewBatch', status: 'accepted', allProposed: true });
    document.querySelectorAll('.row').forEach((row) => {
      row.querySelector('[data-action=open]')?.addEventListener('click', () => {
        vscode.postMessage({ type: 'openCode', path: row.dataset.path, lineStart: Number(row.dataset.ls), lineEnd: Number(row.dataset.le) });
      });
      row.querySelector('[data-action=paper]')?.addEventListener('click', () => {
        vscode.postMessage({ type: 'locatePaper', linkId: row.dataset.id });
      });
      row.querySelector('[data-action=accept]')?.addEventListener('click', () => {
        vscode.postMessage({ type: 'review', linkId: row.dataset.id, status: 'accepted' });
      });
      row.querySelector('[data-action=reject]')?.addEventListener('click', () => {
        vscode.postMessage({ type: 'review', linkId: row.dataset.id, status: 'rejected' });
      });
      row.querySelector('[data-action=reset]')?.addEventListener('click', () => {
        vscode.postMessage({ type: 'review', linkId: row.dataset.id, status: 'proposed' });
      });
      row.addEventListener('mouseenter', (ev) => {
        vscode.postMessage({
          type: 'previewCode',
          linkId: row.dataset.id,
          path: row.dataset.path,
          lineStart: Number(row.dataset.ls),
          lineEnd: Number(row.dataset.le),
        });
        hover.style.display = 'block';
        hover.style.left = Math.min(ev.clientX + 12, window.innerWidth - 440) + 'px';
        hover.style.top = Math.min(ev.clientY + 12, window.innerHeight - 160) + 'px';
        hover.innerHTML = (row.querySelector('.md-snip')?.innerHTML || '') + '<hr/><pre style="white-space:pre-wrap;margin:0">加载代码…</pre>';
      });
      row.addEventListener('mouseleave', () => { hover.style.display = 'none'; });
    });
    window.addEventListener('message', (event) => {
      const msg = event.data;
      if (msg.type === 'codePreview') {
        const paperHtml = document.querySelector('.row[data-id="' + msg.linkId + '"] .md-snip')?.innerHTML || '';
        hover.innerHTML = paperHtml + '<hr/><pre style="white-space:pre-wrap;margin:0">' +
          String(msg.snippet || '').replace(/[&<>]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])) + '</pre>';
      }
    });
  </script>
</body>
</html>`
  }
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function escapeAttr(value: string): string {
  return escapeHtml(value).replaceAll("'", '&#39;')
}

function readSnippet(root: string, relPath: string, lineStart: number, lineEnd: number): string {
  try {
    const full = path.join(root, relPath)
    const lines = fs.readFileSync(full, 'utf8').split(/\r?\n/)
    const start = Math.max(1, lineStart) - 1
    const end = Math.min(lines.length, Math.max(lineEnd, lineStart) + 3)
    return lines.slice(Math.max(0, start - 2), end).join('\n')
  } catch {
    return '(无法读取代码)'
  }
}
