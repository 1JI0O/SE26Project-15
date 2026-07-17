/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_CLOUD_API_BASE_URL?: string
  readonly VITE_CLOUD_PROXY_TARGET?: string
  readonly VITE_RUNTIME_MODE?: 'local' | 'desktop' | 'cloud'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
