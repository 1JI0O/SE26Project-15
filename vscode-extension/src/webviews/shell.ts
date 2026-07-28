import * as vscode from 'vscode'

export { escapeHtml, jsonForScript } from './webviewUtils'

/** Shared webview scaffolding: CSP, nonce, asset URIs and HTML escaping. */
export interface ShellAssets {
  /** `media/...` relative path to webview URI. */
  media: (rel: string) => string
  nonce: string
  csp: string
}

export function shellAssets(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  options: { images?: boolean } = {},
): ShellAssets {
  const nonce = createNonce()
  const source = webview.cspSource
  const img = options.images ? `${source} data: blob:` : `${source} data:`
  return {
    nonce,
    media: (rel: string) =>
      webview
        .asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', ...rel.split('/')))
        .toString(),
    csp: [
      `default-src 'none'`,
      `style-src ${source} 'unsafe-inline'`,
      `script-src ${source} 'nonce-${nonce}'`,
      `font-src ${source}`,
      `img-src ${img}`,
      `worker-src ${source} blob:`,
      `connect-src ${source} blob: data:`,
    ].join('; '),
  }
}

function createNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let out = ''
  for (let i = 0; i < 32; i += 1) {
    out += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return out
}
