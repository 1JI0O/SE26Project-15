import { onBeforeUnmount, onMounted, ref, shallowRef, type Ref } from 'vue'
import type { LSPClient } from '@codemirror/lsp-client'
import { extractErrorDetail, isDesktop } from '@/api/http'
import { materializeCheckout } from '@/api/repository-api'
import { WebSocketLspTransport, buildLspWebSocketUrl } from '@/features/repository/lspTransport'
import { createTraceLabLspClient } from '@/features/repository/traceLabWorkspace'

export function useDesktopPythonLsp(
  projectId: () => number,
  openRelativePath: (path: string) => Promise<void>,
): {
  lspClient: Ref<LSPClient | null>
  lspCheckoutRoot: Ref<string | null>
  lspReady: Ref<boolean>
} {
  const lspClient = shallowRef<LSPClient | null>(null)
  const lspCheckoutRoot = ref<string | null>(null)
  const lspReady = ref(false)
  let transport: WebSocketLspTransport | null = null

  async function connect(): Promise<void> {
    if (!isDesktop) return
    const pid = projectId()
    if (!pid || Number.isNaN(pid)) return

    try {
      const checkout = await materializeCheckout(pid)
      lspCheckoutRoot.value = checkout.path
      transport = new WebSocketLspTransport(buildLspWebSocketUrl(pid))
      await transport.open()
      const client = createTraceLabLspClient(checkout.path, openRelativePath).connect(transport)
      await client.initializing
      lspClient.value = client
      lspReady.value = true
    } catch (error) {
      const detail = extractErrorDetail(error, '语言服务不可用')
      console.info('[lsp]', detail)
      lspClient.value = null
      lspReady.value = false
      lspCheckoutRoot.value = null
      transport?.close()
      transport = null
    }
  }

  onMounted(() => {
    void connect()
  })

  onBeforeUnmount(() => {
    lspClient.value?.disconnect()
    lspClient.value = null
    transport?.close()
    transport = null
    lspReady.value = false
    lspCheckoutRoot.value = null
  })

  return { lspClient, lspCheckoutRoot, lspReady }
}
