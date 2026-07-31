import * as path from 'node:path'
import * as vscode from 'vscode'

/** Open a workspace-relative source file and select a line range. */
export async function openWorkspaceCode(
  relPath: string,
  lineStart: number,
  lineEnd?: number,
): Promise<void> {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
  if (!root) {
    vscode.window.showErrorMessage('请先打开工作区文件夹')
    return
  }
  if (!relPath) {
    vscode.window.showErrorMessage('节点缺少源码路径，无法跳转')
    return
  }
  try {
    const uri = vscode.Uri.file(path.join(root, relPath))
    const doc = await vscode.workspace.openTextDocument(uri)
    const editor = await vscode.window.showTextDocument(doc, vscode.ViewColumn.One)
    const start = Math.max(0, (lineStart || 1) - 1)
    const end = Math.max(start, (lineEnd || lineStart || 1) - 1)
    const range = new vscode.Range(start, 0, end, 999)
    editor.selection = new vscode.Selection(range.start, range.end)
    editor.revealRange(range, vscode.TextEditorRevealType.InCenter)
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    vscode.window.showErrorMessage(`无法打开代码 ${relPath}: ${detail}`)
  }
}
