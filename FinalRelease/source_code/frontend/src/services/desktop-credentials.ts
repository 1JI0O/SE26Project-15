import { isDesktop } from '@/api/http'

// Keep the same localStorage key main already used for web/local installs.
const WEB_DEVICE_KEY = 'tracelab_device_id'
const WEB_LAST_USER_KEY = 'tracelab_last_user_id'

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

/** Persist this machine's cloud device id across logout (same-account re-login). */
export async function saveDeviceId(deviceId: string): Promise<void> {
  if (!deviceId) return
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.setItem(WEB_DEVICE_KEY, deviceId)
    } catch {
      // best-effort
    }
  }
  if (isDesktop) {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('store_cloud_device_id', { deviceId })
  }
}

export async function loadDeviceId(): Promise<string> {
  if (isDesktop) {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const fromKeyring = (await invoke<string | null>('load_cloud_device_id')) ?? ''
      if (fromKeyring) return fromKeyring
    } catch {
      // fall through to localStorage
    }
  }
  if (typeof localStorage === 'undefined') return ''
  return localStorage.getItem(WEB_DEVICE_KEY) ?? ''
}

/** Last successfully authenticated user; used to detect account switches. */
export async function saveLastUserId(userId: string): Promise<void> {
  if (!userId) return
  if (isDesktop) {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('store_cloud_last_user_id', { userId })
    return
  }
  if (typeof localStorage !== 'undefined') localStorage.setItem(WEB_LAST_USER_KEY, userId)
}

export async function loadLastUserId(): Promise<string> {
  if (isDesktop) {
    const { invoke } = await import('@tauri-apps/api/core')
    return (await invoke<string | null>('load_cloud_last_user_id')) ?? ''
  }
  if (typeof localStorage === 'undefined') return ''
  return localStorage.getItem(WEB_LAST_USER_KEY) ?? ''
}
