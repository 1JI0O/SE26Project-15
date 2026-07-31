import { describe, expect, it, vi } from 'vitest'

import { resolveSinglePaperBlock, selectedLineRange } from './annotation-selection'

const document = {
  lineAt(position: number) {
    if (position < 5) return { number: 1 }
    if (position < 11) return { number: 2 }
    return { number: 3 }
  },
}

describe('annotation selection boundaries', () => {
  it('keeps an exclusive next-line offset on the previous line', () => {
    expect(selectedLineRange(document, 0, 5)).toEqual({ startLine: 1, endLine: 1 })
    expect(selectedLineRange(document, 2, 11)).toEqual({ startLine: 1, endLine: 2 })
  })

  it('handles ordinary single-line and multi-line selections', () => {
    expect(selectedLineRange(document, 1, 4)).toEqual({ startLine: 1, endLine: 1 })
    expect(selectedLineRange(document, 5, 13)).toEqual({ startLine: 2, endLine: 3 })
    expect(selectedLineRange(document, 4, 4)).toBeNull()
  })

  it('accepts a paper drag only when both ends resolve to the same block', () => {
    const resolve = vi.fn((node: string) => ({ start: 'p1', end: 'p1' })[node] ?? null)
    expect(resolveSinglePaperBlock('start', 'end', resolve)).toBe('p1')
  })

  it('rejects cross-block and unresolved paper drags', () => {
    const crossBlock = (node: string) => ({ start: 'p1', end: 'p2' })[node] ?? null
    expect(resolveSinglePaperBlock('start', 'end', crossBlock)).toBeNull()
    expect(resolveSinglePaperBlock('missing', 'end', crossBlock)).toBeNull()
  })
})
