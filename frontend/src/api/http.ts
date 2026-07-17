import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

export const isDesktop =
  typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export const runtimeMode =
  import.meta.env.VITE_RUNTIME_MODE ?? (isDesktop ? 'desktop' : 'local')

export const localApiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ??
  (isDesktop ? 'http://127.0.0.1:8765/api/v1' : '/api/v1')

export const cloudApiBaseUrl =
  import.meta.env.VITE_CLOUD_API_BASE_URL ?? '/api/v1'

export const cloudConfigured =
  runtimeMode === 'cloud' || Boolean(import.meta.env.VITE_CLOUD_API_BASE_URL)

// Desktop and the locally hosted Web app both own a Local API workspace. They
// may opt individual projects into cloud sync. Cloud Web operates directly on
// Cloud API entities instead and must never create a second local outbox.
export const hasLocalWorkspace = runtimeMode !== 'cloud'
export const localCloudSyncAvailable = hasLocalWorkspace && cloudConfigured

export const localHttp = axios.create({
  baseURL: localApiBaseUrl,
  timeout: 120_000,
})

export const cloudHttp = axios.create({
  baseURL: cloudApiBaseUrl,
  timeout: 120_000,
  withCredentials: true,
})

let accessToken = ''
let refreshHandler: (() => Promise<string>) | null = null
let refreshPromise: Promise<string> | null = null

export function setCloudAccessToken(token: string) {
  accessToken = token
}

export function setCloudRefreshHandler(handler: () => Promise<string>) {
  refreshHandler = handler
}

cloudHttp.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

cloudHttp.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
  const isAuthEndpoint = config?.url?.includes('/auth/')
  if (error.response?.status !== 401 || !config || config._retried || isAuthEndpoint) {
    throw error
  }
  config._retried = true
  if (!refreshHandler) throw error
  refreshPromise ??= refreshHandler().finally(() => {
    refreshPromise = null
  })
  const token = await refreshPromise
  config.headers.Authorization = `Bearer ${token}`
  return cloudHttp.request(config)
})

// Existing domain clients remain local in Desktop/local Web. Cloud Web uses its
// dedicated UUID-based clients and never calls the loopback API.
export const http = localHttp
export const apiBaseUrl = localApiBaseUrl
