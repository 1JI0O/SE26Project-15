import {
  LSPClient,
  LSPPlugin,
  Workspace,
  languageServerExtensions,
  type WorkspaceFile,
} from '@codemirror/lsp-client'
import type { ChangeSet, Text, TransactionSpec } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'
import { uriToRelativePath, checkoutDirUri } from '@/features/repository/lspTransport'

class TraceLabWorkspaceFile implements WorkspaceFile {
  constructor(
    readonly uri: string,
    readonly languageId: string,
    public version: number,
    public doc: Text,
    readonly view: EditorView,
  ) {}

  getView(): EditorView {
    return this.view
  }
}

export class TraceLabWorkspace extends Workspace {
  files: TraceLabWorkspaceFile[] = []
  private fileVersions: Record<string, number> = Object.create(null)

  constructor(
    client: LSPClient,
    private readonly checkoutRoot: string,
    private readonly openRelativePath: (path: string) => Promise<void>,
  ) {
    super(client)
  }

  private nextFileVersion(uri: string): number {
    this.fileVersions[uri] = (this.fileVersions[uri] ?? -1) + 1
    return this.fileVersions[uri]
  }

  syncFiles() {
    const result: Array<{
      file: WorkspaceFile
      prevDoc: Text
      changes: ChangeSet
    }> = []
    for (const file of this.files) {
      const plugin = LSPPlugin.get(file.view)
      if (!plugin) continue
      const changes: ChangeSet = plugin.unsyncedChanges
      if (!changes.empty) {
        result.push({ changes, file, prevDoc: file.doc })
        file.doc = file.view.state.doc
        file.version = this.nextFileVersion(file.uri)
        plugin.clear()
      }
    }
    return result
  }

  openFile(uri: string, languageId: string, view: EditorView): void {
    if (this.getFile(uri)) {
      throw new Error('TraceLab workspace does not support multiple views on the same file')
    }
    const file = new TraceLabWorkspaceFile(
      uri,
      languageId,
      this.nextFileVersion(uri),
      view.state.doc,
      view,
    )
    this.files.push(file)
    this.client.didOpen(file)
  }

  closeFile(uri: string, _view: EditorView): void {
    const file = this.getFile(uri)
    if (!file) return
    this.files = this.files.filter((item) => item !== file)
    this.client.didClose(uri)
  }

  override updateFile(uri: string, update: TransactionSpec): void {
    const file = this.getFile(uri)
    file?.getView()?.dispatch(update)
  }

  override async displayFile(uri: string): Promise<EditorView | null> {
    const existing = this.getFile(uri)
    if (existing) return existing.getView()

    const relativePath = uriToRelativePath(this.checkoutRoot, uri)
    if (!relativePath) return null

    await this.openRelativePath(relativePath)
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 50))
      const opened = this.getFile(uri)
      if (opened) return opened.getView()
    }
    return null
  }
}

export function createTraceLabLspClient(
  checkoutRoot: string,
  openRelativePath: (path: string) => Promise<void>,
): LSPClient {
  return new LSPClient({
    rootUri: checkoutDirUri(checkoutRoot),
    timeout: 15_000,
    extensions: languageServerExtensions(),
    workspace: (client) => new TraceLabWorkspace(client, checkoutRoot, openRelativePath),
  })
}
