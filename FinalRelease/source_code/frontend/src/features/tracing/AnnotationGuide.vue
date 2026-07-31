<template>
  <div v-if="annotation.active" class="annotation-guide" role="status" aria-live="polite">
    <ol class="step-rail">
      <li v-for="item in rail" :key="item.key" :class="['rail-item', item.state]">
        <span class="rail-dot">{{ item.state === 'done' ? '✓' : item.index }}</span>
        <span class="rail-label">{{ item.label }}</span>
      </li>
    </ol>

    <div class="guide-body">
      <p class="guide-instruction">{{ instruction }}</p>
    </div>

    <div class="guide-actions">
      <template v-if="isConfirming">
        <el-button size="small" @click="annotation.retryPick()">重选</el-button>
        <el-button size="small" type="primary" @click="annotation.confirmPick()">
          {{ annotation.step === 'confirm-paper' ? '确认，下一步选代码' : '确认，填写信息' }}
        </el-button>
      </template>
      <el-button
        size="small"
        text
        :disabled="annotation.submitting"
        @click="annotation.cancel()"
      >
        退出标注
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { useAnnotationStore } from '@/stores/annotation'

const annotation = useAnnotationStore()

const isConfirming = computed(
  () => annotation.step === 'confirm-paper' || annotation.step === 'confirm-code',
)

const instruction = computed(() => {
  switch (annotation.step) {
    case 'select-paper':
      return '第 1 步：在论文中拖选一段文字（或点击段落、公式、图表）。'
    case 'confirm-paper':
      return '已选中论文片段。可继续点选其他条目切换，确认后进入下一步。'
    case 'select-code':
      return '第 2 步：在代码编辑器中拖选需要关联的若干行。'
    case 'confirm-code':
      return '已选中代码片段。可继续拖选切换，确认后填写关系信息。'
    case 'form':
      return '第 3 步：填写关系类型、置信度与描述。'
    default:
      return ''
  }
})

/** Three-stage rail; both sides collapse into one step each. */
const rail = computed(() => {
  const paperState = annotation.paperConfirmed
    ? 'done'
    : annotation.step === 'select-paper' || annotation.step === 'confirm-paper'
      ? 'current'
      : 'todo'
  const codeState = annotation.codeConfirmed
    ? 'done'
    : annotation.step === 'select-code' || annotation.step === 'confirm-code'
      ? 'current'
      : 'todo'
  const formState = annotation.step === 'form' ? 'current' : 'todo'
  return [
    { key: 'paper', index: 1, label: '选论文', state: paperState },
    { key: 'code', index: 2, label: '选代码', state: codeState },
    { key: 'form', index: 3, label: '填信息', state: formState },
  ]
})
</script>

<style scoped>
.annotation-guide {
  grid-area: guide;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 8px 14px;
  border-bottom: 1px solid #d6e4df;
  background: #f2f9f6;
  color: #24333d;
  font-size: 13px;
}

.step-rail {
  display: flex;
  flex: none;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
  white-space: nowrap;
}

.rail-item {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #8a9aa6;
}

.rail-item + .rail-item::before {
  content: '›';
  margin-right: 5px;
  color: #b6c4cd;
}

.rail-dot {
  display: inline-flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-size: 11px;
  line-height: 1;
}

.rail-item.current {
  color: #1f8f78;
  font-weight: 600;
}

.rail-item.done {
  color: #67c23a;
}

.guide-body {
  min-width: 0;
  overflow: hidden;
}

.guide-instruction {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.guide-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
</style>
