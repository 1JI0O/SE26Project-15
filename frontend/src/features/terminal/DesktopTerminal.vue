<template>
  <div class="desktop-terminal-shell">
    <header class="desktop-terminal-header">
      <span class="desktop-terminal-title">
        <span class="desktop-terminal-status" aria-hidden="true" />
        项目终端
      </span>
      <span v-if="cwd" class="desktop-terminal-cwd" :title="cwd">{{ cwd }}</span>
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
let disposeTerminal: (() => void) | null = null
let unmounted = false

function defaultShell(): string {
  if (typeof navigator !== 'undefined' && /win/i.test(navigator.platform)) {
    return 'powershell.exe'
  }
  return '/bin/zsh'
}

function terminalProcess(): { file: string; args: string[] } {
  const shell = defaultShell()
  if (typeof navigator !== 'undefined' && /win/i.test(navigator.platform)) {
    return {
      file: shell,
      args: [
        '-NoExit',
        '-Command',
        'Remove-Item Env:NO_COLOR -ErrorAction SilentlyContinue',
      ],
    }
  }
  return {
    file: '/usr/bin/env',
    args: ['-u', 'NO_COLOR', shell],
  }
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

  if (unmounted) return

  const term = new Terminal({
    cursorBlink: true,
    cursorStyle: 'bar',
    cursorWidth: 2,
    cursorInactiveStyle: 'bar',
    fontSize: 13,
    fontFamily:
      '"SFMono-Regular", "SF Mono", Menlo, Monaco, "Cascadia Mono", Consolas, "Liberation Mono", monospace',
    fontWeight: '400',
    fontWeightBold: '600',
    letterSpacing: 0,
    lineHeight: 1.25,
    minimumContrastRatio: 4.5,
    rescaleOverlappingGlyphs: true,
    scrollback: 5000,
    smoothScrollDuration: 80,
    theme: {
      background: '#fbfcfd',
      foreground: '#26323d',
      cursor: '#1f8f78',
      cursorAccent: '#ffffff',
      selectionBackground: '#cce8e1',
      selectionForeground: '#16232f',
      selectionInactiveBackground: '#e2f0ed',
      scrollbarSliderBackground: 'rgba(107, 119, 133, 0.22)',
      scrollbarSliderHoverBackground: 'rgba(107, 119, 133, 0.38)',
      scrollbarSliderActiveBackground: 'rgba(31, 143, 120, 0.45)',
      black: '#24313d',
      red: '#b64a3c',
      green: '#14805e',
      yellow: '#a15f00',
      blue: '#2563eb',
      magenta: '#7c3aed',
      cyan: '#0f7890',
      white: '#d8dee6',
      brightBlack: '#6b7785',
      brightRed: '#e15a4a',
      brightGreen: '#16a34a',
      brightYellow: '#d97706',
      brightBlue: '#5885ff',
      brightMagenta: '#8b5cf6',
      brightCyan: '#0891b2',
      brightWhite: '#ffffff',
    },
  })
  const fitAddon = new FitAddon()
  term.loadAddon(fitAddon)

  const host = hostRef.value
  if (!host || unmounted) {
    term.dispose()
    return
  }

  term.open(host)
  fitAddon.fit()

  const process = terminalProcess()
  const pty = spawn(process.file, process.args, {
    cols: term.cols,
    rows: term.rows,
    cwd: checkoutPath,
    name: 'xterm-256color',
    env: {
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
    },
  })

  const dataDisposable = pty.onData((chunk) => {
    term.write(chunk)
  })
  const inputDisposable = term.onData((data) => {
    pty.write(data)
  })

  let resizeFrame: number | null = null
  let lastCols = term.cols
  let lastRows = term.rows

  const syncSize = (): void => {
    resizeFrame = null
    if (unmounted || host.clientWidth <= 0 || host.clientHeight <= 0) return

    fitAddon.fit()
    if (term.cols <= 0 || term.rows <= 0) return
    if (term.cols === lastCols && term.rows === lastRows) return

    lastCols = term.cols
    lastRows = term.rows
    pty.resize(term.cols, term.rows)
  }

  const scheduleSizeSync = (): void => {
    if (resizeFrame !== null || unmounted) return
    resizeFrame = window.requestAnimationFrame(syncSize)
  }

  const observer = new ResizeObserver(scheduleSizeSync)
  resizeObserver = observer
  observer.observe(host)
  scheduleSizeSync()
  term.focus()

  let disposed = false
  disposeTerminal = () => {
    if (disposed) return
    disposed = true

    if (resizeFrame !== null) {
      window.cancelAnimationFrame(resizeFrame)
      resizeFrame = null
    }
    observer.disconnect()
    if (resizeObserver === observer) resizeObserver = null

    inputDisposable.dispose()
    dataDisposable.dispose()
    pty.kill()
    term.dispose()
  }
})

onBeforeUnmount(() => {
  unmounted = true
  disposeTerminal?.()
  disposeTerminal = null
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<style scoped>
.desktop-terminal-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #fbfcfd;
  color: #26323d;
}

.desktop-terminal-header {
  display: flex;
  min-width: 0;
  min-height: 31px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 12px;
  border-bottom: 1px solid #d8dee6;
  background: #f8f9fb;
  color: #26323d;
  font-size: 11px;
}

.desktop-terminal-title {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
  font-weight: 650;
  letter-spacing: 0.01em;
}

.desktop-terminal-status {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #1f8f78;
  box-shadow: 0 0 0 2px rgba(31, 143, 120, 0.12);
}

.desktop-terminal-cwd {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #6b7785;
  font-family: "SFMono-Regular", "SF Mono", Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
}

.desktop-terminal-cwd.muted {
  color: #9aa4ae;
  font-family: inherit;
}

.desktop-terminal-host {
  min-height: 0;
  height: 100%;
  padding: 8px 10px 7px;
  overflow: hidden;
  background: #fbfcfd;
}

.desktop-terminal-host :deep(.xterm) {
  height: 100%;
  color: #26323d;
}

.desktop-terminal-host :deep(.xterm-viewport) {
  overflow-y: auto;
  background: #fbfcfd !important;
  scrollbar-color: rgba(107, 119, 133, 0.32) transparent;
}
</style>
