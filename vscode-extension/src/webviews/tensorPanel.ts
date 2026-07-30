import * as vscode from 'vscode'
import { CoreRunner } from '../coreRunner'
import { openWorkspaceCode } from '../openCode'
import { zh } from '../zh'
import { escapeHtml, shellAssets } from './shell'

interface TensorNode {
  id: string
  label?: string
  op?: string
  source_path?: string
  line_start?: number
  line_end?: number
  x?: number
  y?: number
  width?: number
  height?: number
  expandable?: boolean
  component_symbol_id?: string
}

interface TensorEdge {
  id?: string
  source: string
  target: string
  points?: number[][]
}

interface TensorGraph {
  nodes?: TensorNode[]
  edges?: TensorEdge[]
  available_roots?: Array<{ symbol_id: string; label: string }>
  selected_root?: string
  default_root?: string
  root_symbol?: string
  view?: string
}

export class TensorPanelProvider {
  static readonly viewType = 'tracelab.tensor'
  private panel?: vscode.WebviewPanel
  private view?: vscode.WebviewView
  private currentView: 'architecture' | 'debug' = 'architecture'
  private currentRoot = ''
  private navStack: string[] = []
  private dirty = true

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly runner: CoreRunner,
  ) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this.view = webviewView
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
    }
    webviewView.onDidDispose(() => {
      this.view = undefined
    })
    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible && this.dirty) void this.refresh()
    })
    this.bind(webviewView.webview)
    void this.refresh()
  }

  open(): void {
    void vscode.commands.executeCommand(`${TensorPanelProvider.viewType}.focus`)
    this.view?.show?.(true)
    void this.refresh()
  }

  private bind(webview: vscode.Webview): void {
    webview.onDidReceiveMessage(async (message) => {
      if (message.type === 'openCode') {
        await openWorkspaceCode(message.path, message.lineStart, message.lineEnd)
      }
      if (message.type === 'setView') {
        this.currentView = message.view === 'debug' ? 'debug' : 'architecture'
        this.navStack = []
        void this.refresh()
      }
      if (message.type === 'setRoot') {
        this.currentRoot = String(message.root || '')
        this.navStack = []
        void this.refresh()
      }
      if (message.type === 'expand') {
        const next = String(message.root || '')
        if (next) {
          if (this.currentRoot) {
            this.navStack.push(this.currentRoot)
          }
          this.currentRoot = next
          void this.refresh()
        }
      }
      if (message.type === 'back') {
        this.currentRoot = this.navStack.pop() || ''
        void this.refresh()
      }
    })
  }

  /** Mark stale; the graph is only recomputed while the view is actually shown. */
  invalidate(): void {
    this.dirty = true
    if (this.view?.visible || this.panel?.visible) {
      void this.refresh()
    }
  }

  async refresh(): Promise<void> {
    const target = this.panel?.webview ?? this.view?.webview
    if (!target) return
    if (this.view && !this.view.visible && !this.panel) {
      this.dirty = true
      return
    }
    this.dirty = false
    target.html = await this.buildHtml(target)
  }

  private async buildHtml(webview: vscode.Webview): Promise<string> {
    const assets = shellAssets(webview, this.extensionUri)
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!root) {
      return emptyHtml(zh.openFolderFirst, assets.media, assets.csp)
    }
    const result = await this.runner.tensorFlow(root, {
      view: this.currentView,
      root: this.currentRoot || undefined,
    })
    if (!result.ok) {
      return emptyHtml(String(result.error ?? zh.runAnalyzeFirst), assets.media, assets.csp)
    }
    const graph = (result.graph as TensorGraph) || {}
    const nodes = graph.nodes ?? []
    const edges = graph.edges ?? []
    const roots = graph.available_roots ?? []
    const selected =
      this.currentRoot || graph.selected_root || graph.root_symbol || graph.default_root || ''

    if (!nodes.length) {
      return emptyHtml(zh.tensorEmpty, assets.media, assets.csp)
    }

    const maxX = Math.max(...nodes.map((n) => (n.x ?? 0) + (n.width ?? 180)), 640)
    const maxY = Math.max(...nodes.map((n) => (n.y ?? 0) + (n.height ?? 72)), 400)
    const rootOptions = roots
      .map(
        (item) =>
          `<option value="${escapeHtml(item.symbol_id)}"${item.symbol_id === selected ? ' selected' : ''}>${escapeHtml(item.label || item.symbol_id)}</option>`,
      )
      .join('')

    const nodeSvg = nodes
      .map((node) => {
        const x = node.x ?? 0
        const y = node.y ?? 0
        const w = node.width ?? 180
        const h = node.height ?? 72
        const title = escapeHtml([node.label, node.op, node.expandable ? '可展开' : ''].filter(Boolean).join(' · '))
        return `<g class="node" data-path="${escapeHtml(node.source_path || '')}" data-line="${node.line_start || 1}"
          data-line-end="${node.line_end || node.line_start || 1}"
          data-expandable="${node.expandable ? '1' : '0'}" data-component="${escapeHtml(node.component_symbol_id || '')}">
          <title>${title}</title>
          <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" />
          <text x="${x + 10}" y="${y + 26}">${escapeHtml((node.label || node.id).slice(0, 24))}</text>
          <text class="sub" x="${x + 10}" y="${y + 46}">${escapeHtml((node.op || '').slice(0, 20))}${node.expandable ? '  +' : ''}</text>
        </g>`
      })
      .join('')

    const edgeSvg = edges
      .map((edge) => {
        const source = nodes.find((n) => n.id === edge.source)
        const target = nodes.find((n) => n.id === edge.target)
        if (!source || !target) {
          return ''
        }
        const points =
          edge.points && edge.points.length >= 2
            ? edge.points
            : [
                [(source.x ?? 0) + (source.width ?? 180), (source.y ?? 0) + (source.height ?? 72) / 2],
                [target.x ?? 0, (target.y ?? 0) + (target.height ?? 72) / 2],
              ]
        const d = points
          .map((point, index) => `${index === 0 ? 'M' : 'L'}${point[0]},${point[1]}`)
          .join(' ')
        return `<path class="edge" d="${d}" />`
      })
      .join('')

    const viewLabel = this.currentView === 'debug' ? zh.debug : zh.architecture
    const { media, nonce, csp } = assets
    return `<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<link rel="stylesheet" href="${media('ui.css')}" />
<style>
  .stage { position: relative; min-height: 0; overflow: hidden; }
  svg { width: 100%; height: 100%; cursor: grab; }
  svg.dragging { cursor: grabbing; }
  .edge { fill: none; stroke: var(--tl-fg-muted); stroke-width: 1.4; opacity: .75; }
  .node rect {
    fill: var(--tl-surface-raised);
    stroke: var(--tl-accent);
    stroke-width: 1.2;
    cursor: pointer;
  }
  .node:hover rect { fill: var(--vscode-list-hoverBackground, var(--tl-surface-raised)); stroke-width: 1.8; }
  .node text { fill: var(--tl-fg); font-size: 11px; pointer-events: none; }
  .node .sub { fill: var(--tl-fg-muted); font-size: 10px; }
</style></head>
<body class="tl-shell">
  <header class="tl-bar">
    <select id="root" title="${escapeHtml(zh.selectRoot)}">${rootOptions || `<option value="">${escapeHtml(selected || '无')}</option>`}</select>
    <span class="tl-bar-group">
      <button id="arch" class="${this.currentView === 'architecture' ? 'active' : ''}">${zh.architecture}</button>
      <button id="debug" class="${this.currentView === 'debug' ? 'active' : ''}">${zh.debug}</button>
    </span>
    <button class="tl-ghost" id="back" ${this.navStack.length ? '' : 'disabled'}>${zh.back}</button>
    <span class="tl-bar-group">
      <button id="zoomOut" title="${escapeHtml(zh.zoomOut)}">−</button>
      <button id="fit" title="${escapeHtml(zh.fit)}">适应</button>
      <button id="zoomIn" title="${escapeHtml(zh.zoomIn)}">+</button>
    </span>
    <span class="tl-bar-spacer"></span>
    <span class="tl-chip tl-chip-accent">${nodes.length} 节点</span>
    <span class="tl-chip">${viewLabel}</span>
    <span class="tl-muted">${zh.tensorHint}</span>
  </header>
  <div class="stage">
    <svg id="canvas" viewBox="0 0 ${maxX + 40} ${maxY + 40}">
      ${edgeSvg}
      ${nodeSvg}
    </svg>
  </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const svg = document.getElementById('canvas');
    let vb = { x: 0, y: 0, w: ${maxX + 40}, h: ${maxY + 40} };
    function apply() { svg.setAttribute('viewBox', vb.x + ' ' + vb.y + ' ' + vb.w + ' ' + vb.h); }
    apply();
    document.getElementById('root').onchange = (e) => vscode.postMessage({ type: 'setRoot', root: e.target.value });
    document.getElementById('arch').onclick = () => vscode.postMessage({ type: 'setView', view: 'architecture' });
    document.getElementById('debug').onclick = () => vscode.postMessage({ type: 'setView', view: 'debug' });
    document.getElementById('back').onclick = () => vscode.postMessage({ type: 'back' });
    document.getElementById('zoomIn').onclick = () => { vb.w *= 0.85; vb.h *= 0.85; apply(); };
    document.getElementById('zoomOut').onclick = () => { vb.w *= 1.15; vb.h *= 1.15; apply(); };
    document.getElementById('fit').onclick = () => { vb = { x: 0, y: 0, w: ${maxX + 40}, h: ${maxY + 40} }; apply(); };
    svg.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const factor = ev.deltaY < 0 ? 0.9 : 1.1;
      const rect = svg.getBoundingClientRect();
      const mx = vb.x + ((ev.clientX - rect.left) / rect.width) * vb.w;
      const my = vb.y + ((ev.clientY - rect.top) / rect.height) * vb.h;
      vb.w *= factor; vb.h *= factor;
      vb.x = mx - ((ev.clientX - rect.left) / rect.width) * vb.w;
      vb.y = my - ((ev.clientY - rect.top) / rect.height) * vb.h;
      apply();
    }, { passive: false });
    let dragging = false, lastX = 0, lastY = 0;
    svg.addEventListener('mousedown', (ev) => {
      if (ev.target.closest('.node')) return;
      dragging = true; lastX = ev.clientX; lastY = ev.clientY; svg.classList.add('dragging');
    });
    window.addEventListener('mousemove', (ev) => {
      if (!dragging) return;
      const rect = svg.getBoundingClientRect();
      vb.x -= ((ev.clientX - lastX) / rect.width) * vb.w;
      vb.y -= ((ev.clientY - lastY) / rect.height) * vb.h;
      lastX = ev.clientX; lastY = ev.clientY; apply();
    });
    window.addEventListener('mouseup', () => { dragging = false; svg.classList.remove('dragging'); });
    document.querySelectorAll('.node').forEach((node) => {
      node.addEventListener('click', () => {
        const p = node.getAttribute('data-path');
        if (!p) return;
        vscode.postMessage({
          type: 'openCode',
          path: p,
          lineStart: Number(node.getAttribute('data-line') || 1),
          lineEnd: Number(node.getAttribute('data-line-end') || node.getAttribute('data-line') || 1),
        });
      });
      node.addEventListener('dblclick', (ev) => {
        ev.preventDefault();
        const expandable = node.getAttribute('data-expandable') === '1';
        const component = node.getAttribute('data-component');
        if (expandable && component) {
          vscode.postMessage({ type: 'expand', root: component });
        }
      });
    });
  </script>
</body></html>`
  }
}

function emptyHtml(message: string, media: (rel: string) => string, csp: string): string {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <link rel="stylesheet" href="${media('ui.css')}" />
</head>
<body>
  <div class="tl-empty"><strong>张量流图</strong><span>${escapeHtml(message)}</span></div>
</body>
</html>`
}
