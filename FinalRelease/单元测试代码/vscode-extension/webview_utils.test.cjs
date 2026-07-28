const assert = require('node:assert/strict')
const test = require('node:test')

const { escapeHtml, jsonForScript } = require('../../../vscode-extension/out/webviews/webviewUtils.js')

test('escapeHtml escapes HTML-significant characters and nullish values', () => {
  assert.equal(
    escapeHtml(`<tag a="x">Tom & Jerry's</tag>`),
    '&lt;tag a=&quot;x&quot;&gt;Tom &amp; Jerry&#39;s&lt;/tag&gt;',
  )
  assert.equal(escapeHtml(null), '')
})

test('jsonForScript prevents script breakouts and preserves round-trip data', () => {
  const input = {
    closingTag: '</script><script>alert(1)</script>',
    separators: `left${String.fromCharCode(0x2028)}middle${String.fromCharCode(0x2029)}right`,
    ampersand: 'A&B',
  }
  const serialized = jsonForScript(input)

  assert.equal(serialized.includes('<'), false)
  assert.equal(serialized.includes('>'), false)
  assert.equal(serialized.includes('&'), false)
  assert.equal(serialized.includes(String.fromCharCode(0x2028)), false)
  assert.equal(serialized.includes(String.fromCharCode(0x2029)), false)
  assert.deepEqual(JSON.parse(serialized), input)
})

test('jsonForScript serializes undefined as null', () => {
  assert.equal(jsonForScript(undefined), 'null')
})
