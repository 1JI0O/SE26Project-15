<template>
  <article class="tensor-flow-board">
    <header class="flow-header">
      <div class="flow-title">
        <el-button
          v-if="canGoBack"
          text
          size="small"
          :icon="ArrowLeft"
          aria-label="返回上一级架构"
          @click="$emit('back')"
        />
        <div>
          <h2>{{ currentView === 'architecture' ? '模型架构图' : '算子调试图' }}</h2>
          <span>{{ rootLabel }}</span>
        </div>
        <el-tag v-if="degraded" type="warning" effect="plain" size="small">
          兼容数据
        </el-tag>
        <el-tag
          v-if="['pending', 'queued', 'running', 'stale'].includes(analysisStatus)"
          type="info"
          effect="plain"
          size="small"
        >
          后台分析{{ analysisStale ? ' · 显示旧缓存' : '' }}
        </el-tag>
      </div>

      <div class="flow-toolbar">
        <el-select
          :model-value="rootSymbol"
          class="root-select"
          size="small"
          filterable
          placeholder="选择主模型"
          @change="onRootChange"
        >
          <el-option
            v-for="root in availableRoots"
            :key="root.symbolId"
            :label="root.label"
            :value="root.symbolId"
          />
        </el-select>
        <el-select-v2
          v-model="focusedNodeId"
          class="node-search"
          size="small"
          filterable
          clearable
          :options="nodeSearchOptions"
          placeholder="搜索节点"
          @change="focusSelectedNode"
        />
        <el-button-group>
          <el-button
            size="small"
            :type="currentView === 'architecture' ? 'primary' : 'default'"
            @click="$emit('viewChange', 'architecture')"
          >
            架构
          </el-button>
          <el-button
            size="small"
            :type="currentView === 'debug' ? 'primary' : 'default'"
            @click="$emit('viewChange', 'debug')"
          >
            调试
          </el-button>
        </el-button-group>
        <el-button-group>
          <el-tooltip content="缩小">
            <el-button size="small" :icon="ZoomOut" aria-label="缩小" @click="zoomBy(0.82)" />
          </el-tooltip>
          <el-button size="small" class="zoom-label" @click="fitView">
            {{ zoomPercent }}%
          </el-button>
          <el-tooltip content="放大">
            <el-button size="small" :icon="ZoomIn" aria-label="放大" @click="zoomBy(1.22)" />
          </el-tooltip>
          <el-tooltip content="适应画布">
            <el-button size="small" :icon="FullScreen" aria-label="适应画布" @click="fitView" />
          </el-tooltip>
        </el-button-group>
      </div>
    </header>

    <div v-if="loading" class="state-placeholder">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <span>正在读取模型架构缓存...</span>
    </div>
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
    </div>
    <div v-else-if="!nodes.length" class="state-placeholder">
      <el-icon
        v-if="['pending', 'queued', 'running', 'stale'].includes(analysisStatus)"
        class="is-loading"
        :size="22"
      ><Loading /></el-icon>
      <span>
        {{ ['pending', 'queued', 'running', 'stale'].includes(analysisStatus)
          ? '模型架构正在后台生成，完成后会自动显示'
          : '未识别到可展示的模型主路径' }}
      </span>
    </div>

    <div v-else class="tensor-flow-canvas">
      <svg
        ref="svgRef"
        :viewBox="viewBox"
        role="img"
        aria-label="可交互模型架构图"
        :class="{ panning: panState !== null }"
        @wheel.prevent="onWheel"
        @pointerdown="startPan"
        @pointermove="movePan"
        @pointerup="endPan"
        @pointercancel="endPan"
        @mouseleave="cancelPan"
      >
        <defs>
          <marker
            id="flow-arrow"
            markerHeight="8"
            markerWidth="8"
            orient="auto"
            refX="7"
            refY="4"
          >
            <path d="M0,0 L8,4 L0,8 Z" fill="#1f8f78" />
          </marker>
        </defs>
        <g class="edge-layer">
          <path
            v-for="edge in visibleEdges"
            :key="`${edge.id}-path`"
            :d="edgePath(edge.points)"
            class="flow-edge"
            marker-end="url(#flow-arrow)"
          />
        </g>
        <g v-if="showEdgeLabels" class="edge-label-layer">
          <g v-for="label in visibleEdgeLabels" :key="`${label.id}-label`">
            <rect
              :x="label.rectX"
              :y="label.rectY"
              :width="label.rectWidth"
              :height="label.rectHeight"
              rx="4"
              class="edge-label-bg"
            />
            <text :x="label.x" :y="label.y" text-anchor="middle" class="edge-label">
              {{ label.text }}
            </text>
          </g>
        </g>
        <g class="node-layer">
          <g
            v-for="node in visibleNodes"
            :key="node.id"
            :class="[
              'flow-node',
              node.kind,
              { active: selectedNode?.id === node.id, external: node.external },
            ]"
            role="button"
            tabindex="0"
            @pointerdown.stop
            @click.stop="selectNode(node)"
            @dblclick.stop="expandNode(node)"
            @keydown.enter.prevent="selectNode(node)"
          >
            <title>
              {{ node.title }} · {{ node.expandable ? '双击展开' : node.kindLabel }} ·
              {{ node.sourcePath }}:{{ node.lineStart }}
            </title>
            <rect :x="node.x" :y="node.y" :width="node.width" :height="node.height" rx="6" />
            <text v-if="showNodeDetails" :x="node.x + 12" :y="node.y + 20" class="node-kind">
              {{ node.external && node.kind === 'component' ? 'Black box' : node.kindLabel }}
            </text>
            <g v-if="node.expandable" class="expand-badge">
              <circle :cx="node.x + node.width - 17" :cy="node.y + 17" r="9" />
              <text :x="node.x + node.width - 17" :y="node.y + 20">+</text>
            </g>
            <text
              v-if="showNodeTitles"
              :ref="(el) => registerText(node, 'title', el as SVGTextElement)"
              :x="node.x + 12"
              :y="node.y + 45"
              class="node-title"
            >{{ node.title }}</text>
            <text
              v-if="showNodeDetails"
              :ref="(el) => registerText(node, 'detail', el as SVGTextElement)"
              :x="node.x + 12"
              :y="node.y + 68"
              class="node-detail"
            >{{ node.detail }}</text>
          </g>
        </g>
      </svg>
      <span class="canvas-hint">滚轮缩放 · 拖动画布 · 双击带 + 的模块下钻</span>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ArrowLeft, FullScreen, Loading, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import type {
  TensorFlowEdge,
  TensorFlowEdgeLabel,
  TensorFlowNode,
  TensorFlowRoot,
  TensorFlowView,
} from '@/composables/useTensorFlow'

