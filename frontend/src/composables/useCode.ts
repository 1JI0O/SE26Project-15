import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { isAxiosError } from 'axios'
import {
  getCode,
  getWorkspaceCodeFile,
  getWorkspaceCodeTree,
  importCodeFromGitHub,
  saveWorkspaceCodeFile,
  uploadCode,
} from '@/api/repository-api'
import type {
  RepositorySummary,
  WorkspaceCodeFile,
  WorkspaceCodeTreeNode,
} from '@/types/repositories'

export type TagType = 'success' | 'warning' | 'info' | 'primary' | 'danger'

export interface CodeFile {
  path: string
  name: string
  badge: string
  status: string
  statusType: TagType
  symbol: string
  paperRef: string
  linkedLines: number[]
  content: string
}

export interface VisibleTreeNode extends WorkspaceCodeTreeNode {
  depth: number
}

const EDITABLE_EXTENSIONS = new Set([
  '.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.kt', '.go', '.rs',
  '.c', '.cc', '.cpp', '.h', '.hpp', '.cs', '.swift', '.rb', '.php', '.lua',
  '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd',
  '.md', '.rst', '.txt', '.text', '.log',
  '.yaml', '.yml', '.toml', '.json', '.jsonl',
  '.xml', '.html', '.htm', '.css', '.scss', '.less', '.vue', '.svelte',
  '.ini', '.cfg', '.conf', '.env', '.properties', '.sql', '.csv', '.tsv',
  '.gitignore', '.dockerignore', '.editorconfig',
])

const EDITABLE_BASENAMES = new Set(['makefile', 'dockerfile', 'license', 'readme', 'cmakelists.txt'])

const BLOCKED_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico', '.tif', '.tiff',
  '.pt', '.pth', '.ckpt', '.safetensors', '.bin', '.onnx', '.h5', '.hdf5', '.pb', '.tflite',
  '.npy', '.npz', '.pkl', '.pickle', '.parquet', '.feather', '.arrow',
  '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
  '.mp4', '.mp3', '.wav', '.avi', '.mov',
  '.ttf', '.otf', '.woff', '.woff2', '.pdf',
  '.exe', '.dll', '.so', '.dylib', '.o', '.a', '.class', '.jar', '.wasm', '.db', '.sqlite',
])

function fileExtension(path: string): string {
  const index = path.lastIndexOf('.')
  if (index <= 0) return ''
  return path.slice(index).toLowerCase()
}

export function isEditableFile(path: string): boolean {
  const ext = fileExtension(path)
  const basename = path.split('/').pop()?.toLowerCase() ?? ''
  if (ext && BLOCKED_EXTENSIONS.has(ext)) return false
  if (ext && EDITABLE_EXTENSIONS.has(ext)) return true
  return EDITABLE_BASENAMES.has(basename)
}

export function blockedFileMessage(path: string): string {
  const ext = fileExtension(path)
  if (['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico', '.tif', '.tiff'].includes(ext)) {
    return '图片文件不支持在代码编辑器中打开。'
  }
  if (['.pt', '.pth', '.ckpt', '.safetensors', '.bin', '.onnx', '.h5', '.pkl', '.pickle', '.npy', '.npz'].includes(ext)) {
    return '模型权重或二进制数据文件不支持在代码编辑器中打开。'
  }
  return '该文件类型不支持在代码编辑器中打开，请选择代码或文本文件。'
}

export function fileIcon(filename: string): string {
  if (!isEditableFile(filename)) return 'BIN'
  if (filename.endsWith('.py')) return 'PY'
  if (filename.endsWith('.yaml') || filename.endsWith('.yml')) return 'YML'
  if (filename.endsWith('.md')) return 'MD'
  return 'FILE'
}

function folderKey(path: string): string {
  return path || '__root__'
}

function countLines(value: string): number {
  if (!value) return 1
  let count = 1
  for (const char of value) {
    if (char === '\n') count += 1
  }
  return count
}

