<template>
  <article class="flow-inspector">
    <header>
      <h2>节点定位</h2>
    </header>

    <div v-if="node" class="inspector-body">
      <strong>{{ node.title }}</strong>
      <span>
        {{ node.external ? '外部/标准黑盒' : node.kindLabel }} · {{ node.tensorShape }}
      </span>
      <p>{{ node.description }}</p>
      <dl>
        <div>
          <dt>代码位置</dt>
          <dd>{{ node.sourcePath }}:{{ node.lineStart }}</dd>
        </div>
        <div>
          <dt>当前文件</dt>
          <dd>{{ currentFilePath }}</dd>
        </div>
      </dl>
      <div class="inspector-actions">
        <el-button type="primary" plain @click="$emit('jumpToCode', node)">
          跳转到代码
        </el-button>
        <el-button v-if="node.expandable" @click="$emit('expandNode', node)">
          展开模块
        </el-button>
      </div>
    </div>

    <el-empty v-else description="点击图中节点查看代码定位" />

    <p class="api-note">
      当前接口由静态分析生成节点、边、代码定位和可推断的张量形状；后续 Agent 继续复用同一结构。
    </p>
  </article>
</template>

<script setup lang="ts">
import type { TensorFlowNode } from '@/composables/useTensorFlow'

defineProps<{
  node: TensorFlowNode | null
  currentFilePath: string
}>()

defineEmits<{
  jumpToCode: [node: TensorFlowNode]
  expandNode: [node: TensorFlowNode]
}>()
</script>

<style scoped>
.flow-inspector {
  display: grid;
  align-content: start;
  gap: 14px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  padding: 16px;
}

.flow-inspector header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.flow-inspector h2 {
  margin: 0;
}

.inspector-body {
  display: grid;
  gap: 10px;
}

.inspector-body strong,
.inspector-body span {
  display: block;
}

.inspector-body span {
  color: #667789;
  line-height: 1.6;
}

.inspector-body p {
  margin: 0;
  line-height: 1.6;
}

.inspector-body dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.inspector-body dl div {
  display: grid;
  gap: 3px;
  padding: 10px;
  border-radius: 6px;
  background: #f8fafc;
}

.inspector-body dt {
  color: #667789;
  font-size: 12px;
}

.inspector-body dd {
  margin: 0;
  color: #24313d;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
}

.inspector-actions {
  display: flex;
  gap: 8px;
}

.api-note {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  background: #f0faf7;
  color: #667789;
  font-size: 12px;
  line-height: 1.6;
}
</style>
