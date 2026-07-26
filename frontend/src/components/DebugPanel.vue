<template>
  <div v-if="debug.enabled.value && debug.panelOpen.value" class="debug-panel">
    <header>
      <strong>调试输出</strong>
      <span class="debug-count">{{ debug.entries.value.length }} 条</span>
      <span class="debug-spacer" />
      <el-button size="small" text @click="copyAll">复制</el-button>
      <el-button size="small" text @click="debug.clear()">清空</el-button>
      <el-button size="small" text @click="debug.panelOpen.value = false">收起</el-button>
    </header>
    <ul class="debug-list">
      <li v-for="entry in reversed" :key="entry.id" :class="['debug-entry', entry.level]">
        <div class="debug-head">
          <span class="debug-time">{{ entry.at }}</span>
          <span class="debug-scope">{{ entry.scope }}</span>
          <span class="debug-message">{{ entry.message }}</span>
          <button v-if="entry.detail" class="debug-toggle" @click="toggle(entry.id)">
            {{ expanded.has(entry.id) ? '收起详情' : '展开详情' }}
          </button>
        </div>
        <pre v-if="entry.detail && expanded.has(entry.id)" class="debug-detail">{{
          entry.detail
        }}</pre>
      </li>
      <li v-if="!debug.entries.value.length" class="debug-empty">
        暂无输出。调试模式开启后，界面捕获到的每个错误都会带完整信息记录在这里。
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { useDebug } from '@/composables/useDebug'

const debug = useDebug()
const expanded = ref<Set<number>>(new Set())

const reversed = computed(() => debug.entries.value.slice().reverse())

function toggle(id: number): void {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

async function copyAll(): Promise<void> {
  try {
    await navigator.clipboard.writeText(debug.exportText())
    ElMessage.success('调试输出已复制')
  } catch {
    ElMessage.warning('浏览器拒绝了剪贴板访问，请手动选择文本复制')
  }
}
</script>

<style scoped>
.debug-panel {
  position: fixed;
  /* Docked left so it never fights the trace summary boxes pinned bottom-right. */
  left: 62px;
  bottom: 46px;
  z-index: 2400;
  display: flex;
  width: min(560px, calc(100vw - 36px));
  max-height: 46vh;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #c9a8a1;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 12px 34px rgba(19, 35, 47, 0.22);
}

header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid #e6ebf0;
  background: #fdf5f3;
  color: #8a3b2c;
  font-size: 12px;
}

.debug-count {
  color: #a8837a;
  font-size: 11px;
}

.debug-spacer {
  flex: 1;
}

.debug-list {
  margin: 0;
  padding: 6px 8px;
  min-height: 0;
  overflow-y: auto;
  list-style: none;
}

.debug-entry {
  padding: 6px 8px;
  border-left: 3px solid #d8dee6;
  border-radius: 3px;
  margin-bottom: 5px;
  background: #f8fafb;
}

.debug-entry.warn {
  border-left-color: #d99a2b;
  background: #fdf8ee;
}

.debug-entry.error {
  border-left-color: #c0483a;
  background: #fdf1ef;
}

.debug-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  font-size: 11px;
}

.debug-time {
  color: #94a1ad;
  font-family: "SFMono-Regular", Consolas, monospace;
}

.debug-scope {
  color: #55636f;
  font-weight: 700;
}

.debug-message {
  flex: 1;
  min-width: 0;
  color: #26323d;
  word-break: break-word;
}

.debug-toggle {
  border: 1px solid #d8dee6;
  border-radius: 3px;
  background: #ffffff;
  color: #586675;
  cursor: pointer;
  font: inherit;
  font-size: 10px;
  padding: 0 6px;
}

.debug-detail {
  margin: 6px 0 0;
  max-height: 220px;
  overflow: auto;
  padding: 6px 8px;
  border-radius: 3px;
  background: #ffffff;
  color: #44525f;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.debug-empty {
  padding: 10px 8px;
  color: #8a95a1;
  font-size: 11px;
  line-height: 1.6;
}
</style>
