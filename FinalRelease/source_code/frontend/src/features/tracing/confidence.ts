// Shared confidence → color mapping for trace review surfaces (matrix bars, evidence drawer).
export function confidenceColor(pct: number): string {
  if (pct >= 80) return '#1f8f78'
  if (pct >= 50) return '#d97706'
  return '#e15a4a'
}
