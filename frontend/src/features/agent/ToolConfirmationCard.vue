<template>
  <div :class="['tool-card', tool.status]">
    <div class="tool-header">
      <el-tag :type="statusTagType" effect="plain" size="small">{{ statusLabel }}</el-tag>
      <span class="tool-name">{{ tool.tool }}</span>
    </div>
    <p class="tool-desc">{{ tool.description }}</p>
    <div class="tool-files">
      <el-tag
        v-for="file in tool.affectedFiles"
        :key="file"
        size="small"
        type="info"
        effect="plain"
      >
        {{ file }}
      </el-tag>
    </div>
    <div v-if="tool.status === 'pending'" class="tool-actions">
      <el-button type="primary" size="small" @click="$emit('confirm', tool.id)">
        确认执行
      </el-button>
      <el-button size="small" @click="$emit('reject', tool.id)">
        驳回
      </el-button>
    </div>
    <div v-else-if="tool.status === 'confirmed'" class="tool-result">
      <el-icon><i class="el-icon-check" /></el-icon>
      <span>已确认执行</span>
    </div>
    <div v-else-if="tool.status === 'rejected'" class="tool-result rejected">
      <el-icon><i class="el-icon-close" /></el-icon>
      <span>已驳回</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ToolCall } from '@/composables/useAgent'

const props = defineProps<{
  tool: ToolCall
}>()

defineEmits<{
  confirm: [toolId: string]
  reject: [toolId: string]
}>()

const statusTagType = computed(() => {
  switch (props.tool.status) {
    case 'confirmed': return 'success'
    case 'rejected': return 'danger'
    case 'executed': return 'success'
    default: return 'warning'
  }
})

const statusLabel = computed(() => {
  switch (props.tool.status) {
    case 'confirmed': return '已确认'
    case 'rejected': return '已驳回'
    case 'executed': return '已执行'
    default: return '待确认'
  }
})
</script>

<style scoped>
.tool-card {
  padding: 14px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
  display: grid;
  gap: 10px;
}

.tool-card.confirmed {
  border-color: #1f8f78;
  background: #f0faf7;
}

.tool-card.rejected {
  border-color: #e15a4a;
  background: #fef2f2;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-name {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  color: #16232f;
  font-weight: 600;
}

.tool-desc {
  margin: 0;
  color: #2d3b48;
  line-height: 1.6;
  font-size: 14px;
}

.tool-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tool-actions {
  display: flex;
  gap: 8px;
  padding-top: 4px;
}

.tool-result {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #1f8f78;
  font-size: 13px;
  font-weight: 600;
}

.tool-result.rejected {
  color: #e15a4a;
}
</style>
