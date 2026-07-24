import { http } from '@/api/http'
import type {
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
