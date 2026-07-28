import * as vscode from 'vscode'
import { CoreRunner } from './coreRunner'
import { publicSettingsView, SecretStore } from './secrets'
import { zh } from './zh'

export class SidebarWebviewProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'tracelab.sidebar'
  private view?: vscode.WebviewView
  private taskMessage = ''
  private analysisLog: string[] = []

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly runner: CoreRunner,
    private readonly secrets: SecretStore,
    private readonly onAction: (command: string) => void,
  ) {}

  setTaskMessage(message: string): void {
    this.taskMessage = message
    if (message.trim()) {
      this.analysisLog.push(message)
      if (this.analysisLog.length > 200) {
        this.analysisLog = this.analysisLog.slice(-200)
      }
    }
    void this.postState()
  }

  clearAnalysisLog(): void {
    this.analysisLog = []
    void this.postState()
  }

  refresh(): void {
    void this.postState()
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this.view = webviewView
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    }
    webviewView.webview.html = this.renderShell()
    webviewView.webview.onDidReceiveMessage(async (message) => {
      if (message.type === 'action') {
        this.onAction(String(message.command))
        return
      }
      if (message.type === 'saveSettings') {
        await this.saveSettings(message.payload ?? {})
        await this.postState(zh.settingsSaved)
        return
      }
      if (message.type === 'clearSecret') {
        if (message.target === 'llm') {
          await this.secrets.clearLlmApiKey()
        } else if (message.target === 'mineru') {
          await this.secrets.clearMineruToken()
        }
        await this.postState(zh.keyCleared)
        return
      }
      if (message.type === 'probe') {
        const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
        if (!folder) {
          await this.postState(zh.openFolderFirst)
          return
        }
        const target = message.target === 'mineru' ? 'mineru' : 'llm'
        this.setTaskMessage(`测试 ${target} 连通性…`)
        const result = await this.runner.probe(folder, target)
        const detail = result.ok
          ? `成功 ${String(result.detail ?? '')} (${String(result.latency_ms ?? '?')}ms)`
          : `失败 ${String(result.detail ?? result.error ?? 'unknown')}`
        this.setTaskMessage(detail)
        await this.postState(detail)
        if (!result.ok) {
          vscode.window.showErrorMessage(`TraceLab ${target} 连通性测试失败: ${detail}`)
        } else {
          vscode.window.showInformationMessage(`TraceLab ${target}: ${detail}`)
        }
      }
    })
    void this.postState()
  }

  private async saveSettings(payload: Record<string, unknown>): Promise<void> {
    const cfg = vscode.workspace.getConfiguration('tracelab')
    const mineru = (payload.mineru ?? {}) as Record<string, unknown>
    const llm = (payload.llm ?? {}) as Record<string, unknown>
    const target = vscode.ConfigurationTarget.Global
    await cfg.update('mineru.provider', String(mineru.provider ?? 'official'), target)
    await cfg.update('mineru.baseUrl', String(mineru.base_url ?? ''), target)
    await cfg.update('mineru.model', String(mineru.model ?? 'vlm'), target)
    await cfg.update('mineru.language', String(mineru.language ?? 'en'), target)
    await cfg.update(
      'mineru.requestTimeoutSeconds',
      Number(mineru.request_timeout_seconds ?? 120),
      target,
    )
    await cfg.update(
      'mineru.taskTimeoutSeconds',
      Number(mineru.task_timeout_seconds ?? 1800),
      target,
    )
    await cfg.update('llm.baseUrl', String(llm.base_url ?? ''), target)
    await cfg.update('llm.model', String(llm.model ?? 'deepseek-chat'), target)
    await cfg.update('llm.thinkingMode', String(llm.thinking_mode ?? ''), target)
    await cfg.update('llm.timeoutSeconds', Number(llm.timeout_seconds ?? 120), target)
    // Empty / placeholder never deletes secrets — only non-empty new values update.
    if (typeof mineru.api_token === 'string') {
      await this.secrets.setMineruToken(mineru.api_token)
    }
    if (typeof llm.api_key === 'string') {
      await this.secrets.setLlmApiKey(llm.api_key)
    }
  }

  private async postState(flash?: string): Promise<void> {
    if (!this.view) {
      return
    }
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    const status = folder ? await this.runner.status(folder) : { ok: false, error: 'no workspace' }
    const settings = await publicSettingsView(this.secrets)
    await this.view.webview.postMessage({
      type: 'state',
      status,
      settings,
      taskMessage: this.taskMessage,
      analysisLog: this.analysisLog,
      workspace: folder ?? '',
      flash,
    })
  }

  private renderShell(): string {
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';" />
  <style>
    :root { color-scheme: light dark; font-family: var(--vscode-font-family); font-size: 12px; }
    body { margin: 0; padding: 10px; color: var(--vscode-foreground); }
    h2 { font-size: 12px; margin: 14px 0 8px; text-transform: none; opacity: .85; }
    .card { border: 1px solid var(--vscode-widget-border); border-radius: 6px; padding: 8px; margin-bottom: 10px; }
    .row { display: grid; gap: 4px; margin-bottom: 8px; }
    label { opacity: .8; }
    input, select, textarea {
      width: 100%; box-sizing: border-box; background: var(--vscode-input-background);
      color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border);
      padding: 4px 6px; border-radius: 4px;
    }
    button {
      background: var(--vscode-button-background); color: var(--vscode-button-foreground);
      border: 0; border-radius: 4px; padding: 5px 8px; cursor: pointer; margin: 2px 4px 2px 0;
    }
    button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
    .status { line-height: 1.55; }
    .task { min-height: 1.4em; color: var(--vscode-descriptionForeground); white-space: pre-wrap; }
    .log {
      max-height: 180px; overflow: auto; white-space: pre-wrap; font-family: var(--vscode-editor-font-family);
      font-size: 11px; line-height: 1.4; color: var(--vscode-descriptionForeground);
    }
    .ok { color: #3ba55d; } .bad { color: #f04747; }
    .actions { display: flex; flex-wrap: wrap; gap: 4px; }
    .path { word-break: break-all; opacity: .85; }
  </style>
</head>
<body>
  <div class="card status" id="status">加载中…</div>
  <div class="card task" id="task"></div>
  <h2>${zh.analysisLog}</h2>
  <div class="card log" id="log"></div>
  <h2>${zh.workflow}</h2>
  <div class="actions">
    <button data-cmd="tracelab.init">${zh.init}</button>
    <button data-cmd="tracelab.importPdf">${zh.importPdf}</button>
    <button data-cmd="tracelab.parsePaper">${zh.parsePaper}</button>
    <button data-cmd="tracelab.analyzeCode">${zh.analyzeCode}</button>
    <button data-cmd="tracelab.generateTrace">${zh.generateTrace}</button>
    <button class="secondary" data-cmd="tracelab.openPaper">${zh.openPaper}</button>
    <button class="secondary" data-cmd="tracelab.openMatrix">${zh.openMatrix}</button>
    <button class="secondary" data-cmd="tracelab.openTensor">${zh.openTensor}</button>
  </div>

  <h2>${zh.llmSection}</h2>
  <div class="card" id="llm">
    <div class="row"><label>${zh.baseUrl}</label><input id="llm.base_url" /></div>
    <div class="row"><label>${zh.model}</label><input id="llm.model" placeholder="deepseek-chat" /></div>
    <div class="row"><label>${zh.thinkingMode}</label>
      <select id="llm.thinking_mode">
        <option value="">默认</option>
        <option value="enabled">启用</option>
        <option value="disabled">关闭</option>
      </select>
    </div>
    <div class="row"><label>${zh.timeout}</label><input id="llm.timeout_seconds" type="number" min="1" max="600" /></div>
    <div class="row"><label>${zh.apiKey} <span id="llm.keyStatus"></span></label><input id="llm.api_key" type="password" /></div>
    <button id="saveLlm">${zh.saveLlm}</button>
    <button class="secondary" id="clearLlm">${zh.clearLlmKey}</button>
    <button class="secondary" id="probeLlm">${zh.probeLlm}</button>
  </div>

  <h2>${zh.mineruSection}</h2>
  <div class="card" id="mineru">
    <div class="row"><label>${zh.provider}</label>
      <select id="mineru.provider"><option value="official">官方 API</option><option value="local">本地服务</option></select>
    </div>
    <div class="row"><label>${zh.baseUrl}</label><input id="mineru.base_url" /></div>
    <div class="row"><label>${zh.model}（官方）</label>
      <select id="mineru.model"><option value="vlm">vlm</option><option value="pipeline">pipeline</option></select>
    </div>
    <div class="row"><label>${zh.language}</label><input id="mineru.language" /></div>
    <div class="row"><label>${zh.requestTimeout}</label><input id="mineru.request_timeout_seconds" type="number" /></div>
    <div class="row"><label>${zh.taskTimeout}</label><input id="mineru.task_timeout_seconds" type="number" /></div>
    <div class="row"><label>${zh.apiToken} <span id="mineru.tokenStatus"></span></label><input id="mineru.api_token" type="password" /></div>
    <button id="saveMineru">${zh.saveMineru}</button>
    <button class="secondary" id="clearMineru">${zh.clearMineruToken}</button>
    <button class="secondary" id="probeMineru">${zh.probeMineru}</button>
  </div>

  <script>
    const vscode = acquireVsCodeApi();
    function val(id) { return document.getElementById(id).value; }
    function set(id, v) { const el = document.getElementById(id); if (el) el.value = v ?? ''; }
    document.querySelectorAll('[data-cmd]').forEach((btn) => {
      btn.addEventListener('click', () => vscode.postMessage({ type: 'action', command: btn.dataset.cmd }));
    });
    function collectPayload() {
      return {
        llm: {
          base_url: val('llm.base_url'),
          model: val('llm.model'),
          thinking_mode: val('llm.thinking_mode'),
          timeout_seconds: Number(val('llm.timeout_seconds') || 120),
          api_key: val('llm.api_key'),
        },
        mineru: {
          provider: val('mineru.provider'),
          base_url: val('mineru.base_url'),
          model: val('mineru.model'),
          language: val('mineru.language'),
          request_timeout_seconds: Number(val('mineru.request_timeout_seconds') || 120),
          task_timeout_seconds: Number(val('mineru.task_timeout_seconds') || 1800),
          api_token: val('mineru.api_token'),
        }
      };
    }
    document.getElementById('saveLlm').onclick = () => vscode.postMessage({ type: 'saveSettings', payload: collectPayload() });
    document.getElementById('saveMineru').onclick = () => vscode.postMessage({ type: 'saveSettings', payload: collectPayload() });
    document.getElementById('clearLlm').onclick = () => vscode.postMessage({ type: 'clearSecret', target: 'llm' });
    document.getElementById('clearMineru').onclick = () => vscode.postMessage({ type: 'clearSecret', target: 'mineru' });
    document.getElementById('probeLlm').onclick = () => vscode.postMessage({ type: 'probe', target: 'llm' });
    document.getElementById('probeMineru').onclick = () => vscode.postMessage({ type: 'probe', target: 'mineru' });

    window.addEventListener('message', (event) => {
      const msg = event.data;
      if (msg.type !== 'state') return;
      const s = msg.status || {};
      const settings = msg.settings || {};
      const root = msg.workspace ? (msg.workspace + '/.tracelab') : '';
      document.getElementById('status').innerHTML =
        s.ok === false
          ? ('<div class="bad">状态查询失败：' + String(s.error || 'unknown') + '</div>' +
             '<div class="hint">产物目录：<span class="path">' + (root || '—') + '</span></div>')
          : (
        '<div>密钥跨工作区持久保存在 VS Code SecretStorage</div>' +
        '<div>${zh.artifactsRoot}：<span class="path">' + (root || '—') + '</span></div>' +
        '<div>论文：' + (s.paper_ready ? '<span class="ok">${zh.paperReady}</span>' : '<span class="bad">${zh.paperMissing}</span>') + '</div>' +
        '<div>代码：' + (s.analysis_ready ? '<span class="ok">${zh.codeReady}</span>' : '<span class="bad">${zh.codeMissing}</span>') + '</div>' +
        '<div>追溯：' + (s.links_total ?? 0) + ' 条 / ' + (s.links_proposed ?? 0) + ' 待审' +
          (s.links_accepted != null ? ' / ' + s.links_accepted + ' 已接受' : '') + '</div>' +
        '<div>张量节点：' + (s.tensor_nodes ?? 0) + '</div>' +
        '<div>PDF：' + (s.has_pdf ? '<span class="ok">${zh.pdfImported}</span>' : '<span class="bad">${zh.pdfNone}</span>') + '</div>'
      );
      document.getElementById('task').textContent = msg.taskMessage || msg.flash || '';
      const log = Array.isArray(msg.analysisLog) ? msg.analysisLog : [];
      document.getElementById('log').textContent = log.length ? log.join('\\n') : '（暂无）';
      const logEl = document.getElementById('log');
      logEl.scrollTop = logEl.scrollHeight;
      const llm = settings.llm || {};
      const mineru = settings.mineru || {};
      set('llm.base_url', llm.base_url);
      set('llm.model', llm.model);
      set('llm.thinking_mode', llm.thinking_mode || '');
      set('llm.timeout_seconds', llm.timeout_seconds ?? 120);
      set('llm.api_key', '');
      document.getElementById('llm.api_key').placeholder = llm.has_key ? '${zh.keyConfigured}' : '${zh.keyMissing}';
      document.getElementById('llm.keyStatus').innerHTML = llm.has_key
        ? '<span class="ok">已配置</span>' : '<span class="bad">未配置</span>';
      set('mineru.provider', mineru.provider || 'official');
      set('mineru.base_url', mineru.base_url);
      set('mineru.model', mineru.model || 'vlm');
      set('mineru.language', mineru.language || 'en');
      set('mineru.request_timeout_seconds', mineru.request_timeout_seconds ?? 120);
      set('mineru.task_timeout_seconds', mineru.task_timeout_seconds ?? 1800);
      set('mineru.api_token', '');
      document.getElementById('mineru.api_token').placeholder = mineru.has_token ? '${zh.tokenConfigured}' : '${zh.tokenMissing}';
      document.getElementById('mineru.tokenStatus').innerHTML = mineru.has_token
        ? '<span class="ok">已配置</span>' : '<span class="bad">未配置</span>';
    });
  </script>
</body>
</html>`
  }
}
