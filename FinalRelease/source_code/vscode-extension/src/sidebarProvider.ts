import * as vscode from 'vscode'
import { CoreRunner } from './coreRunner'

export class SidebarProvider implements vscode.TreeDataProvider<SidebarItem> {
  private readonly emitter = new vscode.EventEmitter<void>()
  readonly onDidChangeTreeData = this.emitter.event

  constructor(private readonly runner: CoreRunner) {}

  refresh(): void {
    this.emitter.fire()
  }

  getTreeItem(element: SidebarItem): vscode.TreeItem {
    return element
  }

  async getChildren(element?: SidebarItem): Promise<SidebarItem[]> {
    if (element) {
      return []
    }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    if (!root) {
      return [new SidebarItem('请先打开工作区文件夹', vscode.TreeItemCollapsibleState.None)]
    }
    const status = await this.runner.status(root)
    return [
      new SidebarItem(
        status.paper_ready ? '论文：已解析' : '论文：未解析',
        vscode.TreeItemCollapsibleState.None,
      ),
      new SidebarItem(
        status.analysis_ready ? '代码：已分析' : '代码：未分析',
        vscode.TreeItemCollapsibleState.None,
      ),
      new SidebarItem(
        `追溯：${String(status.links_total ?? 0)}（待审 ${String(status.links_proposed ?? 0)}）`,
        vscode.TreeItemCollapsibleState.None,
      ),
      new SidebarItem('— 操作 —', vscode.TreeItemCollapsibleState.None),
      commandItem('初始化 .tracelab', 'tracelab.init'),
      commandItem('导入论文', 'tracelab.importPdf'),
      commandItem('解析论文', 'tracelab.parsePaper'),
      commandItem('分析代码', 'tracelab.analyzeCode'),
      commandItem('生成追溯', 'tracelab.generateTrace'),
      commandItem('打开论文', 'tracelab.openPaper'),
      commandItem('打开追溯矩阵', 'tracelab.openMatrix'),
      commandItem('打开张量流图', 'tracelab.openTensor'),
      commandItem('配置 MinerU', 'tracelab.configureMineru'),
      commandItem('配置 LLM', 'tracelab.configureLlm'),
    ]
  }
}

class SidebarItem extends vscode.TreeItem {
  constructor(label: string, collapsibleState: vscode.TreeItemCollapsibleState) {
    super(label, collapsibleState)
  }
}

function commandItem(label: string, command: string): SidebarItem {
  const item = new SidebarItem(label, vscode.TreeItemCollapsibleState.None)
  item.command = { command, title: label }
  return item
}
