<template>
  <article class="agent-panel">
    <header class="agent-toolbar">
      <el-tooltip :content="mode === 'chat' ? '会话历史' : '返回会话'" placement="bottom">
        <el-button
          text
          :icon="mode === 'chat' ? Clock : ArrowLeft"
          :aria-label="mode === 'chat' ? '会话历史' : '返回会话'"
          @click="mode = mode === 'chat' ? 'history' : 'chat'"
        />
      </el-tooltip>
      <strong :title="activeConversation?.title">{{ toolbarTitle }}</strong>
      <div class="toolbar-actions">
        <el-tooltip content="Agent 能力" placement="bottom">
          <el-button
            text
            :icon="SetUp"
            aria-label="Agent 能力"
            @click="openCapabilities"
          />
        </el-tooltip>
        <el-tooltip content="Agent 记忆" placement="bottom">
          <el-button
            text
            :icon="CollectionTag"
            aria-label="Agent 记忆"
            @click="openMemories"
          />
        </el-tooltip>
        <el-tooltip content="新建会话" placement="bottom">
          <el-button text :icon="Plus" aria-label="新建会话" @click="startConversation()" />
        </el-tooltip>
      </div>
    </header>

    <section v-if="mode === 'history'" class="session-view">
      <div class="section-heading">
        <span>会话</span>
        <label><input v-model="showArchived" type="checkbox" @change="loadConversations()" /> 已归档</label>
      </div>
      <div v-if="conversationLoading" class="panel-state">正在加载会话…</div>
      <div v-else-if="!conversations.length" class="panel-state">暂无会话</div>
      <div v-else class="session-list">
        <button
          v-for="conversation in conversations"
          :key="conversation.conversation_id"
          :class="['session-item', { active: conversation.conversation_id === activeConversationId }]"
          @click="activateConversation(conversation.conversation_id)"
        >
          <span class="session-title">{{ conversation.title }}</span>
          <small>
            {{ conversation.message_count }} 条消息 · {{ formatTime(conversation.updated_at) }}
            <span v-if="conversation.status === 'archived'"> · 已归档</span>
          </small>
        </button>
      </div>
      <div v-if="activeConversation" class="session-actions">
        <el-button size="small" :icon="EditPen" @click="renameActive">重命名</el-button>
        <el-button
          v-if="activeConversation.status === 'active'"
          size="small"
          :icon="FolderDelete"
          @click="archiveActive"
        >
          归档
        </el-button>
      </div>
    </section>

    <section v-else-if="mode === 'memory'" class="memory-view">
      <div class="section-heading">
        <span>项目与跨项目记忆</span>
        <small>{{ memories.length }} 条</small>
      </div>
      <div class="memory-create">
        <el-input
          v-model="memoryDraft"
          type="textarea"
          :rows="2"
          maxlength="8000"
          placeholder="记录偏好、约束或项目决策"
        />
        <div>
          <el-select v-model="memoryScope" size="small" aria-label="记忆范围">
            <el-option label="当前项目" value="project" />
            <el-option label="跨项目" value="global" />
          </el-select>
          <el-button
            size="small"
            type="primary"
            :loading="memorySaving"
            :disabled="!memoryDraft.trim()"
            @click="addMemory"
          >
            记录
          </el-button>
        </div>
      </div>
      <div v-if="memoryLoading" class="panel-state">正在加载记忆…</div>
      <div v-else-if="!memories.length" class="panel-state">暂无记忆</div>
      <div v-else class="memory-list">
        <article v-for="memory in memories" :key="memory.memory_id" class="memory-item">
          <div>
            <span :class="['scope-tag', memory.scope]">
              {{ memory.scope === 'global' ? '跨项目' : '当前项目' }}
            </span>
            <span>{{ kindLabel(memory.kind) }}</span>
          </div>
          <p>{{ memory.content }}</p>
          <el-button
            text
            :icon="Delete"
            aria-label="删除记忆"
            @click="removeMemory(memory.memory_id)"
          />
        </article>
      </div>
    </section>

    <section v-else-if="mode === 'capabilities'" class="capability-view">
      <div class="section-heading">
        <span>Skill 与 Tool</span>
        <small>{{ capabilities.filter((item) => item.eligible).length }} 个可用</small>
      </div>
      <p class="capability-notice">
        外部能力默认关闭。启用前需明确标记为可信；写工具仍需逐次确认。
      </p>
      <div v-if="capabilityLoading" class="panel-state">正在发现能力…</div>
      <div v-else class="capability-list">
        <article
          v-for="capability in capabilities"
          :key="capability.capability_id"
          class="capability-item"
        >
          <div class="capability-main">
            <div>
              <span class="capability-kind">{{ capability.kind }}</span>
              <strong>{{ capability.title }}</strong>
            </div>
            <p>{{ capability.description }}</p>
            <small :title="capability.source">{{ shortRef(capability.source) }}</small>
          </div>
          <div class="capability-controls">
            <label v-if="capability.source !== 'builtin' && capability.source !== 'bundled'">
              <input
                :checked="capability.trusted"
                type="checkbox"
                @change="setCapabilityTrust(capability, $event)"
              />
              信任
            </label>
            <el-switch
              :model-value="capability.enabled"
              size="small"
              :disabled="capabilityUpdating === capability.capability_id"
              @change="setCapabilityEnabled(capability, Boolean($event))"
            />
          </div>
        </article>
      </div>
    </section>

    <template v-else>
      <div class="chat-stage">
        <div v-if="hasContext" class="context-strip">
          <span v-if="paperRef" :title="paperRef">论文 · {{ paperRef }}</span>
          <span v-if="codeRef" :title="codeRef">代码 · {{ shortRef(codeRef) }}</span>
          <span v-if="graphNodeId" :title="graphNodeId">图 · {{ shortRef(graphNodeId) }}</span>
        </div>

        <section ref="messageViewport" class="message-viewport">
        <div v-if="conversationLoading" class="panel-state">正在加载对话…</div>
        <div v-else-if="!messages.length" class="empty-chat">
          <ChatDotRound />
          <strong>开始分析</strong>
          <span>可询问论文、代码、追溯关系或模型架构。</span>
        </div>
        <template v-else>
          <article
            v-for="item in messages"
            :key="item.message_id"
            :class="['message-row', item.role]"
          >
            <div v-if="item.role === 'tool'" class="persisted-tool">
              <span>工具执行结果</span>
              <code>{{ item.content }}</code>
            </div>
            <div v-else class="message-bubble">
              <div class="message-meta">
                <strong>{{ item.role === 'user' ? '你' : 'Agent' }}</strong>
                <time>{{ formatTime(item.created_at) }}</time>
              </div>
              <p v-if="item.role === 'user'" class="message-plain">{{ item.content }}</p>
              <div
                v-else
                class="message-markdown"
                v-html="renderAgentMarkdown(item.content)"
              />

              <div v-if="item.tool_events.length" class="tool-event-list">
                <div
                  v-for="(event, index) in item.tool_events"
                  :key="`${item.message_id}-${event.tool_name}-${index}`"
                  :class="['tool-event', event.status]"
                >
                  <span class="event-status" />
                  <div>
                    <strong>{{ toolLabel(event.tool_name) }}</strong>
                    <small>{{ event.summary }}</small>
                  </div>
                  <button
                    v-if="event.result.ui_action"
                    type="button"
                    @click="emitUiAction(event.result.ui_action)"
                  >
                    定位
                  </button>
                </div>
              </div>

              <div v-if="item.citations.length" class="citation-list">
                <span
                  v-for="citation in item.citations"
                  :key="`${item.message_id}-${citation.side}-${citation.ref}`"
                  :title="citation.quote"
                >
                  {{ citation.side }} · {{ shortRef(citation.ref) }}
                </span>
              </div>

              <div v-if="item.degraded" class="degraded-note">
                安全降级 · {{ item.degraded_reason || 'provider unavailable' }}
              </div>

              <section v-if="item.confirmation" class="confirmation-card">
                <header>
                  <div>
                    <span>需要确认</span>
                    <strong>{{ toolLabel(item.confirmation.tool_name) }}</strong>
                  </div>
                  <small>{{ confirmationLabel(item.confirmation.status) }}</small>
                </header>
                <pre>{{ JSON.stringify(item.confirmation.parameter_summary, null, 2) }}</pre>
                <div v-if="item.confirmation.status === 'pending'" class="confirmation-actions">
                  <el-button
                    size="small"
                    :loading="decidingId === item.confirmation.confirmation_id"
                    @click="decide(item.confirmation, 'reject')"
                  >
                    拒绝
                  </el-button>
                  <el-button
                    size="small"
                    type="primary"
                    :loading="decidingId === item.confirmation.confirmation_id"
                    @click="decide(item.confirmation, 'accept')"
                  >
                    执行
                  </el-button>
                </div>
                <p v-if="item.confirmation.error_summary" class="confirmation-error">
                  {{ item.confirmation.error_summary }}
                </p>
              </section>
            </div>
          </article>
        </template>
        <details v-if="sending" class="run-progress" open>
          <summary>
            <span class="progress-spinner" />
            {{ activeProgress || 'Agent 正在分析环境' }}
          </summary>
          <div v-if="liveToolEvents.length" class="live-tool-list">
            <div
              v-for="(event, index) in liveToolEvents"
              :key="`${event.tool_name}-${index}`"
              :class="['tool-event', event.status]"
            >
              <span class="event-status" />
              <div>
                <strong>{{ toolLabel(event.tool_name) }}</strong>
                <small>{{ event.summary }}</small>
              </div>
            </div>
          </div>
        </details>
        </section>
      </div>

      <footer class="composer">
        <el-input
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 6 }"
          maxlength="8000"
          resize="none"
          :disabled="hasPendingConfirmation"
          :placeholder="hasPendingConfirmation ? '请先处理待确认的工具操作' : '询问或要求 Agent 修改当前环境'"
          @keydown.meta.enter.prevent="send"
          @keydown.ctrl.enter.prevent="send"
        />
        <div class="composer-footer">
          <span>{{ contextLabel }}</span>
          <el-button
            circle
            type="primary"
            :icon="Promotion"
            :loading="sending"
            :disabled="!draft.trim() || !activeConversationId || hasPendingConfirmation"
            aria-label="发送消息"
            @click="send"
          />
        </div>
      </footer>
    </template>
  </article>
