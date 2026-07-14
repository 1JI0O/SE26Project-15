import { computed, ref } from 'vue'
import type { TagType } from './useCode'

export interface TensorFlowNode {
  id: string
  kind: 'input' | 'operation' | 'branch' | 'merge' | 'output'
  kindLabel: string
  title: string
  detail: string
  description: string
  tensorShape: string
  sourcePath: string
  lineStart: number
  lineEnd: number
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
  anchor: 'start' | 'middle' | 'end'
  rectX: number
  rectY: number
  rectWidth: number
  rectHeight: number
}

// Placeholder data — will be replaced by API call in iteration 2
const PLACEHOLDER_NODES: TensorFlowNode[] = [
  {
    id: 'images',
    kind: 'input',
    kindLabel: 'Input',
    title: 'images',
    detail: 'N x 3 x 224 x 224',
    description: '训练循环中从 dataloader 取出的输入张量。',
    tensorShape: 'N x 3 x 224 x 224',
    sourcePath: 'train.py',
    lineStart: 5,
    lineEnd: 7,
    x: 32,
    y: 72,
    width: 170,
    height: 104,
  },
  {
    id: 'conv1',
    kind: 'operation',
    kindLabel: 'Conv',
    title: 'conv1 + bn1 + relu',
    detail: 'models/resnet.py:20',
    description: 'BasicBlock.forward 中的第一段卷积、归一化和激活。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 20,
    lineEnd: 20,
    x: 286,
    y: 72,
    width: 210,
    height: 104,
  },
  {
    id: 'conv2',
    kind: 'operation',
    kindLabel: 'Conv',
    title: 'conv2 + bn2',
    detail: 'models/resnet.py:21',
    description: '残差分支中的第二段卷积和归一化。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 21,
    lineEnd: 21,
    x: 580,
    y: 72,
    width: 190,
    height: 104,
  },
  {
    id: 'shortcut',
    kind: 'branch',
    kindLabel: 'Branch',
    title: 'identity / downsample',
    detail: 'projection shortcut',
    description: '当维度变化时进入 downsample，否则保留 identity 分支。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 22,
    lineEnd: 23,
    x: 286,
    y: 306,
    width: 300,
    height: 108,
  },
  {
    id: 'add',
    kind: 'merge',
    kindLabel: 'Merge',
    title: 'out += identity',
    detail: 'models/resnet.py:24',
    description: '残差张量与 shortcut 张量相加，对应论文公式 y = F(x, Wi) + x。',
    tensorShape: 'N x C x H x W',
    sourcePath: 'models/resnet.py',
    lineStart: 24,
    lineEnd: 24,
    x: 812,
    y: 198,
    width: 180,
    height: 108,
  },
  {
    id: 'logits',
    kind: 'output',
    kindLabel: 'Output',
    title: 'logits',
    detail: 'train.py:7',
    description: '模型前向输出，随后进入 loss 和 backward 训练链路。',
    tensorShape: 'N x classes',
    sourcePath: 'train.py',
    lineStart: 7,
    lineEnd: 8,
    x: 812,
    y: 360,
    width: 180,
    height: 104,
  },
]

const PLACEHOLDER_EDGES: TensorFlowEdge[] = [
  {
    id: 'images-conv1',
    source: 'images',
    target: 'conv1',
    label: 'input tensor',
    points: [[202, 124], [286, 124]],
  },
  {
    id: 'conv1-conv2',
    source: 'conv1',
    target: 'conv2',
    label: 'feature tensor',
    points: [[496, 124], [580, 124]],
  },
  {
    id: 'conv2-add',
    source: 'conv2',
    target: 'add',
    label: 'residual',
    points: [[770, 124], [792, 124], [792, 252], [812, 252]],
  },
  {
    id: 'images-shortcut',
    source: 'images',
    target: 'shortcut',
    label: 'identity branch',
    points: [[118, 176], [118, 360], [286, 360]],
  },
  {
    id: 'shortcut-add',
    source: 'shortcut',
    target: 'add',
    label: 'shortcut tensor',
    points: [[586, 360], [700, 360], [700, 278], [812, 278]],
  },
  {
    id: 'add-logits',
    source: 'add',
    target: 'logits',
    label: 'block output',
    points: [[902, 306], [902, 360]],
  },
]

