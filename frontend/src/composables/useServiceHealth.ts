import { ref } from 'vue'
import { http } from '@/api/http'

export interface ServiceStatus {
  name: string
  available: boolean
  reason?: string
}

export function useServiceHealth() {
  const minerU = ref<ServiceStatus>({ name: 'MinerU (PDF 解析)', available: true })
  const llm = ref<ServiceStatus>({ name: 'LLM (追溯分析)', available: true })
  const checking = ref(false)

  /**
   * Check backend health endpoint to determine service availability.
   * Sets degraded flags when services are unavailable.
   */
  async function checkHealth(): Promise<void> {
    checking.value = true
    try {
      const { data } = await http.get<{ status: string; services?: Record<string, { status: string; message?: string }> }>('/health')
      if (data.services) {
        const miner = data.services['mineru']
        const llmSvc = data.services['llm']
        minerU.value = {
          name: 'MinerU (PDF 解析)',
          available: miner?.status === 'ok',
          reason: miner?.message,
        }
        llm.value = {
          name: 'LLM (追溯分析)',
          available: llmSvc?.status === 'ok',
          reason: llmSvc?.message,
        }
      }
    } catch {
      // If health endpoint doesn't exist or fails, assume degraded
      minerU.value = {
        name: 'MinerU (PDF 解析)',
        available: false,
        reason: '无法连接后端服务',
      }
      llm.value = {
        name: 'LLM (追溯分析)',
        available: false,
        reason: '无法连接后端服务',
      }
    } finally {
      checking.value = false
    }
  }

  const hasDegradedServices = () => !minerU.value.available || !llm.value.available

  return {
    minerU,
    llm,
    checking,
    checkHealth,
    hasDegradedServices,
  }
}