</template>

<script setup lang="ts">
import 'katex/dist/katex.min.css'
import {
  ArrowLeft,
  ChatDotRound,
  Clock,
  CollectionTag,
  Delete,
  EditPen,
  FolderDelete,
  Plus,
  Promotion,
  SetUp,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import {
  createAgentConversation,
  createAgentMemory,
  decideConversationConfirmation,
  deleteAgentMemory,
  getAgentConversation,
  listAgentCapabilities,
  listAgentConversations,
  listAgentMemories,
  streamAgentRunEvents,
  submitAgentRun,
  updateAgentCapability,
  updateAgentConversation,
} from '@/api/agent-api'
import { renderPaperMarkdown } from '@/features/papers/markdown-renderer'
import type {
  AgentCapability,
  AgentConfirmation,
  AgentConversation,
  AgentConversationDetail,
  AgentMemory,
  AgentMessage,
  AgentRunEvent,
  AgentToolEvent,
  AgentUiAction,
} from '@/types/agent'

const props = defineProps<{
  projectId: number
  paperRef?: string
  codeRef?: string
  graphNodeId?: string
  filePath?: string
  line?: number
  traceId?: string
  graphRootSymbol?: string
}>()

const emit = defineEmits<{
  executed: []
  uiAction: [action: AgentUiAction]
}>()

const mode = ref<'chat' | 'history' | 'memory' | 'capabilities'>('chat')
const conversations = ref<AgentConversation[]>([])
const activeConversationId = ref('')
const detail = ref<AgentConversationDetail | null>(null)
const draft = ref('')
const sending = ref(false)
const conversationLoading = ref(false)
const decidingId = ref('')
const showArchived = ref(false)
const messageViewport = ref<HTMLElement | null>(null)
const memories = ref<AgentMemory[]>([])
const memoryDraft = ref('')
const memoryScope = ref<'project' | 'global'>('project')
const memoryLoading = ref(false)
const memorySaving = ref(false)
const capabilities = ref<AgentCapability[]>([])
const capabilityLoading = ref(false)
const capabilityUpdating = ref('')
const activeProgress = ref('')
const liveToolEvents = ref<AgentToolEvent[]>([])
let initializeGeneration = 0
let conversationLoadGeneration = 0
let activationGeneration = 0
let activeRunAbort: AbortController | null = null

const activeConversation = computed(() =>
  conversations.value.find((item) => item.conversation_id === activeConversationId.value),
)
const messages = computed<AgentMessage[]>(() =>
  (detail.value?.messages || []).filter((item) => item.role !== 'system'),
)
const hasPendingConfirmation = computed(() =>
  messages.value.some((item) => item.confirmation?.status === 'pending'),
)
const toolbarTitle = computed(() => {
  if (mode.value === 'history') return '会话历史'
  if (mode.value === 'memory') return 'Agent 记忆'
  if (mode.value === 'capabilities') return 'Agent 能力'
  return activeConversation.value?.title || 'Agent'
})
const hasContext = computed(() => Boolean(props.paperRef || props.codeRef || props.graphNodeId))
const contextLabel = computed(() => {
  const count = [props.paperRef, props.codeRef, props.graphNodeId].filter(Boolean).length
  return count ? `已附加 ${count} 项上下文` : '项目上下文自动注入'
})

onMounted(initialize)
watch(
  () => props.projectId,
  () => {
    activeRunAbort?.abort()
    void initialize()
  },
)

async function initialize(): Promise<void> {
  const generation = ++initializeGeneration
  const projectId = props.projectId
  activeConversationId.value = ''
  detail.value = null
  mode.value = 'chat'
  await loadConversations(projectId)
  if (generation !== initializeGeneration || projectId !== props.projectId) return
  const active = conversations.value.find((item) => item.status === 'active')
  if (active) await activateConversation(active.conversation_id, true, projectId)
  else await startConversation(true, projectId)
}

async function loadConversations(projectId = props.projectId): Promise<void> {
  const generation = ++conversationLoadGeneration
  conversationLoading.value = true
  try {
    const loaded = await listAgentConversations(projectId, showArchived.value)
    if (generation === conversationLoadGeneration && projectId === props.projectId) {
      conversations.value = loaded
    }
  } catch (cause) {
    ElMessage.error('会话历史加载失败')
    console.error(cause)
  } finally {
    if (generation === conversationLoadGeneration) conversationLoading.value = false
  }
}

async function startConversation(
  preserveMode = false,
  projectId = props.projectId,
): Promise<void> {
  try {
    const conversation = await createAgentConversation(projectId)
    if (projectId !== props.projectId) return
    await loadConversations(projectId)
    activeConversationId.value = conversation.conversation_id
    detail.value = { ...conversation, messages: [] }
    if (!preserveMode) mode.value = 'chat'
    draft.value = ''
  } catch (cause) {
    ElMessage.error('新建会话失败')
    console.error(cause)
  }
}

async function activateConversation(
  conversationId: string,
  preserveMode = false,
  projectId = props.projectId,
): Promise<void> {
  const generation = ++activationGeneration
  conversationLoading.value = true
  try {
    activeConversationId.value = conversationId
    const loaded = await getAgentConversation(projectId, conversationId)
    if (generation !== activationGeneration || projectId !== props.projectId) return
    detail.value = loaded
    if (!preserveMode) mode.value = 'chat'
    await scrollToBottom()
  } catch (cause) {
    ElMessage.error('会话加载失败')
    console.error(cause)
  } finally {
    if (generation === activationGeneration) conversationLoading.value = false
  }
}

async function renameActive(): Promise<void> {
  const conversation = activeConversation.value
  if (!conversation) return
  try {
    const result = await ElMessageBox.prompt('输入新的会话名称', '重命名会话', {
      inputValue: conversation.title,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
    })
    await updateAgentConversation(props.projectId, conversation.conversation_id, {
      title: result.value.trim(),
    })
    await loadConversations()
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') console.error(cause)
  }
}

async function archiveActive(): Promise<void> {
  const conversation = activeConversation.value
  if (!conversation) return
  try {
    await ElMessageBox.confirm('归档后仍可在会话历史中查看。', '归档当前会话')
    await updateAgentConversation(props.projectId, conversation.conversation_id, {
      status: 'archived',
    })
    await loadConversations()
    const next = conversations.value.find((item) => item.status === 'active')
    if (next) await activateConversation(next.conversation_id)
    else await startConversation()
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') console.error(cause)
  }
}

async function send(): Promise<void> {
  const text = draft.value.trim()
  if (!text || !activeConversationId.value || sending.value || hasPendingConfirmation.value) return
  const projectId = props.projectId
  const conversationId = activeConversationId.value
  const controller = new AbortController()
  activeRunAbort = controller
  sending.value = true
  draft.value = ''
  activeProgress.value = '正在创建持久化运行'
  liveToolEvents.value = []
  let submitted = false
  try {
    const response = await submitAgentRun(
      projectId,
      conversationId,
      text,
      {
        paper_block_id: props.paperRef || undefined,
        code_symbol_id: props.codeRef || undefined,
        graph_node_id: props.graphNodeId || undefined,
        file_path: props.filePath || undefined,
        line: props.line,
        trace_id: props.traceId || undefined,
        graph_root_symbol: props.graphRootSymbol || undefined,
      },
    )
    submitted = true
    if (props.projectId === projectId && activeConversationId.value === conversationId && detail.value) {
      detail.value.messages.push(response.user_message)
      Object.assign(detail.value, response.conversation)
    }
    const streamingMessage: AgentMessage = {
      message_id: `stream-${response.run_id}`,
      conversation_id: conversationId,
      project_id: projectId,
      role: 'assistant',
      content: '',
      citations: [],
      tool_events: [],
      degraded: false,
      degraded_reason: null,
      run_id: response.run_id,
      confirmation: null,
      created_at: new Date().toISOString(),
    }
    if (props.projectId === projectId && activeConversationId.value === conversationId) {
      detail.value?.messages.push(streamingMessage)
      await scrollToBottom()
    }
    await streamAgentRunEvents(
      projectId,
      response.run_id,
      (event) => {
        if (props.projectId === projectId && activeConversationId.value === conversationId) {
          handleRunEvent(event, streamingMessage)
        }
      },
      controller.signal,
    )
    const completedDetail = await getAgentConversation(projectId, conversationId)
    if (props.projectId === projectId && activeConversationId.value === conversationId) {
      detail.value = completedDetail
      const completed = [...completedDetail.messages]
        .reverse()
        .find((item) => item.run_id === response.run_id)
      if (completed) runUiActions(completed)
      await loadConversations(projectId)
      await scrollToBottom()
    }
  } catch (cause) {
    if (!submitted) draft.value = text
    if (
      submitted &&
      props.projectId === projectId &&
      activeConversationId.value === conversationId
    ) {
      detail.value = await getAgentConversation(projectId, conversationId)
    }
    if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
      ElMessage.error('Agent 请求失败')
      console.error(cause)
    }
  } finally {
    if (activeRunAbort === controller) activeRunAbort = null
    sending.value = false
    activeProgress.value = ''
    liveToolEvents.value = []
  }
}

