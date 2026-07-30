import * as fs from 'node:fs'
import * as vscode from 'vscode'
import { CoreRunner } from '../coreRunner'
import { openWorkspaceCode } from '../openCode'
import {
  computeHighlightRects,
  loadLinks,
  loadPaperDocument,
  paperStamp,
  resolveMarkdownAssets,
  toMarks,
} from '../paperData'
import { tracelabPaths } from '../workspaceStatus'
import { zh } from '../zh'
import { escapeHtml, shellAssets } from './shell'

/**
 * Paper reader (Markdown + PDF original) in an editor column.
 *
 * The HTML is a static shell rendered once; artifacts arrive over `postMessage`.
 * Re-setting `webview.html` on every refresh used to reload the whole webview —
 * discarding the rendered Markdown and restarting the PDF fetch, which is what
 * made opening the paper feel like it took minutes after a trace run.
 */
export class PdfPanelProvider {
  private panel?: vscode.WebviewPanel
  private focusLinkId?: string
  private sentStamp = ''

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly runner: CoreRunner,
  ) {}

  open(context: vscode.ExtensionContext, options?: { linkId?: string }): void {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!root) {
      vscode.window.showErrorMessage(zh.openFolderFirst)
      return
    }
    const paths = tracelabPaths(root)
    if (
      !fs.existsSync(paths.sourcePdf) &&
      !fs.existsSync(paths.paperDocumentJson) &&
      !fs.existsSync(paths.documentMd)
    ) {
      vscode.window.showErrorMessage('请先导入并解析论文（.tracelab/papers/）')
      return
    }
    this.focusLinkId = options?.linkId

    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside, true)
      this.postData(root)
      return
    }

    this.panel = vscode.window.createWebviewPanel(
      'tracelab.paper',
      zh.paperTitle,
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(this.extensionUri, 'media'),
          vscode.Uri.file(paths.root),
        ],
      },
    )
    this.panel.iconPath = vscode.Uri.joinPath(this.extensionUri, 'media', 'tracelab.svg')
    this.panel.onDidDispose(() => {
      this.panel = undefined
      this.sentStamp = ''
    })
    this.panel.webview.onDidReceiveMessage(async (message) => {
      if (message?.type === 'openCode') {
        await openWorkspaceCode(message.path, message.lineStart, message.lineEnd)
      }
      if (message?.type === 'ready') {
        this.sentStamp = ''
        this.postData(root)
      }
    })
    this.panel.webview.html = this.renderShell(this.panel.webview)
  }

  /** Reveal the paper view and focus one trace link. */
  locateLink(linkId: string, context?: vscode.ExtensionContext): void {
    this.focusLinkId = linkId
    if (!this.panel) {
      if (context) this.open(context, { linkId })
      return
    }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!root) return
    this.panel.reveal(vscode.ViewColumn.Beside, true)
    this.postData(root)
    void this.panel.webview.postMessage({ type: 'focus', linkId })
  }

  refresh(root?: string): void {
    const workspace = root ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!this.panel || !workspace) return
    this.postData(workspace)
  }

  /** Send artifacts only when they actually changed (mtime stamp). */
  private postData(workspace: string): void {
    const webview = this.panel?.webview
    if (!webview) return
    const stamp = `${paperStamp(workspace)}|${this.focusLinkId ?? ''}`
    if (stamp === this.sentStamp) {
      if (this.focusLinkId) {
        void webview.postMessage({ type: 'focus', linkId: this.focusLinkId })
      }
      return
    }
    this.sentStamp = stamp

    const paths = tracelabPaths(workspace)
    const paper = loadPaperDocument(workspace)
    const links = loadLinks(workspace)
    const markdown = resolveMarkdownAssets(workspace, paper.markdown, (file) =>
      webview.asWebviewUri(vscode.Uri.file(file)).toString(),
    )
    void webview.postMessage({
      type: 'paper',
      title: paper.title,
      source: paper.source,
      parsedDir: paths.parsed,
      markdown: markdown || `# ${zh.noMarkdown}`,
      sections: paper.sections,
      marks: toMarks(links),
      // Page-relative boxes are computed here so the webview never receives the
      // full `blocks` array (per-line bboxes dominate the payload).
      rects: computeHighlightRects(paper.blocks, links),
      pdfUri: fs.existsSync(paths.sourcePdf)
        ? webview.asWebviewUri(vscode.Uri.file(paths.sourcePdf)).toString()
        : '',
      focusLinkId: this.focusLinkId ?? null,
    })
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
  <link rel="stylesheet" href="${media('paper.css')}" />
</head>
<body class="tl-shell">
  <header class="tl-bar">
    <span class="tl-bar-group" role="tablist">
      <button id="tabMd" class="active" role="tab">${escapeHtml(zh.markdown)}</button>
      <button id="tabPdf" role="tab" disabled>${escapeHtml(zh.pdfOriginal)}</button>
    </span>
    <select id="toc" title="${escapeHtml(zh.outline)}">
      <option value="">${escapeHtml(zh.outline)}</option>
    </select>
    <span id="pdfZoom" class="tl-bar-group" hidden>
      <button id="pdfZoomOut" title="${escapeHtml(zh.zoomOut)}">−</button>
      <button id="pdfZoomLabel" class="tl-zoom-label" title="${escapeHtml(zh.fit)}">100%</button>
      <button id="pdfZoomIn" title="${escapeHtml(zh.zoomIn)}">+</button>
    </span>
    <span class="tl-bar-spacer"></span>
    <span id="paperTitle" class="tl-chip tl-chip-accent">—</span>
    <span id="paperMeta" class="tl-muted"></span>
  </header>
  <main class="tl-scroll" id="content">
    <section id="mdPane" class="tl-pane active">
      <article id="md" class="tl-md tl-paper"></article>
      <div id="mdBusy" class="tl-empty"><span class="tl-spin"></span><span>正在渲染论文…</span></div>
    </section>
    <section id="pdfPane" class="tl-pane">
      <div id="pdfRoot"></div>
      <div id="pdfError" class="tl-empty tl-bad" hidden></div>
    </section>
  </main>
  <script nonce="${nonce}" src="${media('paper/markdown-it.min.js')}"></script>
  <script nonce="${nonce}" src="${media('paper/katex.min.js')}"></script>
  <script nonce="${nonce}" src="${media('paper/purify.min.js')}"></script>
  <script nonce="${nonce}" src="${media('tl-markdown.js')}"></script>
  <script nonce="${nonce}" type="module">
    import * as pdfjsLib from '${media('pdfjs/pdf.min.mjs')}';
    window.__tlPdfjs = pdfjsLib;
    pdfjsLib.GlobalWorkerOptions.workerSrc = '${media('pdfjs/pdf.worker.min.mjs')}';
    window.__tlPdfAssets = { cMapUrl: '${media('pdfjs/cmaps/')}', stdFontUrl: '${media('pdfjs/standard_fonts/')}' };
    window.dispatchEvent(new Event('tl-pdfjs-ready'));
  </script>
  <script nonce="${nonce}" src="${media('paper.js')}"></script>
</body>
</html>`
  }
}
