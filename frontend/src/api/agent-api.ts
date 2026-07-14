import { http } from '@/api/http'
import type {
  AgentConfirmation,
  AgentContext,
  AgentQueryResponse,
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
