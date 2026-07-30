/**
 * Paper reader client.
 *
 * Data arrives via postMessage (`type: 'paper'`), so the shell paints
 * immediately and a refresh never restarts the PDF load. Markdown is rendered in
 * chunks across frames to keep the webview responsive on long papers, and PDF
 * pages render lazily with bounded concurrency.
 */
;(function () {
  'use strict'

  var vscodeApi = acquireVsCodeApi()
  var mdRoot = document.getElementById('md')
  var mdBusy = document.getElementById('mdBusy')
  var contentEl = document.getElementById('content')
  var tabMd = document.getElementById('tabMd')
  var tabPdf = document.getElementById('tabPdf')
  var tocEl = document.getElementById('toc')
  var zoomBox = document.getElementById('pdfZoom')
  var zoomLabel = document.getElementById('pdfZoomLabel')
  var pdfRoot = document.getElementById('pdfRoot')
  var pdfError = document.getElementById('pdfError')

  var state = { marks: [], rects: {}, pdfUri: '', focusLinkId: null, markdown: '' }
  var pdf = { doc: null, url: '', zoom: 100, pages: new Map(), token: 0, observer: null, active: 0 }
  var pdfjsReady = false

  window.addEventListener('tl-pdfjs-ready', function () {
    pdfjsReady = true
  })

  /* ------------------------------ view switch ------------------------------ */
  function showPane(which) {
    var isPdf = which === 'pdf'
    tabMd.classList.toggle('active', !isPdf)
    tabPdf.classList.toggle('active', isPdf)
    document.getElementById('mdPane').classList.toggle('active', !isPdf)
    document.getElementById('pdfPane').classList.toggle('active', isPdf)
    zoomBox.hidden = !isPdf || !state.pdfUri
    if (isPdf) void ensurePdf()
  }

  tabMd.addEventListener('click', function () {
    showPane('md')
  })
  tabPdf.addEventListener('click', function () {
    if (state.pdfUri) showPane('pdf')
  })
  tocEl.addEventListener('change', function (event) {
    var id = event.target.value
    if (!id) return
    showPane('md')
    var target = document.getElementById(id)
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })

  /* ---------------------------- markdown render ---------------------------- */
  var renderJob = 0

  /**
   * Render markdown into the pane in slices, one animation frame apart.
   * KaTeX over a whole paper is tens of milliseconds per formula; doing it in one
   * synchronous pass left the panel blank for a long time on big papers.
   */
  function renderMarkdown(source) {
    var job = ++renderJob
    mdRoot.innerHTML = ''
    mdBusy.hidden = false
    var slices = splitTopLevel(source)
    var index = 0

    function step() {
      if (job !== renderJob) return
      var started = Date.now()
      // Keep each frame under ~40ms so scrolling and the tab switch stay live.
      while (index < slices.length && Date.now() - started < 40) {
        var host = document.createElement('div')
        try {
          host.innerHTML = window.TraceLabMd.render(slices[index], { headingIds: true })
        } catch (error) {
          host.textContent = slices[index]
        }
        while (host.firstChild) mdRoot.appendChild(host.firstChild)
        index += 1
      }
      if (index < slices.length) {
        requestAnimationFrame(step)
        return
      }
      mdBusy.hidden = true
      renumberHeadings()
      applyMarks()
      focusMark(state.focusLinkId, false)
    }
    requestAnimationFrame(step)
  }

  /** Split on blank lines outside fenced code / display math so slices stay valid. */
  function splitTopLevel(source) {
    var lines = String(source || '').split('\n')
    var slices = []
    var buffer = []
    var inFence = false
    var inMath = false
    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i]
      if (/^\s*(```|~~~)/.test(line)) inFence = !inFence
      var dollars = (line.match(/\$\$/g) || []).length
      if (!inFence && dollars % 2 === 1) inMath = !inMath
      buffer.push(line)
      if (!inFence && !inMath && line.trim() === '' && buffer.length > 24) {
        slices.push(buffer.join('\n'))
        buffer = []
      }
    }
    if (buffer.length) slices.push(buffer.join('\n'))
    return slices.length ? slices : ['']
  }

  /** Heading ids restart per slice, so renumber once the document is complete. */
  function renumberHeadings() {
    var headings = mdRoot.querySelectorAll('h1,h2,h3,h4,h5,h6')
    for (var i = 0; i < headings.length; i += 1) {
      headings[i].id = 'section-' + (i + 1)
    }
  }

  function fillOutline(sections) {
    var options = ['<option value="">大纲</option>']
    var headings = mdRoot.querySelectorAll('h1,h2,h3,h4,h5,h6')
    if (headings.length) {
      for (var i = 0; i < headings.length; i += 1) {
        var text = (headings[i].textContent || '').trim().slice(0, 80)
        options.push(
          '<option value="section-' + (i + 1) + '">' + window.TraceLabMd.escapeHtml(text) + '</option>',
        )
      }
    } else {
      for (var s = 0; s < sections.length; s += 1) {
        options.push(
          '<option value="' +
            window.TraceLabMd.escapeHtml(sections[s].id) +
            '">' +
            window.TraceLabMd.escapeHtml(sections[s].title) +
            '</option>',
        )
      }
    }
    tocEl.innerHTML = options.join('')
  }

  /* ----------------------------- trace marks ------------------------------ */
  function texKey(value) {
    return String(value || '')
      .replace(/\$\$?/g, ' ')
      .replace(/\\(?:left|right|!|,|;|:|quad|qquad|displaystyle|nonumber)\b/g, ' ')
      .replace(/\\begin\{[^}]*\}|\\end\{[^}]*\}/g, ' ')
      .replace(/[\s{}]/g, '')
      .toLowerCase()
  }

  function renderedTex(el) {
    var node = el.querySelector('annotation[encoding="application/x-tex"]')
    return node ? node.textContent || '' : ''
  }

  function isBlockLevelTarget(quote) {
    return /[$\\]|\\begin\{/.test(String(quote || ''))
  }

  function isEmptyContainer(el) {
    return String(el.textContent || '').replace(/\s+/g, ' ').trim().length === 0
  }

  var VISUAL = '.math-display, .table-scroll, table, pre, img, blockquote'

  function resolveVisualBlock(anchor) {
    var container = anchor.closest('h1,h2,h3,h4,h5,h6,p,li,pre,blockquote,td') || anchor
    if (!isEmptyContainer(container)) return container
    var sibling = container.nextElementSibling
    while (sibling && isEmptyContainer(sibling) && !sibling.matches(VISUAL)) {
      sibling = sibling.nextElementSibling
    }
    if (sibling && (sibling.matches(VISUAL) || !isEmptyContainer(sibling))) return sibling
    return container
  }

  function findNearbyVisualBlock(start) {
    var sibling = start.nextElementSibling
    for (var step = 0; step < 3 && sibling; step += 1) {
      if (sibling.matches(VISUAL)) return sibling
      if (!isEmptyContainer(sibling) && sibling.tagName !== 'P') return sibling
      sibling = sibling.nextElementSibling
    }
    return null
  }

  function findFormulaByTex(quote) {
    var needle = texKey(quote)
    if (needle.length < 4) return null
    var candidates = mdRoot.querySelectorAll('.math-display')
    for (var i = 0; i < candidates.length; i += 1) {
      var key = texKey(renderedTex(candidates[i]))
      if (key && (key.indexOf(needle) >= 0 || needle.indexOf(key) >= 0)) return candidates[i]
    }
    return null
  }

  function resolveBlockHost(blockId, quote) {
    var host = null
    var anchor = blockId
      ? mdRoot.querySelector('[data-paper-block-id="' + CSS.escape(blockId) + '"]')
      : null
    if (anchor) {
      host = resolveVisualBlock(anchor)
      if (isBlockLevelTarget(quote) && !host.matches('.math-display')) {
        host = findNearbyVisualBlock(host) || host
      }
    }
    if (isBlockLevelTarget(quote)) {
      var byTex = findFormulaByTex(quote)
      if (byTex && (!host || !host.matches('.math-display'))) host = byTex
    }
    return host
  }

  function wrapQuote(host, mark) {
    if (isBlockLevelTarget(mark.quote)) return null
    var quote = String(mark.quote || '').trim()
    var lead = quote.split(/[$\\]/)[0].trim()
    var candidates = [quote, lead].filter(function (item) {
      return item.length >= 6
    })
    var raw = host.textContent || ''
    var needle = ''
    var index = -1
    for (var i = 0; i < candidates.length; i += 1) {
      var at = raw.indexOf(candidates[i])
      if (at >= 0) {
        needle = candidates[i]
        index = at
        break
      }
    }
    if (index < 0) return null
    var walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT)
    var consumed = 0
    var startNode = null
    var startOffset = 0
    var endNode = null
    var endOffset = 0
    var end = index + needle.length
    var node = walker.nextNode()
    while (node) {
      var length = node.data.length
      if (!startNode && consumed + length > index) {
        startNode = node
        startOffset = index - consumed
      }
      if (startNode && consumed + length >= end) {
        endNode = node
        endOffset = end - consumed
        break
      }
      consumed += length
      node = walker.nextNode()
    }
    if (!startNode || !endNode) return null
    try {
      var range = document.createRange()
      range.setStart(startNode, startOffset)
      range.setEnd(endNode, endOffset)
      var el = document.createElement('mark')
      el.dataset.traceTarget = mark.linkId
      el.className = 'trace-mark trace-mark-' + mark.status
      range.surroundContents(el)
      return el
    } catch (error) {
      return null
    }
  }

  /** Undo a previous pass so re-applying after a review does not nest marks. */
  function clearMarks() {
    var wrapped = mdRoot.querySelectorAll('mark.trace-mark')
    for (var i = 0; i < wrapped.length; i += 1) {
      var el = wrapped[i]
      var parent = el.parentNode
      if (!parent) continue
      while (el.firstChild) parent.insertBefore(el.firstChild, el)
      parent.removeChild(el)
      parent.normalize()
    }
    var blocks = mdRoot.querySelectorAll('[data-trace-target]')
    for (var b = 0; b < blocks.length; b += 1) {
      var block = blocks[b]
      block.removeAttribute('data-trace-target')
      block.classList.remove(
        'trace-block-target',
        'trace-block-proposed',
        'trace-block-accepted',
        'trace-block-rejected',
        'trace-target-active',
      )
    }
  }

  function applyMarks() {
    clearMarks()
    for (var i = 0; i < state.marks.length; i += 1) {
      var mark = state.marks[i]
      var host = resolveBlockHost(mark.blockId, mark.quote)
      if (!host) continue
      var precise = wrapQuote(host, mark)
      var el = precise || host
      if (!precise) {
        host.classList.add('trace-block-target', 'trace-block-' + mark.status)
        host.dataset.traceTarget = mark.linkId
      } else {
        el.dataset.traceTarget = mark.linkId
      }
    }
  }

  // Delegated so re-applying marks after a review never stacks listeners.
  mdRoot.addEventListener('click', function (event) {
    var target = event.target.closest ? event.target.closest('[data-trace-target]') : null
    if (!target) return
    var linkId = target.dataset.traceTarget
    for (var i = 0; i < state.marks.length; i += 1) {
      if (state.marks[i].linkId !== linkId) continue
      vscodeApi.postMessage({
        type: 'openCode',
        path: state.marks[i].path,
        lineStart: state.marks[i].lineStart,
        lineEnd: state.marks[i].lineEnd,
      })
      return
    }
  })

  /** PDF hit boxes are rebuilt per render, so a direct listener is fine there. */
  function bindOpen(el, target) {
    el.addEventListener('click', function () {
      vscodeApi.postMessage({
        type: 'openCode',
        path: target.path,
        lineStart: target.lineStart,
        lineEnd: target.lineEnd,
      })
    })
  }

  function focusMark(linkId, switchPane) {
    var previous = mdRoot.querySelector('.trace-target-active')
    if (previous) previous.classList.remove('trace-target-active')
    if (!linkId) return
    var target = mdRoot.querySelector('[data-trace-target="' + CSS.escape(linkId) + '"]')
    if (target) {
      target.classList.add('trace-target-active')
      if (switchPane !== false) showPane('md')
      target.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
    if (state.pdfUri && hasRectFor(linkId)) {
      showPane('pdf')
      scrollToRect(linkId)
    }
  }

  function hasRectFor(linkId) {
    for (var page in state.rects) {
      var list = state.rects[page]
      for (var i = 0; i < list.length; i += 1) {
        if (list[i].linkId === linkId) return true
      }
    }
    return false
  }

  function scrollToRect(linkId) {
    for (var page in state.rects) {
      var list = state.rects[page]
      for (var i = 0; i < list.length; i += 1) {
        if (list[i].linkId !== linkId) continue
        var meta = pdf.pages.get(Number(page))
        if (meta && meta.wrap) {
          meta.wrap.scrollIntoView({ behavior: 'smooth', block: 'center' })
          void renderPage(Number(page), pdf.token)
        }
        return
      }
    }
  }

  /* -------------------------------- PDF ---------------------------------- */
  function contentWidth() {
    return Math.max(320, (contentEl.clientWidth || 720) - 48)
  }

  function updateZoomLabel() {
    zoomLabel.textContent = Math.round(pdf.zoom) + '%'
  }

  async function ensurePdf() {
    if (!state.pdfUri) {
      pdfError.hidden = false
      pdfError.textContent = '尚未导入 source.pdf — 请先导入论文 PDF'
      return
    }
    if (pdf.doc && pdf.url === state.pdfUri) return
    if (!pdfjsReady) {
      await new Promise(function (resolve) {
        window.addEventListener('tl-pdfjs-ready', resolve, { once: true })
      })
    }
    pdf.url = state.pdfUri
    pdfError.hidden = true
    pdfRoot.innerHTML = '<div class="tl-empty"><span class="tl-spin"></span><span>正在加载 PDF…</span></div>'
    try {
      // `disableRange`/`disableStream`: the webview resource protocol does not
      // serve HTTP ranges, so pdf.js would probe, fail, and refetch the file.
      // One plain request off a local file is the fast path here.
      pdf.doc = await window.__tlPdfjs.getDocument({
        url: state.pdfUri,
        cMapUrl: window.__tlPdfAssets.cMapUrl,
        cMapPacked: true,
        standardFontDataUrl: window.__tlPdfAssets.stdFontUrl,
        disableRange: true,
        disableStream: true,
        disableAutoFetch: true,
        verbosity: 0,
      }).promise
      await rebuildPdf()
    } catch (error) {
      pdf.doc = null
      pdf.url = ''
      pdfRoot.innerHTML = ''
      pdfError.hidden = false
      pdfError.textContent = 'PDF 渲染失败: ' + (error && error.message ? error.message : String(error))
    }
  }

  async function rebuildPdf() {
    if (!pdf.doc) return
    pdf.token += 1
    var token = pdf.token
    updateZoomLabel()
    var first = await pdf.doc.getPage(1)
    var viewport = first.getViewport({ scale: 1 })
    var defaultAspect = viewport.width / viewport.height
    if (token !== pdf.token) return

    pdfRoot.innerHTML = ''
    var width = contentWidth() * (pdf.zoom / 100)
    var next = new Map()
    for (var pageNum = 1; pageNum <= pdf.doc.numPages; pageNum += 1) {
      var previous = pdf.pages.get(pageNum)
      var aspect = (previous && previous.aspect) || defaultAspect
      var wrap = document.createElement('div')
      wrap.className = 'page'
      wrap.dataset.page = String(pageNum)
      wrap.style.width = width + 'px'
      wrap.style.height = width / aspect + 'px'
      wrap.innerHTML = '<div class="page-placeholder">第 ' + pageNum + ' 页</div>'
      pdfRoot.appendChild(wrap)
      next.set(pageNum, { wrap: wrap, aspect: aspect, rendered: false, rendering: false })
    }
    pdf.pages = next
    observePages()
    void renderPage(1, token)
  }

  function observePages() {
    if (pdf.observer) pdf.observer.disconnect()
    pdf.observer = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i += 1) {
          if (!entries[i].isIntersecting) continue
          var pageNum = Number(entries[i].target.dataset.page)
          if (pageNum) void renderPage(pageNum, pdf.token)
        }
      },
      // One screen of lookahead: the old 200% margin queued a dozen pages at
      // once behind pdf.js's single worker.
      { root: contentEl, rootMargin: '100% 0px' },
    )
    pdf.pages.forEach(function (meta) {
      if (meta.wrap) pdf.observer.observe(meta.wrap)
    })
  }

  var renderQueue = []

  async function renderPage(pageNum, token) {
    var meta = pdf.pages.get(pageNum)
    if (!pdf.doc || !meta || meta.rendered || meta.rendering || token !== pdf.token) return
    if (pdf.active >= 2) {
      if (renderQueue.indexOf(pageNum) < 0) renderQueue.push(pageNum)
      return
    }
    meta.rendering = true
    pdf.active += 1
    try {
      var page = await pdf.doc.getPage(pageNum)
      if (token !== pdf.token) return
      var dpr = Math.min(window.devicePixelRatio || 1, 2)
      var unscaled = page.getViewport({ scale: 1 })
      meta.aspect = unscaled.width / unscaled.height
      var cssWidth = contentWidth() * (pdf.zoom / 100)
      var viewport = page.getViewport({ scale: (cssWidth / unscaled.width) * dpr })
      var cssHeight = viewport.height / dpr
      var canvas = document.createElement('canvas')
      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      canvas.style.width = cssWidth + 'px'
      canvas.style.height = cssHeight + 'px'
      await page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport }).promise
      if (token !== pdf.token) return
      meta.wrap.style.width = cssWidth + 'px'
      meta.wrap.style.height = cssHeight + 'px'
      meta.wrap.innerHTML = ''
      meta.wrap.appendChild(canvas)
      paintHits(meta, pageNum, cssWidth, cssHeight)
      meta.rendered = true
    } catch (error) {
      if (meta.wrap) {
        meta.wrap.innerHTML = '<div class="page-placeholder">第 ' + pageNum + ' 页渲染失败</div>'
      }
    } finally {
      meta.rendering = false
      pdf.active -= 1
      var pending = renderQueue.shift()
      if (pending) void renderPage(pending, token)
    }
  }

  function paintHits(meta, pageNum, cssWidth, cssHeight) {
    var rects = state.rects[pageNum] || state.rects[String(pageNum)] || []
    for (var i = 0; i < rects.length; i += 1) {
      var rect = rects[i]
      if (rect.pageAspect && Math.abs(rect.pageAspect - meta.aspect) > 0.02) continue
      var hit = document.createElement('div')
      hit.className =
        'hit ' +
        rect.status +
        (rect.precise ? '' : ' coarse') +
        (rect.linkId === state.focusLinkId ? ' focus' : '')
      hit.style.left = rect.left * cssWidth + 'px'
      hit.style.top = rect.top * cssHeight + 'px'
      hit.style.width = rect.width * cssWidth + 'px'
      hit.style.height = rect.height * cssHeight + 'px'
      hit.title = rect.quote || ''
      bindOpen(hit, rect)
      meta.wrap.appendChild(hit)
    }
  }

  document.getElementById('pdfZoomIn').addEventListener('click', function () {
    pdf.zoom = Math.min(250, pdf.zoom + 25)
    void rebuildPdf()
  })
  document.getElementById('pdfZoomOut').addEventListener('click', function () {
    pdf.zoom = Math.max(50, pdf.zoom - 25)
    void rebuildPdf()
  })
  zoomLabel.addEventListener('click', function () {
    pdf.zoom = 100
    void rebuildPdf()
  })

  /* ------------------------------- messages ------------------------------- */
  window.addEventListener('message', function (event) {
    var message = event.data || {}
    if (message.type === 'focus') {
      state.focusLinkId = message.linkId || null
      focusMark(state.focusLinkId, true)
      return
    }
    if (message.type !== 'paper') return

    state.marks = Array.isArray(message.marks) ? message.marks : []
    state.rects = message.rects || {}
    state.focusLinkId = message.focusLinkId || null
    document.getElementById('paperTitle').textContent = message.title || '论文'
    document.getElementById('paperMeta').textContent = [message.source, message.parsedDir]
      .filter(Boolean)
      .join(' · ')

    var pdfChanged = state.pdfUri !== (message.pdfUri || '')
    state.pdfUri = message.pdfUri || ''
    tabPdf.disabled = !state.pdfUri
    if (pdfChanged) {
      pdf.doc = null
      pdf.url = ''
      pdf.pages = new Map()
    }

    if (message.markdown !== state.markdown) {
      state.markdown = message.markdown || ''
      renderMarkdown(state.markdown)
      // Outline is filled once headings exist; renderMarkdown finishes async.
      setTimeout(function () {
        fillOutline(Array.isArray(message.sections) ? message.sections : [])
      }, 0)
    } else {
      applyMarks()
      focusMark(state.focusLinkId, false)
    }

    if (!document.getElementById('pdfPane').classList.contains('active')) return
    void ensurePdf()
  })

  var resizeTimer = 0
  window.addEventListener('resize', function () {
    if (!pdf.doc) return
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(function () {
      void rebuildPdf()
    }, 250)
  })

  vscodeApi.postMessage({ type: 'ready' })
})()
