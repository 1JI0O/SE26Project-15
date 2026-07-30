/** TraceLab sidebar client: workspace status, workflow actions, settings forms. */
;(function () {
  'use strict'

  var vscodeApi = acquireVsCodeApi()

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"]/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]
    })
  }

  function val(id) {
    var el = document.getElementById(id)
    return el ? el.value : ''
  }

  function set(id, value) {
    var el = document.getElementById(id)
    if (el) el.value = value == null ? '' : value
  }

  var buttons = document.querySelectorAll('[data-cmd]')
  for (var i = 0; i < buttons.length; i += 1) {
    buttons[i].addEventListener('click', function (event) {
      vscodeApi.postMessage({
        type: 'action',
        command: event.currentTarget.getAttribute('data-cmd'),
      })
    })
  }

  function payload() {
    return {
      llm: {
        base_url: val('llm.base_url'),
        model: val('llm.model'),
        thinking_mode: val('llm.thinking_mode'),
        timeout_seconds: Number(val('llm.timeout_seconds') || 120),
        api_key: val('llm.api_key'),
      },
      mineru: {
        provider: val('mineru.provider'),
        base_url: val('mineru.base_url'),
        model: val('mineru.model'),
        language: val('mineru.language'),
        request_timeout_seconds: Number(val('mineru.request_timeout_seconds') || 120),
        task_timeout_seconds: Number(val('mineru.task_timeout_seconds') || 1800),
        api_token: val('mineru.api_token'),
      },
    }
  }

  function save() {
    vscodeApi.postMessage({ type: 'saveSettings', payload: payload() })
  }

  document.getElementById('saveLlm').addEventListener('click', save)
  document.getElementById('saveMineru').addEventListener('click', save)
  document.getElementById('clearLlm').addEventListener('click', function () {
    vscodeApi.postMessage({ type: 'clearSecret', target: 'llm' })
  })
  document.getElementById('clearMineru').addEventListener('click', function () {
    vscodeApi.postMessage({ type: 'clearSecret', target: 'mineru' })
  })
  document.getElementById('probeLlm').addEventListener('click', function () {
    vscodeApi.postMessage({ type: 'probe', target: 'llm' })
  })
  document.getElementById('probeMineru').addEventListener('click', function () {
    vscodeApi.postMessage({ type: 'probe', target: 'mineru' })
  })

  function flag(ok, okText, badText) {
    return ok
      ? '<span class="tl-ok">' + esc(okText) + '</span>'
      : '<span class="tl-bad">' + esc(badText) + '</span>'
  }

  function renderStatus(status, workspace) {
    var badge = document.getElementById('statusBadge')
    var body = document.getElementById('statusBody')
    if (!status || status.ok === false) {
      badge.textContent = '未就绪'
      badge.className = 'tl-chip rejected'
      body.innerHTML =
        '<div class="tl-muted">请先打开工作区文件夹，再运行「初始化」。</div>' +
        (workspace ? '<div class="tl-path">' + esc(workspace) + '/.tracelab</div>' : '')
      return
    }
    var ready = status.paper_ready && status.analysis_ready
    badge.textContent = ready ? '就绪' : '待完善'
    badge.className = 'tl-chip ' + (ready ? 'accepted' : 'proposed')
    body.innerHTML =
      '<dl class="tl-status-grid">' +
      '<dt>论文</dt><dd>' +
      flag(status.paper_ready, '已解析', '等待解析') +
      '</dd>' +
      '<dt>PDF</dt><dd>' +
      flag(status.has_pdf, '已导入', '未导入') +
      '</dd>' +
      '<dt>代码</dt><dd>' +
      flag(status.analysis_ready, '已分析', '等待分析') +
      '</dd>' +
      '<dt>张量节点</dt><dd>' +
      (status.tensor_nodes || 0) +
      '</dd>' +
      '<dt>追溯</dt><dd>' +
      (status.links_total || 0) +
      ' 条 · 待审 ' +
      (status.links_proposed || 0) +
      ' · 已接受 ' +
      (status.links_accepted || 0) +
      '</dd>' +
      '</dl>' +
      '<div class="tl-path">' +
      esc(status.tracelab_root || '') +
      '</div>' +
      '<div class="tl-muted">密钥跨工作区保存在 VS Code SecretStorage</div>'
  }

  function renderLog(entries) {
    var logEl = document.getElementById('log')
    var list = Array.isArray(entries) ? entries : []
    // Newest first, matching the desktop Agent log.
    logEl.innerHTML = list
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

  window.addEventListener('message', function (event) {
    var message = event.data || {}
    if (message.type !== 'state') return

    renderStatus(message.status, message.workspace)
    renderLog(message.analysisLog)

    var task = document.getElementById('task')
    var text = message.taskMessage || message.flash || ''
    task.hidden = !text
    task.innerHTML = message.busy
      ? '<span class="tl-spin"></span><span>' + esc(text) + '</span>'
      : esc(text)

    var settings = message.settings || {}
    var llm = settings.llm || {}
    var mineru = settings.mineru || {}
    set('llm.base_url', llm.base_url)
    set('llm.model', llm.model)
    set('llm.thinking_mode', llm.thinking_mode || '')
    set('llm.timeout_seconds', llm.timeout_seconds == null ? 120 : llm.timeout_seconds)
    set('llm.api_key', '')
    document.getElementById('llm.api_key').placeholder = llm.has_key
      ? '已配置 — 留空则保留'
      : '未配置'
    document.getElementById('llm.keyStatus').innerHTML = flag(llm.has_key, '已配置', '未配置')

    set('mineru.provider', mineru.provider || 'official')
    set('mineru.base_url', mineru.base_url)
    set('mineru.model', mineru.model || 'vlm')
    set('mineru.language', mineru.language || 'en')
    set(
      'mineru.request_timeout_seconds',
      mineru.request_timeout_seconds == null ? 120 : mineru.request_timeout_seconds,
    )
    set(
      'mineru.task_timeout_seconds',
      mineru.task_timeout_seconds == null ? 1800 : mineru.task_timeout_seconds,
    )
    set('mineru.api_token', '')
    document.getElementById('mineru.api_token').placeholder = mineru.has_token
      ? '已配置 — 留空则保留'
      : '未配置'
    document.getElementById('mineru.tokenStatus').innerHTML = flag(
      mineru.has_token,
      '已配置',
      '未配置',
    )
  })

  vscodeApi.postMessage({ type: 'ready' })
})()
