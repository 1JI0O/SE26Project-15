<template>
  <div class="editor-shell">
    <div class="editor-tabs">
      <span>{{ file?.path || '' }}</span>
      <div>
        <el-tag v-if="file" size="small" :type="file.statusType" effect="plain">
          {{ file.status }}
        </el-tag>
        <el-tag v-if="isDirty" size="small" type="warning" effect="plain">
          未保存演示
        </el-tag>
        <el-tag v-else-if="file" size="small" type="success" effect="plain">已同步</el-tag>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!file" class="editor-body">
      <el-empty description="从左侧文件树选择可编辑的代码或文本文件" />
    </div>

    <!-- Editor content -->
    <div v-else class="editor-body">
      <aside class="line-gutter">
        <span v-for="line in lineNumbers" :key="line">{{ line }}</span>
      </aside>
      <textarea
        :value="content"
        spellcheck="false"
        class="code-editor"
        :aria-label="`${file.path} 可编辑代码内容`"
        @input="$emit('input', $event)"
      />
    </div>

    <div v-if="file" class="editor-footer">
      <span>当前符号: {{ file.symbol }}</span>
      <span>关联段落: {{ file.paperRef }}</span>
      <el-button
        size="small"
        type="primary"
        plain
        :loading="saving"
        @click="$emit('save')"
      >
        保存编辑
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { CodeFile } from '@/composables/useCode'

defineProps<{
  file: CodeFile | undefined
  content: string
  lineNumbers: number[]
  isDirty: boolean
  saving: boolean
}>()

defineEmits<{
  input: [event: Event]
  save: []
}>()
</script>

<style scoped>
.editor-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.editor-tabs,
.editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  background: #ffffff;
}

.editor-tabs {
  border-bottom: 1px solid #dce3ea;
}

.editor-tabs div {
  display: inline-flex;
  gap: 6px;
}

.editor-footer {
  border-top: 1px solid #dce3ea;
  color: #667789;
  font-size: 12px;
}

.editor-body {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
  background: #fbfcfd;
}

.line-gutter {
  overflow: hidden;
  padding: 14px 10px;
  border-right: 1px solid #e4e9ee;
  color: #9aa7b4;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 22px;
  text-align: right;
  user-select: none;
}

.line-gutter span {
  display: block;
}

.code-editor {
  width: 100%;
  height: 100%;
  min-height: 0;
  resize: none;
  border: 0;
  outline: 0;
  padding: 14px;
  background: #fbfcfd;
  color: #16232f;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 22px;
  white-space: pre;
  overflow: auto;
}

@media (max-width: 820px) {
  .editor-tabs,
  .editor-footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
