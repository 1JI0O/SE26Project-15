/**
 * Trace matrix client.
 *
 * Rows arrive over postMessage and are rendered here, so reviewing a link only
 * patches the list instead of reloading the webview (which used to reset the
 * scroll position and the filter).
 */
;(function () {
  'use strict'

  var vscodeApi = acquireVsCodeApi()
  var esc = window.TraceLabMd.escapeHtml
  var listEl = document.getElementById('list')
  var previewBody = document.getElementById('previewBody')
  var filterEl = document.getElementById('filter')

  var rows = []
  var filter = 'all'
  var picked = new Set()
  var selectedId = null
  var hoverId = null
  var codeCache = new Map()

  /* -------------------------------- list ---------------------------------- */
  function visibleRows() {
    return filter === 'all'
      ? rows
      : rows.filter(function (row) {
          return row.status === filter
        })
  }

  function statusLabel(status) {
    return { proposed: '待审', accepted: '已接受', rejected: '已拒绝' }[status] || status
  }

  function rowHtml(row) {
    return (
      '<article class="tl-row ' +
      esc(row.status) +
      (row.id === selectedId ? ' selected' : '') +
      '" data-id="' +
      esc(row.id) +
      '">' +
      '<div class="tl-row-head">' +
      '<input type="checkbox" class="tl-pick"' +
      (picked.has(row.id) ? ' checked' : '') +
      ' title="选择该关系" />' +
      '<span class="tl-chip ' +
      esc(row.status) +
      '">' +
      esc(statusLabel(row.status)) +
      '</span>' +
      (row.relationType ? '<strong>' + esc(row.relationType) + '</strong>' : '') +
      '<span class="tl-row-conf" title="置信度"><span class="tl-meter tl-chip-accent"><i style="width:' +
      Math.max(0, Math.min(100, row.confidence)) +
      '%"></i></span>' +
      row.confidence +
      '%</span>' +
      (row.source ? '<span class="tl-chip">' + esc(row.source) + '</span>' : '') +
      '<span class="tl-bar-spacer"></span>' +
      '</div>' +
      '<div class="tl-md tl-row-snip" data-role="snippet" data-id="' +
      esc(row.id) +
      '"></div>' +
      '<div class="tl-row-code">' +
      esc(row.codePath) +
      ':' +
      row.lineStart +
      (row.lineEnd && row.lineEnd !== row.lineStart ? '-' + row.lineEnd : '') +
      '</div>' +
      (row.rationale ? '<div class="tl-row-why">' + esc(row.rationale) + '</div>' : '') +
      '<div class="tl-row-actions">' +
      '<button class="tl-quiet" data-action="open">打开代码</button>' +
      '<button class="tl-quiet" data-action="paper">定位论文</button>' +
      (row.status === 'proposed'
        ? '<button class="tl-quiet tl-ok" data-action="accept">接受</button>' +
          '<button class="tl-quiet tl-bad" data-action="reject">拒绝</button>'
        : '<button class="tl-quiet" data-action="reset">撤回</button>') +
      '</div>' +
      '</article>'
    )
  }

  function renderList() {
    var items = visibleRows()
    if (!items.length) {
      listEl.innerHTML =
        '<div class="tl-empty"><strong>暂无追溯关系</strong>' +
        '<span>' +
        (rows.length ? '当前筛选下没有关系，试试「全部」。' : '请先配置 LLM 并运行「生成追溯」。') +
        '</span></div>'
      return
    }
    listEl.innerHTML = items.map(rowHtml).join('')
    var hosts = listEl.querySelectorAll('[data-role="snippet"]')
    for (var i = 0; i < hosts.length; i += 1) {
      var row = findRow(hosts[i].dataset.id)
      if (row) hosts[i].innerHTML = window.TraceLabMd.renderSnippet(row.paperMarkdown)
    }
    updateCounts()
  }

  function updateCounts() {
    var proposed = 0
    var accepted = 0
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i].status === 'proposed') proposed += 1
      else if (rows[i].status === 'accepted') accepted += 1
    }
    document.getElementById('countAll').textContent = '显示 ' + visibleRows().length + ' / ' + rows.length + ' 条'
    document.getElementById('countProposed').textContent = '待审 ' + proposed
    document.getElementById('countAccepted').textContent = '已接受 ' + accepted
    var selected = document.getElementById('countSelected')
    selected.hidden = picked.size === 0
    selected.textContent = '已选 ' + picked.size
  }

  function findRow(id) {
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i].id === id) return rows[i]
    }
    return null
  }

  /* ------------------------------- preview -------------------------------- */
  function previewBlockHtml(row, kind) {
    var code = codeCache.get(row.id)
    return (
      '<div class="tl-preview-block ' +
      (kind === 'hover' ? 'hover' : 'pinned') +
      '">' +
      '<div class="tl-row-head">' +
      '<span class="tl-chip ' +
      esc(row.status) +
      '">' +
      esc(kind === 'hover' ? '悬浮预览' : '已选中关系') +
      '</span>' +
      (row.relationType ? '<span class="tl-chip tl-chip-accent">' + esc(row.relationType) + '</span>' : '') +
      '</div>' +
      '<div class="tl-preview-side">' +
      '<span class="tl-label">论文</span>' +
      '<div class="tl-md tl-preview-quote" data-role="preview-md" data-id="' +
      esc(row.id) +
      '"></div>' +
      '<span class="tl-muted tl-mono">' +
      esc(row.blockId) +
      (row.targetType ? ' · ' + esc(row.targetType) : '') +
      '</span>' +
      '</div>' +
      '<div class="tl-preview-side">' +
      '<span class="tl-label">代码</span>' +
      '<pre class="tl-preview-code">' +
      esc(code == null ? '加载代码…' : code) +
      '</pre>' +
      '<span class="tl-muted tl-mono">' +
      esc(row.codePath) +
      ':' +
      row.lineStart +
      (row.symbol ? ' · ' + esc(row.symbol) : '') +
      '</span>' +
      '</div>' +
      '<div class="tl-preview-scores"><span>置信 ' +
      row.confidence +
      '%</span>' +
      (row.source ? '<span>来源 ' + esc(row.source) + '</span>' : '') +
      '</div>' +
      (row.rationale ? '<p class="tl-muted" style="margin:6px 0 0">' + esc(row.rationale) + '</p>' : '') +
      '</div>'
    )
  }

  function renderPreview() {
    var hover = hoverId && hoverId !== selectedId ? findRow(hoverId) : null
    var pinned = selectedId ? findRow(selectedId) : null
    if (!hover && !pinned) {
      previewBody.innerHTML =
        '<div class="tl-empty"><strong>暂无预览关系</strong>' +
        '<span>悬浮列表可临时预览，点击可固定关系。</span></div>'
      return
    }
    var html = ''
    if (hover) html += previewBlockHtml(hover, 'hover')
    if (pinned) html += previewBlockHtml(pinned, 'pinned')
    previewBody.innerHTML = html
    var mdHosts = previewBody.querySelectorAll('[data-role="preview-md"]')
    for (var i = 0; i < mdHosts.length; i += 1) {
      var row = findRow(mdHosts[i].dataset.id)
      if (row) mdHosts[i].innerHTML = window.TraceLabMd.renderSnippet(row.paperMarkdown)
    }
  }

  function requestCode(row) {
    if (codeCache.has(row.id)) return
    vscodeApi.postMessage({
      type: 'previewCode',
      linkId: row.id,
      path: row.codePath,
      lineStart: row.lineStart,
      lineEnd: row.lineEnd,
    })
  }

  /* ------------------------------ interaction ----------------------------- */
  listEl.addEventListener('click', function (event) {
    var rowEl = event.target.closest('.tl-row')
    if (!rowEl) return
    var id = rowEl.dataset.id
    var row = findRow(id)
    if (!row) return

    if (event.target.classList.contains('tl-pick')) {
      if (event.target.checked) picked.add(id)
      else picked.delete(id)
      updateCounts()
      return
    }
    var action = event.target.dataset ? event.target.dataset.action : null
    if (action === 'open') {
      vscodeApi.postMessage({
        type: 'openCode',
        path: row.codePath,
        lineStart: row.lineStart,
        lineEnd: row.lineEnd,
      })
      return
    }
    if (action === 'paper') {
      vscodeApi.postMessage({ type: 'locatePaper', linkId: id })
      return
    }
    if (action === 'accept' || action === 'reject' || action === 'reset') {
      vscodeApi.postMessage({
        type: 'review',
        linkId: id,
        status: action === 'accept' ? 'accepted' : action === 'reject' ? 'rejected' : 'proposed',
      })
      return
    }
    selectedId = selectedId === id ? null : id
    requestCode(row)
    renderList()
    renderPreview()
  })

  listEl.addEventListener('mouseover', function (event) {
    var rowEl = event.target.closest('.tl-row')
    if (!rowEl || rowEl.dataset.id === hoverId) return
    hoverId = rowEl.dataset.id
    var row = findRow(hoverId)
    if (row) requestCode(row)
    renderPreview()
  })

  listEl.addEventListener('mouseleave', function () {
    hoverId = null
    renderPreview()
  })

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && selectedId) {
      selectedId = null
      renderList()
      renderPreview()
    }
  })

  filterEl.addEventListener('change', function (event) {
    filter = event.target.value
    vscodeApi.postMessage({ type: 'filter', value: filter })
    renderList()
  })

  document.getElementById('selectProposed').addEventListener('click', function () {
    picked = new Set(
      visibleRows()
        .filter(function (row) {
          return row.status === 'proposed'
        })
        .map(function (row) {
          return row.id
        }),
    )
    renderList()
  })

  function batch(status) {
    if (!picked.size) return
    vscodeApi.postMessage({ type: 'reviewBatch', status: status, ids: [...picked] })
    picked = new Set()
  }

  document.getElementById('batchAccept').addEventListener('click', function () {
    batch('accepted')
  })
  document.getElementById('batchReject').addEventListener('click', function () {
    batch('rejected')
  })
  document.getElementById('batchReset').addEventListener('click', function () {
    batch('proposed')
  })
  document.getElementById('acceptAllProposed').addEventListener('click', function () {
    vscodeApi.postMessage({ type: 'reviewBatch', status: 'accepted', allProposed: true })
  })

  /* ------------------------------- messages ------------------------------- */
  window.addEventListener('message', function (event) {
    var message = event.data || {}
    if (message.type === 'rows') {
      rows = Array.isArray(message.rows) ? message.rows : []
      if (message.filter) {
        filter = message.filter
        filterEl.value = filter
      }
      var alive = new Set(
        rows.map(function (row) {
          return row.id
        }),
      )
      picked = new Set(
        [...picked].filter(function (id) {
          return alive.has(id)
        }),
      )
      if (selectedId && !alive.has(selectedId)) selectedId = null
      renderList()
      renderPreview()
      return
    }
    if (message.type === 'filter') {
      filter = message.value
      filterEl.value = filter
      renderList()
      return
    }
    if (message.type === 'codePreview') {
      codeCache.set(message.linkId, String(message.snippet || ''))
      renderPreview()
      return
    }
    if (message.type === 'agent') {
      renderAgent(message)
    }
  })

  function renderAgent(message) {
    var badge = document.getElementById('agentBadge')
    var activity = document.getElementById('agentActivity')
    var bar = document.getElementById('agentBar')
    var logEl = document.getElementById('agentLog')
    badge.textContent = message.running ? '进行中' : '空闲'
    badge.className = 'tl-chip' + (message.running ? ' proposed' : '')
    activity.innerHTML = message.running
      ? '<span class="tl-spin"></span><span>' + esc(message.activity || '启动中…') + '</span>'
      : esc(message.activity || 'Agent 自主读取论文与代码证据')
    bar.hidden = !message.running
    var log = Array.isArray(message.log) ? message.log : []
    logEl.hidden = log.length === 0
    // Newest first, matching the desktop Agent log.
    logEl.innerHTML = log
      .slice()
      .reverse()
      .map(function (entry, index) {
        return (
          '<li' +
          (index === 0 ? ' class="tl-log-latest"' : '') +
          '>' +
          (entry.step ? '<span class="tl-log-step">#' + entry.step + '</span>' : '') +
          '<span>' +
          esc(entry.text) +
          '</span></li>'
        )
      })
      .join('')
  }

  vscodeApi.postMessage({ type: 'ready' })
})()
