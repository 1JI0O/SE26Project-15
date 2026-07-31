import DOMPurify from 'dompurify'
import katex from 'katex'
import MarkdownIt from 'markdown-it'
import type StateBlock from 'markdown-it/lib/rules_block/state_block.mjs'
import type StateInline from 'markdown-it/lib/rules_inline/state_inline.mjs'

import { extractPaperMarkdownSnippet } from './paper-snippet'

type AssetResolver = (path: string) => string

function mathPlugin(markdown: MarkdownIt): void {
  markdown.inline.ruler.before(
    'escape',
    'math_inline',
    (state: StateInline, silent: boolean): boolean => {
      const start = state.pos
      if (state.src[start] !== '$' || state.src[start + 1] === '$') return false
      let end = start + 1
      while ((end = state.src.indexOf('$', end)) !== -1) {
        if (state.src[end - 1] !== '\\' && state.src.slice(start + 1, end).trim()) break
        end += 1
      }
      if (end === -1) return false
      if (!silent) {
        const token = state.push('math_inline', 'math', 0)
        token.content = state.src.slice(start + 1, end)
      }
      state.pos = end + 1
      return true
    },
  )

  markdown.block.ruler.before(
    'fence',
    'math_block',
    (state: StateBlock, startLine: number, endLine: number, silent: boolean): boolean => {
      const start = state.bMarks[startLine] + state.tShift[startLine]
      const lineEnd = state.eMarks[startLine]
      const opening = state.src.slice(start, lineEnd).trim()
      if (!opening.startsWith('$$')) return false

      let content = opening.slice(2)
      let nextLine = startLine
      if (content.endsWith('$$') && content.length > 2) {
        content = content.slice(0, -2)
      } else {
        const chunks = [content]
        let closed = false
        while (++nextLine < endLine) {
          const lineStart = state.bMarks[nextLine] + state.tShift[nextLine]
          const currentEnd = state.eMarks[nextLine]
          const current = state.src.slice(lineStart, currentEnd)
          if (current.trim().endsWith('$$')) {
            chunks.push(current.replace(/\$\$\s*$/, ''))
            closed = true
            break
          }
          chunks.push(current)
        }
        if (!closed) return false
        content = chunks.join('\n')
      }

      if (!silent) {
        const token = state.push('math_block', 'math', 0)
        token.block = true
        token.content = content.trim()
        token.map = [startLine, nextLine + 1]
      }
      state.line = nextLine + 1
      return true
    },
    { alt: ['paragraph', 'reference', 'blockquote', 'list'] },
  )

  markdown.renderer.rules.math_inline = (tokens, index) =>
    katex.renderToString(tokens[index].content, { throwOnError: false, displayMode: false })
  markdown.renderer.rules.math_block = (tokens, index) =>
    `<div class="math-display">${katex.renderToString(tokens[index].content, {
      throwOnError: false,
      displayMode: true,
    })}</div>`
}

export function renderPaperMarkdown(markdownText: string, resolveAsset: AssetResolver): string {
  const markdown = new MarkdownIt({ html: true, linkify: true, typographer: false })
  const renderToken = Array.from(crypto.getRandomValues(new Uint32Array(4)))
    .map((value) => value.toString(16))
    .join('-')
  mathPlugin(markdown)

  let headingIndex = 0
  markdown.renderer.rules.heading_open = (tokens, index, options, _environment, renderer) => {
    headingIndex += 1
    tokens[index].attrSet('id', `section-${headingIndex}`)
    return renderer.renderToken(tokens, index, options)
  }

  // NOTE: paragraphs deliberately get no `data-paper-block-id` here. The backend already
  // injects `<span data-paper-block-id="p1-b6">` anchors carrying the real MinerU block ids
  // (`paper_markdown.inject_block_anchors`). Adding the attribute to the wrapping `<p>` as well
  // shadowed them: `closest('[data-paper-block-id]')` from selected text hit the paragraph
  // first and returned an invented `para-N` id that matches no stored block, which broke both
  // evidence quoting and highlight resolution. Use `resolveBlockIdAt` to read the real id.

  const fallbackImageRenderer = markdown.renderer.rules.image
  markdown.renderer.rules.image = (tokens, index, options, environment, renderer) => {
    const source = tokens[index].attrGet('src')
    if (source) {
      const resolvedSource = resolveAsset(source)
      tokens[index].attrSet('src', resolvedSource)
      tokens[index].attrSet('data-paper-asset-url', resolvedSource)
      tokens[index].attrSet('data-paper-render-token', renderToken)
    }
    tokens[index].attrSet('loading', 'lazy')
    tokens[index].attrSet('decoding', 'async')
    return fallbackImageRenderer
      ? fallbackImageRenderer(tokens, index, options, environment, renderer)
      : renderer.renderToken(tokens, index, options)
  }

  const rendered = markdown.render(markdownText)
  const sanitized = DOMPurify.sanitize(rendered, {
    ADD_ATTR: [
      'id',
      'loading',
      'decoding',
      'rowspan',
      'colspan',
      'data-paper-asset-url',
      'data-paper-render-token',
      'data-paper-block-id',
    ],
  })
  const template = document.createElement('template')
  template.innerHTML = sanitized
  for (const image of template.content.querySelectorAll('img')) {
    if (
      image.dataset.paperRenderToken !== renderToken ||
      !image.dataset.paperAssetUrl
    ) {
      image.remove()
      continue
    }
    delete image.dataset.paperRenderToken
  }
  for (const element of template.content.querySelectorAll<HTMLElement>('[style]')) {
    const style = element.getAttribute('style') || ''
    if (/url\s*\(|@import|expression\s*\(/i.test(style)) element.removeAttribute('style')
  }
  for (const table of template.content.querySelectorAll('table')) {
    const wrapper = document.createElement('div')
    wrapper.className = 'table-scroll'
    table.parentNode?.insertBefore(wrapper, table)
    wrapper.append(table)
  }
  return template.innerHTML
}

/** Render a short markdown snippet (paper quote / rationale) with the same math rules as the paper pane. */
export function renderTraceRichText(text: string): string {
  const value = text.trim()
  if (!value) return ''
  return renderPaperMarkdown(value, () => '')
}

/** Render paper evidence by slicing the MinerU markdown source (keeps `$` / `$$`), not bare TeX quotes. */
export function renderPaperEvidenceHtml(
  markdown: string,
  blockId: string,
  quote = '',
  occurrence = 1,
): string {
  const snippet = extractPaperMarkdownSnippet(markdown, blockId, quote, occurrence)
  return renderTraceRichText(snippet || quote || blockId)
}
