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
    <div v-else ref="editorContainer" :class="['editor-body', { 'annotation-mode': annotation.annotationMode }]" />

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
import {
  Decoration,
  EditorView,
  keymap,
  lineNumbers,
  highlightActiveLine,
  highlightActiveLineGutter,
  type DecorationSet,
} from '@codemirror/view'
import { EditorState, RangeSetBuilder, StateEffect, StateField, type Extension } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { syntaxHighlighting, HighlightStyle, indentOnInput, bracketMatching, foldGutter } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import type { LSPClient } from '@codemirror/lsp-client'
import { jumpToDefinition } from '@codemirror/lsp-client'
import { useAnnotationStore } from '@/stores/annotation'
import type { CodeFile } from '@/composables/useCode'
import type { CodeTargetView } from '@/composables/useTraceIndex'

const annotation = useAnnotationStore()
import { checkoutFileUri } from '@/features/repository/lspTransport'

const props = defineProps<{
  file: CodeFile | undefined
  content: string
  isDirty: boolean
  saving: boolean
  traceTargets?: CodeTargetView[]
  activeTargetIds?: Set<string>
  hoverTargetIds?: Set<string>
  revealActive?: boolean
  lspEnabled?: boolean
  lspClient?: LSPClient | null
  lspCheckoutRoot?: string | null
}>()

const emit = defineEmits<{
  save: []
  change: [content: string]
  traceHover: [targetId: string]
  traceLeave: []
  tracePin: [targetId: string]
  gotoDefinition: [payload: { path: string; line: number; column: number; identifier: string }]
}>()

const editorContainer = ref<HTMLDivElement | null>(null)
let editorView: EditorView | null = null
let ignoreUpdate = false
// The editor is destroyed and rebuilt asynchronously whenever the file changes (language pack
// import). A reveal requested during that window must survive until the new view exists, and a
// stale mount must never win over a newer file switch. The path is kept so a queued reveal is
// never replayed onto a different file the user opened in the meantime.
let pendingReveal: { path: string; line: number; endLine?: number } | null = null
let mounting = false
let mountToken = 0
let flashTimer: number | undefined
let revealFrame = 0

const setTraceDecorations = StateEffect.define<DecorationSet>()
const traceField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    value = value.map(tr.changes)
    for (const effect of tr.effects) {
      if (effect.is(setTraceDecorations)) value = effect.value
    }
    return value
  },
  provide: (field) => EditorView.decorations.from(field),
})

// One-shot flash on the jump target line; cleared by a timer.
const flashLineDeco = Decoration.line({ class: 'cm-line-flash' })
const setFlashLine = StateEffect.define<number | null>()
const flashField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    value = value.map(tr.changes)
    for (const effect of tr.effects) {
      if (effect.is(setFlashLine)) {
        value =
          effect.value === null ? Decoration.none : Decoration.set([flashLineDeco.range(effect.value)])
      }
    }
    return value
  },
  provide: (field) => EditorView.decorations.from(field),
})

// Persistent marker for the line range picked in annotation mode. CodeMirror dims its own
// selection once the dialog takes focus, so the chosen rows need a decoration that survives blur.
const annotationLineDeco = Decoration.line({ class: 'cm-annotation-range' })
const setAnnotationRange = StateEffect.define<{ from: number; to: number } | null>()
const annotationRangeField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    value = value.map(tr.changes)
    for (const effect of tr.effects) {
      if (effect.is(setAnnotationRange)) {
        if (effect.value === null) {
          value = Decoration.none
        } else {
          const builder = new RangeSetBuilder<Decoration>()
          const doc = tr.state.doc
          const startLine = doc.lineAt(effect.value.from).number
          const endLine = doc.lineAt(effect.value.to).number
          for (let line = startLine; line <= endLine; line += 1) {
            builder.add(doc.line(line).from, doc.line(line).from, annotationLineDeco)
          }
          value = builder.finish()
        }
      }
    }
    return value
  },
  provide: (field) => EditorView.decorations.from(field),
})