const props = defineProps<{
  nodes: TensorFlowNode[]
  edges: TensorFlowEdge[]
  edgeLabels: TensorFlowEdgeLabel[]
  selectedNode: TensorFlowNode | null
  edgePath: (points: TensorFlowEdge['points']) => string
  loading: boolean
  error: string | null
  degraded: boolean
  analysisStatus: 'missing' | 'pending' | 'queued' | 'running' | 'ready' | 'failed' | 'stale'
  analysisStale: boolean
  currentView: TensorFlowView
  rootSymbol: string | null
  rootLabel: string
  availableRoots: TensorFlowRoot[]
  canGoBack: boolean
}>()

const emit = defineEmits<{
  nodeClick: [node: TensorFlowNode]
  expandNode: [node: TensorFlowNode]
  viewChange: [view: TensorFlowView]
  rootChange: [symbolId: string]
  back: []
}>()

const svgRef = ref<SVGSVGElement | null>(null)
const focusedNodeId = ref('')
const view = reactive({ x: 0, y: 0, width: 1040, height: 520 })
const fittedWidth = ref(1040)
const canvasSize = reactive({ width: 1040, height: 520 })
let resizeObserver: ResizeObserver | null = null
const panState = ref<{
  clientX: number
  clientY: number
  viewX: number
  viewY: number
} | null>(null)

