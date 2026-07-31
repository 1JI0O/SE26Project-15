interface LineAtDocument {
  lineAt(position: number): { number: number }
}

export interface SelectedLineRange {
  startLine: number
  endLine: number
}

/** Treat `to` as an exclusive offset so a drag ending at the next line start stays on the prior line. */
export function selectedLineRange(
  document: LineAtDocument,
  from: number,
  to: number,
): SelectedLineRange | null {
  if (to <= from) return null
  return {
    startLine: document.lineAt(from).number,
    endLine: document.lineAt(to - 1).number,
  }
}

/** A manual paper link is block-granular, so cross-block drags must be rejected. */
export function resolveSinglePaperBlock<T>(
  startContainer: T,
  endContainer: T,
  resolve: (container: T) => string | null,
): string | null {
  const startBlock = resolve(startContainer)
  if (!startBlock) return null
  return resolve(endContainer) === startBlock ? startBlock : null
}