const gotoTargetDeco = Decoration.mark({ class: 'cm-goto-target' })
const setGotoHover = StateEffect.define<{ from: number; to: number } | null>()
const gotoHoverField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    value = value.map(tr.changes)
    for (const effect of tr.effects) {
      if (effect.is(setGotoHover)) {
        value =
          effect.value === null
            ? Decoration.none
            : Decoration.set([gotoTargetDeco.range(effect.value.from, effect.value.to)])
      }
    }
    return value
  },
  provide: (field) => EditorView.decorations.from(field),
})

const IDENTIFIER_RE = /[A-Za-z_][A-Za-z0-9_]*/g

function extractIdentifier(lineText: string, column: number): string | null {
  let hit: { start: number; end: number; text: string } | null = null
  for (const match of lineText.matchAll(IDENTIFIER_RE)) {
    const start = match.index ?? 0
    const end = start + match[0].length
    if (start <= column && column <= end) {
      hit = { start, end, text: match[0] }
      break
    }
  }
  if (!hit) return null
  let expandedStart = hit.start
  let expandedEnd = hit.end
  while (expandedStart > 0 && lineText[expandedStart - 1] === '.') {
    const prefix = lineText.slice(0, expandedStart - 1)
    const priorMatches = [...prefix.matchAll(IDENTIFIER_RE)]
    const prior = priorMatches.length > 0 ? priorMatches[priorMatches.length - 1] : undefined
    if (!prior || (prior.index ?? 0) + prior[0].length !== expandedStart - 1) break
    expandedStart = prior.index ?? expandedStart
  }
  while (expandedEnd < lineText.length && lineText[expandedEnd] === '.') {
    const suffix = lineText.slice(expandedEnd + 1)
    const next = IDENTIFIER_RE.exec(suffix)
    IDENTIFIER_RE.lastIndex = 0
    if (!next || next.index !== 0) break
    expandedEnd = expandedEnd + 1 + next[0].length
  }
  return lineText.slice(expandedStart, expandedEnd)
}

function modifierHeld(event: MouseEvent | KeyboardEvent): boolean {
  return event.metaKey || event.ctrlKey
}

function updateGotoHover(view: EditorView, event: MouseEvent): void {
  if (props.lspEnabled) {
    view.dispatch({ effects: setGotoHover.of(null) })
    return
  }
  if (!modifierHeld(event)) {
    view.dispatch({ effects: setGotoHover.of(null) })
    return
  }
  const pos = view.posAtCoords({ x: event.clientX, y: event.clientY })
  if (pos == null) {
    view.dispatch({ effects: setGotoHover.of(null) })
    return
  }
  const line = view.state.doc.lineAt(pos)
  const column = pos - line.from
  const ident = extractIdentifier(line.text, column)
  if (!ident) {
    view.dispatch({ effects: setGotoHover.of(null) })
    return
  }
  const start = line.text.indexOf(ident, Math.max(0, column - ident.length))
  if (start < 0) {
    view.dispatch({ effects: setGotoHover.of(null) })
    return
  }
  view.dispatch({
    effects: setGotoHover.of({ from: line.from + start, to: line.from + start + ident.length }),
  })
}

function currentFileTargets(): CodeTargetView[] {
  const path = props.file?.path
  if (!path) return []
  return (props.traceTargets ?? []).filter((target) => target.path === path)
}

function targetRange(doc: EditorState['doc'], target: CodeTargetView): { from: number; to: number } | null {
  if (
    target.charStart != null &&
    target.charEnd != null &&
    target.charStart >= 0 &&
    target.charEnd > target.charStart &&
    target.charEnd <= doc.length
  ) {
    return { from: target.charStart, to: target.charEnd }
  }
  const lineStart = target.matchLineStart ?? target.lineStart
  const lineEnd = target.matchLineEnd ?? target.lineEnd
  if (lineStart >= 1 && lineEnd >= lineStart && lineEnd <= doc.lines) {
    return { from: doc.line(lineStart).from, to: doc.line(lineEnd).to }
  }
  return null
}

