import { computed, ref, type Ref } from 'vue'

import type { TraceEvidence, TraceLink, TraceStatus } from '@/types/tracing'

/**
 * Shared, bidirectional in-memory index over the current trace links.
 *
 * Both panes read from the SAME derived index (architecture doc §13.3): paper→code and
 * code→paper are two views of one relation graph, never two model runs. Only current
 * `proposed`/`accepted` links participate; hovering a target on either side highlights the
 * counterpart targets on the other side, ranked by relevance, with an optional click-to-pin.
 */

export interface PaperTargetView {
  targetId: string
  blockId: string
  quote: string
  occurrence: number
  charStart: number | null
  charEnd: number | null
  targetType: string
  salience: number
  status: TraceStatus
  /** Links where this is the paper side, sorted by relevance desc. */
  links: TraceLink[]
}

export interface CodeTargetView {
  targetId: string
  path: string
  lineStart: number
  lineEnd: number
  matchLineStart: number | null
  matchLineEnd: number | null
  charStart: number | null
  charEnd: number | null
  role: string
  status: TraceStatus
  links: TraceLink[]
}

const paperSide = (link: TraceLink): TraceEvidence | undefined =>
  link.evidence.find((item) => item.side === 'paper')

const codeSide = (link: TraceLink): TraceEvidence | undefined =>
  link.evidence.find((item) => item.side === 'code')

const paperTargetId = (link: TraceLink): string | null =>
  link.paper_target_id || paperSide(link)?.target_id || null

const codeTargetId = (link: TraceLink): string | null =>
  link.code_target_id || codeSide(link)?.target_id || null

/** accepted wins over proposed for resting decoration intensity. */
const mergeStatus = (current: TraceStatus, incoming: TraceStatus): TraceStatus =>
  current === 'accepted' || incoming === 'accepted' ? 'accepted' : current

export function useTraceIndex(links: Ref<TraceLink[]>) {
  const activeSide = ref<'paper' | 'code' | null>(null)
  const activeTargetId = ref<string | null>(null)
  const pinned = ref(false)

  const visibleLinks = computed(() =>
    links.value.filter((link) => link.status === 'proposed' || link.status === 'accepted'),
  )

  const paperTargets = computed<Map<string, PaperTargetView>>(() => {
    const map = new Map<string, PaperTargetView>()
    for (const link of visibleLinks.value) {
      const id = paperTargetId(link)
      const evidence = paperSide(link)
      if (!id || !evidence) continue
      const existing = map.get(id)
      if (existing) {
        existing.links.push(link)
        existing.status = mergeStatus(existing.status, link.status)
      } else {
        map.set(id, {
          targetId: id,
          blockId: evidence.ref,
          quote: evidence.quote,
          occurrence: evidence.occurrence ?? 1,
          charStart: evidence.char_start ?? null,
          charEnd: evidence.char_end ?? null,
          targetType: evidence.target_type ?? 'method_text',
          salience: evidence.salience ?? 0,
          status: link.status,
          links: [link],
        })
      }
    }
    for (const view of map.values()) {
      view.links.sort((a, b) => b.relevance - a.relevance)
    }
    return map
  })

  const codeTargets = computed<Map<string, CodeTargetView>>(() => {
    const map = new Map<string, CodeTargetView>()
    for (const link of visibleLinks.value) {
      const id = codeTargetId(link)
      const evidence = codeSide(link)
      if (!id || !evidence) continue
      const existing = map.get(id)
      if (existing) {
        existing.links.push(link)
        existing.status = mergeStatus(existing.status, link.status)
      } else {
        map.set(id, {
          targetId: id,
          path: evidence.path ?? '',
          lineStart: evidence.line_start ?? 1,
          lineEnd: evidence.line_end ?? evidence.line_start ?? 1,
          matchLineStart: evidence.match_line_start ?? null,
          matchLineEnd: evidence.match_line_end ?? null,
          charStart: evidence.char_start ?? null,
          charEnd: evidence.char_end ?? null,
          role: evidence.role ?? 'model_component',
          status: link.status,
          links: [link],
        })
      }
    }
    for (const view of map.values()) {
      view.links.sort((a, b) => b.relevance - a.relevance)
    }
    return map
  })

  /** Links attached to the currently active target, sorted by relevance. */
  const activeLinks = computed<TraceLink[]>(() => {
    if (!activeTargetId.value) return []
    if (activeSide.value === 'paper') {
      return paperTargets.value.get(activeTargetId.value)?.links ?? []
    }
    if (activeSide.value === 'code') {
      return codeTargets.value.get(activeTargetId.value)?.links ?? []
    }
    return []
  })

  const activePaperTargetIds = computed<Set<string>>(() => {
    const ids = new Set<string>()
    if (activeSide.value === 'paper' && activeTargetId.value) {
      ids.add(activeTargetId.value)
    } else if (activeSide.value === 'code') {
      for (const link of activeLinks.value) {
        const id = paperTargetId(link)
        if (id) ids.add(id)
      }
    }
    return ids
  })

  const activeCodeTargetIds = computed<Set<string>>(() => {
    const ids = new Set<string>()
    if (activeSide.value === 'code' && activeTargetId.value) {
      ids.add(activeTargetId.value)
    } else if (activeSide.value === 'paper') {
      for (const link of activeLinks.value) {
        const id = codeTargetId(link)
        if (id) ids.add(id)
      }
    }
    return ids
  })

  function hoverPaper(targetId: string): void {
    if (pinned.value) return
    activeSide.value = 'paper'
    activeTargetId.value = targetId
  }

  function hoverCode(targetId: string): void {
    if (pinned.value) return
    activeSide.value = 'code'
    activeTargetId.value = targetId
  }

  function clearHover(): void {
    if (pinned.value) return
    activeSide.value = null
    activeTargetId.value = null
  }

  function pin(side: 'paper' | 'code', targetId: string): void {
    if (pinned.value && activeSide.value === side && activeTargetId.value === targetId) {
      pinned.value = false
      activeSide.value = null
      activeTargetId.value = null
      return
    }
    activeSide.value = side
    activeTargetId.value = targetId
    pinned.value = true
  }

  function unpin(): void {
    pinned.value = false
    activeSide.value = null
    activeTargetId.value = null
  }

  return {
    activeSide,
    activeTargetId,
    pinned,
    paperTargets,
    codeTargets,
    activeLinks,
    activePaperTargetIds,
    activeCodeTargetIds,
    hoverPaper,
    hoverCode,
    clearHover,
    pin,
    unpin,
  }
}

export type TraceIndex = ReturnType<typeof useTraceIndex>