function handleRunEvent(event: AgentRunEvent, streamingMessage: AgentMessage): void {
  const payload = event.payload
  if (event.event_type === 'message.delta') {
    streamingMessage.content += String(payload.delta || '')
    void scrollToBottom()
    return
  }
  if (event.event_type === 'message.reset') {
    streamingMessage.content = ''
    return
  }
  if (event.event_type === 'reasoning.summary') {
    activeProgress.value = String(payload.summary || '正在分析当前证据')
    return
  }
  if (event.event_type === 'tool.started') {
    liveToolEvents.value.push({
      tool_name: String(payload.tool_name || 'tool'),
      status: 'running',
      summary: String(payload.summary || '正在执行'),
      result: {},
    })
    activeProgress.value = String(payload.summary || '正在与项目环境交互')
    return
  }
  if (['tool.completed', 'tool.failed', 'tool.reused'].includes(event.event_type)) {
    const name = String(payload.tool_name || 'tool')
    const pending = [...liveToolEvents.value]
      .reverse()
      .find((item) => item.tool_name === name && item.status === 'running')
    const status = event.event_type === 'tool.failed' ? 'failed' : 'succeeded'
    if (pending) {
      pending.status = status
      pending.summary = String(payload.summary || pending.summary)
      pending.result = (payload.result as Record<string, unknown>) || {}
    } else {
      liveToolEvents.value.push({
        tool_name: name,
        status,
        summary: String(payload.summary || event.event_type),
        result: (payload.result as Record<string, unknown>) || {},
      })
    }
    return
  }
  if (event.event_type === 'run.started') activeProgress.value = '正在读取会话与项目上下文'
  if (event.event_type === 'run.failed') activeProgress.value = '运行失败，正在保存进度'
}