function buildTraceDecorations(state: EditorState): DecorationSet {
  const active = props.activeTargetIds ?? new Set<string>()
  const hover = props.hoverTargetIds ?? new Set<string>()
  const ranged = currentFileTargets()
    .map((target) => ({ target, range: targetRange(state.doc, target) }))
    .filter((entry): entry is { target: CodeTargetView; range: { from: number; to: number } } =>
      entry.range !== null,
    )
    .sort((a, b) => a.range.from - b.range.from || a.range.to - b.range.to)
  const builder = new RangeSetBuilder<Decoration>()
  for (const { target, range } of ranged) {
    const classes = ['trace-code-mark', `trace-code-${target.status}`]
    if (target.multiplicity && target.multiplicity !== '1_to_1') {
      classes.push(`trace-code-${target.multiplicity}`)
    }
    if (active.has(target.targetId)) classes.push('trace-code-active')
    else if (hover.has(target.targetId)) classes.push('trace-code-hover')
    const attributes: Record<string, string> = { 'data-trace-target': target.targetId }
    if (target.fanoutCount > 1) attributes['data-fanout'] = String(target.fanoutCount)
    if (target.multiplicity && target.multiplicity !== '1_to_1') {
      attributes['data-multiplicity'] = target.multiplicity
    }
    builder.add(
      range.from,
      range.to,
      Decoration.mark({
        class: classes.join(' '),
        attributes,
      }),
    )
  }
  return builder.finish()
}

function refreshTraceDecorations(): void {
  if (!editorView) return
  editorView.dispatch({ effects: setTraceDecorations.of(buildTraceDecorations(editorView.state)) })
}

function revealActiveCodeTarget(): void {
  if (!editorView) return
  const active = props.activeTargetIds ?? new Set<string>()
  const hit = currentFileTargets().find((target) => active.has(target.targetId))
  if (!hit) return
  const range = targetRange(editorView.state.doc, hit)
  if (!range) return
  editorView.dispatch({ effects: EditorView.scrollIntoView(range.from, { y: 'center' }) })
}

function traceTargetFromEvent(event: Event): string | null {
  const el = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-trace-target]')
  return el?.dataset.traceTarget ?? null
}

// Track the last target the pointer reported so a single hover over one highlight span doesn't
// re-emit `traceHover` for every glyph the mouse crosses (CodeMirror splits marks per line/token).
let lastHoveredTarget: string | null = null

const traceDomHandlers = EditorView.domEventHandlers({
  mousemove: (event, view) => {
    updateGotoHover(view, event)
    return false
  },
  mouseleave: (_event, view) => {
    view.dispatch({ effects: setGotoHover.of(null) })
    return false
  },
  mouseover: (event) => {
    const id = traceTargetFromEvent(event)
    if (id === lastHoveredTarget) return
    lastHoveredTarget = id
    if (id) emit('traceHover', id)
    else emit('traceLeave')
  },
  mouseout: (event) => {
    // Only clear when the pointer actually leaves the current target for non-target space.
    const to = (event as MouseEvent).relatedTarget as HTMLElement | null
    const stillInTarget = to?.closest?.('[data-trace-target]')
    if (!stillInTarget && lastHoveredTarget !== null) {
      lastHoveredTarget = null
      emit('traceLeave')
    }
  },
  mousedown: (event, view) => {
    if (props.lspEnabled && modifierHeld(event) && props.file?.path.endsWith('.py')) {
      event.preventDefault()
      jumpToDefinition(view)
      return true
    }
    if (
      !props.lspEnabled
      && modifierHeld(event)
      && props.file?.path.endsWith('.py')
    ) {
      const pos = view.posAtCoords({ x: event.clientX, y: event.clientY })
      if (pos != null) {
        const line = view.state.doc.lineAt(pos)
        const column = pos - line.from
        const identifier = extractIdentifier(line.text, column)
        if (identifier) {
          event.preventDefault()
          emit('gotoDefinition', {
            path: props.file.path,
            line: line.number,
            column,
            identifier,
          })
          return true
        }
      }
    }
    // Annotation mode owns the drag: let CodeMirror build the selection, then read it on mouseup.
    if (annotation.annotationMode) return false
    // Normal mode: pin trace target
    const id = traceTargetFromEvent(event)
    if (id) emit('tracePin', id)
    return false
  },
  // The range is only final once the drag ends, so the capture must happen here — a mousedown
  // handler always sees the pre-drag (empty) selection.
  mouseup: (_event, view) => {
    if (!annotation.annotationMode || !props.file) return false
    const selection = view.state.selection.main
    if (selection.empty) return false
    const doc = view.state.doc
    const fromLine = doc.lineAt(selection.from)
    const toLine = doc.lineAt(selection.to)
    view.dispatch({
      effects: setAnnotationRange.of({ from: fromLine.from, to: toLine.from }),
    })
    annotation.selectCodeSymbol(`${props.file.path}:${fromLine.number}-${toLine.number}`)
    return false
  },
})

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
  const extensions: Extension[] = [
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
    traceField,
    flashField,
    annotationRangeField,
    gotoHoverField,
    traceDomHandlers,
    langExt,
  ]
  if (
    props.lspEnabled
    && props.lspClient
    && props.lspCheckoutRoot
    && props.file?.path.endsWith('.py')
  ) {
    extensions.push(
      props.lspClient.plugin(
        checkoutFileUri(props.lspCheckoutRoot, props.file.path),
        'python',
      ),
    )
  }
  return extensions
}

