import { describe, expect, it } from 'vitest'

import {
  resolveSinglePaperBlock,
  selectedLineRange,
} from '../../../frontend/src/features/tracing/annotation-selection'

const document = {
  lineAt(position: number) {
    if (position < 5) return { number: 1 }
    if (position < 11) return { number: 2 }
    return { number: 3 }
  },
}

describe('annotation selection boundaries', () => {
  it('uses the last selected character for the inclusive end line', () => {
    expect(selectedLineRange(document, 0, 5)).toEqual({ startLine: 1, endLine: 1 })
    expect(selectedLineRange(document, 2, 11)).toEqual({ startLine: 1, endLine: 2 })
  })

  it('accepts same-block paper drags and rejects cross-block drags', () => {
    const same = (node: string) => ({ start: 'p1', end: 'p1' })[node] ?? null
    const cross = (node: string) => ({ start: 'p1', end: 'p2' })[node] ?? null
    expect(resolveSinglePaperBlock('start', 'end', same)).toBe('p1')
    expect(resolveSinglePaperBlock('start', 'end', cross)).toBeNull()
  })
})
