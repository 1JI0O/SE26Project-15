import axios from 'axios'

const isDesktop =
  typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ??
  (isDesktop ? 'http://127.0.0.1:8765/api/v1' : '/api/v1')

export const http = axios.create({
  baseURL: apiBaseUrl,
  timeout: 120_000,
})
