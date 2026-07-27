import type { Transport } from '@codemirror/lsp-client'

export class WebSocketLspTransport implements Transport {
  private handlers = new Set<(value: string) => void>()
  private ws: WebSocket | null = null

  constructor(private readonly url: string) {}

  open(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url)
      this.ws.onopen = () => resolve()
      this.ws.onerror = () => reject(new Error('无法连接语言服务'))
      this.ws.onmessage = (event) => {
        const payload = typeof event.data === 'string' ? event.data : String(event.data)
        for (const handler of this.handlers) handler(payload)
      }
      this.ws.onclose = () => {
        this.ws = null
      }
    })
  }

  send(message: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('语言服务连接已断开')
    }
    this.ws.send(message)
  }

  subscribe(handler: (value: string) => void): void {
    this.handlers.add(handler)
  }

  unsubscribe(handler: (value: string) => void): void {
    this.handlers.delete(handler)
  }

  close(): void {
    this.ws?.close()
    this.ws = null
    this.handlers.clear()
  }
}

export function buildLspWebSocketUrl(projectId: number | string): string {
  const httpBase = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8765/api/v1'
  const wsBase = httpBase.replace(/^http/i, 'ws')
  return `${wsBase}/projects/${projectId}/workspace/lsp`
}

export function checkoutDirUri(checkoutRoot: string): string {
  const normalized = checkoutRoot.replace(/\\/g, '/').replace(/\/$/, '')
  if (normalized.startsWith('/')) {
    return `file://${encodeURI(normalized)}`
  }
  return `file:///${encodeURI(normalized)}`
}

export function checkoutFileUri(checkoutRoot: string, relativePath: string): string {
  const root = checkoutRoot.replace(/\\/g, '/').replace(/\/$/, '')
  const rel = relativePath.replace(/\\/g, '/').replace(/^\//, '')
  return `file://${encodeURI(`${root}/${rel}`)}`
}

export function uriToRelativePath(checkoutRoot: string, uri: string): string | null {
  const rootUri = checkoutDirUri(checkoutRoot)
  const normalizedUri = decodeURI(uri)
  const normalizedRoot = decodeURI(rootUri)
  if (!normalizedUri.startsWith(normalizedRoot)) return null
  const suffix = normalizedUri.slice(normalizedRoot.length).replace(/^\//, '')
  return suffix || null
}
