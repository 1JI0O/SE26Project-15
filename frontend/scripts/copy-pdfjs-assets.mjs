/**
 * Stage pdf.js character maps and standard fonts into `public/pdfjs/`.
 *
 * pdf.js loads these lazily at runtime and defaults to fetching them from a CDN. The
 * desktop shell has no network guarantee and the app is local-first, so they are copied
 * into the build output and referenced by a same-origin path instead (see PdfReader.vue).
 *
 * cmaps matter for PDFs using CJK encodings without embedded fonts — common enough in
 * Chinese papers that dropping them would show blank glyphs.
 */

import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)

// Resolve through the package rather than assuming a node_modules layout: pnpm stores
// real files under .pnpm/, so a hard-coded path would miss.
const pdfjsRoot = path.dirname(require.resolve('pdfjs-dist/package.json'))
const target = path.join(frontendRoot, 'public', 'pdfjs')

const assets = ['cmaps', 'standard_fonts']
const missing = assets.filter((name) => !existsSync(path.join(pdfjsRoot, name)))
if (missing.length > 0) {
  console.error(`[pdfjs-assets] missing in pdfjs-dist: ${missing.join(', ')}`)
  process.exit(1)
}

rmSync(target, { recursive: true, force: true })
mkdirSync(target, { recursive: true })
for (const name of assets) {
  cpSync(path.join(pdfjsRoot, name), path.join(target, name), { recursive: true })
}

console.log(`[pdfjs-assets] staged ${assets.join(', ')} into public/pdfjs`)
