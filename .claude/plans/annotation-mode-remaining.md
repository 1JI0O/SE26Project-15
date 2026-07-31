# Annotation Mode - Remaining Frontend Work

## Completed ✅
1. ✅ Backend PATCH/DELETE endpoints (`/api/routes/traces.py`)
2. ✅ Backend Agent CRUD tools (update_trace_link, delete_trace_link, query_trace_links, get_trace_link)
3. ✅ Frontend annotation store (`/stores/annotation.ts`)
4. ✅ Activity bar button in ProjectWorkspaceView
5. ✅ AnnotationDialog component created

## Remaining Frontend Work 🚧

### 1. Selection Handlers in PaperReader.vue
**Location**: `frontend/src/features/papers/PaperReader.vue`

Add click handler to paper blocks:
```vue
<script setup>
import { useAnnotationStore } from '@/stores/annotation'
const annotation = useAnnotationStore()

function handleBlockClick(blockId: string, event: MouseEvent) {
  if (annotation.annotationMode) {
    event.stopPropagation()
    annotation.selectPaperBlock(blockId)
  }
}
</script>

<template>
  <!-- Add to paper block elements -->
  <div 
    :class="['paper-block', { 
      'annotation-selectable': annotation.annotationMode,
      'annotation-selected': annotation.selectedPaperRef === block.id 
    }]"
    @click="handleBlockClick(block.id, $event)"
  >
    <!-- existing content -->
  </div>
</template>

<style>
.annotation-selectable {
  cursor: crosshair;
}
.annotation-selectable:hover {
  outline: 2px solid #409eff;
}
.annotation-selected {
  outline: 3px solid #67c23a !important;
  background: rgba(103, 194, 58, 0.1);
}
</style>
```

### 2. Selection Handlers in CodeEditor.vue
**Location**: `frontend/src/features/repository/CodeEditor.vue`

Add click handler to code symbols in file tree or editor decorations:
```vue
<script setup>
import { useAnnotationStore } from '@/stores/annotation'
const annotation = useAnnotationStore()

function handleSymbolClick(symbolId: string, event: MouseEvent) {
  if (annotation.annotationMode) {
    event.stopPropagation()
    annotation.selectCodeSymbol(symbolId)
  }
}
</script>

<template>
  <!-- Add to symbol tree nodes -->
  <div 
    :class="['symbol-item', { 
      'annotation-selectable': annotation.annotationMode,
      'annotation-selected': annotation.selectedCodeRef === symbol.id 
    }]"
    @click="handleSymbolClick(symbol.id, $event)"
  >
    <!-- existing content -->
  </div>
</template>

<style>
.annotation-selectable {
  cursor: crosshair;
}
.annotation-selectable:hover {
  background: #ecf5ff;
}
.annotation-selected {
  background: #f0f9ff !important;
  border-left: 3px solid #67c23a;
}
</style>
```

### 3. Fresh Link Highlight in TraceMatrix.vue
**Location**: `frontend/src/features/tracing/TraceMatrix.vue`

Listen for trace-link-created event and add temporary highlight:
```vue
<script setup>
const freshTraceIds = ref<Set<string>>(new Set())

onMounted(() => {
  window.addEventListener('trace-link-created', handleNewTraceLink)
})

onUnmounted(() => {
  window.removeEventListener('trace-link-created', handleNewTraceLink)
})

function handleNewTraceLink(event: CustomEvent) {
  const { traceId } = event.detail
  freshTraceIds.value.add(traceId)
  
  // Remove highlight after 3 seconds
  setTimeout(() => {
    freshTraceIds.value.delete(traceId)
  }, 3000)
  
  // Refresh trace data
  trace.refresh()
}
</script>

<template>
  <tr 
    :class="['trace-row', { fresh: freshTraceIds.has(row.id) }]"
  >
    <!-- existing content -->
  </tr>
</template>

<style>
@keyframes flash-yellow {
  0% { background-color: #fdf6ec; }
  50% { background-color: #f5daa5; }
  100% { background-color: transparent; }
}

.trace-row.fresh {
  animation: flash-yellow 3s ease-out;
}
</style>
```

### 4. Evidence Auto-Generation (Backend Fix)
**Location**: `backend/app/api/routes/traces.py` line 85-137

The create endpoint currently requires evidence array. For manual annotation mode, we should auto-generate evidence:

```python
@router.post("", response_model=TraceLinkRead, status_code=status.HTTP_201_CREATED)
def create_trace_link(
    project_id: int,
    payload: TraceLinkCreate,
    session: Session = Depends(get_session),
) -> TraceLinkRead:
    project = get_project_or_404(project_id, session)
    paper = _latest_paper(session, project_id)
    code = _latest_code(session, project_id)
    
    # ... existing validation ...
    
    # Auto-generate evidence if empty (for manual annotation)
    evidence = payload.evidence
    if not evidence and paper and code:
        # Find paper block
        paper_block = next(
            (p for p in paper.paragraphs_json if str(p.get("id")) == payload.paper_ref),
            None
        )
        # Find code symbol
        code_symbol = next(
            (s for s in code.symbols_json if str(s.get("id")) == payload.code_ref),
            None
        )
        
        if paper_block:
            evidence.append({
                "side": "paper",
                "ref": payload.paper_ref,
                "quote": paper_block.get("content", "")[:500],
            })
        if code_symbol:
            evidence.append({
                "side": "code",
                "ref": payload.code_ref,
                "quote": code_symbol.get("signature", "")[:500],
                "path": code_symbol.get("path"),
                "line_start": code_symbol.get("line_start"),
                "line_end": code_symbol.get("line_end"),
            })
    
    # ... rest of existing logic ...
```

## Testing Checklist
- [ ] Backend: PATCH /projects/{id}/trace-links/{trace_id} updates fields
- [ ] Backend: DELETE /projects/{id}/trace-links/{trace_id} soft-deletes
- [ ] Backend: Agent query_trace_links returns filtered results
- [ ] Backend: Agent update_trace_link requires confirmation
- [ ] Backend: Agent delete_trace_link requires confirmation
- [ ] Frontend: Annotation mode button toggles mode
- [ ] Frontend: Paper blocks become selectable in annotation mode
- [ ] Frontend: Code symbols become selectable in annotation mode
- [ ] Frontend: Dialog opens when both selected
- [ ] Frontend: Created link appears in matrix with flash
- [ ] Frontend: Agent can query/update/delete via conversation

## Quick Implementation Time Estimate
- Selection handlers (PaperReader + CodeEditor): ~30 min
- Fresh link highlight (TraceMatrix): ~15 min
- Evidence auto-generation fix: ~20 min
- Testing: ~30 min
**Total: ~1.5 hours**
