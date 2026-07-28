export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll("&", "&amp;")
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

/** Serialize data for an inline script without allowing HTML parser breakouts. */
export function jsonForScript(value: unknown): string {
  const slash = String.fromCharCode(92)
  return JSON.stringify(value ?? null)
    .replaceAll('<', slash + 'u003c')
    .replaceAll('>', slash + 'u003e')
    .replaceAll('&', slash + 'u0026')
    .replaceAll(String.fromCharCode(0x2028), slash + 'u2028')
    .replaceAll(String.fromCharCode(0x2029), slash + 'u2029')
}