async function mountEditor(token: number): Promise<void> {
  if (!editorContainer.value || !props.file) return

  const langExt = await getLanguageExtension(props.file.path)
  // A newer file switch started while the language pack was loading; let it own the view.
  if (token !== mountToken || !editorContainer.value || !props.file) return
  const extensions = createExtensions(langExt)

  const state = EditorState.create({
    doc: props.content,
    extensions,
  })

  editorView = new EditorView({
    state,
    parent: editorContainer.value,
  })
  refreshTraceDecorations()
  // A queued reveal is replayed by the file watcher once `mounting` clears, so nothing to do here.
}

function destroyEditor(): void {
  if (editorView) {
    editorView.destroy()
    editorView = null
  }
  window.cancelAnimationFrame(revealFrame)
}

// Watch for file changes — recreate editor (flush: post ensures DOM is ready)
watch(() => props.file, async (newFile) => {
  const token = ++mountToken
  mounting = true
  destroyEditor()
  if (newFile) {
    await nextTick()
    await mountEditor(token)
  }
  if (token === mountToken) {
    mounting = false
    if (pendingReveal) applyPendingReveal()
  }
}, { immediate: true, flush: 'post' })

watch(
  () => [props.lspEnabled, props.lspClient, props.lspCheckoutRoot] as const,
  async () => {
    if (!props.file) return
    const token = ++mountToken
    mounting = true
    destroyEditor()
    await nextTick()
    await mountEditor(token)
    if (token === mountToken) {
      mounting = false
      if (pendingReveal) applyPendingReveal()
    }
  },
)

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

watch(
  () => props.traceTargets,
  () => refreshTraceDecorations(),
  { deep: true },
)

// Selection change → refresh strong highlight + one-time reveal scroll (only when this pane is
// the counterpart, i.e. revealActive). Hover change → weak highlight only, never scrolls.
watch(
  () => props.activeTargetIds,
  () => {
    refreshTraceDecorations()
    if (props.revealActive) nextTick(() => revealActiveCodeTarget())
  },
  { deep: true },
)

watch(
  () => props.hoverTargetIds,
  () => refreshTraceDecorations(),
  { deep: true },
)

// Expose method to get current editor content
function getEditorContent(): string {
  return editorView?.state.doc.toString() ?? ''
}

/**
 * Go to a specific line (1-based), select it, and center it in the viewport.
 * File switches rebuild the editor asynchronously, so the request is queued and applied by
 * whichever of goToLine / mountEditor happens last (last request wins).
 *
 * `endLine` is the last line of the traced range: a short range is centred as a whole, a long
 * one centres on its first line so the reader lands on the declaration rather than mid-body.
 */
