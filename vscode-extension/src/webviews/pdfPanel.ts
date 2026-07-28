import * as fs from 'node:fs'
import * as path from 'node:path'
import * as vscode from 'vscode'
import { CoreRunner } from '../coreRunner'
import { openWorkspaceCode } from '../openCode'
import { zh } from '../zh'

interface PaperBlock {
  id: string
  text?: string
  kind?: string
  bbox?: number[]
  page?: number
  page_number?: number
  lines?: Array<{ text: string; bbox?: number[] }>
  page_size?: number[]
  render_anchor?: string
}

interface TraceLink {
  id: string
  status: string
  paper_target: { block_id: string; quote: string }
  code_target: { path: string; line_start: number; line_end: number }
}

interface PaperDocument {
  title?: string
  markdown?: string
  sections?: Array<{ id: string; title: string; level: number }>
  blocks?: PaperBlock[]
  source?: string
}

export class PdfPanelProvider {
  private panel?: vscode.WebviewPanel
  private focusLinkId?: string

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
    const tracelab = this.runner.tracelabRoot(root)
    const pdfPath = path.join(tracelab, 'papers', 'source.pdf')
    const paperDoc = path.join(tracelab, 'papers', 'parsed', 'paper_document.json')
    const documentMd = path.join(tracelab, 'papers', 'parsed', 'document.md')
    if (!fs.existsSync(pdfPath) && !fs.existsSync(paperDoc) && !fs.existsSync(documentMd)) {
      vscode.window.showErrorMessage('请先导入并解析论文（.tracelab/papers/）')
      return
    }
    this.focusLinkId = options?.linkId

    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside)
      this.refresh(root)
      return
    }

    this.panel = vscode.window.createWebviewPanel(
      'tracelab.paper',
      zh.paperTitle,
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(this.extensionUri, 'media'),
          vscode.Uri.file(tracelab),
          vscode.Uri.file(root),
        ],
      },
    )
    this.panel.onDidDispose(() => {
      this.panel = undefined
    })
    this.panel.webview.onDidReceiveMessage(async (message) => {
      if (message.type === 'openCode') {
        await openWorkspaceCode(message.path, message.lineStart, message.lineEnd)
      }
    })
    this.refresh(root)
  }

  locateLink(linkId: string, context?: vscode.ExtensionContext): void {
    this.focusLinkId = linkId
    if (!this.panel && context) {
      this.open(context, { linkId })
      return
    }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!root || !this.panel) {
      return
    }
    this.panel.reveal(vscode.ViewColumn.Beside)
    this.refresh(root)
  }

  refresh(root?: string): void {
    if (!this.panel) {
      return
    }
    const workspace = root ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!workspace) {
      return
    }
    this.panel.webview.html = this.render(this.panel.webview, workspace)
  }

  private loadPaper(tracelab: string): PaperDocument {
    const paperPath = path.join(tracelab, 'papers', 'parsed', 'paper_document.json')
    const fromJson = this.runner.readJsonFile<PaperDocument>(paperPath)
    if (fromJson?.markdown) {
      return fromJson
    }
    const mdPath = path.join(tracelab, 'papers', 'parsed', 'document.md')
    const normalized = this.runner.readJsonFile<{
      title?: string
      paragraphs?: Array<{ id: string; text?: string; page?: number }>
    }>(path.join(tracelab, 'papers', 'parsed', 'normalized.json'))
    let markdown = fromJson?.markdown || ''
    if (!markdown && fs.existsSync(mdPath)) {
      markdown = fs.readFileSync(mdPath, 'utf8')
    }
    const blocks =
      fromJson?.blocks ??
      (normalized?.paragraphs || []).map((p) => ({
        id: String(p.id),
        text: p.text,
        page: p.page,
      }))
    return {
      title: fromJson?.title || normalized?.title || '论文',
      markdown: markdown || `# ${zh.noMarkdown}`,
      sections: fromJson?.sections || [],
      blocks,
      source: fromJson?.source || (markdown ? 'document.md' : 'missing'),
    }
  }

  private render(webview: vscode.Webview, root: string): string {
    const tracelab = this.runner.tracelabRoot(root)
    const pdfPath = path.join(tracelab, 'papers', 'source.pdf')
    const paper = this.loadPaper(tracelab)
    const links =
      this.runner.readJsonFile<{ links: TraceLink[] }>(path.join(tracelab, 'traces', 'links.json'))
        ?.links ?? []

    const assetsRoot = path.join(tracelab, 'papers', 'parsed', 'assets')
    const media = (rel: string) =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', ...rel.split('/'))).toString()

    const resolveAssetInMarkdown = (markdown: string): string => {
      return markdown.replace(
        /!\[([^\]]*)\]\((?!https?:|data:|blob:)([^)]+)\)/g,
        (_m, alt: string, src: string) => {
          const cleaned = src.replace(/^\.\//, '')
          const candidates = [
            path.join(assetsRoot, cleaned),
            path.join(assetsRoot, 'images', path.basename(cleaned)),
            path.join(assetsRoot, cleaned.replace(/^images\//, 'images/')),
          ]
          for (const filePath of candidates) {
            if (fs.existsSync(filePath)) {
              return `![${alt}](${webview.asWebviewUri(vscode.Uri.file(filePath)).toString()})`
            }
          }
          return `![${alt}](${src})`
        },
      )
    }

    const markdown = resolveAssetInMarkdown(paper.markdown || `# ${zh.noMarkdown}`)
    const blocks = paper.blocks ?? []
    const focusLink = links.find((link) => link.id === this.focusLinkId)
    const focusBlockId = focusLink?.paper_target.block_id
    const marks = links.map((link) => ({
      targetId: link.id,
      blockId: link.paper_target.block_id,
      quote: link.paper_target.quote || '',
      status: link.status,
      path: link.code_target.path,
      lineStart: link.code_target.line_start,
      lineEnd: link.code_target.line_end,
    }))
    const toc = (paper.sections || [])
      .map(
        (section) =>
          `<option value="${escapeHtml(section.id)}">${escapeHtml(section.title)}</option>`,
      )
      .join('')

    const pdfUri = fs.existsSync(pdfPath)
      ? webview.asWebviewUri(vscode.Uri.file(pdfPath)).toString()
      : ''
    const pdfJs = media('pdfjs/pdf.min.mjs')
    const worker = media('pdfjs/pdf.worker.min.mjs')
    const cMapUrl = media('pdfjs/cmaps/')
    const stdFont = media('pdfjs/standard_fonts/')
    const parsedHint = path.join(tracelab, 'papers', 'parsed')

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource}; img-src ${webview.cspSource} data: blob:; worker-src ${webview.cspSource} blob:; connect-src ${webview.cspSource};" />
  <link rel="stylesheet" href="${media('paper/katex.min.css')}" />
  <style>
    body { margin: 0; display: grid; grid-template-rows: auto 1fr; height: 100vh; font: 13px/1.55 var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); }
    .toolbar { display: flex; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--vscode-widget-border); align-items: center; flex-wrap: wrap; }
    .view-switch button.active { outline: 1px solid var(--vscode-focusBorder); }
    .content { overflow: auto; padding: 16px 20px 48px; }
    .pane { display: none; } .pane.active { display: block; }
    #md :is(h1,h2,h3,h4) { scroll-margin-top: 12px; }
    #md img { max-width: 100%; }
    #md mark[data-trace-target], #md .trace-block-target { background: rgba(255,196,0,.28); cursor: pointer; border-radius: 2px; }
    #md mark.trace-mark-accepted, #md .trace-block-accepted { background: rgba(80,200,120,.28); }
    #md mark.active, #md .trace-block-target.active, #md .trace-target-active { background: rgba(80,160,255,.35); outline: 1px solid #4af; }
    .math-display { overflow-x: auto; margin: 12px 0; }
    .page { position: relative; margin: 0 auto 16px; width: fit-content; box-shadow: 0 1px 6px rgba(0,0,0,.25); }
    canvas { display: block; }
    .hit {
      position: absolute; padding: 0; border: 0; border-radius: 2px; cursor: pointer;
      background: rgba(88, 133, 255, 0.18);
      box-shadow: inset 0 -2px 0 rgba(88, 133, 255, 0.55);
      mix-blend-mode: multiply;
    }
    .hit.coarse {
      background: rgba(88, 133, 255, 0.10);
      outline: 1px dashed rgba(88, 133, 255, 0.45);
      outline-offset: 1px;
      box-shadow: none;
    }
    .hit.focus {
      background: rgba(255, 205, 90, 0.35);
      outline: 2px solid #e0a83a;
      outline-offset: 1px;
      box-shadow: inset 0 -2px 0 #e0a83a;
    }
    .error { color: #f04747; padding: 12px; white-space: pre-wrap; }
    .hint { opacity: .7; font-size: 11px; }
    #pdfZoomLabel { min-width: 3.5em; text-align: center; }
  </style>
</head>
<body>
  <div class="toolbar">
    <div class="view-switch">
      <button id="tabMd" class="active">${zh.markdown}</button>
      <button id="tabPdf" ${pdfUri ? '' : 'disabled'}>${zh.pdfOriginal}</button>
    </div>
    <label>${zh.outline}
      <select id="toc"><option value="">—</option>${toc}</select>
    </label>
    <span id="pdfZoomControls" hidden>
      <button id="pdfZoomOut" type="button">缩小</button>
      <span id="pdfZoomLabel">150%</span>
      <button id="pdfZoomIn" type="button">放大</button>
      <button id="pdfZoomFit" type="button">适应宽度</button>
    </span>
    <span>${escapeHtml(paper.title || '论文')} · ${escapeHtml(paper.source || '')}</span>
    <span class="hint">${escapeHtml(parsedHint)}</span>
  </div>
  <main class="content">
    <div id="mdPane" class="pane active"><article id="md"></article></div>
    <div id="pdfPane" class="pane"><div id="pdfRoot"></div><div id="pdfError" class="error" hidden></div></div>
  </main>
  <script src="${media('paper/markdown-it.min.js')}"></script>
  <script src="${media('paper/katex.min.js')}"></script>
  <script src="${media('paper/purify.min.js')}"></script>
  <script type="module">
    import * as pdfjsLib from '${pdfJs}';
    pdfjsLib.GlobalWorkerOptions.workerSrc = '${worker}';
    const vscodeApi = acquireVsCodeApi();
    const markdownSource = ${JSON.stringify(markdown)};
    const marks = ${JSON.stringify(marks)};
    const blocks = ${JSON.stringify(blocks)};
    const focusLinkId = ${JSON.stringify(this.focusLinkId ?? null)};
    const focusBlockId = ${JSON.stringify(focusBlockId ?? null)};
    const pdfUrl = ${JSON.stringify(pdfUri)};

    function renderMarkdown(src) {
      const md = window.markdownit({ html: true, linkify: true });
      let headingIndex = 0;
      const defaultHeading = md.renderer.rules.heading_open || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
      };
      md.renderer.rules.heading_open = (tokens, idx, options, env, self) => {
        headingIndex += 1;
        tokens[idx].attrSet('id', 'section-' + headingIndex);
        return defaultHeading(tokens, idx, options, env, self);
      };
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
      return DOMPurify.sanitize(md.render(src), { ADD_ATTR: ['id', 'data-paper-block-id', 'data-trace-target', 'loading'] });
    }

    const mdRoot = document.getElementById('md');
    mdRoot.innerHTML = renderMarkdown(markdownSource);

    function texKey(value) {
      return String(value || '')
        .replace(/\\$\\$?/g, ' ')
        .replace(/\\\\(?:left|right|!|,|;|:|quad|qquad|displaystyle|nonumber)\\b/g, ' ')
        .replace(/\\\\begin\\{[^}]*\\}|\\\\end\\{[^}]*\\}/g, ' ')
        .replace(/[\\s{}]/g, '')
        .toLowerCase();
    }
    function renderedTex(el) {
      return el.querySelector('annotation[encoding="application/x-tex"]')?.textContent || '';
    }
    function isBlockLevelTarget(quote) {
      return /[$\\\\]|\\\\begin\\{/.test(String(quote || ''));
    }
    function isEmptyContainer(el) {
      return String(el.textContent || '').replace(/\\s+/g, ' ').trim().length === 0;
    }
    function resolveVisualBlock(anchor) {
      const container = anchor.closest('h1,h2,h3,h4,h5,h6,p,li,pre,blockquote,td') || anchor;
      if (!isEmptyContainer(container)) return container;
      let sibling = container.nextElementSibling;
      while (sibling && isEmptyContainer(sibling) && !sibling.matches('.math-display, .table-scroll, table, pre, img, blockquote')) {
        sibling = sibling.nextElementSibling;
      }
      if (sibling && (sibling.matches('.math-display, .table-scroll, table, pre, img, blockquote') || !isEmptyContainer(sibling))) {
        return sibling;
      }
      return container;
    }
    function findNearbyVisualBlock(start, maxSteps = 3) {
      let sibling = start.nextElementSibling;
      for (let step = 0; step < maxSteps && sibling; step += 1) {
        if (sibling.matches('.math-display, .table-scroll, table, pre, img, blockquote')) return sibling;
        if (!isEmptyContainer(sibling) && sibling.tagName !== 'P') return sibling;
        sibling = sibling.nextElementSibling;
      }
      return null;
    }
    function findFormulaByTex(quote) {
      const needle = texKey(quote);
      if (needle.length < 4) return null;
      for (const el of mdRoot.querySelectorAll('.math-display')) {
        if (texKey(renderedTex(el)).includes(needle) || needle.includes(texKey(renderedTex(el)))) {
          return el;
        }
      }
      return null;
    }
    function resolveBlockHost(blockId, quote) {
      const anchor = mdRoot.querySelector('[data-paper-block-id="' + CSS.escape(blockId) + '"]');
      let host = null;
      if (anchor) {
        host = resolveVisualBlock(anchor);
        if (isBlockLevelTarget(quote) && !host.matches('.math-display')) {
          host = findNearbyVisualBlock(host) || host;
        }
      }
      if (isBlockLevelTarget(quote)) {
        const byTex = findFormulaByTex(quote);
        if (byTex && (!host || !host.matches('.math-display'))) host = byTex;
      }
      return host;
    }
    function wrapQuote(host, mark) {
      if (isBlockLevelTarget(mark.quote)) return null;
      const quote = String(mark.quote || '').trim();
      const plainLead = quote.split(/[$\\\\]/)[0].trim();
      const candidates = [quote, plainLead].filter((c) => c.length >= 6);
      const raw = host.textContent || '';
      let needle = '', index = -1;
      for (const candidate of candidates) {
        const idx = raw.indexOf(candidate);
        if (idx >= 0) { needle = candidate; index = idx; break; }
      }
      if (index < 0 || !needle) return null;
      const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
      let consumed = 0, startNode = null, startOffset = 0, endNode = null, endOffset = 0;
      const end = index + needle.length;
      let node = walker.nextNode();
      while (node) {
        const length = node.data.length;
        if (!startNode && consumed + length > index) { startNode = node; startOffset = index - consumed; }
        if (startNode && consumed + length >= end) { endNode = node; endOffset = end - consumed; break; }
        consumed += length; node = walker.nextNode();
      }
      if (!startNode || !endNode) return null;
      try {
        const range = document.createRange();
        range.setStart(startNode, startOffset); range.setEnd(endNode, endOffset);
        const el = document.createElement('mark');
        el.dataset.traceTarget = mark.targetId;
        el.className = 'trace-mark trace-mark-' + mark.status;
        range.surroundContents(el);
        return el;
      } catch (_) { return null; }
    }
    function showMd() {
      document.getElementById('tabMd').classList.add('active');
      document.getElementById('tabPdf').classList.remove('active');
      document.getElementById('mdPane').classList.add('active');
      document.getElementById('pdfPane').classList.remove('active');
      document.getElementById('pdfZoomControls').hidden = true;
    }
    let pdfStarted = false;
    function showPdf() {
      document.getElementById('tabPdf').classList.add('active');
      document.getElementById('tabMd').classList.remove('active');
      document.getElementById('pdfPane').classList.add('active');
      document.getElementById('mdPane').classList.remove('active');
      document.getElementById('pdfZoomControls').hidden = !pdfUrl;
      if (pdfUrl && !pdfStarted) {
        pdfStarted = true;
        void ensurePdf();
      }
    }
    let focusEl = null;
    for (const mark of marks) {
      const host = resolveBlockHost(mark.blockId, mark.quote);
      if (!host) continue;
      const precise = wrapQuote(host, mark);
      const el = precise || host;
      if (!precise) {
        host.classList.add('trace-block-target', 'trace-block-' + mark.status);
        host.dataset.traceTarget = mark.targetId;
      }
      if (mark.targetId === focusLinkId || mark.blockId === focusBlockId) {
        el.classList.add('active', 'trace-target-active');
        focusEl = el;
      }
      el.addEventListener('click', () => {
        vscodeApi.postMessage({ type: 'openCode', path: mark.path, lineStart: mark.lineStart, lineEnd: mark.lineEnd });
      });
    }
    if (focusEl) {
      showMd();
      focusEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else if (focusLinkId) {
      showPdf();
    }
    document.getElementById('tabMd').onclick = showMd;
    document.getElementById('tabPdf').onclick = () => { if (pdfUrl) showPdf(); };
    document.getElementById('toc').onchange = (e) => {
      const id = e.target.value;
      if (!id) return;
      showMd();
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    function textKey(v) { return String(v || '').toLowerCase().replace(/[^0-9a-z\\u4e00-\\u9fff]+/g, ''); }
    function pageShapeAgrees(block, pageAspect) {
      const size = block.page_size;
      if (!pageAspect || !Array.isArray(size) || size.length !== 2) return true;
      const [w, h] = size;
      if (!(w > 0) || !(h > 0)) return true;
      return Math.abs(w / h - pageAspect) <= 0.02;
    }
    function linesForQuote(lines, quote) {
      const needle = textKey(quote);
      if (needle.length < 8) return [];
      let joined = ''; const owner = [];
      lines.forEach((line, index) => {
        const key = textKey(line.text || '');
        joined += key;
        for (let i = 0; i < key.length; i++) owner.push(index);
      });
      const at = joined.indexOf(needle);
      if (at < 0) return [];
      const covered = new Set();
      for (let i = at; i < at + needle.length && i < owner.length; i++) covered.add(owner[i]);
      return [...covered].sort((a, b) => a - b);
    }
    function highlightRects(pageAspects) {
      const rects = [];
      for (const mark of marks) {
        const block = blocks.find((b) => b.id === mark.blockId);
        if (!block) continue;
        const page = Number(block.page || block.page_number || 1);
        if (!pageShapeAgrees(block, pageAspects.get(page))) continue;
        const lines = Array.isArray(block.lines) ? block.lines : [];
        const covered = lines.length ? linesForQuote(lines, mark.quote) : [];
        let used = false;
        for (const index of covered) {
          const line = lines[index];
          if (!line || !Array.isArray(line.bbox) || line.bbox.length !== 4) continue;
          const [x0,y0,x1,y1] = line.bbox;
          const width = Math.abs(x1-x0), height = Math.abs(y1-y0);
          if (width <= 0 || height <= 0) continue;
          rects.push({ page, left: Math.min(x0,x1), top: Math.min(y0,y1), width, height, precise: true, mark });
          used = true;
        }
        if (!used && Array.isArray(block.bbox) && block.bbox.length === 4) {
          const [x0,y0,x1,y1] = block.bbox;
          const width = Math.abs(x1-x0), height = Math.abs(y1-y0);
          if (width > 0 && height > 0) {
            rects.push({ page, left: Math.min(x0,x1), top: Math.min(y0,y1), width, height, precise: false, mark });
          }
        }
      }
      return rects;
    }
    async function ensurePdf() {
      const err = document.getElementById('pdfError');
      const rootEl = document.getElementById('pdfRoot');
      const zoomLabel = document.getElementById('pdfZoomLabel');
      if (!pdfUrl) { err.hidden = false; err.textContent = '${zh.noPdf}'; return; }
      let pdfDoc = null;
      let zoomPercent = 100;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const pageMeta = new Map();
      let observer = null;
      let paintToken = 0;

      function updateZoomLabel() {
        zoomLabel.textContent = Math.round(zoomPercent) + '%';
      }

      function layoutPlaceholders(defaultAspect) {
        rootEl.innerHTML = '';
        const contentWidth = Math.max(320, (document.querySelector('.content')?.clientWidth || 720) - 40);
        for (let pageNum = 1; pageNum <= pdfDoc.numPages; pageNum++) {
          const prev = pageMeta.get(pageNum) || {};
          const aspect = prev.aspect || defaultAspect || (612 / 792);
          const cssWidth = contentWidth * (zoomPercent / 100);
          const cssHeight = cssWidth / aspect;
          const wrap = document.createElement('div');
          wrap.className = 'page';
          wrap.dataset.page = String(pageNum);
          wrap.style.width = cssWidth + 'px';
          wrap.style.height = cssHeight + 'px';
          wrap.style.background = 'var(--vscode-editor-inactiveSelectionBackground)';
          wrap.innerHTML = '<div style="padding:8px;opacity:.6;font-size:11px">第 ' + pageNum + ' 页</div>';
          rootEl.appendChild(wrap);
          pageMeta.set(pageNum, { ...prev, wrap, rendered: false, aspect, cssWidth, cssHeight });
        }
      }

      async function renderPage(pageNum, token) {
        const meta = pageMeta.get(pageNum);
        if (!meta || !meta.wrap || meta.rendered || meta.rendering || token !== paintToken) return;
        meta.rendering = true;
        try {
          const page = await pdfDoc.getPage(pageNum);
          if (token !== paintToken) return;
          const contentWidth = Math.max(320, (document.querySelector('.content')?.clientWidth || 720) - 40);
          const unscaled = page.getViewport({ scale: 1 });
          meta.aspect = unscaled.width / unscaled.height;
          const cssWidth = contentWidth * (zoomPercent / 100);
          const renderScale = (cssWidth / unscaled.width) * dpr;
          const viewport = page.getViewport({ scale: renderScale });
          const cssHeight = viewport.height / dpr;
          meta.wrap.style.width = cssWidth + 'px';
          meta.wrap.style.height = cssHeight + 'px';
          meta.wrap.innerHTML = '';
          const canvas = document.createElement('canvas');
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = cssWidth + 'px';
          canvas.style.height = cssHeight + 'px';
          meta.wrap.appendChild(canvas);
          await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
          if (token !== paintToken) return;
          const pageAspects = new Map();
          for (const [n, m] of pageMeta) pageAspects.set(n, m.aspect);
          for (const rect of highlightRects(pageAspects).filter((r) => r.page === pageNum)) {
            const hit = document.createElement('div');
            hit.className = 'hit' + (rect.precise ? '' : ' coarse') + (rect.mark.targetId === focusLinkId ? ' focus' : '');
            hit.style.left = (rect.left * cssWidth) + 'px';
            hit.style.top = (rect.top * cssHeight) + 'px';
            hit.style.width = (rect.width * cssWidth) + 'px';
            hit.style.height = (rect.height * cssHeight) + 'px';
            hit.title = rect.mark.quote || '';
            hit.onclick = () => vscodeApi.postMessage({
              type: 'openCode', path: rect.mark.path, lineStart: rect.mark.lineStart, lineEnd: rect.mark.lineEnd
            });
            meta.wrap.appendChild(hit);
            if (rect.mark.targetId === focusLinkId) meta.wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
          meta.rendered = true;
        } catch (e) {
          if (meta.wrap) meta.wrap.innerHTML = '<div class="error">第 ' + pageNum + ' 页失败</div>';
        } finally {
          meta.rendering = false;
        }
      }

      function observe() {
        if (observer) observer.disconnect();
        const scrollRoot = document.querySelector('.content');
        observer = new IntersectionObserver((entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const pageNum = Number(entry.target.dataset.page);
            if (pageNum) void renderPage(pageNum, paintToken);
          }
        }, { root: scrollRoot, rootMargin: '200% 0px' });
        for (const meta of pageMeta.values()) {
          if (meta.wrap) observer.observe(meta.wrap);
        }
      }

      async function rebuild() {
        paintToken += 1;
        const token = paintToken;
        updateZoomLabel();
        const p1 = await pdfDoc.getPage(1);
        const v1 = p1.getViewport({ scale: 1 });
        const defaultAspect = v1.width / v1.height;
        for (let n = 1; n <= pdfDoc.numPages; n++) {
          const prev = pageMeta.get(n) || {};
          pageMeta.set(n, { ...prev, aspect: prev.aspect || defaultAspect, rendered: false });
        }
        layoutPlaceholders(defaultAspect);
        observe();
        for (let n = 1; n <= Math.min(2, pdfDoc.numPages); n++) {
          void renderPage(n, token);
        }
      }

      try {
        err.hidden = true;
        rootEl.innerHTML = '<div style="padding:12px;opacity:.75">正在加载 PDF…</div>';
        pdfDoc = await pdfjsLib.getDocument({
          url: pdfUrl, cMapUrl: '${cMapUrl}', cMapPacked: true, standardFontDataUrl: '${stdFont}',
        }).promise;
        await rebuild();
        document.getElementById('pdfZoomIn').onclick = async () => {
          zoomPercent = Math.min(250, zoomPercent + 25);
          await rebuild();
        };
        document.getElementById('pdfZoomOut').onclick = async () => {
          zoomPercent = Math.max(75, zoomPercent - 25);
          await rebuild();
        };
        document.getElementById('pdfZoomFit').onclick = async () => {
          zoomPercent = 100;
          await rebuild();
        };
      } catch (e) {
        err.hidden = false;
        err.textContent = 'PDF 渲染失败: ' + (e && e.message ? e.message : String(e));
      }
    }
    // PDF loads lazily when the PDF tab is opened (showPdf -> ensurePdf).
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
