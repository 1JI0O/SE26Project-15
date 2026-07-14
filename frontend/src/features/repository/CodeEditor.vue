<template>
  <div class="editor-shell">
    <div class="editor-tabs">
      <span>{{ file?.path || '' }}</span>
      <div>
        <el-tag v-if="file" size="small" :type="file.statusType" effect="plain">
          {{ file.status }}
        </el-tag>
        <el-tag v-if="isDirty" size="small" type="warning" effect="plain">
          未保存演示
        </el-tag>
        <el-tag v-else-if="file" size="small" type="success" effect="plain">已同步</el-tag>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!file" class="editor-empty">
      <el-empty description="从左侧文件树选择可编辑的代码或文本文件" />
    </div>

    <!-- CodeMirror editor -->
    <div v-else ref="editorContainer" class="editor-body" />

    <div v-if="file" class="editor-footer">
      <span>当前符号: {{ file.symbol }}</span>
      <span>关联段落: {{ file.paperRef }}</span>
      <el-button
        size="small"
        type="primary"
        plain
        :loading="saving"
        @click="$emit('save')"
      >
        保存编辑
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view'
import { EditorState, type Extension } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { syntaxHighlighting, HighlightStyle, indentOnInput, bracketMatching, foldGutter } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import type { CodeFile } from '@/composables/useCode'

const props = defineProps<{
  file: CodeFile | undefined
  content: string
  isDirty: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  save: []
  change: [content: string]
}>()

const editorContainer = ref<HTMLDivElement | null>(null)
let editorView: EditorView | null = null
let ignoreUpdate = false

async function getLanguageExtension(path: string): Promise<Extension> {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  switch (ext) {
    case 'py':
      return (await import('@codemirror/lang-python')).python()
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return (await import('@codemirror/lang-javascript')).javascript({ jsx: true })
    case 'ts':
    case 'tsx':
      return (await import('@codemirror/lang-javascript')).javascript({ jsx: true, typescript: true })
    case 'html':
    case 'htm':
    case 'vue':
    case 'svelte':
      return (await import('@codemirror/lang-html')).html()
    case 'css':
    case 'scss':
    case 'less':
      return (await import('@codemirror/lang-css')).css()
    case 'json':
    case 'jsonl':
      return (await import('@codemirror/lang-json')).json()
    case 'yaml':
    case 'yml':
      return (await import('@codemirror/lang-yaml')).yaml()
    case 'md':
    case 'rst':
      return (await import('@codemirror/lang-markdown')).markdown()
    case 'sql':
      return (await import('@codemirror/lang-sql')).sql()
    case 'xml':
    case 'svg':
      return (await import('@codemirror/lang-xml')).xml()
    default:
      return []
  }
}

// Syntax highlighting theme matching the page's calm color palette
const workbenchHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: '#8b5cf6', fontWeight: '600' },
  { tag: tags.controlKeyword, color: '#8b5cf6', fontWeight: '600' },
  { tag: tags.operatorKeyword, color: '#8b5cf6' },
  { tag: tags.definitionKeyword, color: '#8b5cf6', fontWeight: '600' },
  { tag: tags.moduleKeyword, color: '#8b5cf6' },
  { tag: tags.operator, color: '#667789' },
  { tag: tags.punctuation, color: '#667789' },
  { tag: tags.bracket, color: '#667789' },
  { tag: tags.squareBracket, color: '#667789' },
  { tag: tags.brace, color: '#667789' },
  { tag: tags.paren, color: '#667789' },
  { tag: tags.separator, color: '#667789' },
  { tag: tags.string, color: '#16a34a' },
  { tag: tags.special(tags.string), color: '#16a34a' },
  { tag: tags.regexp, color: '#16a34a' },
  { tag: tags.number, color: '#d97706' },
  { tag: tags.integer, color: '#d97706' },
  { tag: tags.float, color: '#d97706' },
  { tag: tags.bool, color: '#d97706' },
  { tag: tags.null, color: '#d97706' },
  { tag: tags.className, color: '#0891b2', fontWeight: '600' },
  { tag: tags.typeName, color: '#0891b2' },
  { tag: tags.self, color: '#e15a4a', fontStyle: 'italic' },
  { tag: tags.function(tags.variableName), color: '#2563eb' },
  { tag: tags.function(tags.definition(tags.variableName)), color: '#2563eb', fontWeight: '600' },
  { tag: tags.definition(tags.variableName), color: '#16232f' },
  { tag: tags.variableName, color: '#16232f' },
  { tag: tags.propertyName, color: '#2563eb' },
  { tag: tags.definition(tags.propertyName), color: '#2563eb' },
  { tag: tags.comment, color: '#9aa7b4', fontStyle: 'italic' },
  { tag: tags.lineComment, color: '#9aa7b4', fontStyle: 'italic' },
  { tag: tags.blockComment, color: '#9aa7b4', fontStyle: 'italic' },
  { tag: tags.docComment, color: '#9aa7b4', fontStyle: 'italic' },
  { tag: tags.meta, color: '#667789' },
  { tag: tags.annotation, color: '#667789' },
  { tag: tags.tagName, color: '#e15a4a' },
  { tag: tags.attributeName, color: '#d97706' },
  { tag: tags.attributeValue, color: '#16a34a' },
  { tag: tags.heading, color: '#16232f', fontWeight: '700' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strong, fontWeight: '700' },
  { tag: tags.link, color: '#2563eb', textDecoration: 'underline' },
  { tag: tags.atom, color: '#d97706' },
  { tag: tags.escape, color: '#e15a4a' },
  { tag: tags.invalid, color: '#e15a4a', textDecoration: 'underline wavy' },
])

