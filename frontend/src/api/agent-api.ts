import { apiBaseUrl, http } from '@/api/http'
import type {
  AgentCapability,
  AgentAnalysisDiagnostics,
  AgentAnalysisJob,
  AgentAnalysisKind,
  AgentConfirmation,
  AgentContext,
  AgentConversation,
  AgentConversationDecisionResponse,
  AgentConversationDetail,
  AgentMemory,
  AgentQueryResponse,
  AgentRunEvent,
  AgentRunSubmission,
  AgentTurnResponse,
} from '@/types/agent'

export async function createAgentAnalysisJob(
  projectId: number,
  payload: {
    kind: AgentAnalysisKind
    root_symbol?: string | null
    depth?: number
    force?: boolean
  },
): Promise<AgentAnalysisJob> {
  const { data } = await http.post<AgentAnalysisJob>(
    `/projects/${projectId}/agent/analysis-jobs`,
    payload,
  )
  return data
}

export async function getAgentAnalysisJob(
  projectId: number,
  jobId: string,
): Promise<AgentAnalysisJob> {
  const { data } = await http.get<AgentAnalysisJob>(
    `/projects/${projectId}/agent/analysis-jobs/${jobId}`,
  )
  return data
}

export async function cancelAgentAnalysisJob(
  projectId: number,
  jobId: string,
): Promise<AgentAnalysisJob> {
  const { data } = await http.post<AgentAnalysisJob>(
    `/projects/${projectId}/agent/analysis-jobs/${encodeURIComponent(jobId)}/cancel`,
  )
  return data
}

/** Full failure detail for one analysis run — only fetched while debug mode is on. */
export async function getAgentAnalysisDiagnostics(
  projectId: number,
  jobId: string,
): Promise<AgentAnalysisDiagnostics> {
  const { data } = await http.get<AgentAnalysisDiagnostics>(
    `/projects/${projectId}/agent/analysis-jobs/${encodeURIComponent(jobId)}/diagnostics`,
  )
  return data
}

export async function streamAgentAnalysisJob(
  projectId: number,
  jobId: string,
  onEvent: (event: AgentRunEvent) => void,
): Promise<void> {
  const response = await fetch(
    `${apiBaseUrl}/projects/${projectId}/agent/analysis-jobs/${encodeURIComponent(jobId)}/events`,
    { headers: { Accept: 'text/event-stream' } },
  )
  if (!response.ok || !response.body) throw new Error(`analysis_stream_${response.status}`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const line = frame.split('\n').find((item) => item.startsWith('data:'))
      if (line) onEvent(JSON.parse(line.slice(5).trim()) as AgentRunEvent)
    }
    if (done) break
  }
}

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

export async function submitAgentRun(
  projectId: number,
  conversationId: string,
  message: string,
  context: AgentContext,
): Promise<AgentRunSubmission> {
  const { data } = await http.post<AgentRunSubmission>(
    `/projects/${projectId}/agent/conversations/${conversationId}/runs`,
    { message, context },
  )
  return data
}

export async function streamAgentRunEvents(
  projectId: number,
  runId: string,
  onEvent: (event: AgentRunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let cursor = 0
  let retries = 0
  let terminal = false

  const consumeFrame = (frame: string): void => {
    const dataLine = frame.split('\n').find((line) => line.startsWith('data:'))
    if (!dataLine) return
    const event = JSON.parse(dataLine.slice(5).trim()) as AgentRunEvent
    if (event.sequence <= cursor) return
    cursor = event.sequence
    terminal = ['run.completed', 'run.failed'].includes(event.event_type)
    onEvent(event)
  }

  while (!terminal) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    try {
      const response = await fetch(
        `${apiBaseUrl}/projects/${projectId}/agent/runs/${encodeURIComponent(runId)}` +
          `/events?after=${cursor}`,
        { headers: { Accept: 'text/event-stream' }, signal },
      )
      if (!response.ok || !response.body) throw new Error(`agent_stream_${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        buffer += decoder.decode(value, { stream: !done })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) consumeFrame(frame)
        if (done) {
          if (buffer.trim()) consumeFrame(buffer)
          break
        }
      }
      retries = terminal ? retries : retries + 1
    } catch (cause) {
      if (signal?.aborted) throw cause
      retries += 1
      if (retries > 5) throw cause
    }
    if (!terminal) {
      if (retries > 5) throw new Error('agent_stream_disconnected')
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(resolve, Math.min(500 * 2 ** retries, 4000))
        signal?.addEventListener(
          'abort',
          () => {
            window.clearTimeout(timeout)
            reject(new DOMException('Aborted', 'AbortError'))
          },
          { once: true },
        )
      })
    }
  }
}

export async function listAgentCapabilities(projectId: number): Promise<AgentCapability[]> {
  const { data } = await http.get<AgentCapability[]>(
    `/projects/${projectId}/agent/capabilities`,
  )
  return data
}

export async function updateAgentCapability(
  projectId: number,
  capabilityId: string,
  patch: { enabled: boolean; trusted: boolean },
): Promise<AgentCapability> {
  const { data } = await http.patch<AgentCapability>(
    `/projects/${projectId}/agent/capabilities/${encodeURIComponent(capabilityId)}`,
    patch,
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