const EDGE_LABEL_LAYOUT: Record<string, { text: string; x: number; y: number; anchor: 'start' | 'middle' | 'end' }> = {
  'images-conv1': { text: 'input tensor', x: 244, y: 108, anchor: 'middle' },
  'conv1-conv2': { text: 'feature tensor', x: 538, y: 108, anchor: 'middle' },
  'conv2-add': { text: 'residual', x: 804, y: 188, anchor: 'start' },
  'images-shortcut': { text: 'identity branch', x: 48, y: 286, anchor: 'start' },
  'shortcut-add': { text: 'shortcut tensor', x: 643, y: 382, anchor: 'middle' },
  'add-logits': { text: 'block output', x: 952, y: 334, anchor: 'end' },
}

function defaultEdgeLabelLayout(edge: TensorFlowEdge) {
  const points = edge.points
  const [startX, startY] = points[0]
  const [endX, endY] = points[points.length - 1]
  return {
    text: edge.label,
    x: (startX + endX) / 2,
    y: (startY + endY) / 2 - 12,
    anchor: 'middle' as const,
  }
}

function buildEdgeLabel(edge: TensorFlowEdge): TensorFlowEdgeLabel {
  const layout = EDGE_LABEL_LAYOUT[edge.id] ?? defaultEdgeLabelLayout(edge)
  const rectWidth = Math.max(layout.text.length * 7.2 + 14, 72)
  const rectHeight = 22
  const rectX =
    layout.anchor === 'middle'
      ? layout.x - rectWidth / 2
      : layout.anchor === 'end'
        ? layout.x - rectWidth + 6
        : layout.x - 6
  const rectY = layout.y - 16

  return {
    id: edge.id,
    text: layout.text,
    x: layout.x,
    y: layout.y,
    anchor: layout.anchor,
    rectX,
    rectY,
    rectWidth,
    rectHeight,
  }
}

export function useTensorFlow() {
  const nodes = ref<TensorFlowNode[]>(PLACEHOLDER_NODES)
  const edges = ref<TensorFlowEdge[]>(PLACEHOLDER_EDGES)
  const selectedNode = ref<TensorFlowNode | null>(PLACEHOLDER_NODES[0] ?? null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const degraded = ref(true) // placeholder data = degraded mode

  const edgeLabels = computed(() => edges.value.map((e) => buildEdgeLabel(e)))

  function edgePath(points: TensorFlowEdge['points']): string {
    return points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  }

  function selectNode(node: TensorFlowNode): void {
    selectedNode.value = node
  }

  return {
    nodes,
    edges,
    selectedNode,
    loading,
    error,
    degraded,
    edgeLabels,
    edgePath,
    selectNode,
  }
}

export const conflictItems = [
  {
    level: '高风险',
    type: 'danger' as TagType,
    title: 'stride 下采样与论文描述不一致',
    description: '配置中 stage3 stride 被改为 1，可能改变张量尺寸变化路径和论文基线。',
  },
  {
    level: '中风险',
    type: 'warning' as TagType,
    title: '训练 batch size 被缩小',
    description: 'batch size 从 256 改为 64，需要同步调整学习率或记录偏差。',
  },
  {
    level: '待确认',
    type: 'info' as TagType,
    title: 'loss 函数存在本地替换',
    description: '代码使用 label smoothing，论文原文未明确描述该策略。',
  },
]

export const reportCards = [
  { value: '86%', title: '追溯覆盖率', description: '方法、模型结构和训练配置已有候选链接。' },
  { value: '12', title: '已确认关系', description: '可进入报告的证据链数量。' },
  { value: '3', title: '冲突项', description: '需要人工解释或回滚的魔改影响。' },
  { value: 'Flow JSON', title: '流程图接口', description: '返回节点、边、张量形状和代码定位。' },
]
