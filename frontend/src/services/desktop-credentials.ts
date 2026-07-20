import { isDesktop } from '@/api/http'

export async function saveRefreshToken(token: string): Promise<void> {
  if (!isDesktop) return
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('store_cloud_refresh_token', { token })
}

export async function loadRefreshToken(): Promise<string> {
  if (!isDesktop) return ''
  const { invoke } = await import('@tauri-apps/api/core')
  return (await invoke<string | null>('load_cloud_refresh_token')) ?? ''
}

export async function deleteRefreshToken(): Promise<void> {
  if (!isDesktop) return
  const { invoke } = await import('@tauri-apps/api/core')
  await invoke('delete_cloud_refresh_token')
}
