import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { createTraceLink } from '@/api/trace-api'
import type { TraceRelationType } from '@/types/tracing'

/**
 * Guided steps for adding one trace relation by hand.
 *
 * Each side has a select/confirm pair so the user explicitly advances, but the pane stays
 * pickable through confirm: clicking another paper/code target replaces the pending pick
 * without exiting the flow.
 */
export type AnnotationStep =
  | 'idle'
  | 'select-paper'
  | 'confirm-paper'
  | 'select-code'
  | 'confirm-code'
  | 'form'

export interface AnnotationPick {
  ref: string
  /** Human-readable excerpt kept for the submit dialog summary. */
  preview: string
  /** Extra context for the code side (path plus line range). */
  detail?: string
}

export const useAnnotationStore = defineStore('annotation', () => {
  const step = ref<AnnotationStep>('idle')
  const paperPick = ref<AnnotationPick | null>(null)
  const codePick = ref<AnnotationPick | null>(null)
  const submitting = ref(false)
  let generation = 0

  /** True whenever the guided flow owns the panes (selection handlers, cursors, overlays). */
  const active = computed(() => step.value !== 'idle')
  /** Paper pane accepts picks while selecting or confirming (so the user can switch). */
  const pickingPaper = computed(
    () => step.value === 'select-paper' || step.value === 'confirm-paper',
  )
  const pickingCode = computed(
    () => step.value === 'select-code' || step.value === 'confirm-code',
  )
  /** Keep a confirmed pick highlighted for the rest of the flow. */
  const paperConfirmed = computed(
    () => paperPick.value !== null && step.value !== 'select-paper' && step.value !== 'confirm-paper',
  )
  const codeConfirmed = computed(
    () => codePick.value !== null && step.value !== 'select-code' && step.value !== 'confirm-code',
  )
  const formVisible = computed(() => step.value === 'form')

  function clearFlow(): void {
    paperPick.value = null
    codePick.value = null
    step.value = 'idle'
  }

  function start(): void {
    if (submitting.value) return
    generation += 1
    clearFlow()
    step.value = 'select-paper'
  }

  function cancel(): void {
    if (submitting.value) return
    generation += 1
    clearFlow()
  }

  /** Drop project-scoped state and invalidate any request completing after navigation. */
  function resetForProject(): void {
    generation += 1
    clearFlow()
    submitting.value = false
  }

  /** Toggle used by the toolbar button. */
  function toggle(): void {
    if (active.value) cancel()
    else start()
  }

  function pickPaper(pick: AnnotationPick): void {
    if (submitting.value) return
    // Stay pickable through confirm so the user can switch before advancing.
    if (step.value !== 'select-paper' && step.value !== 'confirm-paper') return
    paperPick.value = pick
    step.value = 'confirm-paper'
  }

  function pickCode(pick: AnnotationPick): void {
    if (submitting.value) return
    if (step.value !== 'select-code' && step.value !== 'confirm-code') return
    codePick.value = pick
    step.value = 'confirm-code'
  }

  /** Accept the pending pick and advance; from confirm-code this opens the form. */
  function confirmPick(): void {
    if (submitting.value) return
    if (step.value === 'confirm-paper') step.value = 'select-code'
    else if (step.value === 'confirm-code') step.value = 'form'
  }

  /** Discard the pending pick and stay on the same side. */
  function retryPick(): void {
    if (submitting.value) return
    if (step.value === 'confirm-paper') {
      paperPick.value = null
      step.value = 'select-paper'
    } else if (step.value === 'confirm-code') {
      codePick.value = null
      step.value = 'select-code'
    }
  }

  /** From the form, go back to re-pick the code side. */
  function backToCode(): void {
    if (submitting.value) return
    if (step.value !== 'form') return
    codePick.value = null
    step.value = 'select-code'
  }

  async function submit(
    projectId: number,
    payload: {
      relationType: TraceRelationType
      confidence: number
      rationale: string
    },
  ): Promise<string> {
    if (!paperPick.value || !codePick.value) throw new Error('annotation_incomplete')
    if (!Number.isInteger(projectId) || projectId <= 0) throw new Error('annotation_project_invalid')
    if (submitting.value) throw new Error('annotation_submitting')
    const submissionGeneration = generation
    submitting.value = true
    try {
      const created = await createTraceLink(projectId, {
        paper_ref: paperPick.value.ref,
        code_ref: codePick.value.ref,
        relation_type: payload.relationType,
        // The slider works in percent; the API takes a 0-1 confidence.
        confidence: payload.confidence / 100,
        rationale: payload.rationale,
        // Empty: the backend derives both quotes and anchor ids from the two refs.
        evidence: [],
      })
      if (generation === submissionGeneration) clearFlow()
      return created.id
    } finally {
      if (generation === submissionGeneration) submitting.value = false
    }
  }

  return {
    step,
    paperPick,
    codePick,
    submitting,
    active,
    pickingPaper,
    pickingCode,
    paperConfirmed,
    codeConfirmed,
    formVisible,
    start,
    cancel,
    resetForProject,
    toggle,
    pickPaper,
    pickCode,
    confirmPick,
    retryPick,
    backToCode,
    submit,
  }
})
