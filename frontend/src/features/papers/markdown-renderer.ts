import DOMPurify from 'dompurify'
import katex from 'katex'
import MarkdownIt from 'markdown-it'
import type StateBlock from 'markdown-it/lib/rules_block/state_block.mjs'
import type StateInline from 'markdown-it/lib/rules_inline/state_inline.mjs'

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
  mathPlugin(markdown)

  let headingIndex = 0
  markdown.renderer.rules.heading_open = (tokens, index, options, _environment, renderer) => {
    headingIndex += 1
    tokens[index].attrSet('id', `section-${headingIndex}`)
    return renderer.renderToken(tokens, index, options)
  }

  const fallbackImageRenderer = markdown.renderer.rules.image
  markdown.renderer.rules.image = (tokens, index, options, environment, renderer) => {
    const source = tokens[index].attrGet('src')
    if (source) {
      const resolvedSource = resolveAsset(source)
      tokens[index].attrSet('src', resolvedSource)
      tokens[index].attrSet('data-paper-asset-url', resolvedSource)
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
    ],
  })
  const template = document.createElement('template')
  template.innerHTML = sanitized
  for (const table of template.content.querySelectorAll('table')) {
    const wrapper = document.createElement('div')
    wrapper.className = 'table-scroll'
    table.parentNode?.insertBefore(wrapper, table)
    wrapper.append(table)
  }
  return template.innerHTML
}
