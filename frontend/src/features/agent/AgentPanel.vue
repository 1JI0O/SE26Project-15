<template>
  <article class="agent-panel">
    <header class="agent-header">
      <div>
        <h2>AI Agent</h2>
        <p>自动分析论文与代码的对应关系，生成追溯建议和冲突检测。写操作需人工确认。</p>
      </div>
      <div class="agent-stats">
        <el-tag type="warning" effect="plain" size="small">{{ pendingCount }} 待确认</el-tag>
        <el-tag type="success" effect="plain" size="small">{{ confirmedCount }} 已确认</el-tag>
      </div>
    </header>

    <!-- Degraded state -->
    <div v-if="degraded" class="degraded-banner">
      <el-tag type="warning" effect="plain" size="small">降级模式</el-tag>
      <span>Agent 后端服务暂不可用，当前为占位演示数据。代码浏览功能不受影响。</span>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="state-placeholder">
      <el-icon class="is-loading" :size="24"><i class="el-icon-loading" /></el-icon>
      <span>Agent 分析中...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="state-placeholder state-error">
      <span>{{ error }}</span>
    </div>

    <!-- Empty state -->
    <div v-else-if="!messages.length && !pendingTools.length" class="state-placeholder">
      <span>上传论文和代码后，Agent 将自动分析并生成建议</span>
    </div>

    <!-- Content -->
    <template v-else>
      <!-- Messages -->
      <div class="message-list">
        <div
          v-for="msg in messages"
          :key="msg.id"
          :class="['message', msg.role]"
        >
          <div class="message-meta">
            <strong>{{ msg.role === 'agent' ? 'Agent' : '操作者' }}</strong>
            <span>{{ msg.timestamp }}</span>
          </div>
          <p>{{ msg.content }}</p>
        </div>
      </div>

      <!-- Pending tool confirmations -->
      <div v-if="pendingTools.length" class="tool-section">
        <h3>工具调用确认</h3>
        <p class="tool-section-desc">以下操作将修改项目数据，请确认或驳回。</p>
        <div class="tool-list">
          <ToolConfirmationCard
            v-for="tool in pendingTools"
            :key="tool.id"
            :tool="tool"
            @confirm="$emit('confirmTool', $event)"
            @reject="$emit('rejectTool', $event)"
          />
        </div>
      </div>
    </template>
  </article>
</template>

<script setup lang="ts">
import type { AgentMessage, ToolCall } from '@/composables/useAgent'
import ToolConfirmationCard from './ToolConfirmationCard.vue'

defineProps<{
  messages: AgentMessage[]
  pendingTools: ToolCall[]
  loading: boolean
  error: string | null
  degraded: boolean
  confirmedCount: number
  rejectedCount: number
  pendingCount: number
}>()

defineEmits<{
  confirmTool: [toolId: string]
  rejectTool: [toolId: string]
}>()
</script>

<style scoped>
.agent-panel {
  display: grid;
  gap: 16px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.agent-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.agent-header h2 {
  margin: 0;
}

.agent-header p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.agent-stats {
  display: flex;
  gap: 6px;
}

.degraded-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 6px;
  background: #fffbeb;
  border: 1px solid #fbbf24;
  color: #92400e;
  font-size: 13px;
}

.state-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 32px;
  color: #667789;
}

.state-error {
  color: #e15a4a;
}

.message-list {
  display: grid;
  gap: 12px;
}

.message {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f8fafc;
}

.message.agent {
  border-left: 3px solid #1f8f78;
}

.message.user {
  border-left: 3px solid #667789;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.message-meta strong {
  font-size: 13px;
  color: #16232f;
}

.message-meta span {
  font-size: 12px;
  color: #9aa7b4;
}

.message p {
  margin: 0;
  color: #2d3b48;
  line-height: 1.7;
  font-size: 14px;
}

.tool-section {
  padding-top: 8px;
  border-top: 1px solid #edf1f4;
}

.tool-section h3 {
  margin: 0;
  font-size: 15px;
  color: #16232f;
}

.tool-section-desc {
  margin: 4px 0 12px;
  color: #667789;
  font-size: 13px;
}

.tool-list {
  display: grid;
  gap: 10px;
}
</style>
