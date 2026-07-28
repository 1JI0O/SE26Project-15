/**
 * Shared Markdown + KaTeX renderer for TraceLab webviews.
 *
 * Lives as a real file (not an inline template string) so the `$$` / backslash
 * escapes stay readable and behave identically in the paper reader and the
 * trace-matrix evidence snippets.
 *
 * Requires markdown-it, katex and DOMPurify to be loaded first.
 * Exposes `window.TraceLabMd`.
 */
(function () {
  'use strict'

  var SANITIZE = {
    ADD_ATTR: ['id', 'data-paper-block-id', 'data-trace-target', 'loading', 'target'],
  }

  function mathInline(state, silent) {
    var start = state.pos
    if (state.src[start] !== '$' || state.src[start + 1] === '$') return false
    var end = start + 1
    while ((end = state.src.indexOf('$', end)) !== -1) {
      if (state.src[end - 1] !== '\\') break
      end += 1
    }
    if (end === -1) return false
    if (end === start + 1) return false
    if (!silent) {
      var token = state.push('math_inline', 'math', 0)
      token.content = state.src.slice(start + 1, end)
    }
    state.pos = end + 1
    return true
  }

  function mathBlock(state, startLine, endLine, silent) {
    var pos = state.bMarks[startLine] + state.tShift[startLine]
    var max = state.eMarks[startLine]
    var opening = state.src.slice(pos, max).trim()
    if (opening.indexOf('$$') !== 0) return false
    var content = opening.slice(2)
    var nextLine = startLine
    if (/\$\$$/.test(content) && content.length > 2) {
      content = content.slice(0, -2)
    } else {
      var chunks = [content]
      var closed = false
      while (++nextLine < endLine) {
        var lineStart = state.bMarks[nextLine] + state.tShift[nextLine]
        var lineEnd = state.eMarks[nextLine]
        var line = state.src.slice(lineStart, lineEnd)
        if (/\$\$\s*$/.test(line.trim())) {
          chunks.push(line.replace(/\$\$\s*$/, ''))
          closed = true
          break
        }
        chunks.push(line)
      }
      if (!closed) return false
      content = chunks.join('\n')
    }
    if (!silent) {
      var token = state.push('math_block', 'math', 0)
      token.block = true
      token.content = content.trim()
      token.map = [startLine, nextLine + 1]
    }
    state.line = nextLine + 1
    return true
  }

  function tex(source, displayMode) {
    try {
      return window.katex.renderToString(source, {
        throwOnError: false,
        displayMode: displayMode,
        strict: false,
        trust: false,
      })
    } catch (error) {
      return '<code class="tl-math-error">' + escapeHtml(String(source)) + '</code>'
    }
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"]/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]
    })
  }

  /**
   * @param {{html?: boolean, linkify?: boolean, headingIds?: boolean}} [options]
   */
  function createRenderer(options) {
    var opts = options || {}
    var md = window.markdownit({
      html: opts.html !== false,
      linkify: Boolean(opts.linkify),
      breaks: false,
    })

    if (opts.headingIds) {
      var headingIndex = 0
      var defaultHeading =
        md.renderer.rules.heading_open ||
        function (tokens, idx, config, env, self) {
          return self.renderToken(tokens, idx, config)
        }
      md.renderer.rules.heading_open = function (tokens, idx, config, env, self) {
        headingIndex += 1
        tokens[idx].attrSet('id', 'section-' + headingIndex)
        return defaultHeading(tokens, idx, config, env, self)
      }
    }

    md.inline.ruler.before('escape', 'math_inline', mathInline)
    md.block.ruler.before('fence', 'math_block', mathBlock, {
      alt: ['paragraph', 'reference', 'blockquote', 'list'],
    })
    md.renderer.rules.math_inline = function (tokens, idx) {
      return tex(tokens[idx].content, false)
    }
    md.renderer.rules.math_block = function (tokens, idx) {
      return '<div class="math-display">' + tex(tokens[idx].content, true) + '</div>'
    }
    return md
  }

  /** Render a full markdown document (sanitized). */
  function render(source, options) {
    var md = createRenderer(options)
    return window.DOMPurify.sanitize(md.render(String(source || '')), SANITIZE)
  }

  /**
   * Render a short evidence snippet. Bare `$…$` pairs are preserved by the host
   * extractor, so plain fragments still round-trip through the math rules.
   */
  function renderSnippet(source) {
    if (!String(source || '').trim()) return ''
    return render(source, { html: false, linkify: false })
  }

  window.TraceLabMd = {
    createRenderer: createRenderer,
    render: render,
    renderSnippet: renderSnippet,
    escapeHtml: escapeHtml,
  }
})()