async function decide(
  confirmation: AgentConfirmation,
  decision: 'accept' | 'reject',
): Promise<void> {
  if (!activeConversationId.value) return
  decidingId.value = confirmation.confirmation_id
  try {
    const response = await decideConversationConfirmation(
      props.projectId,
      activeConversationId.value,
      confirmation.confirmation_id,
      decision,
    )
    detail.value = await getAgentConversation(props.projectId, activeConversationId.value)
    if (response.confirmation.status === 'executed') emit('executed')
    if (response.assistant_message) runUiActions(response.assistant_message)
    await loadConversations()
    await scrollToBottom()
  } catch (cause) {
    ElMessage.error('工具操作确认失败')
    console.error(cause)
  } finally {
    decidingId.value = ''
  }
}

function runUiActions(message: AgentMessage): void {
  for (const event of message.tool_events) {
    if (event.status === 'succeeded' && event.result.ui_action) {
      emitUiAction(event.result.ui_action)
    }
  }
}

function emitUiAction(action: AgentUiAction): void {
  emit('uiAction', action)
}

async function openMemories(): Promise<void> {
  mode.value = 'memory'
  memoryLoading.value = true
  try {
    memories.value = await listAgentMemories(props.projectId)
  } catch (cause) {
    ElMessage.error('Agent 记忆加载失败')
    console.error(cause)
  } finally {
    memoryLoading.value = false
  }
}

