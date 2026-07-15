import { computed, ref } from 'vue'
import { getWorkspaceTensorFlow } from '@/api/repository-api'

export type TensorFlowNodeKind =
  | 'input'
  | 'component'
  | 'operation'
  | 'branch'
  | 'merge'
  | 'output'
export type TensorFlowView = 'architecture' | 'debug'

export interface TensorFlowRoot {
  symbolId: string
  label: string
  sourcePath: string
}

export interface TensorFlowNode {
  id: string
  kind: TensorFlowNodeKind
  kindLabel: string
  title: string
  detail: string
  description: string
  tensorShape: string
  sourcePath: string
  lineStart: number
  lineEnd: number
  componentSymbolId: string | null
  expandable: boolean
  external: boolean
  x: number
  y: number
  width: number
  height: number
}

export interface TensorFlowEdge {
  id: string
  source: string
  target: string
  label: string
  points: Array<[number, number]>
}

export interface TensorFlowEdgeLabel {
  id: string
  text: string
  x: number
  y: number
  anchor: 'middle'
  rectX: number
  rectY: number
  rectWidth: number
  rectHeight: number
}

const KIND_LABELS: Record<TensorFlowNodeKind, string> = {
  input: 'Input',
  component: 'Module',
  operation: 'Operation',
  branch: 'Branch',
  merge: 'Merge',
  output: 'Output',
}

function normalizeKind(value: string): TensorFlowNodeKind {
  if (
    value === 'input' ||
    value === 'component' ||
    value === 'branch' ||
    value === 'merge' ||
    value === 'output'
  ) {
    return value
  }
  return 'operation'
}

function tensorShapeLabel(value: string | Array<number | null> | null): string {
  if (Array.isArray(value)) return value.map((item) => item ?? '?').join(' x ')
  return value || 'shape unknown'
}

function buildEdgeLabel(edge: TensorFlowEdge): TensorFlowEdgeLabel {
  const points = edge.points
  const middle = points[Math.floor((points.length - 1) / 2)] ?? [0, 0]
  const next = points[Math.min(Math.floor((points.length - 1) / 2) + 1, points.length - 1)] ?? middle
  const text = edge.label
  const x = (middle[0] + next[0]) / 2
  const y = (middle[1] + next[1]) / 2 - 12
  const rectWidth = Math.max(text.length * 7.2 + 14, 58)
  return {
    id: edge.id,
    text,
    x,
    y,
    anchor: 'middle',
    rectX: x - rectWidth / 2,
    rectY: y - 16,
    rectWidth,
    rectHeight: 22,
  }
}

export function useTensorFlow(projectId: () => number) {
  const nodes = ref<TensorFlowNode[]>([])
  const edges = ref<TensorFlowEdge[]>([])
  const selectedNode = ref<TensorFlowNode | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const degraded = ref(false)
  const renderer = ref('')
  const currentView = ref<TensorFlowView>('architecture')
  const rootSymbol = ref<string | null>(null)
  const rootLabel = ref('')
  const availableRoots = ref<TensorFlowRoot[]>([])
  const navigationStack = ref<TensorFlowRoot[]>([])

  const edgeLabels = computed(() => edges.value.filter((edge) => edge.label).map(buildEdgeLabel))

  async function loadTensorFlow(
    options: { view?: TensorFlowView; rootSymbol?: string | null } = {},
  ): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const payload = await getWorkspaceTensorFlow(projectId(), {
        view: options.view ?? currentView.value,
        rootSymbol: options.rootSymbol === undefined ? rootSymbol.value : options.rootSymbol,
      })
      renderer.value = payload.renderer
      currentView.value = payload.view
      rootSymbol.value = payload.root_symbol
      rootLabel.value = payload.root_label || '模型架构'
      availableRoots.value = payload.available_roots.map((root) => ({
        symbolId: root.symbol_id,
        label: root.label,
        sourcePath: root.source_path,
      }))
      degraded.value = !['architecture-dag-v2', 'semantic-dag-v1'].includes(payload.renderer)
      nodes.value = payload.nodes.map((node) => {
        const kind = normalizeKind(node.kind)
        return {
          id: node.id,
          kind,
          kindLabel: KIND_LABELS[kind],
          title: node.label,
          detail: `${node.source_path}:${node.line_start}`,
          description: node.description,
          tensorShape: tensorShapeLabel(node.tensor_shape),
          sourcePath: node.source_path,
          lineStart: node.line_start,
          lineEnd: node.line_end,
          componentSymbolId: node.component_symbol_id,
          expandable: node.expandable,
          external: node.external,
          x: node.x,
          y: node.y,
          width: node.width,
          height: node.height,
        }
      })
      edges.value = payload.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label,
        points: edge.points.map(([x, y]) => [x, y] as [number, number]),
      }))
      selectedNode.value = nodes.value[0] ?? null
    } catch (cause) {
      nodes.value = []
      edges.value = []
      selectedNode.value = null
      error.value = '模型架构分析结果加载失败'
      console.error(cause)
    } finally {
      loading.value = false
    }
  }

  function edgePath(points: TensorFlowEdge['points']): string {
    return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  }

  function selectNode(node: TensorFlowNode): void {
    selectedNode.value = node
  }

  async function expandNode(node: TensorFlowNode): Promise<void> {
    if (!node.expandable || !node.componentSymbolId) return
    if (rootSymbol.value) {
      navigationStack.value.push({
        symbolId: rootSymbol.value,
        label: rootLabel.value,
        sourcePath: node.sourcePath,
      })
    }
    await loadTensorFlow({ view: 'architecture', rootSymbol: node.componentSymbolId })
  }

  async function navigateBack(): Promise<void> {
    const parent = navigationStack.value.pop()
    if (!parent) return
    await loadTensorFlow({ view: 'architecture', rootSymbol: parent.symbolId })
  }

  async function selectRoot(symbolId: string): Promise<void> {
    navigationStack.value = []
    await loadTensorFlow({ view: 'architecture', rootSymbol: symbolId })
  }

  async function setView(view: TensorFlowView): Promise<void> {
    await loadTensorFlow({ view, rootSymbol: rootSymbol.value })
  }

  return {
    nodes,
    edges,
    selectedNode,
    loading,
    error,
    degraded,
    renderer,
    currentView,
    rootSymbol,
    rootLabel,
    availableRoots,
    navigationStack,
    edgeLabels,
    edgePath,
    selectNode,
    expandNode,
    navigateBack,
    selectRoot,
    setView,
    loadTensorFlow,
  }
}
