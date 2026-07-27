import { http } from '@/api/http'
import type {
  IntegrationProbeRequest,
  IntegrationProbeResult,
  IntegrationSettings,
  IntegrationSettingsUpdate,
} from '@/types/integration-settings'

export async function getIntegrationSettings(): Promise<IntegrationSettings> {
  const { data } = await http.get<IntegrationSettings>('/settings/integrations')
  return data
}

export async function updateIntegrationSettings(
  payload: IntegrationSettingsUpdate,
): Promise<IntegrationSettings> {
  const { data } = await http.put<IntegrationSettings>(
    '/settings/integrations',
    payload,
  )
  return data
}

/** Never rejects on an unreachable endpoint — the failure is the answer, returned as ok=false. */
export async function probeIntegration(
  payload: IntegrationProbeRequest,
  timeoutMs = 35_000,
): Promise<IntegrationProbeResult> {
  const { data } = await http.post<IntegrationProbeResult>(
    '/settings/integrations/probe',
    payload,
    { timeout: timeoutMs },
  )
  return data
}