async function openCapabilities(): Promise<void> {
  mode.value = 'capabilities'
  capabilityLoading.value = true
  try {
    capabilities.value = await listAgentCapabilities(props.projectId)
  } catch (cause) {
    ElMessage.error('Agent 能力发现失败')
    console.error(cause)
  } finally {
    capabilityLoading.value = false
  }
}

async function setCapabilityEnabled(
  capability: AgentCapability,
  enabled: boolean,
): Promise<void> {
  await patchCapability(capability, enabled, capability.trusted)
}

async function setCapabilityTrust(
  capability: AgentCapability,
  event: Event,
): Promise<void> {
  const trusted = (event.target as HTMLInputElement).checked
  await patchCapability(capability, capability.enabled, trusted)
}

async function patchCapability(
  capability: AgentCapability,
  enabled: boolean,
  trusted: boolean,
): Promise<void> {
  capabilityUpdating.value = capability.capability_id
  try {
    await updateAgentCapability(
      props.projectId,
      capability.capability_id,
      { enabled, trusted },
    )
    capabilities.value = await listAgentCapabilities(props.projectId)
  } catch (cause) {
    ElMessage.error('能力设置更新失败')
    console.error(cause)
  } finally {
    capabilityUpdating.value = ''
  }
}

async function addMemory(): Promise<void> {
  const content = memoryDraft.value.trim()
  if (!content) return
  memorySaving.value = true
  try {
    await createAgentMemory(props.projectId, {
      content,
      scope: memoryScope.value,
      kind: 'preference',
      conversation_id: activeConversationId.value || undefined,
    })
    memoryDraft.value = ''
    memories.value = await listAgentMemories(props.projectId)
  } catch (cause) {
    ElMessage.error('记忆保存失败')
    console.error(cause)
  } finally {
    memorySaving.value = false
  }
}

