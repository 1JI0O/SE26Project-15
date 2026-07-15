import { http } from '@/api/http'
import type {
  AgentConfirmation,
  AgentContext,
  AgentConversation,
  AgentConversationDecisionResponse,
  AgentConversationDetail,
  AgentMemory,
  AgentQueryResponse,
  AgentTurnResponse,
} from '@/types/agent'

export async function queryAgent(
  projectId: number,
  message: string,
  context: AgentContext,
): Promise<AgentQueryResponse> {
  const { data } = await http.post<AgentQueryResponse>(
    `/projects/${projectId}/agent/query`,
    { message, context },
  )
  return data
}

export async function decideAgentConfirmation(
  projectId: number,
  confirmationId: string,
  decision: 'accept' | 'reject',
): Promise<AgentConfirmation> {
  const { data } = await http.post<AgentConfirmation>(
    `/projects/${projectId}/agent/confirmations/${confirmationId}/decision`,
    { decision },
  )
  return data
}

export async function listAgentConversations(
  projectId: number,
  includeArchived = false,
): Promise<AgentConversation[]> {
  const { data } = await http.get<AgentConversation[]>(
    `/projects/${projectId}/agent/conversations`,
    { params: { include_archived: includeArchived } },
  )
  return data
}

export async function createAgentConversation(
  projectId: number,
  title = '新对话',
): Promise<AgentConversation> {
  const { data } = await http.post<AgentConversation>(
    `/projects/${projectId}/agent/conversations`,
    { title },
  )
  return data
}

export async function getAgentConversation(
  projectId: number,
  conversationId: string,
): Promise<AgentConversationDetail> {
  const { data } = await http.get<AgentConversationDetail>(
    `/projects/${projectId}/agent/conversations/${conversationId}`,
  )
  return data
}

export async function updateAgentConversation(
  projectId: number,
  conversationId: string,
  patch: { title?: string; status?: 'active' | 'archived' },
): Promise<AgentConversation> {
  const { data } = await http.patch<AgentConversation>(
    `/projects/${projectId}/agent/conversations/${conversationId}`,
    patch,
  )
  return data
}

export async function sendAgentMessage(
  projectId: number,
  conversationId: string,
  message: string,
  context: AgentContext,
): Promise<AgentTurnResponse> {
  const { data } = await http.post<AgentTurnResponse>(
    `/projects/${projectId}/agent/conversations/${conversationId}/messages`,
    { message, context },
  )
  return data
}

export async function decideConversationConfirmation(
  projectId: number,
  conversationId: string,
  confirmationId: string,
  decision: 'accept' | 'reject',
): Promise<AgentConversationDecisionResponse> {
  const { data } = await http.post<AgentConversationDecisionResponse>(
    `/projects/${projectId}/agent/conversations/${conversationId}` +
      `/confirmations/${confirmationId}/decision`,
    { decision },
  )
  return data
}

export async function listAgentMemories(projectId: number): Promise<AgentMemory[]> {
  const { data } = await http.get<AgentMemory[]>(`/projects/${projectId}/agent/memories`)
  return data
}

export async function createAgentMemory(
  projectId: number,
  payload: {
    content: string
    scope: 'project' | 'global'
    kind?: AgentMemory['kind']
    conversation_id?: string
  },
): Promise<AgentMemory> {
  const { data } = await http.post<AgentMemory>(
    `/projects/${projectId}/agent/memories`,
    payload,
  )
  return data
}

export async function deleteAgentMemory(
  projectId: number,
  memoryId: string,
): Promise<void> {
  await http.delete(`/projects/${projectId}/agent/memories/${memoryId}`)
}
