import * as vscode from 'vscode'
import { CoreRunner } from './coreRunner'
import { publicSettingsView, SecretStore } from './secrets'
import { readWorkspaceStatus } from './workspaceStatus'
import { escapeHtml, shellAssets } from './webviews/shell'
import { zh } from './zh'

interface LogEntry {
  step?: number
  text: string
}

export class SidebarWebviewProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'tracelab.sidebar'
  private view?: vscode.WebviewView
  private taskMessage = ''
  private busy = false
  private analysisLog: LogEntry[] = []

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly runner: CoreRunner,
    private readonly secrets: SecretStore,
    private readonly onAction: (command: string) => void,
  ) {}

  setTaskMessage(message: string, options: { step?: number; log?: boolean } = {}): void {
    this.taskMessage = message
    if (options.log !== false && message.trim()) {
      this.analysisLog.push({ step: options.step, text: message })
      if (this.analysisLog.length > 200) {
        this.analysisLog = this.analysisLog.slice(-200)
      }
    }
    void this.postState()
  }

  setBusy(busy: boolean): void {
    this.busy = busy
    void this.postState()
  }

  clearAnalysisLog(): void {
    this.analysisLog = []
    void this.postState()
  }

  refresh(): void {
    void this.postState()
  }

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
    }
    webviewView.onDidDispose(() => {
      this.view = undefined
    })
    webviewView.webview.html = this.renderShell(webviewView.webview)
    webviewView.webview.onDidReceiveMessage(async (message) => {
      if (message?.type === 'ready') {
        await this.postState()
        return
      }
      if (message?.type === 'action') {
        this.onAction(String(message.command))
        return
      }
      if (message?.type === 'saveSettings') {
        await this.saveSettings(message.payload ?? {})
        await this.postState(zh.settingsSaved)
        return
      }
      if (message?.type === 'clearSecret') {
        if (message.target === 'llm') await this.secrets.clearLlmApiKey()
        else if (message.target === 'mineru') await this.secrets.clearMineruToken()
        await this.postState(zh.keyCleared)
        return
      }
      if (message?.type === 'probe') {
        await this.probe(message.target === 'mineru' ? 'mineru' : 'llm')
      }
    })
  }

  private async probe(target: 'llm' | 'mineru'): Promise<void> {
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!folder) {
      await this.postState(zh.openFolderFirst)
      return
    }
    this.setTaskMessage(`测试 ${target} 连通性…`)
    const result = await this.runner.probe(folder, target)
    const detail = result.ok
      ? `成功 ${String(result.detail ?? '')} (${String(result.latency_ms ?? '?')}ms)`
      : `失败 ${String(result.detail ?? result.error ?? 'unknown')}`
    this.setTaskMessage(detail)
    await this.postState(detail)
    if (result.ok) {
      vscode.window.showInformationMessage(`TraceLab ${target}: ${detail}`)
    } else {
      vscode.window.showErrorMessage(`TraceLab ${target} 连通性测试失败: ${detail}`)
    }
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

  /**
   * Post state to the webview. Status is read straight from `.tracelab/` — the
   * CLI would spawn a process, and this runs on every Agent progress event.
   */
  private async postState(flash?: string): Promise<void> {
    if (!this.view) return
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    await this.view.webview.postMessage({
      type: 'state',
      status: folder ? readWorkspaceStatus(folder) : { ok: false },
      settings: await publicSettingsView(this.secrets),
      taskMessage: this.taskMessage,
      busy: this.busy,
      analysisLog: this.analysisLog,
      workspace: folder ?? '',
      flash,
    })
  }

  private renderShell(webview: vscode.Webview): string {
    const { media, nonce, csp } = shellAssets(webview, this.extensionUri)
    const step = (index: number, label: string, command: string, primary = true) =>
      `<button class="${primary ? '' : 'tl-ghost'} tl-step" data-cmd="${command}">
         <span class="tl-step-index">${index}</span>${escapeHtml(label)}
       </button>`
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <link rel="stylesheet" href="${media('ui.css')}" />
  <link rel="stylesheet" href="${media('sidebar.css')}" />
</head>
<body>
  <section class="tl-card" id="statusCard">
    <header class="tl-card-head">
      <span>工作区</span>
      <span class="tl-chip" id="statusBadge">加载中</span>
    </header>
    <div class="tl-card-body" id="statusBody"></div>
  </section>

  <div class="tl-task" id="task" hidden></div>

  <h2 class="tl-section-title">${escapeHtml(zh.workflow)}</h2>
  <div class="tl-steps">
    ${step(1, zh.init, 'tracelab.init')}
    ${step(2, zh.importPdf, 'tracelab.importPdf')}
    ${step(3, zh.parsePaper, 'tracelab.parsePaper')}
    ${step(4, zh.analyzeCode, 'tracelab.analyzeCode')}
    ${step(5, zh.generateTrace, 'tracelab.generateTrace')}
  </div>
  <div class="tl-open-row">
    <button class="tl-ghost" data-cmd="tracelab.openPaper">${escapeHtml(zh.openPaper)}</button>
    <button class="tl-ghost" data-cmd="tracelab.openMatrix">${escapeHtml(zh.openMatrix)}</button>
    <button class="tl-ghost" data-cmd="tracelab.openTensor">${escapeHtml(zh.openTensor)}</button>
  </div>

  <h2 class="tl-section-title">${escapeHtml(zh.analysisLog)}</h2>
  <ul class="tl-log" id="log"></ul>

  <h2 class="tl-section-title">${escapeHtml(zh.llmSection)}</h2>
  <div class="tl-card">
    <div class="tl-card-body">
      <div class="tl-field"><label class="tl-label" for="llm.base_url">${escapeHtml(zh.baseUrl)}</label><input id="llm.base_url" /></div>
      <div class="tl-field"><label class="tl-label" for="llm.model">${escapeHtml(zh.model)}</label><input id="llm.model" placeholder="deepseek-chat" /></div>
      <div class="tl-field"><label class="tl-label" for="llm.thinking_mode">${escapeHtml(zh.thinkingMode)}</label>
        <select id="llm.thinking_mode">
          <option value="">默认</option>
          <option value="enabled">启用</option>
          <option value="disabled">关闭</option>
        </select>
      </div>
      <div class="tl-field"><label class="tl-label" for="llm.timeout_seconds">${escapeHtml(zh.timeout)}</label><input id="llm.timeout_seconds" type="number" min="1" max="600" /></div>
      <div class="tl-field">
        <label class="tl-label" for="llm.api_key">${escapeHtml(zh.apiKey)} <span id="llm.keyStatus"></span></label>
        <input id="llm.api_key" type="password" />
      </div>
      <div class="tl-open-row">
        <button id="saveLlm">${escapeHtml(zh.saveLlm)}</button>
        <button class="tl-ghost" id="probeLlm">${escapeHtml(zh.probeLlm)}</button>
        <button class="tl-ghost" id="clearLlm">${escapeHtml(zh.clearLlmKey)}</button>
      </div>
    </div>
  </div>

  <h2 class="tl-section-title">${escapeHtml(zh.mineruSection)}</h2>
  <div class="tl-card">
    <div class="tl-card-body">
      <div class="tl-field"><label class="tl-label" for="mineru.provider">${escapeHtml(zh.provider)}</label>
        <select id="mineru.provider"><option value="official">官方 API</option><option value="local">本地服务</option></select>
      </div>
      <div class="tl-field"><label class="tl-label" for="mineru.base_url">${escapeHtml(zh.baseUrl)}</label><input id="mineru.base_url" /></div>
      <div class="tl-field"><label class="tl-label" for="mineru.model">${escapeHtml(zh.model)}（官方）</label>
        <select id="mineru.model"><option value="vlm">vlm</option><option value="pipeline">pipeline</option></select>
      </div>
      <div class="tl-field"><label class="tl-label" for="mineru.language">${escapeHtml(zh.language)}</label><input id="mineru.language" /></div>
      <div class="tl-field"><label class="tl-label" for="mineru.request_timeout_seconds">${escapeHtml(zh.requestTimeout)}</label><input id="mineru.request_timeout_seconds" type="number" /></div>
      <div class="tl-field"><label class="tl-label" for="mineru.task_timeout_seconds">${escapeHtml(zh.taskTimeout)}</label><input id="mineru.task_timeout_seconds" type="number" /></div>
      <div class="tl-field">
        <label class="tl-label" for="mineru.api_token">${escapeHtml(zh.apiToken)} <span id="mineru.tokenStatus"></span></label>
        <input id="mineru.api_token" type="password" />
      </div>
      <div class="tl-open-row">
        <button id="saveMineru">${escapeHtml(zh.saveMineru)}</button>
        <button class="tl-ghost" id="probeMineru">${escapeHtml(zh.probeMineru)}</button>
        <button class="tl-ghost" id="clearMineru">${escapeHtml(zh.clearMineruToken)}</button>
      </div>
    </div>
  </div>

  <script nonce="${nonce}" src="${media('sidebar.js')}"></script>
</body>
</html>`
  }
}