async function removeMemory(memoryId: string): Promise<void> {
  try {
    await deleteAgentMemory(props.projectId, memoryId)
    memories.value = memories.value.filter((item) => item.memory_id !== memoryId)
  } catch (cause) {
    ElMessage.error('记忆删除失败')
    console.error(cause)
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  const viewport = messageViewport.value
  if (viewport) viewport.scrollTop = viewport.scrollHeight
}

function shortRef(value: string): string {
  if (value.length <= 34) return value
  return `…${value.slice(-33)}`
}

function renderAgentMarkdown(content: string): string {
  return renderPaperMarkdown(content, () => '')
}

function formatTime(value: string): string {
  const date = new Date(value)
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function kindLabel(kind: AgentMemory['kind']): string {
  return {
    fact: '事实',
    preference: '偏好',
    decision: '决策',
    constraint: '约束',
    summary: '摘要',
  }[kind]
}

function confirmationLabel(status: AgentConfirmation['status']): string {
  return {
    pending: '等待处理',
    approved: '已批准',
    rejected: '已拒绝',
    expired: '已过期',
    executed: '已执行',
    failed: '执行失败',
  }[status]
}

function toolLabel(toolName: string): string {
  const labels: Record<string, string> = {
    get_project_overview: '读取项目环境',
    search_paper: '检索论文',
    get_paper_block: '读取论文段落',
    search_code: '检索代码',
    read_code_file: '读取代码文件',
    get_code_symbol: '读取代码符号',
    get_architecture: '读取架构图',
    get_graph_node: '读取图节点',
    list_trace_links: '读取追溯关系',
    get_trace_detail: '读取追溯证据',
    recall_memory: '检索 Agent 记忆',
    propose_code_patch: '生成代码补丁',
    analyze_change_risk: '分析修改风险',
    open_code_location: '定位代码',
    focus_architecture: '聚焦架构图',
    save_code_file: '保存代码修改',
    rerun_analysis: '重新运行分析',
    update_trace_status: '更新追溯状态',
    create_trace_link: '创建追溯关系',
  }
  return labels[toolName] ?? toolName
}
</script>

<style scoped>
.agent-panel {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: 36px minmax(0, 1fr) auto;
  overflow: hidden;
  background: #ffffff;
  color: #27333e;
}

.agent-toolbar {
  display: grid;
  min-width: 0;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  border-bottom: 1px solid #d8dee6;
  background: #f8f9fb;
}

.agent-toolbar strong {
  overflow: hidden;
  font-size: 12px;
  text-align: center;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toolbar-actions {
  display: flex;
  align-items: center;
}

.context-strip {
  display: flex;
  min-height: 28px;
  gap: 5px;
  align-items: center;
  padding: 4px 8px;
  overflow-x: auto;
  border-bottom: 1px solid #e2e7ec;
  background: #fbfcfd;
  white-space: nowrap;
}

.chat-stage {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.context-strip span,
.citation-list span,
.scope-tag {
  padding: 2px 5px;
  border-radius: 3px;
  background: #edf3f2;
  color: #526b68;
  font-size: 9px;
}

.message-viewport {
  flex: 1;
  min-height: 0;
  padding: 10px;
  overflow-y: auto;
  background: #ffffff;
}

.message-row {
  display: flex;
  margin-bottom: 12px;
}

.message-row.user {
  justify-content: flex-end;
}

.message-bubble {
  width: min(94%, 620px);
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #dce2e8;
  border-radius: 5px;
  background: #f8fafb;
}

.message-row.user .message-bubble {
  width: auto;
  max-width: 88%;
  border-color: #c9e1db;
  background: #edf7f4;
}

.message-meta,
.section-heading,
.confirmation-card header,
.composer-footer,
.memory-item > div,
.session-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.message-meta strong {
  font-size: 11px;
}

.message-meta time,
.section-heading small,
.message-meta time,
.session-item small {
  color: #87919d;
  font-size: 9px;
}

.message-plain,
.message-markdown {
  margin: 7px 0 0;
  color: #384653;
  font-size: 12px;
  line-height: 1.58;
  overflow-wrap: anywhere;
}

.message-plain {
  white-space: pre-wrap;
}

.message-markdown :deep(> :first-child) {
  margin-top: 0;
}

.message-markdown :deep(> :last-child) {
  margin-bottom: 0;
}

.message-markdown :deep(p),
.message-markdown :deep(ul),
.message-markdown :deep(ol),
.message-markdown :deep(blockquote),
.message-markdown :deep(pre),
.message-markdown :deep(.table-scroll),
.message-markdown :deep(.math-display) {
  margin: 0 0 8px;
}

.message-markdown :deep(h1),
.message-markdown :deep(h2),
.message-markdown :deep(h3),
.message-markdown :deep(h4) {
  margin: 12px 0 6px;
  color: #27333e;
  line-height: 1.35;
}

.message-markdown :deep(h1) {
  font-size: 16px;
}

.message-markdown :deep(h2) {
  font-size: 14px;
}

.message-markdown :deep(h3),
.message-markdown :deep(h4) {
  font-size: 12px;
}

.message-markdown :deep(ul),
.message-markdown :deep(ol) {
  padding-left: 20px;
}

.message-markdown :deep(li + li) {
  margin-top: 3px;
}

.message-markdown :deep(blockquote) {
  padding: 3px 8px;
  border-left: 3px solid #a7c8c0;
  background: #f1f6f5;
  color: #65727e;
}

.message-markdown :deep(code) {
  padding: 1px 4px;
  border-radius: 3px;
  background: #e9eef2;
  color: #2f4652;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
}

.message-markdown :deep(pre) {
  max-width: 100%;
  padding: 8px;
  overflow: auto;
  border: 1px solid #d8e0e6;
  border-radius: 4px;
  background: #f4f6f8;
}

.message-markdown :deep(pre code) {
  padding: 0;
  background: transparent;
  color: #263640;
  white-space: pre;
}

.message-markdown :deep(.table-scroll),
.message-markdown :deep(.math-display) {
  max-width: 100%;
  overflow: auto;
}

.message-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.message-markdown :deep(th),
.message-markdown :deep(td) {
  padding: 4px 6px;
  border: 1px solid #d8e0e6;
  text-align: left;
}

.message-markdown :deep(th) {
  background: #eef3f5;
}

.message-markdown :deep(a) {
  color: #147866;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.message-markdown :deep(img) {
  max-width: 100%;
  height: auto;
}

.tool-event-list {
  display: grid;
  gap: 4px;
  margin-top: 8px;
}

.tool-event {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 6px;
  align-items: center;
  padding: 5px 6px;
  border: 1px solid #dfe5ea;
  border-radius: 3px;
  background: #ffffff;
}

.event-status {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #1f8f78;
}

.tool-event.failed .event-status {
  background: #c45b4b;
}

.tool-event.running .event-status {
  animation: pulse 1.2s infinite ease-in-out;
  background: #4f85b5;
}

.tool-event.pending_confirmation .event-status {
  background: #c18328;
}

.tool-event div {
  display: grid;
  min-width: 0;
}

.tool-event strong,
.tool-event small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-event strong {
  font-size: 10px;
}

.tool-event small {
  color: #74808c;
  font-size: 9px;
}

.tool-event button {
  padding: 2px 5px;
  border: 0;
  background: transparent;
  color: #147866;
  cursor: pointer;
  font-size: 9px;
}

.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.degraded-note {
  margin-top: 8px;
  padding: 5px 6px;
  border-left: 2px solid #c18328;
  background: #fff8eb;
  color: #8b621f;
  font-size: 10px;
}

.confirmation-card {
  margin-top: 8px;
  padding: 8px;
  border: 1px solid #e2c58d;
  border-radius: 4px;
  background: #fffaf0;
}

.confirmation-card header div {
  display: grid;
  gap: 2px;
}

.confirmation-card header span,
.confirmation-card header small {
  color: #99702d;
  font-size: 9px;
}

.confirmation-card header strong {
  font-size: 11px;
}

.confirmation-card pre {
  max-height: 140px;
  margin: 7px 0;
  padding: 6px;
  overflow: auto;
  border: 1px solid #ece2cf;
  background: #ffffff;
  color: #58636e;
  font-size: 9px;
  white-space: pre-wrap;
}

.confirmation-actions {
  display: flex;
  justify-content: flex-end;
  gap: 5px;
}

.confirmation-error {
  margin: 6px 0 0;
  color: #b34e3d;
  font-size: 9px;
}

.persisted-tool {
  display: grid;
  width: 100%;
  gap: 4px;
  padding: 6px 8px;
  border-left: 2px solid #9aa7b2;
  background: #f5f7f9;
  color: #6f7b87;
  font-size: 9px;
}

.persisted-tool code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-progress {
  margin-top: 8px;
  padding: 7px 8px;
  border: 1px solid #d8e0e6;
  border-radius: 4px;
  background: #f8fafb;
  color: #65727e;
  font-size: 10px;
}

.run-progress summary {
  display: flex;
  gap: 7px;
  align-items: center;
  cursor: pointer;
  list-style: none;
}

.progress-spinner {
  width: 8px;
  height: 8px;
  border: 1px solid #a9c9c1;
  border-top-color: #1f8f78;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.live-tool-list {
  display: grid;
  gap: 4px;
  margin-top: 7px;
}

.composer {
  padding: 8px;
  border-top: 1px solid #d8dee6;
  background: #f8f9fb;
}

.composer :deep(.el-textarea__inner) {
  border-radius: 4px;
  box-shadow: 0 0 0 1px #cfd7df inset;
  font-size: 12px;
}

.composer-footer {
  margin-top: 6px;
}

.composer-footer span {
  color: #7a8692;
  font-size: 9px;
}

.empty-chat,
.panel-state {
  display: grid;
  place-items: center;
  color: #7a8692;
  text-align: center;
}

.empty-chat {
  min-height: 180px;
  align-content: center;
  gap: 6px;
}

.empty-chat svg {
  width: 24px;
  color: #1f8f78;
}

.empty-chat strong {
  color: #3d4a56;
  font-size: 12px;
}

.empty-chat span,
.panel-state {
  font-size: 10px;
}

.session-view,
.memory-view,
.capability-view {
  display: grid;
  min-height: 0;
  grid-column: 1;
  grid-row: 2 / 4;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.section-heading {
  min-height: 32px;
  padding: 0 9px;
  border-bottom: 1px solid #e0e5ea;
  color: #5d6975;
  font-size: 10px;
  font-weight: 700;
}

.section-heading label {
  color: #7a8692;
  font-size: 9px;
  font-weight: 400;
}

.session-list,
.memory-list {
  min-height: 0;
  padding: 6px;
  overflow-y: auto;
}

.session-item {
  display: grid;
  width: 100%;
  gap: 3px;
  padding: 8px;
  overflow: hidden;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: #3c4955;
  cursor: pointer;
  text-align: left;
}

.session-item:hover,
.session-item.active {
  background: #edf3f2;
}

.session-item.active {
  box-shadow: inset 2px 0 #1f8f78;
}

.session-title {
  overflow: hidden;
  font-size: 11px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-actions {
  padding: 7px;
  border-top: 1px solid #e0e5ea;
}

.memory-view {
  grid-template-rows: auto auto minmax(0, 1fr);
}

.capability-view {
  grid-template-rows: auto auto minmax(0, 1fr);
}

.capability-notice {
  margin: 0;
  padding: 7px 9px;
  border-bottom: 1px solid #e0e5ea;
  background: #fffaf0;
  color: #7d673f;
  font-size: 9px;
  line-height: 1.45;
}

.capability-list {
  min-height: 0;
  padding: 6px;
  overflow-y: auto;
}

.capability-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid #e3e8ec;
}

.capability-main {
  min-width: 0;
}

.capability-main > div {
  display: flex;
  gap: 5px;
  align-items: center;
}

.capability-main strong {
  overflow: hidden;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.capability-main p {
  margin: 4px 0;
  color: #66727e;
  font-size: 9px;
  line-height: 1.4;
}

.capability-main small {
  display: block;
  overflow: hidden;
  color: #929ca6;
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.capability-kind {
  padding: 1px 4px;
  border-radius: 2px;
  background: #edf3f2;
  color: #426b62;
  font-size: 8px;
  text-transform: uppercase;
}

.capability-controls {
  display: grid;
  align-content: center;
  justify-items: end;
  gap: 6px;
}

.capability-controls label {
  color: #6f7b87;
  font-size: 8px;
  white-space: nowrap;
}

.memory-create {
  display: grid;
  gap: 6px;
  padding: 8px;
  border-bottom: 1px solid #e0e5ea;
}

.memory-create > div {
  display: flex;
  justify-content: space-between;
  gap: 6px;
}

.memory-create .el-select {
  width: 100px;
}

.memory-list {
  display: grid;
  align-content: start;
  gap: 6px;
}

.memory-item {
  position: relative;
  padding: 8px 34px 8px 8px;
  border: 1px solid #dde3e8;
  border-radius: 4px;
  background: #fbfcfd;
}

.memory-item > div {
  justify-content: flex-start;
  color: #7a8692;
  font-size: 9px;
}

.scope-tag.global {
  background: #eef1fa;
  color: #596c9b;
}

.memory-item p {
  margin: 7px 0 0;
  color: #3d4a56;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.memory-item > .el-button {
  position: absolute;
  top: 4px;
  right: 3px;
}

@keyframes pulse {
  0%,
  80%,
  100% {
    opacity: 0.35;
    transform: scale(0.8);
  }
  40% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
