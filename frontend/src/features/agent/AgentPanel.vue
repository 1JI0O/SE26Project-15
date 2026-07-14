<template>
  <article class="agent-panel">
    <header>
      <div>
        <h2>论文与代码 Agent</h2>
        <p>基于当前论文、代码、张量图和追溯关系回答问题；写操作必须由用户确认。</p>
      </div>
      <el-tag v-if="response?.degraded" type="warning" effect="plain">安全降级</el-tag>
      <el-tag v-else type="success" effect="plain">工具确认已启用</el-tag>
    </header>

    <div class="context-row">
      <span>论文：{{ paperRef || '未选中' }}</span>
      <span>代码：{{ codeRef || '未选中' }}</span>
      <span>图节点：{{ graphNodeId || '未选中' }}</span>
    </div>

    <el-input
      v-model="message"
      type="textarea"
      :rows="4"
      maxlength="8000"
      show-word-limit
      placeholder="例如：解释当前张量节点与论文方法的对应关系"
      @keydown.meta.enter="send"
      @keydown.ctrl.enter="send"
    />
    <div class="agent-actions">
      <span>只读工具自动执行；保存代码、重跑分析和更新追溯状态会先展示确认卡片。</span>
      <el-button type="primary" :loading="loading" :disabled="!message.trim()" @click="send">
        发送
      </el-button>
    </div>

    <section v-if="response" class="answer-block">
      <h3>Agent 回复</h3>
      <p>{{ response.answer }}</p>
      <el-alert
        v-if="response.degraded"
        type="warning"
        :closable="false"
        :title="`当前未调用 LLM：${response.degraded_reason || 'provider unavailable'}`"
      />
      <div v-if="response.citations.length" class="citation-list">
        <span v-for="citation in response.citations" :key="`${citation.side}-${citation.ref}`">
          {{ citation.side }} · {{ citation.ref }}
        </span>
      </div>
    </section>

    <section v-if="confirmation" class="confirmation-card">
      <div>
        <el-tag type="warning" effect="plain">等待确认</el-tag>
        <h3>{{ toolLabel(confirmation.tool_name) }}</h3>
        <pre>{{ JSON.stringify(confirmation.parameter_summary, null, 2) }}</pre>
      </div>
      <div v-if="confirmation.status === 'pending'" class="confirmation-actions">
        <el-button :loading="deciding" @click="decide('reject')">拒绝</el-button>
        <el-button type="primary" :loading="deciding" @click="decide('accept')">确认执行</el-button>
      </div>
      <el-alert
        v-else
        :type="confirmation.status === 'executed' ? 'success' : 'warning'"
        :closable="false"
        :title="`操作状态：${confirmation.status}${confirmation.error_summary ? ` · ${confirmation.error_summary}` : ''}`"
      />
    </section>
  </article>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { decideAgentConfirmation, queryAgent } from '@/api/agent-api'
import type { AgentConfirmation, AgentQueryResponse } from '@/types/agent'

const props = defineProps<{
  projectId: number
  paperRef?: string
  codeRef?: string
  graphNodeId?: string
}>()

const emit = defineEmits<{
  executed: []
}>()

const message = ref('')
const loading = ref(false)
const deciding = ref(false)
const response = ref<AgentQueryResponse | null>(null)
const confirmation = ref<AgentConfirmation | null>(null)

function toolLabel(toolName: string): string {
  const labels: Record<string, string> = {
    save_code_file: '保存代码修改',
    rerun_analysis: '重新运行代码分析',
    update_trace_status: '更新追溯审阅状态',
  }
  return labels[toolName] ?? toolName
}

async function send(): Promise<void> {
  if (!message.value.trim()) return
  loading.value = true
  try {
    const result = await queryAgent(props.projectId, message.value.trim(), {
      paper_block_id: props.paperRef || undefined,
      code_symbol_id: props.codeRef || undefined,
      graph_node_id: props.graphNodeId || undefined,
    })
    response.value = result
    confirmation.value = result.confirmation
  } catch (cause) {
    ElMessage.error('Agent 请求失败')
    console.error(cause)
  } finally {
    loading.value = false
  }
}

async function decide(decision: 'accept' | 'reject'): Promise<void> {
  if (!confirmation.value) return
  deciding.value = true
  try {
    confirmation.value = await decideAgentConfirmation(
      props.projectId,
      confirmation.value.confirmation_id,
      decision,
    )
    if (confirmation.value.status === 'executed') emit('executed')
  } catch (cause) {
    ElMessage.error('Agent 操作确认失败')
    console.error(cause)
  } finally {
    deciding.value = false
  }
}
</script>

<style scoped>
.agent-panel {
  display: grid;
  gap: 16px;
  padding: 16px;
}

.agent-panel header,
.agent-actions,
.confirmation-actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.agent-panel h2,
.agent-panel h3 {
  margin: 0;
}

.agent-panel header p,
.answer-block p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.context-row,
.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.context-row span,
.citation-list span {
  padding: 6px 9px;
  border-radius: 6px;
  background: #f3f7f6;
  color: #536475;
  font-size: 12px;
}

.agent-actions span {
  color: #667789;
  font-size: 12px;
  line-height: 1.5;
}

.answer-block,
.confirmation-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.confirmation-card pre {
  max-height: 220px;
  margin: 12px 0 0;
  overflow: auto;
  color: #536475;
  white-space: pre-wrap;
}

@media (max-width: 820px) {
  .agent-panel header,
  .agent-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
