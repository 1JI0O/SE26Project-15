import { computed, ref } from 'vue'

/**
 * Opt-in diagnostics channel for the workbench.
 *
 * Normal operation surfaces short Chinese messages ("Agent 追溯失败"), which is the right default
 * but useless when something actually breaks. With debug mode on, every failure the UI catches is
 * recorded verbatim — HTTP status, server `detail`, stack — and rendered in a panel the user can
 * copy from. It is off by default and persisted per-browser so it survives a reload while
 * investigating.
 */

export type DebugLevel = 'info' | 'warn' | 'error'

export interface DebugEntry {
  id: number
  at: string
  level: DebugLevel
  scope: string
  message: string
  detail?: string
}

const STORAGE_KEY = 'tracelab.debug.enabled'
const MAX_ENTRIES = 300

const enabled = ref(window.localStorage.getItem(STORAGE_KEY) === '1')
const entries = ref<DebugEntry[]>([])
const panelOpen = ref(false)
let nextId = 1

function serialize(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (value instanceof Error) return `${value.name}: ${value.message}\n${value.stack ?? ''}`
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** Pull the most informative text out of an axios/fetch failure without importing axios here. */
function describeCause(cause: unknown): string {
  if (cause == null) return ''
  const response = (cause as { response?: { status?: number; data?: unknown } }).response
  const parts: string[] = []
  if (response?.status) parts.push(`HTTP ${response.status}`)
  const detail = (response?.data as { detail?: unknown } | undefined)?.detail
  if (detail != null) parts.push(serialize(detail))
  else if (response?.data != null) parts.push(serialize(response.data))
  const config = (cause as { config?: { method?: string; url?: string } }).config
  if (config?.url) parts.push(`${(config.method ?? 'get').toUpperCase()} ${config.url}`)
  parts.push(serialize(cause))
  return parts.filter(Boolean).join('\n')
}

export function useDebug() {
  function setEnabled(value: boolean): void {
    enabled.value = value
    window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
    if (!value) panelOpen.value = false
  }

  function record(level: DebugLevel, scope: string, message: string, cause?: unknown): void {
    if (!enabled.value) return
    const detail = describeCause(cause)
    entries.value = [
      ...entries.value.slice(-(MAX_ENTRIES - 1)),
      {
        id: nextId++,
        at: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        level,
        scope,
        message,
        detail: detail || undefined,
      },
    ]
    // Errors are surfaced immediately so a mid-run failure doesn't require hunting for the panel.
    if (level === 'error') panelOpen.value = true
  }

  return {
    enabled,
    entries,
    panelOpen,
    hasEntries: computed(() => entries.value.length > 0),
    errorCount: computed(() => entries.value.filter((item) => item.level === 'error').length),
    setEnabled,
    info: (scope: string, message: string, cause?: unknown) => record('info', scope, message, cause),
    warn: (scope: string, message: string, cause?: unknown) => record('warn', scope, message, cause),
    error: (scope: string, message: string, cause?: unknown) =>
      record('error', scope, message, cause),
    clear: () => {
      entries.value = []
    },
    exportText: (): string =>
      entries.value
        .map((item) =>
          [
            `[${item.at}] ${item.level.toUpperCase()} ${item.scope} — ${item.message}`,
            item.detail,
          ]
            .filter(Boolean)
            .join('\n'),
        )
        .join('\n\n'),
  }
}

export type DebugChannel = ReturnType<typeof useDebug>