function goToLine(line: number, endLine?: number): void {
  pendingReveal = { path: props.file?.path ?? '', line, endLine }
  if (editorView && !mounting) applyPendingReveal()
}

function applyPendingReveal(): void {
  if (!editorView || !pendingReveal) return
  // A reveal queued for another file is stale — the user has since opened something else.
  if (pendingReveal.path && props.file && pendingReveal.path !== props.file.path) {
    pendingReveal = null
    return
  }
  const doc = editorView.state.doc
  const lineNum = Math.max(1, Math.min(pendingReveal.line, doc.lines))
  const rangeEnd = pendingReveal.endLine
  pendingReveal = null
  const lineObj = doc.line(lineNum)
  // Centre the whole match only while it still fits comfortably on screen.
  const lastLine = rangeEnd ? Math.max(1, Math.min(rangeEnd, doc.lines)) : lineNum
  const focusLine =
    lastLine > lineNum && lastLine - lineNum <= 12
      ? Math.floor((lineNum + lastLine) / 2)
      : lineNum
  const centre = (): void => {
    if (!editorView) return
    const current = editorView.state.doc
    const safe = Math.max(1, Math.min(focusLine, current.lines))
    editorView.dispatch({
      effects: EditorView.scrollIntoView(current.line(safe).from, { y: 'center' }),
    })
  }
  editorView.dispatch({
    selection: { anchor: lineObj.from, head: lineObj.to },
    effects: setFlashLine.of(lineObj.from),
  })
  centre()
  editorView.focus()
  // A freshly mounted view has not measured its own geometry yet, so the scroll above can land
  // short. Re-issue it once on the next frame, when line heights are known.
  window.cancelAnimationFrame(revealFrame)
  revealFrame = window.requestAnimationFrame(centre)
  window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    editorView?.dispatch({ effects: setFlashLine.of(null) })
  }, 1600)
}

// Annotation mode: highlight selected code symbol
watch(
  () => annotation.selectedCodeRef,
  (selectedRef) => {
    if (!editorView) return

    // Remove previous selection highlight from DOM elements
    if (editorContainer.value) {
      editorContainer.value.querySelectorAll('[data-trace-target].annotation-selected').forEach((el) => {
        el.classList.remove('annotation-selected')
      })
    }

    // Selection cleared (dialog submitted or cancelled): drop the range marker.
    if (!selectedRef) {
      editorView.dispatch({ effects: setAnnotationRange.of(null) })
      return
    }

    // Parse code_ref for line-based selection (e.g., "file.py:10-15")
    if (selectedRef && selectedRef.includes(':')) {
      const parts = selectedRef.split(':')
      if (parts.length >= 2) {
        const lineRange = parts[parts.length - 1]
        const match = lineRange.match(/^(\d+)(?:-(\d+))?$/)
        if (match) {
          const startLine = parseInt(match[1], 10)
          const endLine = match[2] ? parseInt(match[2], 10) : startLine

          // Highlight the line range in editor
          const doc = editorView.state.doc
          if (startLine > 0 && startLine <= doc.lines && endLine <= doc.lines) {
            const from = doc.line(startLine).from
            const to = doc.line(endLine).to
            // The ref usually arrives FROM the user's own drag; re-dispatching it would fight
            // their selection and yank the viewport. Only reveal a range they aren't already on.
            const current = editorView.state.selection.main
            const alreadyThere =
              doc.lineAt(current.from).number === startLine
              && doc.lineAt(current.to).number === endLine
            if (alreadyThere) {
              // Drag already painted the marker in the mouseup handler.
            } else {
              editorView.dispatch({
                selection: { anchor: from, head: to },
                effects: [
                  setAnnotationRange.of({ from, to: doc.line(endLine).from }),
                  EditorView.scrollIntoView(from, { y: 'center' }),
                ],
              })
            }
          }
        }
      }
    }

    // Fallback: highlight DOM element for trace-target based refs
    if (selectedRef && editorContainer.value) {
      const selectedEl = editorContainer.value.querySelector(`[data-trace-target="${selectedRef}"]`)
      if (selectedEl) {
        selectedEl.classList.add('annotation-selected')
      }
    }
  },
)

