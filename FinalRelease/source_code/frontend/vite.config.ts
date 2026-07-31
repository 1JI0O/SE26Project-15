import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv, type ProxyOptions } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), '')
  const proxy: Record<string, string | ProxyOptions> = {
    '/api': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
    },
  }
  const cloudTarget = env.VITE_CLOUD_PROXY_TARGET?.replace(/\/$/, '')
  if (cloudTarget) {
    const trustedOrigin = new URL(cloudTarget).origin
    proxy['/cloud-api'] = {
      target: cloudTarget,
      changeOrigin: true,
      secure: true,
      rewrite: (path) => path.replace(/^\/cloud-api/, '/api/v1'),
      cookiePathRewrite: {
        '/api/v1/auth': '/cloud-api/auth',
      },
      configure(server) {
        // Production Cloud API requires its public origin for browser-cookie
        // authentication. The browser still sees a same-origin local proxy.
        server.on('proxyReq', (request) => request.setHeader('Origin', trustedOrigin))
      },
    }
  }
  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy,
    },
  }
})
