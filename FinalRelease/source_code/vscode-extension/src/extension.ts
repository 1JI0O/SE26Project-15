import * as vscode from 'vscode'
import { CliResult, CoreRunner, ProgressEvent } from './coreRunner'
import { SecretStore } from './secrets'
import { SidebarWebviewProvider } from './sidebarWebview'
import { MatrixPanelProvider } from './webviews/matrixPanel'
import { PdfPanelProvider } from './webviews/pdfPanel'
import { TensorPanelProvider } from './webviews/tensorPanel'
import { readWorkspaceStatus } from './workspaceStatus'
import { zh } from './zh'

let sidebar: SidebarWebviewProvider
let matrix: MatrixPanelProvider
let tensor: TensorPanelProvider
let pdf: PdfPanelProvider
let runner: CoreRunner
let refreshTimer: NodeJS.Timeout | undefined

const TASK_LABELS: Record<string, string> = {
  init: zh.init,
  parse: zh.parsePaper,
  analyze: zh.analyzeCode,
  trace: zh.generateTrace,
}

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel('TraceLab')
  const secrets = new SecretStore(context.secrets)
  runner = new CoreRunner(secrets, context.extensionPath, output)
  pdf = new PdfPanelProvider(context.extensionUri, runner)
  matrix = new MatrixPanelProvider(context.extensionUri, runner, (linkId) => {
    pdf.locateLink(linkId, context)
  })
  tensor = new TensorPanelProvider(context.extensionUri, runner)
  sidebar = new SidebarWebviewProvider(context.extensionUri, runner, secrets, (command) => {
    void vscode.commands.executeCommand(command)
  })

  runner.onProgress = reportProgress

  context.subscriptions.push(
    output,
    vscode.window.registerWebviewViewProvider(SidebarWebviewProvider.viewType, sidebar),
    vscode.window.registerWebviewViewProvider(MatrixPanelProvider.viewType, matrix),
    vscode.window.registerWebviewViewProvider(TensorPanelProvider.viewType, tensor),
    vscode.commands.registerCommand('tracelab.refresh', () => refreshAll()),
    vscode.commands.registerCommand('tracelab.init', () => runTask('init')),
    vscode.commands.registerCommand('tracelab.importPdf', () => importPdf()),
    vscode.commands.registerCommand('tracelab.parsePaper', () => runTask('parse')),
    vscode.commands.registerCommand('tracelab.analyzeCode', () => runTask('analyze')),
    vscode.commands.registerCommand('tracelab.generateTrace', () => runTask('trace')),
    vscode.commands.registerCommand('tracelab.openPaper', () => pdf.open(context)),
    vscode.commands.registerCommand('tracelab.openMatrix', () => matrix.open()),
    vscode.commands.registerCommand('tracelab.openTensor', () => tensor.open()),
    vscode.commands.registerCommand('tracelab.configureMineru', () =>
      vscode.commands.executeCommand('workbench.view.extension.tracelab'),
    ),
    vscode.commands.registerCommand('tracelab.configureLlm', () =>
      vscode.commands.executeCommand('workbench.view.extension.tracelab'),
    ),
    vscode.commands.registerCommand('tracelab.showOutput', () => output.show(true)),
    vscode.commands.registerCommand('tracelab.openPanel', () =>
      vscode.commands.executeCommand('workbench.view.extension.tracelab-panel'),
    ),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      void loadWorkspaceArtifacts(context)
    }),
  )

  // Artifacts can also change outside the extension (CLI run, git checkout).
  const watcher = vscode.workspace.createFileSystemWatcher('**/.tracelab/**')
  const onArtifactChange = () => {
    sidebar?.refresh()
    scheduleRefresh()
  }
  watcher.onDidChange(onArtifactChange)
  watcher.onDidCreate(onArtifactChange)
  watcher.onDidDelete(onArtifactChange)
  context.subscriptions.push(watcher)

  void loadWorkspaceArtifacts(context)
}

/** Reload structured artifacts under `.tracelab/` for the active workspace. */
async function loadWorkspaceArtifacts(_context: vscode.ExtensionContext): Promise<void> {
  const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
  refreshAll()
  if (!folder) {
    sidebar?.setTaskMessage(zh.openFolderFirst)
    return
  }
  const status = readWorkspaceStatus(folder)
  const parts: string[] = []
  if (status.has_pdf) {
    parts.push('PDF')
  }
  if (status.paper_ready) {
    parts.push('论文已解析')
  }
  if (status.analysis_ready) {
    parts.push(`代码分析（${String(status.tensor_nodes ?? 0)} 张量节点）`)
  }
  if (Number(status.links_total ?? 0) > 0) {
    parts.push(`${String(status.links_total)} 条追溯`)
  }
  if (parts.length === 0) {
    sidebar?.setTaskMessage('尚无 .tracelab 产物 — 请初始化 / 导入 / 解析 / 分析 / 生成追溯')
    return
  }
  sidebar?.setTaskMessage(`已从 .tracelab 加载：${parts.join(' · ')}`)
}

/**
 * Progress → sidebar task line + matrix Agent log (desktop-aligned copy).
 *
 * Only `analysis.published` batches refresh the matrix, and the refresh is
 * coalesced: a long Agent run emits progress continuously, and refreshing every
 * view on each event used to keep the extension host busy — which also delays the
 * webview resource requests that load the PDF.
 */
