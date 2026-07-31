import { computed, ref, type Ref } from 'vue'

import type { TraceEvidence, TraceLink, TraceStatus } from '@/types/tracing'

/**
 * Shared, bidirectional in-memory index over the current trace links.
 *
 * Both panes read from the SAME derived index (architecture doc §13.3): paper→code and
 * code→paper are two views of one relation graph, never two model runs. Only current
 * `proposed`/`accepted` links participate.
 *
 * Selection model (iteration 5): the single source of truth for "which relation is the
 * user looking at" is a **link id** (`selectedLinkId`), shared by the matrix, the paper pane
 * and the code pane. Clicking anything that belongs to a relation SELECTS it (pins it) and
 * drives a one-time dual jump. Hovering only sets `hoveredLinkId` for a lightweight preview
 * and NEVER changes the selection or triggers a jump. Both panes highlight the selected
 * relation strongly and the hovered relation weakly.
 */

export type TraceMultiplicity = '1_to_1' | '1_to_n' | 'n_to_1' | 'n_to_n'

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
  /** Distinct code targets linked from this paper target. */
  fanoutCount: number
  multiplicity: TraceMultiplicity
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
  fanoutCount: number
  multiplicity: TraceMultiplicity
  links: TraceLink[]
}

/** Both-sides summary of one relation, rendered in the fixed box and the hover preview box. */
export interface TraceLinkSummary {
  linkId: string
  relationType: string
  relevance: number
  confidence: number
  rationale: string
  paper: {
    targetId: string | null
    blockId: string
    quote: string
    targetType: string
    occurrence: number
  }
  code: { symbol: string; path: string; line: number | null }
  /** How many other (lower-relevance) relations share this relation's paper target. */
  otherLinkCount: number
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

function computeMultiplicity(fanoutCount: number, isFanin: boolean): TraceMultiplicity {
  const isFanout = fanoutCount > 1
  if (isFanout && isFanin) return 'n_to_n'
  if (isFanout) return '1_to_n'
  if (isFanin) return 'n_to_1'
  return '1_to_1'
}

function enrichMultiplicity(
  paperMap: Map<string, PaperTargetView>,
  codeMap: Map<string, CodeTargetView>,
): void {
  for (const view of paperMap.values()) {
    const codeIds = new Set<string>()
    for (const link of view.links) {
      const cid = codeTargetId(link)
      if (cid) codeIds.add(cid)
    }
    view.fanoutCount = codeIds.size
    let isFanin = false
    for (const cid of codeIds) {
      const codeView = codeMap.get(cid)
      if (!codeView) continue
      const paperIds = new Set(
        codeView.links.map((link) => paperTargetId(link)).filter((id): id is string => !!id),
      )
      if (paperIds.size > 1) isFanin = true
    }
    view.multiplicity = computeMultiplicity(view.fanoutCount, isFanin)
  }

  for (const view of codeMap.values()) {
    const paperIds = new Set<string>()
    for (const link of view.links) {
      const pid = paperTargetId(link)
      if (pid) paperIds.add(pid)
    }
    view.fanoutCount = paperIds.size
    let isFanin = false
    for (const pid of paperIds) {
      const paperView = paperMap.get(pid)
      if (!paperView) continue
      const codeIds = new Set(
        paperView.links.map((link) => codeTargetId(link)).filter((id): id is string => !!id),
      )
      if (codeIds.size > 1) isFanin = true
    }
    view.multiplicity = computeMultiplicity(view.fanoutCount, isFanin)
  }
}

export function useTraceIndex(links: Ref<TraceLink[]>) {
  // The pinned relation the user selected, and the transient relation under the pointer.
  const selectedLinkId = ref<string | null>(null)
  const hoveredLinkId = ref<string | null>(null)
  // Which side the selection was triggered from (paper|code) — used to bias the popover layout.
  const selectedSide = ref<'paper' | 'code' | null>(null)

  const pinned = computed(() => selectedLinkId.value !== null)

  const visibleLinks = computed(() =>
    links.value.filter((link) => link.status === 'proposed' || link.status === 'accepted'),
  )

  const linkById = computed<Map<string, TraceLink>>(() => {
    const map = new Map<string, TraceLink>()
    for (const link of visibleLinks.value) map.set(link.id, link)
    return map
  })

  const selectedLink = computed<TraceLink | null>(() =>
    selectedLinkId.value ? linkById.value.get(selectedLinkId.value) ?? null : null,
  )

  const hoveredLink = computed<TraceLink | null>(() =>
    hoveredLinkId.value ? linkById.value.get(hoveredLinkId.value) ?? null : null,
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
          fanoutCount: 1,
          multiplicity: '1_to_1',
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
          fanoutCount: 1,
          multiplicity: '1_to_1',
          links: [link],
        })
      }
    }
    for (const view of map.values()) {
      view.links.sort((a, b) => b.relevance - a.relevance)
    }
    return map
  })

  const enrichedPaperTargets = computed(() => {
    const paper = new Map(paperTargets.value)
    const code = new Map(codeTargets.value)
    enrichMultiplicity(paper, code)
    return paper
  })

  const enrichedCodeTargets = computed(() => {
    const paper = new Map(paperTargets.value)
    const code = new Map(codeTargets.value)
    enrichMultiplicity(paper, code)
    return code
  })

  /**
   * Resolve a target id (from a pane hover/click) to the best relation id.
   * A target can back several relations; the highest-relevance one is the primary,
   * the rest remain listed in the popover.
   */
  function linkIdForTarget(side: 'paper' | 'code', targetId: string): string | null {
    const view =
      side === 'paper'
        ? enrichedPaperTargets.value.get(targetId)
        : enrichedCodeTargets.value.get(targetId)
    return view?.links[0]?.id ?? null
  }

  // Highlight the union of the selected relation's two targets (strong) — the hovered
  // relation is decorated separately with a weaker class (see *HoverTargetIds below).
  function targetIdsFor(link: TraceLink | null, side: 'paper' | 'code'): Set<string> {
    const ids = new Set<string>()
    if (!link) return ids
    const id = side === 'paper' ? paperTargetId(link) : codeTargetId(link)
    if (id) ids.add(id)
    return ids
  }

  const activePaperTargetIds = computed(() => targetIdsFor(selectedLink.value, 'paper'))
  const activeCodeTargetIds = computed(() => targetIdsFor(selectedLink.value, 'code'))
  const hoverPaperTargetIds = computed(() => targetIdsFor(hoveredLink.value, 'paper'))
  const hoverCodeTargetIds = computed(() => targetIdsFor(hoveredLink.value, 'code'))

  // ---- summaries ----------------------------------------------------------
  // Both the fixed box (selected relation) and the transient hover box show BOTH sides of a
  // relation, so a single summary shape backs either box.
  const summaryOf = (link: TraceLink | null): TraceLinkSummary | null => {
    if (!link) return null
    const paper = paperSide(link)
    const code = codeSide(link)
    const codeLine = code?.match_line_start ?? code?.line_start ?? null
    const pTargetId = paperTargetId(link)
    // Other relations that share this paper target (one code-segment ↔ many paper fragments, or
    // vice versa). Only the highest-relevance one is shown; the rest are surfaced as a count.
    const shared = pTargetId ? enrichedPaperTargets.value.get(pTargetId)?.links.length ?? 1 : 1
    return {
      linkId: link.id,
      relationType: link.relation_type,
      relevance: Math.round((link.relevance ?? 0) * 100),
      confidence: Math.round((link.confidence ?? 0) * 100),
      rationale: link.rationale ?? '',
      paper: {
        targetId: pTargetId,
        blockId: link.paper_block_id,
        quote: paper?.quote ?? '',
        targetType: paper?.target_type ?? '',
        occurrence: paper?.occurrence ?? 1,
      },
      code: {
        symbol: link.code_symbol_id,
        path: code?.path ?? '',
        line: codeLine,
      },
      otherLinkCount: Math.max(0, shared - 1),
    }
  }

  const selectedSummary = computed<TraceLinkSummary | null>(() => summaryOf(selectedLink.value))
  const hoveredSummary = computed<TraceLinkSummary | null>(() => {
    // Only show the hover box when the pointer is on a DIFFERENT relation than the selected one.
    if (!hoveredLink.value || hoveredLinkId.value === selectedLinkId.value) return null
    return summaryOf(hoveredLink.value)
  })


  // ---- mutators -----------------------------------------------------------

  function select(linkId: string, side: 'paper' | 'code'): void {
    if (!linkId) return
    // Re-selecting the same relation keeps it pinned (idempotent); Esc / the unpin
    // button is the explicit way to clear, so a stray re-click never loses focus.
    selectedLinkId.value = linkId
    selectedSide.value = side
  }

  function selectTarget(side: 'paper' | 'code', targetId: string): void {
    const linkId = linkIdForTarget(side, targetId)
    if (linkId) select(linkId, side)
  }

  function hover(linkId: string): void {
    hoveredLinkId.value = linkId || null
  }

  function hoverTarget(side: 'paper' | 'code', targetId: string): void {
    hoveredLinkId.value = linkIdForTarget(side, targetId)
  }

  function clearHover(): void {
    hoveredLinkId.value = null
  }

  function unselect(): void {
    selectedLinkId.value = null
    selectedSide.value = null
  }

  return {
    // state
    selectedLinkId,
    hoveredLinkId,
    selectedSide,
    pinned,
    // derived
    selectedLink,
    hoveredLink,
    paperTargets: enrichedPaperTargets,
    codeTargets: enrichedCodeTargets,
    activePaperTargetIds,
    activeCodeTargetIds,
    hoverPaperTargetIds,
    hoverCodeTargetIds,
    selectedSummary,
    hoveredSummary,
    // resolvers
    linkIdForTarget,
    // mutators
    select,
    selectTarget,
    hover,
    hoverTarget,
    clearHover,
    unselect,
  }
}

export type TraceIndex = ReturnType<typeof useTraceIndex>
