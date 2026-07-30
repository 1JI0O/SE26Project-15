import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAnnotationStore } from '../../../frontend/src/stores/annotation'

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
    store.retryPick()
    expect(store.step).toBe('select-paper')
    store.pickPaper(paperPick)
    store.confirmPick()
    store.pickCode(codePick)
    store.confirmPick()
    expect(store.formVisible).toBe(true)
    store.backToCode()
    expect(store.step).toBe('select-code')
    expect(store.codePick).toBeNull()
  })

  it('clears project state and submits normalized payload', async () => {
    createTraceLinkMock.mockResolvedValue({ id: 'trace-7' })
    const store = advanceToForm()
    await expect(
      store.submit(7, {
        relationType: 'implements',
        confidence: 85,
        rationale: 'matches the implementation',
      }),
    ).resolves.toBe('trace-7')
    expect(createTraceLinkMock).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ confidence: 0.85, evidence: [] }),
    )
    expect(store.step).toBe('idle')
  })

  it('locks navigation during submit and ignores stale completion after project reset', async () => {
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
    store.cancel()
    expect(store.step).toBe('form')
    store.resetForProject()
    store.start()
    resolveRequest({ id: 'old-trace' })
    await pending
    expect(store.step).toBe('select-paper')
  })
})
