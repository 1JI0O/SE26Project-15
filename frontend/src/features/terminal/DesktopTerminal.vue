<template>
  <div class="desktop-terminal-shell">
    <header class="desktop-terminal-header">
      <span>项目终端</span>
      <span v-if="cwd" class="desktop-terminal-cwd">{{ cwd }}</span>
      <span v-else class="desktop-terminal-cwd muted">未挂载项目检出</span>
    </header>
    <div ref="hostRef" class="desktop-terminal-host" />
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { materializeCheckout } from '@/api/repository-api'

const props = defineProps<{
  projectId: number | string
}>()

const hostRef = ref<HTMLDivElement | null>(null)
const cwd = ref('')

let resizeObserver: ResizeObserver | null = null
let disposePty: (() => void) | null = null

function defaultShell(): string {
  if (typeof navigator !== 'undefined' && /win/i.test(navigator.platform)) {
    return 'powershell.exe'
  }
  return '/bin/zsh'
}

onMounted(async () => {
  const [{ Terminal }, { FitAddon }, { spawn }] = await Promise.all([
    import('@xterm/xterm'),
    import('@xterm/addon-fit'),
    import('tauri-pty'),
  ])
  await import('@xterm/xterm/css/xterm.css')

  let checkoutPath: string | undefined
  try {
    const checkout = await materializeCheckout(props.projectId)
    checkoutPath = checkout.path
    cwd.value = checkout.path
  } catch {
    ElMessage.warning('未能挂载项目检出目录，终端将在默认目录启动')
  }

  const term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
    theme: {
      background: '#0f1419',
      foreground: '#e6edf3',
      cursor: '#1f8f78',
    },
  })
  const fitAddon = new FitAddon()
  term.loadAddon(fitAddon)

  const host = hostRef.value
  if (!host) return

  term.open(host)
  fitAddon.fit()

  const pty = spawn(defaultShell(), [], {
    cols: term.cols,
    rows: term.rows,
    cwd: checkoutPath,
  })

  const decoder = new TextDecoder()
  const dataDisposable = pty.onData((chunk) => {
    term.write(decoder.decode(chunk))
  })
  term.onData((data) => {
    pty.write(data)
  })

  const syncSize = (): void => {
    fitAddon.fit()
    pty.resize(term.cols, term.rows)
  }

  resizeObserver = new ResizeObserver(() => {
    syncSize()
  })
  resizeObserver.observe(host)
  syncSize()

  disposePty = () => {
    dataDisposable.dispose()
    pty.kill()
    term.dispose()
    resizeObserver?.disconnect()
    resizeObserver = null
  }
})

onBeforeUnmount(() => {
  disposePty?.()
  disposePty = null
})
</script>

<style scoped>
.desktop-terminal-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  background: #0f1419;
}

.desktop-terminal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  color: #c9d1d9;
  font-size: 12px;
}

.desktop-terminal-cwd {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #8b949e;
}

.desktop-terminal-cwd.muted {
  color: #6e7681;
}

.desktop-terminal-host {
  min-height: 0;
  height: 100%;
  padding: 4px;
}

.desktop-terminal-host :deep(.xterm) {
  height: 100%;
}

.desktop-terminal-host :deep(.xterm-viewport) {
  overflow-y: auto;
}
</style>
