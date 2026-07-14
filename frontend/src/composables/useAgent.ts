import { ref } from 'vue'
import type { TagType } from './useCode'

export interface AgentMessage {
  id: string
  role: 'agent' | 'user'
  content: string
  timestamp: string
}

export interface ToolCall {
  id: string
  tool: string
  description: string
  status: 'pending' | 'confirmed' | 'rejected' | 'executed'
  result?: string
  affectedFiles: string[]
}

// Placeholder data — will be replaced by backend API in future iteration
const PLACEHOLDER_MESSAGES: AgentMessage[] = [
  {
    id: 'msg-1',
    role: 'agent',
    content: '我分析了论文中的残差连接公式和代码中的 BasicBlock.forward 实现，发现以下对应关系：',
    timestamp: '2026-07-14 15:30',
  },
  {
    id: 'msg-2',
    role: 'agent',
    content: '论文 Section 2.2 描述的 y = F(x, {Wi}) + x 与 resnet.py:24 的 `out += self.shortcut(x)` 完全匹配。但我注意到 stride=2 时 downsample 使用 1x1 卷积，需要确认是否与论文描述的 projection shortcut 一致。',
    timestamp: '2026-07-14 15:30',
  },
]

const PLACEHOLDER_TOOLS: ToolCall[] = [
  {
    id: 'tool-1',
    tool: 'trace_suggest',
    description: '建议添加追溯关系：论文 "identity mapping by shortcuts" ↔ resnet.py BasicBlock.shortcut',
    status: 'pending',
    affectedFiles: ['models/resnet.py'],
  },
  {
    id: 'tool-2',
    tool: 'conflict_detect',
    description: '检测到配置中 stage3 stride 被改为 1，与论文描述不一致，建议标记为冲突项',
    status: 'pending',
    affectedFiles: ['config.py', 'models/resnet.py'],
  },
]

export function useAgent() {
  const messages = ref<AgentMessage[]>(PLACEHOLDER_MESSAGES)
  const pendingTools = ref<ToolCall[]>(PLACEHOLDER_TOOLS)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const degraded = ref(true) // no backend API yet

  function confirmTool(toolId: string): void {
    const tool = pendingTools.value.find(t => t.id === toolId)
    if (tool) {
      tool.status = 'confirmed'
      messages.value = [
        ...messages.value,
        {
          id: `msg-${Date.now()}`,
          role: 'agent',
          content: `已确认：${tool.description}`,
          timestamp: new Date().toLocaleString(),
        },
      ]
    }
  }

  function rejectTool(toolId: string): void {
    const tool = pendingTools.value.find(t => t.id === toolId)
    if (tool) {
      tool.status = 'rejected'
      messages.value = [
        ...messages.value,
        {
          id: `msg-${Date.now()}`,
          role: 'user',
          content: `已驳回：${tool.description}`,
          timestamp: new Date().toLocaleString(),
        },
      ]
    }
  }

  const confirmedCount = () => pendingTools.value.filter(t => t.status === 'confirmed').length
  const rejectedCount = () => pendingTools.value.filter(t => t.status === 'rejected').length
  const pendingCount = () => pendingTools.value.filter(t => t.status === 'pending').length

  return {
    messages,
    pendingTools,
    loading,
    error,
    degraded,
    confirmTool,
    rejectTool,
    confirmedCount,
    rejectedCount,
    pendingCount,
  }
}
