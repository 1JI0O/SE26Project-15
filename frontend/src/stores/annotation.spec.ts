import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAnnotationStore } from './annotation'

const { createTraceLinkMock } = vi.hoisted(() => ({
  createTraceLinkMock: vi.fn(),
}))

vi.mock('@/api/trace-api', () => ({
  createTraceLink: createTraceLinkMock,
}))

const paperPick = { ref: 'paper:paragraph:p1', preview: 'paper excerpt' }
const codePick = { ref: 'code:src/main.py:1-3', preview: 'def run(): pass', detail: 'main.py:1-3' }

function advanceToForm() {
  const store = useAnnotationStore()
  store.start()
  store.pickPaper(paperPick)
  store.confirmPick()
  store.pickCode(codePick)
  store.confirmPick()
  return store
}

describe('guided annotation store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    createTraceLinkMock.mockReset()
  })

  it('enforces paper-confirm-code-confirm-form order and supports retry/back', () => {
    const store = useAnnotationStore()

    store.start()
    expect(store.step).toBe('select-paper')
    store.pickCode(codePick)
    expect(store.step).toBe('select-paper')

    store.pickPaper(paperPick)
    expect(store.step).toBe('confirm-paper')
    expect(store.paperPick).toEqual(paperPick)
    store.retryPick()
    expect(store.step).toBe('select-paper')
    expect(store.paperPick).toBeNull()

    store.pickPaper(paperPick)
    store.confirmPick()
    store.pickCode(codePick)
    expect(store.step).toBe('confirm-code')
    store.confirmPick()
    expect(store.formVisible).toBe(true)
    expect(store.paperConfirmed).toBe(true)
    expect(store.codeConfirmed).toBe(true)

    store.backToCode()
    expect(store.step).toBe('select-code')
    expect(store.codePick).toBeNull()
    expect(store.paperPick).toEqual(paperPick)
  })

  it('clears all project-scoped picks when cancelled or reset', () => {
    const store = advanceToForm()
    store.cancel()
    expect(store.step).toBe('idle')
    expect(store.paperPick).toBeNull()
    expect(store.codePick).toBeNull()

    store.start()
    store.pickPaper(paperPick)
    store.resetForProject()
    expect(store.active).toBe(false)
    expect(store.paperPick).toBeNull()

    store.toggle()
    expect(store.step).toBe('select-paper')
    store.toggle()
    expect(store.step).toBe('idle')
  })

  it('submits the normalized payload and resets after success', async () => {
    createTraceLinkMock.mockResolvedValue({ id: 'trace-7' })
    const store = advanceToForm()

    await expect(
      store.submit(7, {
        relationType: 'implements',
        confidence: 85,
        rationale: 'matches the implementation',
      }),
    ).resolves.toBe('trace-7')

    expect(createTraceLinkMock).toHaveBeenCalledWith(7, {
      paper_ref: paperPick.ref,
      code_ref: codePick.ref,
      relation_type: 'implements',
      confidence: 0.85,
      rationale: 'matches the implementation',
      evidence: [],
    })
    expect(store.step).toBe('idle')
    expect(store.submitting).toBe(false)
  })

  it('locks navigation during submit and preserves the form after failure', async () => {
    let rejectRequest!: (cause: Error) => void
    createTraceLinkMock.mockImplementation(
      () => new Promise((_resolve, reject) => {
        rejectRequest = reject
      }),
    )
    const store = advanceToForm()
    const pending = store.submit(3, {
      relationType: 'tests',
      confidence: 50,
      rationale: 'failure path',
    })

    expect(store.submitting).toBe(true)
    store.cancel()
    store.backToCode()
    store.start()
    expect(store.step).toBe('form')
    await expect(
      store.submit(3, {
        relationType: 'tests',
        confidence: 50,
        rationale: 'duplicate request',
      }),
    ).rejects.toThrow('annotation_submitting')

    rejectRequest(new Error('offline'))
    await expect(pending).rejects.toThrow('offline')
    expect(store.step).toBe('form')
    expect(store.paperPick).toEqual(paperPick)
    expect(store.codePick).toEqual(codePick)
    expect(store.submitting).toBe(false)
  })

  it('does not let an old request completion reset a newly opened project', async () => {
    let resolveRequest!: (value: { id: string }) => void
    createTraceLinkMock.mockImplementation(
      () => new Promise((resolve) => {
        resolveRequest = resolve
      }),
    )
    const store = advanceToForm()
    const pending = store.submit(3, {
      relationType: 'mentions',
      confidence: 60,
      rationale: 'old project request',
    })

    store.resetForProject()
    store.start()
    resolveRequest({ id: 'old-trace' })
    await expect(pending).resolves.toBe('old-trace')
    expect(store.step).toBe('select-paper')
    expect(store.submitting).toBe(false)
  })

  it('rejects incomplete and invalid-project submissions', async () => {
    const store = useAnnotationStore()
    await expect(
      store.submit(1, { relationType: 'defines', confidence: 50, rationale: 'missing picks' }),
    ).rejects.toThrow('annotation_incomplete')

    const ready = advanceToForm()
    await expect(
      ready.submit(Number.NaN, {
        relationType: 'defines',
        confidence: 50,
        rationale: 'bad project',
      }),
    ).rejects.toThrow('annotation_project_invalid')
  })
})
