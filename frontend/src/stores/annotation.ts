import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { createTraceLink } from '@/api/trace-api'
import type { TraceRelationType } from '@/types/tracing'

/**
 * Guided steps for adding one trace relation by hand.
 *
 * The flow is an explicit state machine rather than "pick either side in any order" because
 * the free-form version gave no answer to the only question that matters mid-task — *did my
 * selection register?* Each pick now lands in a `*-confirm` step that shows the captured
 * preview and forces an explicit accept, so the current step alone tells the user what to do
 * next and what the tool believes they selected.
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
  /** Human-readable excerpt of the captured selection, shown back before confirming. */
  preview: string
  /** Extra context for the code side (path plus line range). */
  detail?: string
}

export const useAnnotationStore = defineStore('annotation', () => {
  const step = ref<AnnotationStep>('idle')
  const paperPick = ref<AnnotationPick | null>(null)
  const codePick = ref<AnnotationPick | null>(null)
  const submitting = ref(false)

  /** True whenever the guided flow owns the panes (selection handlers, cursors, overlays). */
  const active = computed(() => step.value !== 'idle')
  /** The paper pane accepts picks only while its own step is current. */
  const pickingPaper = computed(() => step.value === 'select-paper')
  const pickingCode = computed(() => step.value === 'select-code')
  /** Keep a confirmed pick highlighted for the rest of the flow. */
  const paperConfirmed = computed(
    () => paperPick.value !== null && step.value !== 'select-paper' && step.value !== 'confirm-paper',
  )
  const codeConfirmed = computed(
    () => codePick.value !== null && step.value !== 'select-code' && step.value !== 'confirm-code',
  )
  const formVisible = computed(() => step.value === 'form')

  function start(): void {
    paperPick.value = null
    codePick.value = null
    step.value = 'select-paper'
  }

  function cancel(): void {
    paperPick.value = null
    codePick.value = null
    step.value = 'idle'
  }

  /** Toggle used by the toolbar button. */
  function toggle(): void {
    if (active.value) cancel()
    else start()
  }

  function pickPaper(pick: AnnotationPick): void {
    if (step.value !== 'select-paper') return
    paperPick.value = pick
    step.value = 'confirm-paper'
  }

  function pickCode(pick: AnnotationPick): void {
    if (step.value !== 'select-code') return
    codePick.value = pick
    step.value = 'confirm-code'
  }

  /** Accept the pending pick and advance; from confirm-code this opens the form. */
  function confirmPick(): void {
    if (step.value === 'confirm-paper') step.value = 'select-code'
    else if (step.value === 'confirm-code') step.value = 'form'
  }

  /** Discard the pending pick and stay on the same side. */
  function retryPick(): void {
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
      cancel()
      return created.id
    } finally {
      submitting.value = false
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
    toggle,
    pickPaper,
    pickCode,
    confirmPick,
    retryPick,
    backToCode,
    submit,
  }
})