export function useCode(projectId: () => number) {
  const codeTree = ref<WorkspaceCodeTreeNode[]>([])
  const codeFiles = ref<CodeFile[]>([])
  const codeFilename = ref('')
  const ignoreSummary = ref('上传代码包后显示过滤摘要。')
  const analysisSummary = ref<RepositorySummary | null>(null)
  const selectedPath = ref('')
  const uploading = ref(false)
  const importingGithub = ref(false)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)

  const expandedFolders = ref<Set<string>>(new Set(['__root__']))

  const visibleCodeTree = computed<VisibleTreeNode[]>(() =>
    buildVisibleTree(codeTree.value, expandedFolders.value),
  )
  const selectedFile = computed(() => codeFiles.value.find((f) => f.path === selectedPath.value))
  const hasCode = computed(() => codeTree.value.length > 0)

  const editorContent = ref('')
  let editorContentBuffer = ''
  const editorLineCount = ref(1)
  const isEditorDirty = ref(false)
  const editableLineNumbers = computed(() =>
    Array.from({ length: editorLineCount.value }, (_, i) => i + 1),
  )

  watch(selectedFile, (file) => {
    editorContent.value = file?.content ?? ''
    editorContentBuffer = editorContent.value
    editorLineCount.value = countLines(editorContentBuffer)
    isEditorDirty.value = false
  })

  function folderChevron(path: string): string {
    return expandedFolders.value.has(folderKey(path)) ? '▾' : '▸'
  }

  function isFolderExpanded(path: string): boolean {
    return expandedFolders.value.has(folderKey(path))
  }

  function toggleFolder(path: string): void {
    const key = folderKey(path)
    const next = new Set(expandedFolders.value)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    expandedFolders.value = next
  }

  function initExpandedFolders(tree: WorkspaceCodeTreeNode[]): void {
    const next = new Set<string>(['__root__'])
    for (const root of tree) {
      if (root.kind === 'folder') {
        next.add(folderKey(root.path))
        for (const child of root.children ?? []) {
          if (child.kind === 'folder') next.add(folderKey(child.path))
        }
      }
    }
    expandedFolders.value = next
  }

  function buildVisibleTree(
    nodes: WorkspaceCodeTreeNode[],
    expanded: Set<string>,
    depth = 0,
    parentExpanded = true,
  ): VisibleTreeNode[] {
    if (!parentExpanded) return []
    return nodes.flatMap((node) => {
      const current: VisibleTreeNode = { ...node, depth }
      if (node.kind !== 'folder') return [current]
      const isExpanded = expanded.has(folderKey(node.path))
      return [current, ...buildVisibleTree(node.children ?? [], expanded, depth + 1, isExpanded)]
    })
  }

  function findFirstEditableFile(nodes: WorkspaceCodeTreeNode[]): WorkspaceCodeTreeNode | null {
    for (const node of nodes) {
      if (node.kind === 'file' && isEditableFile(node.path)) return node
      const child = findFirstEditableFile(node.children ?? [])
      if (child) return child
    }
    return null
  }

  async function loadCodeTree(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [tree, repository] = await Promise.all([
        getWorkspaceCodeTree(projectId()),
        getCode(projectId()),
      ])
      codeTree.value = tree
      codeFiles.value = []
      selectedPath.value = ''
      initExpandedFolders(tree)
      codeFilename.value = repository.filename
      analysisSummary.value = repository.summary
      ignoreSummary.value = repository.summary
        ? `已忽略 ${repository.summary.ignored_count} 个规则匹配文件。`
        : '已应用 .gitignore 与 macOS 元数据过滤规则。'
      const firstFile = findFirstEditableFile(tree)
      if (firstFile) await openCodeFile(firstFile.path)
    } catch (cause) {
      codeTree.value = []
      codeFilename.value = ''
      analysisSummary.value = null
      if (!(isAxiosError(cause) && cause.response?.status === 404)) {
        error.value = '代码树加载失败'
      }
    } finally {
      loading.value = false
    }
  }

  async function openCodeFile(path: string): Promise<void> {
    if (!isEditableFile(path)) {
      ElMessage.warning(blockedFileMessage(path))
      return
    }
    const cached = codeFiles.value.find((f) => f.path === path)
    selectedPath.value = path
    if (cached) return

    try {
      const payload = await getWorkspaceCodeFile(projectId(), path)
      const mapped: CodeFile = {
        path: payload.path,
        name: payload.name,
        badge: payload.badge,
        status: payload.status,
        statusType: payload.status_type as TagType,
        symbol: payload.symbol,
        paperRef: payload.paper_ref,
        linkedLines: payload.linked_lines,
        content: payload.content,
      }
      codeFiles.value = [...codeFiles.value.filter((f) => f.path !== path), mapped]
    } catch (e) {
      ElMessage.error(`无法加载文件 ${path}`)
      console.error(e)
    }
  }

  function handleTreeNodeClick(node: VisibleTreeNode): void {
    if (node.kind === 'folder') {
      toggleFolder(node.path)
      return
    }
    if (!isEditableFile(node.path)) {
      ElMessage.warning(blockedFileMessage(node.path))
      return
    }
    void openCodeFile(node.path)
  }

  function handleEditorInput(content: string): void {
    editorContentBuffer = content
    const nextLineCount = countLines(content)
    if (nextLineCount !== editorLineCount.value) editorLineCount.value = nextLineCount
    if (!isEditorDirty.value) isEditorDirty.value = true
  }

  async function saveEditorBuffer(): Promise<void> {
    if (!selectedFile.value) return
    saving.value = true
    try {
      const result = await saveWorkspaceCodeFile(projectId(), selectedFile.value.path, editorContentBuffer)
      selectedFile.value.content = editorContentBuffer
      editorContent.value = editorContentBuffer
      isEditorDirty.value = false
      // Refresh version status after save
      if (result.status) {
        selectedFile.value.status = result.message ?? '已保存'
        selectedFile.value.statusType = 'success'
      }
      ElMessage.success('代码编辑已保存')
    } catch (e) {
      ElMessage.error('保存失败')
      console.error(e)
    } finally {
      saving.value = false
    }
  }

  async function refreshFileStatus(path: string): Promise<void> {
    try {
      const payload = await getWorkspaceCodeFile(projectId(), path)
      const existing = codeFiles.value.find(f => f.path === path)
      if (existing) {
        existing.status = payload.status
        existing.statusType = payload.status_type as TagType
        existing.badge = payload.badge
      }
    } catch {
      // silent fail for refresh
    }
  }

  async function handleUpload(file: File): Promise<boolean> {
    uploading.value = true
    try {
      const code = await uploadCode(projectId(), file)
      codeFilename.value = code.filename
      analysisSummary.value = code.summary
      await loadCodeTree()
      ElMessage.success('代码包上传并分析完成')
      return true
    } catch (e) {
      ElMessage.error('代码包上传失败')
      console.error(e)
      return false
    } finally {
      uploading.value = false
    }
  }

  async function handleGitHubImport(url: string): Promise<boolean> {
    importingGithub.value = true
    try {
      const code = await importCodeFromGitHub(projectId(), url)
      codeFilename.value = code.filename
      analysisSummary.value = code.summary
      await loadCodeTree()
      ElMessage.success('GitHub 仓库导入并分析完成')
      return true
    } catch (cause) {
      ElMessage.error('GitHub 仓库导入失败，请检查公开仓库地址')
      console.error(cause)
      return false
    } finally {
      importingGithub.value = false
    }
  }

  return {
    codeTree,
    codeFiles,
    codeFilename,
    ignoreSummary,
    analysisSummary,
    selectedPath,
    uploading,
    importingGithub,
    loading,
    saving,
    error,
    expandedFolders,
    visibleCodeTree,
    selectedFile,
    hasCode,
    editorContent,
    editorLineCount,
    isEditorDirty,
    editableLineNumbers,
    folderChevron,
    isFolderExpanded,
    handleTreeNodeClick,
    handleEditorInput,
    saveEditorBuffer,
    loadCodeTree,
    openCodeFile,
    refreshFileStatus,
    handleUpload,
    handleGitHubImport,
  }
}
