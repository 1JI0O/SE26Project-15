<template>
  <aside class="file-tree">
    <div class="tree-head">
      <strong>Repository</strong>
      <span>已忽略 .git、__pycache__、.DS_Store、__MACOSX、构建产物等文件</span>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="state-placeholder">
      <el-icon class="is-loading" :size="20"><i class="el-icon-loading" /></el-icon>
      <span>加载代码树...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
      <el-button size="small" @click="$emit('retry')">重试</el-button>
    </div>

    <!-- Empty state -->
    <div v-else-if="!hasCode" class="state-placeholder">
      <span>请先上传代码包</span>
    </div>

    <!-- Tree content -->
    <div v-else class="tree-list">
      <button
        v-for="node in visibleTree"
        :key="node.path || node.name"
        :class="[
          'file-node',
          `depth-${node.depth}`,
          {
            active: node.kind === 'file' && node.path === selectedPath,
            folder: node.kind === 'folder',
            expanded: node.kind === 'folder' && isFolderExpanded(node.path),
            blocked: node.kind === 'file' && !isEditable(node.path),
          },
        ]"
        @click="$emit('nodeClick', node)"
      >
        <span class="node-name">
          <span class="node-icon">
            <template v-if="node.kind === 'folder'">{{ chevron(node.path) }}</template>
            <template v-else>{{ icon(node.name) }}</template>
          </span>
          {{ node.name }}
        </span>
        <small v-if="node.kind === 'file'">{{ node.meta }}</small>
      </button>
    </div>

    <div v-if="hasCode" class="ignore-summary">
      <strong>过滤规则</strong>
      <span>{{ ignoreSummary }}</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import type { VisibleTreeNode } from '@/composables/useCode'

const props = defineProps<{
  visibleTree: VisibleTreeNode[]
  selectedPath: string
  ignoreSummary: string
  hasCode: boolean
  loading: boolean
  error: string | null
  isFolderExpanded: (path: string) => boolean
  chevron: (path: string) => string
  icon: (name: string) => string
  isEditable: (path: string) => boolean
}>()

defineEmits<{
  nodeClick: [node: VisibleTreeNode]
  retry: []
}>()
</script>

<style scoped>
.file-tree {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 10px;
  min-height: 0;
  padding: 12px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.tree-head,
.ignore-summary {
  display: grid;
  gap: 4px;
}

.tree-head span,
.ignore-summary span {
  color: #71808f;
  font-size: 12px;
  line-height: 1.4;
}

.state-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: #667789;
  font-size: 13px;
}

.state-error {
  color: #e15a4a;
}

.tree-list {
  overflow: auto;
}

.file-node {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 7px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #2d3b48;
  text-align: left;
  cursor: pointer;
  font: inherit;
}

.file-node.depth-1 { padding-left: 20px; }
.file-node.depth-2 { padding-left: 36px; }
.file-node.depth-3 { padding-left: 52px; }
.file-node.depth-4 { padding-left: 68px; }

.file-node.folder.expanded .node-icon {
  color: #1f8f78;
}

.file-node.folder {
  color: #536475;
  font-weight: 700;
}

.file-node.active {
  background: #e8f4f1;
  color: #1f8f78;
}

.file-node.blocked {
  opacity: 0.72;
}

.file-node.blocked .node-icon {
  color: #9aa7b4;
}

.node-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-icon {
  display: inline-block;
  min-width: 28px;
  color: #1f8f78;
  font-size: 11px;
  font-weight: 700;
}

.file-node.folder .node-icon {
  font-size: 12px;
}

.file-node small {
  color: #71808f;
}

.ignore-summary {
  padding-top: 10px;
  border-top: 1px solid #dce3ea;
}
</style>