function reportProgress(event: ProgressEvent, progress?: vscode.Progress<{ message?: string }>): void {
  const suffix =
    event.total != null && event.current != null ? ` (${event.current}/${event.total})` : ''
  const message = `${event.message}${suffix}`
  const step = typeof event.step === 'number' ? event.step : undefined
  progress?.report({ message })
  sidebar?.setTaskMessage(message, { step })
  matrix?.setAgentState({ running: true, activity: message })
  if (event.event_kind === 'analysis.tool.started' || event.event_kind === 'analysis.published') {
    matrix?.appendAgentLog(message, step)
  }
  if (event.event_kind === 'analysis.published' || event.phase === 'publish') {
    scheduleRefresh()
  }
}

/** Coalesce bursty refreshes (progressive publish) into one pass. */
function scheduleRefresh(): void {
  if (refreshTimer) return
  refreshTimer = setTimeout(() => {
    refreshTimer = undefined
    matrix?.refresh()
    pdf?.refresh()
  }, 400)
}

function refreshAll(): void {
  sidebar?.refresh()
  matrix?.refresh()
  tensor?.invalidate()
  pdf?.refresh()
}

async function runTask(command: 'init' | 'parse' | 'analyze' | 'trace'): Promise<void> {
  const folder = workspaceRoot()
  if (!folder) {
    return
  }

  let replaceTraces = false
  if (command === 'trace') {
    const choice = await promptTraceReplace(folder)
    if (choice === 'cancel') {
      return
    }
    replaceTraces = choice === 'replace'
  }

  let result: CliResult = { ok: false, error: '未开始' }
  const label = TASK_LABELS[command] ?? command
  if (command === 'trace') {
    sidebar.clearAnalysisLog()
    matrix.clearAgentLog()
  }
  sidebar.setBusy(true)
  sidebar.setTaskMessage(`正在${label}…`)
  if (command === 'trace') {
    matrix.setAgentState({ running: true, activity: '启动中…' })
  }
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `TraceLab · ${label}`,
      cancellable: false,
    },
    async (progress) => {
      runner.onProgress = (event) => reportProgress(event, progress)
      if (command === 'init') {
        result = await runner.init(folder)
      } else if (command === 'parse') {
        result = await runner.parse(folder)
      } else if (command === 'analyze') {
        result = await runner.analyze(folder)
      } else {
        result = await runner.trace(folder, { replace: replaceTraces })
      }
    },
  )

  runner.onProgress = reportProgress
  sidebar.setBusy(false)
  matrix.setAgentState({ running: false, activity: '' })
  refreshAll()

  if (!result.ok) {
    const detail = result.error ?? '未知错误'
    sidebar.setTaskMessage(`失败：${detail}`)
    vscode.window
      .showErrorMessage(`TraceLab ${label}失败：${detail}`, '显示输出')
      .then((choice) => {
        if (choice === '显示输出') {
          runner.output.show(true)
        }
      })
    return
  }

  if (result.mineru_error) {
    vscode.window.showWarningMessage(`论文解析使用了回退：${String(result.mineru_error)}`)
  }

  const summary = successSummary(command, result)
  sidebar.setTaskMessage(summary)
  vscode.window.showInformationMessage(summary)
}

/** Ask whether to clear existing traces before regenerating. */
async function promptTraceReplace(folder: string): Promise<'replace' | 'append' | 'cancel'> {
  const status = await runner.status(folder)
  const total = Number(status.links_total ?? 0)
  if (!status.ok || total <= 0) {
    return 'append'
  }
  const picked = await vscode.window.showQuickPick(
    [
      {
        label: '清空后重跑',
        description: `删除现有 ${total} 条追溯，再运行 Agent`,
        id: 'replace' as const,
      },
      {
        label: '保留并追加',
        description: '在现有结果上继续追加（可能重复、难读）',
        id: 'append' as const,
      },
      { label: '取消', description: '不启动追溯', id: 'cancel' as const },
    ],
    {
      title: '生成追溯',
      placeHolder: `当前已有 ${total} 条追溯，请选择`,
      ignoreFocusOut: true,
    },
  )
  return picked?.id ?? 'cancel'
}

function successSummary(command: string, result: CliResult): string {
  if (command === 'trace') {
    return `Agent 追溯完成：新增 ${String(result.created ?? 0)}，总计 ${String(result.total ?? 0)}，步骤 ${String(result.steps ?? '?')}，来源=${String(result.source ?? 'agent')}`
  }
  if (command === 'analyze') {
    const summary = (result.summary as Record<string, unknown> | undefined) ?? {}
    return `分析完成：python=${String(summary.python_file_count ?? '?')}，符号=${String(summary.symbol_count ?? '?')}，张量节点=${String(summary.tensor_node_count ?? '?')}`
  }
  if (command === 'parse') {
    return `解析完成：parser=${String(result.parser ?? 'unknown')}`
  }
  return `TraceLab ${TASK_LABELS[command] ?? command} 已完成`
}

async function importPdf(): Promise<void> {
  const folder = workspaceRoot()
  if (!folder) {
    return
  }
  const picked = await vscode.window.showOpenDialog({
    canSelectMany: false,
    filters: { PDF: ['pdf'] },
  })
  if (!picked?.[0]) {
    return
  }
  sidebar.setTaskMessage('正在导入论文 PDF…')
  const result = await runner.importPdf(folder, picked[0].fsPath)
  refreshAll()
  if (!result.ok) {
    vscode.window.showErrorMessage(`导入 PDF 失败：${result.error ?? '未知错误'}`)
    return
  }
  sidebar.setTaskMessage('论文 PDF 已导入')
  vscode.window.showInformationMessage('论文 PDF 已导入')
}

function workspaceRoot(): string | undefined {
  const folder = vscode.workspace.workspaceFolders?.[0]
  if (!folder) {
    vscode.window.showErrorMessage(zh.openFolderFirst)
    return undefined
  }
  return folder.uri.fsPath
}

export function deactivate(): void {}