const graphBounds = computed(() => {
  if (!props.nodes.length) return { x: 0, y: 0, width: 1040, height: 520 }
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const node of props.nodes) {
    minX = Math.min(minX, node.x)
    minY = Math.min(minY, node.y)
    maxX = Math.max(maxX, node.x + node.width)
    maxY = Math.max(maxY, node.y + node.height)
  }
  return {
    x: minX - 44,
    y: minY - 44,
    width: Math.max(maxX - minX + 88, 360),
    height: Math.max(maxY - minY + 88, 220),
  }
})
const viewBox = computed(() => `${view.x} ${view.y} ${view.width} ${view.height}`)
const zoomPercent = computed(() => Math.round((fittedWidth.value / view.width) * 100))
const projectedNodeWidth = computed(() => {
  const representative = props.nodes[Math.floor(props.nodes.length / 2)]?.width || 180
  return (representative / Math.max(view.width, 1)) * canvasSize.width
})
const nodeSearchOptions = computed(() =>
  props.nodes.map((node) => ({ label: `${node.title} · ${node.sourcePath}`, value: node.id })),
)
const showNodeTitles = computed(() => projectedNodeWidth.value >= 42)
const showNodeDetails = computed(() => projectedNodeWidth.value >= 86)
const showEdgeLabels = computed(
  () => projectedNodeWidth.value >= 74 && (
    props.edges.length <= 800 || projectedNodeWidth.value >= 160
  ),
)
const visibleNodes = computed(() => {
  if (props.nodes.length < 220) return props.nodes
  const margin = Math.max(view.width * 0.08, 100)
  const inViewport = props.nodes.filter((node) => (
    node.x + node.width >= view.x - margin &&
    node.x <= view.x + view.width + margin &&
    node.y + node.height >= view.y - margin &&
    node.y <= view.y + view.height + margin
  ))
  const maximum = projectedNodeWidth.value < 28 ? 320 : 520
  if (inViewport.length <= maximum) return inViewport
  const selectedId = props.selectedNode?.id
  const connected = new Set<string>([selectedId || ''])
  if (selectedId) {
    for (const edge of props.edges) {
      if (edge.source === selectedId) connected.add(edge.target)
      if (edge.target === selectedId) connected.add(edge.source)
    }
  }
  const essential = inViewport.filter((node) => connected.has(node.id))
  const essentialIds = new Set(essential.map((node) => node.id))
  const remaining = Math.max(maximum - essential.length, 0)
  const stride = Math.ceil(inViewport.length / Math.max(remaining, 1))
  return [
    ...essential,
    ...inViewport.filter(
      (node, index) => !essentialIds.has(node.id) && index % stride === 0,
    ),
  ].slice(0, maximum)
})
const visibleEdges = computed(() => {
  if (props.edges.length < 300) return props.edges
  const visibleIds = new Set(visibleNodes.value.map((node) => node.id))
  const connected = props.edges.filter(
    (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
  )
  if (connected.length <= 700) return connected
  const selectedId = props.selectedNode?.id
  const selectedEdges = selectedId
    ? connected.filter((edge) => edge.source === selectedId || edge.target === selectedId)
    : []
  const selectedEdgeIds = new Set(selectedEdges.map((edge) => edge.id))
  const stride = Math.ceil(connected.length / Math.max(700 - selectedEdges.length, 1))
  return [
    ...selectedEdges,
    ...connected.filter((edge, index) => !selectedEdgeIds.has(edge.id) && index % stride === 0),
  ].slice(0, 700)
})
const visibleEdgeLabels = computed(() => {
  const visibleIds = new Set(visibleEdges.value.map((edge) => edge.id))
  return props.edgeLabels.filter((label) => visibleIds.has(label.id))
})

const textRefs = new Map<string, { element: SVGTextElement; maxWidth: number }>()

function registerText(node: TensorFlowNode, slot: string, element: SVGTextElement | null): void {
  const key = `${node.id}:${slot}`
  if (element) textRefs.set(key, { element, maxWidth: node.width - 24 })
  else textRefs.delete(key)
}

function fitTextToNodes(): void {
  for (const { element, maxWidth } of textRefs.values()) {
    element.removeAttribute('textLength')
    element.removeAttribute('lengthAdjust')
    if (element.getComputedTextLength() > maxWidth) {
      element.setAttribute('textLength', String(maxWidth))
      element.setAttribute('lengthAdjust', 'spacingAndGlyphs')
    }
  }
}

function fitView(): void {
  const bounds = graphBounds.value
  const aspect = canvasSize.width / Math.max(canvasSize.height, 1)
  let width = bounds.width
  let height = bounds.height
  if (width / height < aspect) width = height * aspect
  else height = width / aspect
  view.x = bounds.x + bounds.width / 2 - width / 2
  view.y = bounds.y + bounds.height / 2 - height / 2
  view.width = width
  view.height = height
  fittedWidth.value = width
}

function fitReadableView(): void {
  const svg = svgRef.value
  if (!svg) {
    fitView()
    return
  }
  const rect = svg.getBoundingClientRect()
  canvasSize.width = Math.max(rect.width, 1)
  canvasSize.height = Math.max(rect.height, 1)
  fitView()
}

function zoomBy(factor: number, anchorX?: number, anchorY?: number): void {
  const narrowestNode = props.nodes.reduce(
    (minimum, node) => Math.min(minimum, node.width),
    180,
  )
  const minimumWidth = Math.max(
    narrowestNode * 0.75,
    72,
  )
  const maximumWidth = Math.max(fittedWidth.value * 12, 2400)
  const nextWidth = Math.min(Math.max(view.width / factor, minimumWidth), maximumWidth)
  const ratio = nextWidth / view.width
  const selected = props.selectedNode
  const x = anchorX ?? (selected ? selected.x + selected.width / 2 : view.x + view.width / 2)
  const y = anchorY ?? (selected ? selected.y + selected.height / 2 : view.y + view.height / 2)
  view.x = x - (x - view.x) * ratio
  view.y = y - (y - view.y) * ratio
  view.height *= ratio
  view.width = nextWidth
}

function onWheel(event: WheelEvent): void {
  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const anchorX = view.x + ((event.clientX - rect.left) / rect.width) * view.width
  const anchorY = view.y + ((event.clientY - rect.top) / rect.height) * view.height
  zoomBy(event.deltaY < 0 ? 1.14 : 0.88, anchorX, anchorY)
}

function startPan(event: PointerEvent): void {
  if (event.button !== 0) return
  panState.value = {
    clientX: event.clientX,
    clientY: event.clientY,
    viewX: view.x,
    viewY: view.y,
  }
  svgRef.value?.setPointerCapture(event.pointerId)
}

function movePan(event: PointerEvent): void {
  const start = panState.value
  const svg = svgRef.value
  if (!start || !svg) return
  const rect = svg.getBoundingClientRect()
  view.x = start.viewX - ((event.clientX - start.clientX) / rect.width) * view.width
  view.y = start.viewY - ((event.clientY - start.clientY) / rect.height) * view.height
}

function endPan(event: PointerEvent): void {
  if (panState.value && svgRef.value?.hasPointerCapture(event.pointerId)) {
    svgRef.value.releasePointerCapture(event.pointerId)
  }
  panState.value = null
}

function cancelPan(): void {
  panState.value = null
}

function selectNode(node: TensorFlowNode): void {
  focusedNodeId.value = node.id
  emit('nodeClick', node)
}

function expandNode(node: TensorFlowNode): void {
  if (node.expandable) emit('expandNode', node)
}

function focusSelectedNode(value: string): void {
  const node = props.nodes.find((candidate) => candidate.id === value)
  if (!node) return
  const width = Math.min(Math.max(node.width * 2.7, 420), graphBounds.value.width)
  const height = width / (canvasSize.width / Math.max(canvasSize.height, 1))
  view.x = node.x + node.width / 2 - width / 2
  view.y = node.y + node.height / 2 - height / 2
  view.width = width
  view.height = height
  emit('nodeClick', node)
}

function onRootChange(value: string): void {
  if (value) emit('rootChange', value)
}

onMounted(() => {
  nextTick(() => {
    fitReadableView()
    fitTextToNodes()
    if (svgRef.value) {
      resizeObserver = new ResizeObserver(() => {
        const rect = svgRef.value?.getBoundingClientRect()
        if (!rect) return
        canvasSize.width = Math.max(rect.width, 1)
        canvasSize.height = Math.max(rect.height, 1)
        view.height = view.width / (canvasSize.width / canvasSize.height)
      })
      resizeObserver.observe(svgRef.value)
    }
  })
})

onBeforeUnmount(() => resizeObserver?.disconnect())

watch(
  () => props.nodes,
  () => {
    focusedNodeId.value = ''
    nextTick(() => {
      fitReadableView()
      fitTextToNodes()
    })
  },
  { deep: true },
)
</script>

<style scoped>
.tensor-flow-board {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px;
}

.flow-header,
.flow-title,
.flow-toolbar {
  display: flex;
  align-items: center;
}

.flow-header {
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.flow-title {
  min-width: 0;
  gap: 6px;
}

.flow-title > div {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.flow-title h2 {
  margin: 0;
  font-size: 14px;
}

.flow-title span {
  overflow: hidden;
  color: #71808f;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.flow-toolbar {
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}

.root-select {
  width: 150px;
}

.node-search {
  width: 135px;
}

.zoom-label {
  min-width: 48px;
  padding: 5px 7px;
  font-variant-numeric: tabular-nums;
}

.state-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 220px;
  color: #667789;
}

.state-error {
  color: #e15a4a;
}

.tensor-flow-canvas {
  position: relative;
  min-height: 240px;
  margin-top: 8px;
  overflow: hidden;
  border: 1px solid #dce3ea;
  border-radius: 4px;
  background: #fbfcfd;
}

.tensor-flow-canvas svg {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 240px;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.tensor-flow-canvas svg.panning {
  cursor: grabbing;
}

.canvas-hint {
  position: absolute;
  right: 8px;
  bottom: 6px;
  padding: 3px 6px;
  border: 1px solid #dce3ea;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.92);
  color: #82909d;
  font-size: 10px;
  pointer-events: none;
}

.flow-edge {
  fill: none;
  stroke: #1f8f78;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.edge-label-layer {
  pointer-events: none;
}

.edge-label-bg {
  fill: rgba(255, 255, 255, 0.94);
  stroke: #d7e3de;
  stroke-width: 1;
}

.edge-label {
  fill: #4d6470;
  font-size: 10px;
  font-weight: 600;
  dominant-baseline: middle;
}

.flow-node {
  cursor: pointer;
  outline: none;
}

.flow-node rect {
  fill: #ffffff;
  stroke: #cfd9e3;
  stroke-width: 1.5;
  transition: fill 0.12s ease, stroke 0.12s ease;
}

.flow-node:hover rect,
.flow-node.active rect {
  fill: #f0faf7;
  stroke: #1f8f78;
  stroke-width: 2;
}

.flow-node.input rect,
.flow-node.output rect {
  fill: #f0faf7;
}

.flow-node.branch rect {
  fill: #fff8e6;
}

.flow-node.merge rect {
  fill: #eef3ff;
}

.flow-node.external rect {
  stroke-dasharray: 5 3;
}

.node-kind {
  fill: #1f8f78;
  font-size: 11px;
  font-weight: 700;
}

.node-title {
  fill: #24313d;
  font-size: 14px;
  font-weight: 700;
}

.node-detail {
  fill: #667789;
  font-size: 11px;
}

.expand-badge circle {
  fill: #1f8f78;
}

.expand-badge text {
  fill: #ffffff;
  font-size: 13px;
  font-weight: 700;
  text-anchor: middle;
}

@media (max-width: 980px) {
  .node-search,
  .root-select {
    width: 120px;
  }
}
</style>