function createExtensions(langExt: Extension): Extension[] {
  return [
    lineNumbers(),
    highlightActiveLineGutter(),
    history(),
    foldGutter(),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    highlightActiveLine(),
    syntaxHighlighting(workbenchHighlight, { fallback: true }),
    keymap.of([
      ...closeBracketsKeymap,
      ...defaultKeymap,
      ...historyKeymap,
      indentWithTab,
    ]),
    EditorView.updateListener.of((update) => {
      if (update.docChanged && !ignoreUpdate) {
        const value = update.state.doc.toString()
        emit('change', value)
      }
    }),
    langExt,
  ]
}

async function mountEditor(): Promise<void> {
  if (!editorContainer.value || !props.file) return

  const langExt = await getLanguageExtension(props.file.path)
  const extensions = createExtensions(langExt)

  const state = EditorState.create({
    doc: props.content,
    extensions,
  })

  editorView = new EditorView({
    state,
    parent: editorContainer.value,
  })
}

function destroyEditor(): void {
  if (editorView) {
    editorView.destroy()
    editorView = null
  }
}

// Watch for file changes — recreate editor (flush: post ensures DOM is ready)
watch(() => props.file, async (newFile) => {
  destroyEditor()
  if (newFile) {
    await nextTick()
    await mountEditor()
  }
}, { immediate: true, flush: 'post' })

// Watch for external content updates (e.g., after save)
watch(() => props.content, (newContent) => {
  if (!editorView) return
  const currentContent = editorView.state.doc.toString()
  if (currentContent !== newContent) {
    ignoreUpdate = true
    editorView.dispatch({
      changes: {
        from: 0,
        to: editorView.state.doc.length,
        insert: newContent,
      },
    })
    ignoreUpdate = false
  }
})

// Expose method to get current editor content
function getEditorContent(): string {
  return editorView?.state.doc.toString() ?? ''
}

onBeforeUnmount(() => {
  destroyEditor()
})

defineExpose({ getEditorContent })
</script>

<style scoped>
.editor-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #fbfcfd;
}

.editor-tabs,
.editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  background: #ffffff;
}

.editor-tabs {
  border-bottom: 1px solid #dce3ea;
}

.editor-tabs div {
  display: inline-flex;
  gap: 6px;
}

.editor-footer {
  border-top: 1px solid #dce3ea;
  color: #667789;
  font-size: 12px;
}

.editor-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  background: #fbfcfd;
}

.editor-body {
  min-height: 0;
  overflow: hidden;
}

/* Make CodeMirror fill the container */
.editor-body :deep(.cm-editor) {
  height: 100%;
  background: #fbfcfd;
}

.editor-body :deep(.cm-scroller) {
  overflow: auto;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 22px;
}

.editor-body :deep(.cm-gutters) {
  background: #f5f8fa;
  border-right: 1px solid #e4e9ee;
  color: #9aa7b4;
}

.editor-body :deep(.cm-activeLineGutter) {
  background: #e9f6f3;
  color: #1f8f78;
}

.editor-body :deep(.cm-activeLine) {
  background: rgba(31, 143, 120, 0.04);
}

.editor-body :deep(.cm-selectionBackground) {
  background: rgba(31, 143, 120, 0.15) !important;
}

.editor-body :deep(.cm-cursor) {
  border-left-color: #1f8f78;
}

@media (max-width: 820px) {
  .editor-tabs,
  .editor-footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
