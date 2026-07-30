import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { TraceRelationType } from '@/types/tracing'
import { createTraceLink } from '@/api/trace-api'

interface AnnotationState {
  annotationMode: boolean
  selectedPaperRef: string | null
  selectedCodeRef: string | null
  dialogVisible: boolean
}

export const useAnnotationStore = defineStore('annotation', () => {
  const annotationMode = ref(false)
  const selectedPaperRef = ref<string | null>(null)
  const selectedCodeRef = ref<string | null>(null)
  const dialogVisible = ref(false)

  function enterAnnotationMode() {
    annotationMode.value = true
    clearSelection()
  }

  function exitAnnotationMode() {
    annotationMode.value = false
    clearSelection()
    dialogVisible.value = false
  }

  function toggleAnnotationMode() {
    if (annotationMode.value) {
      exitAnnotationMode()
    } else {
      enterAnnotationMode()
    }
  }

  function selectPaperBlock(ref: string) {
    if (!annotationMode.value) return
    selectedPaperRef.value = ref
    checkOpenDialog()
  }

  function selectCodeSymbol(ref: string) {
    if (!annotationMode.value) return
    selectedCodeRef.value = ref
    checkOpenDialog()
  }

  function checkOpenDialog() {
    if (selectedPaperRef.value && selectedCodeRef.value) {
      dialogVisible.value = true
    }
  }

  function clearSelection() {
    selectedPaperRef.value = null
    selectedCodeRef.value = null
  }

  async function createManualTraceLink(payload: {
    relationType: TraceRelationType
    confidence: number
    rationale: string
  }): Promise<{ traceId: string; fresh: boolean }> {
    if (!selectedPaperRef.value || !selectedCodeRef.value) {
      throw new Error('No selection')
    }

    const projectId = parseInt(window.location.pathname.split('/')[2])

    // Create with empty evidence - backend will construct it
    const result = await createTraceLink(projectId, {
      paper_ref: selectedPaperRef.value,
      code_ref: selectedCodeRef.value,
      relation_type: payload.relationType,
      confidence: payload.confidence / 100, // Convert from 0-100 to 0-1
      rationale: payload.rationale,
      evidence: [],
    })

    // Clear selection and close dialog
    clearSelection()
    dialogVisible.value = false

    return {
      traceId: result.id,
      fresh: true,
    }
  }

  return {
    annotationMode,
    selectedPaperRef,
    selectedCodeRef,
    dialogVisible,
    enterAnnotationMode,
    exitAnnotationMode,
    toggleAnnotationMode,
    selectPaperBlock,
    selectCodeSymbol,
    clearSelection,
    createManualTraceLink,
  }
})