onBeforeUnmount(() => {
  window.clearTimeout(flashTimer)
  destroyEditor()
})

defineExpose({ getEditorContent, goToLine })
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

/* Trace target decorations (bidirectional hover). */
.editor-body :deep(.trace-code-mark) {
  border-radius: 2px;
  cursor: pointer;
}

.editor-body :deep(.trace-code-proposed) {
  background: rgba(88, 133, 255, 0.16);
  box-shadow: inset 0 -2px 0 rgba(88, 133, 255, 0.45);
}

.editor-body :deep(.trace-code-accepted) {
  background: rgba(46, 168, 118, 0.2);
  box-shadow: inset 0 -2px 0 rgba(46, 168, 118, 0.6);
}

.editor-body :deep(.trace-code-1_to_n) {
  box-shadow: inset 0 -2px 0 rgba(139, 92, 246, 0.65);
}

.editor-body :deep(.trace-code-n_to_1) {
  box-shadow: inset 0 -2px 0 rgba(8, 145, 178, 0.65);
}

.editor-body :deep(.trace-code-n_to_n) {
  box-shadow: inset 0 -2px 0 rgba(139, 92, 246, 0.65), inset 0 -4px 0 rgba(8, 145, 178, 0.45);
}

.editor-body :deep(.trace-code-mark[data-fanout]::after) {
  content: '×' attr(data-fanout);
  margin-left: 2px;
  padding: 0 3px;
  border-radius: 8px;
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
  font-size: 9px;
  font-weight: 700;
}

.editor-body :deep(.trace-code-mark[data-multiplicity='n_to_1'][data-fanout]::after) {
  background: rgba(8, 145, 178, 0.15);
  color: #0891b2;
}

.editor-body :deep(.trace-code-active) {
  background: rgba(224, 168, 58, 0.32) !important;
  box-shadow: inset 0 -2px 0 #e0a83a, 0 0 0 1px rgba(224, 168, 58, 0.5) !important;
}

/* Weak highlight for the relation currently under the pointer (preview only, not selected). */
.editor-body :deep(.trace-code-hover) {
  background: rgba(224, 168, 58, 0.16);
  box-shadow: 0 0 0 1px rgba(224, 168, 58, 0.45);
}

/* One-shot flash on the line a jump landed on. */
.editor-body :deep(.cm-line-flash) {
  background: rgba(31, 143, 120, 0.18);
}

.editor-body :deep(.cm-goto-target) {
  text-decoration: underline;
  text-decoration-color: #2563eb;
  text-underline-offset: 2px;
  cursor: pointer;
}

/* Annotation mode styles */
.editor-body.annotation-mode :deep(.cm-content) {
  cursor: text !important;
}

.editor-body.annotation-mode :deep(.cm-line) {
  transition: background 0.15s ease;
}

.editor-body.annotation-mode :deep(.cm-line:hover) {
  background: rgba(64, 158, 255, 0.08) !important;
}

.editor-body.annotation-mode :deep(.cm-selectionBackground) {
  background: rgba(64, 158, 255, 0.3) !important;
}

/* Survives blur, so the picked rows stay visible while the dialog is open. */
.editor-body :deep(.cm-annotation-range) {
  background: rgba(103, 194, 58, 0.16);
  box-shadow: inset 3px 0 0 #67c23a;
}

.editor-body.annotation-mode :deep([data-trace-target]) {
  cursor: text !important;
}

.editor-body.annotation-mode :deep([data-trace-target]:hover) {
  background: rgba(64, 158, 255, 0.2) !important;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.5) !important;
}

.editor-body.annotation-mode :deep([data-trace-target].annotation-selected) {
  background: rgba(103, 194, 58, 0.25) !important;
  box-shadow: inset 0 -2px 0 #67c23a, 0 0 0 1px rgba(103, 194, 58, 0.6) !important;
}

@media (max-width: 820px) {
  .editor-tabs,
  .editor-footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
