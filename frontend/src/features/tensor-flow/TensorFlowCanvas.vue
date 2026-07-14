<template>
  <article class="tensor-flow-board">
    <header>
      <h2>代码张量流追踪图</h2>
      <p>
        该图由代码仓库中的模型定义、forward 函数和训练入口生成，用于展示 tensor
        在模块之间的流动路径，不表示 PDF/代码处理流程。
      </p>
      <el-tag v-if="degraded" type="warning" effect="plain" size="small">
        当前为占位数据
      </el-tag>
    </header>

    <!-- Loading state -->
    <div v-if="loading" class="state-placeholder">
      <el-icon class="is-loading" :size="24"><i class="el-icon-loading" /></el-icon>
      <span>加载张量流图...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
    </div>

    <!-- Empty state -->
    <div v-else-if="!nodes.length" class="state-placeholder">
      <span>暂无张量流数据</span>
    </div>

    <!-- Canvas -->
    <div v-else class="tensor-flow-canvas">
      <svg viewBox="0 0 1040 520" role="img" aria-label="代码张量流追踪图">
        <defs>
          <marker
            id="flow-arrow"
            markerHeight="10"
            markerWidth="10"
            orient="auto"
            refX="8"
            refY="5"
          >
            <path d="M0,0 L10,5 L0,10 Z" fill="#1f8f78" />
          </marker>
          <!-- Clip paths for each node to prevent text overflow -->
          <clipPath v-for="node in nodes" :key="`clip-${node.id}`" :id="`clip-${node.id}`">
            <rect :x="node.x + 4" :y="node.y + 4" :width="node.width - 8" :height="node.height - 8" />
          </clipPath>
        </defs>
        <g class="edge-layer">
          <path
            v-for="edge in edges"
            :key="`${edge.id}-path`"
            :d="edgePath(edge.points)"
            class="flow-edge"
            marker-end="url(#flow-arrow)"
          />
        </g>
        <g class="node-layer">
          <g
            v-for="node in nodes"
            :key="node.id"
            :class="[
              'flow-node',
              node.kind,
              { active: selectedNode?.id === node.id },
            ]"
            role="button"
            tabindex="0"
            @click="$emit('nodeClick', node)"
            @keydown.enter.prevent="$emit('nodeClick', node)"
          >
            <rect :x="node.x" :y="node.y" :width="node.width" :height="node.height" rx="10" />
            <text
              :x="node.x + 12"
              :y="node.y + 24"
              class="node-kind"
              :font-size="fitFontSize(node.kindLabel, node.width - 24, 13)"
            >{{ node.kindLabel }}</text>
            <text
              :x="node.x + 12"
              :y="node.y + 50"
              class="node-title"
              :font-size="fitFontSize(node.title, node.width - 24, 15)"
            >{{ truncateText(node.title, node.width - 24, 15) }}</text>
            <text
              :x="node.x + 12"
              :y="node.y + 74"
              class="node-detail"
              :font-size="fitFontSize(node.detail, node.width - 24, 13)"
            >{{ truncateText(node.detail, node.width - 24, 13) }}</text>
          </g>
        </g>
        <g class="edge-label-layer">
          <g v-for="label in edgeLabels" :key="`${label.id}-label`">
            <rect
              :x="label.rectX"
              :y="label.rectY"
              :width="label.rectWidth"
              :height="label.rectHeight"
              rx="6"
              class="edge-label-bg"
            />
            <text
              :x="label.x"
              :y="label.y"
              :text-anchor="label.anchor"
              class="edge-label"
            >
              {{ label.text }}
            </text>
          </g>
        </g>
      </svg>
    </div>
  </article>
</template>

<script setup lang="ts">
import type { TensorFlowEdge, TensorFlowEdgeLabel, TensorFlowNode } from '@/composables/useTensorFlow'

defineProps<{
  nodes: TensorFlowNode[]
  edges: TensorFlowEdge[]
  edgeLabels: TensorFlowEdgeLabel[]
  selectedNode: TensorFlowNode | null
  edgePath: (points: TensorFlowEdge['points']) => string
  loading: boolean
  error: string | null
  degraded: boolean
}>()

defineEmits<{
  nodeClick: [node: TensorFlowNode]
}>()

/**
 * Estimate font size to fit text within available width.
 * Average char width ≈ 0.6 * fontSize for sans-serif.
 */
function fitFontSize(text: string, availableWidth: number, maxFontSize: number): number {
  if (!text) return maxFontSize
  const charWidth = maxFontSize * 0.6
  const neededWidth = text.length * charWidth
  if (neededWidth <= availableWidth) return maxFontSize
  const scaled = Math.floor((availableWidth / neededWidth) * maxFontSize)
  return Math.max(scaled, 9) // minimum 9px
}

/**
 * Truncate text with ellipsis if it's too long for the available width.
 */
function truncateText(text: string, availableWidth: number, fontSize: number): string {
  if (!text) return ''
  const charWidth = fontSize * 0.6
  const maxChars = Math.floor(availableWidth / charWidth)
  if (text.length <= maxChars) return text
  return text.slice(0, maxChars - 1) + '…'
}
</script>

<style scoped>
.tensor-flow-board {
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  padding: 16px;
}

.tensor-flow-board h2 {
  margin: 0;
}

.tensor-flow-board p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.state-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px;
  color: #667789;
}

.state-error {
  color: #e15a4a;
}

.tensor-flow-canvas {
  margin-top: 16px;
  overflow: hidden;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.tensor-flow-canvas svg {
  display: block;
  width: 100%;
  height: auto;
}

.flow-edge {
  fill: none;
  stroke: #1f8f78;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 3;
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
  font-size: 11px;
  font-weight: 700;
  dominant-baseline: middle;
}

.flow-node {
  cursor: pointer;
  outline: none;
}

.flow-node rect {
  fill: #ffffff;
  stroke: #cfd9e3;
  stroke-width: 2;
  transition: fill 0.16s ease, stroke 0.16s ease;
}

.flow-node:hover rect,
.flow-node.active rect {
  fill: #f0faf7;
  stroke: #1f8f78;
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

.node-kind {
  fill: #1f8f78;
  font-size: 13px;
  font-weight: 700;
}

.node-title {
  fill: #24313d;
  font-size: 15px;
  font-weight: 700;
}

.node-detail {
  fill: #667789;
  font-size: 13px;
}
</style>
