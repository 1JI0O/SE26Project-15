# Annotation Mode Implementation Plan

## Overview
Add a manual annotation mode allowing users to create trace links by selecting paper blocks and code symbols directly, with Agent CRUD integration for conversational trace management.

## Requirements Summary
1. Activity bar button to switch between trace display mode and annotation mode
2. Manual trace creation: select paper block + code symbol → create link → highlight in matrix
3. Agent CRUD tools for conversational trace management (create, read, update, delete)

## Architecture Analysis

### Current State (from exploration)
- **Mode switching**: Activity bar (left sidebar, 46px) with icon buttons in `ProjectWorkspaceView.vue`
- **Trace matrix**: `TraceMatrix.vue` displays links, supports batch review
- **Paper display**: `PaperReader.vue` with markdown/PDF view, blocks highlighted when linked
- **Code display**: `CodeEditor.vue` with file tree, symbol navigation, trace decorations
- **Data format**:
  - `paper_ref`: block ID like `"sec-3-p-12"`, `"formula-42"`
  - `code_ref`: symbol ID like `"model.py::forward"`
  - Evidence must include both paper and code sides with quotes
- **Existing Agent tool**: `create_trace_link` in `tools.py` accepts paper_ref, code_ref, relation_type, confidence, rationale (requires confirmation)

### Design Decisions

#### 1. Mode Switching Location
**Decision**: Add annotation mode button to the **activity bar** (not top bar).
- **Why**: Follows existing pattern — trace/flow/conflict/terminal all use activity bar
- **Placement**: Below trace matrix button, above tensor flow button
- **Icon**: `EditPen` or `Plus` (Element Plus icon)
- **Badge**: Show count of annotation-created links

#### 2. Annotation Mode UX Flow
**Decision**: Two-step selection workflow with visual feedback.

**Flow**:
1. User clicks annotation mode button → enters annotation mode
2. In annotation mode:
   - Paper blocks become selectable (cursor changes to crosshair, hover shows blue outline)
   - Code symbols/lines become selectable (same visual treatment)
3. User clicks paper block → it gets selected (green outline + "Selected: sec-3-p-12" chip)
4. User clicks code symbol → opens **annotation dialog**
5. Dialog shows:
   - Selected paper ref + preview (first 100 chars)
   - Selected code ref + preview (signature or first 3 lines)
   - Relation type dropdown (implements, computes, defines, etc.)
   - Confidence slider (0-100%, default 80%)
   - Rationale textarea (required, min 20 chars)
6. User fills form → clicks "Create" → link appears in trace matrix with `source: "manual"`, `status: "accepted"`, highlighted in yellow for 3s
7. Selection clears, user can create another link

**Edge cases**:
- Click same type twice → replaces selection (show warning toast)
- Click annotation mode button again → exits mode, clears selection
- Navigate away → exits mode automatically

#### 3. Highlight Strategy
**Decision**: Use existing trace status system + temporary flash animation.

- New manual links get `status: "accepted"` and `source: "manual"` immediately (no proposed state)
- Add `fresh: true` flag in frontend state for 3 seconds after creation
- `TraceMatrix.vue` adds `.fresh-link` class → yellow background fade-out animation
- Paper and code editors update their trace decorations immediately via existing `useTraceIndex` reactivity

#### 4. Agent CRUD Tools
**Decision**: Extend existing `create_trace_link`, add new tools for update/delete/query.

**New tools** (in `backend/app/services/agent/tools.py`):

1. **`create_trace_link`** (already exists, keep as-is)
   - Returns: trace link ID on success
   
2. **`update_trace_link`** (NEW)
   - Args: `trace_id`, optional `relation_type`, `confidence`, `rationale`
   - Requires confirmation
   - Returns: updated link summary
   
3. **`delete_trace_link`** (NEW)
   - Args: `trace_id`, `reason`
   - Requires confirmation
   - Returns: confirmation message
   
4. **`query_trace_links`** (NEW, read-only)
   - Args: optional `paper_ref`, `code_ref`, `status`, `source`
   - No confirmation needed (read-only)
   - Returns: list of matching links with id, refs, confidence, rationale
   
5. **`get_trace_link`** (NEW, read-only)
   - Args: `trace_id`
   - No confirmation needed
   - Returns: full link detail including evidence

**Why separate tools**: Allows granular permission control and clearer Agent reasoning traces.

#### 5. Backend API Additions
**Decision**: Add PATCH and DELETE endpoints, keep POST as-is.

- `PATCH /projects/{id}/trace-links/{trace_id}` → update rationale/confidence/relation_type
- `DELETE /projects/{id}/trace-links/{trace_id}` → soft delete (set status to rejected? or hard delete?)
  - **Recommendation**: Soft delete (set `status: "rejected"`, add `deleted_by: "agent"` or `"manual"`)
- `GET /projects/{id}/trace-links?paper_ref=...&code_ref=...&source=...` → query (already exists, verify filtering)

## Implementation Steps

### Phase 1: Backend CRUD API (1-2 files)
1. Add PATCH/DELETE handlers in `backend/app/api/routes/traces.py`
2. Update `TraceLinkUpdate` schema in `backend/app/schemas/traces.py`
3. Add query filtering in existing GET handler
4. Tests in `backend/tests/tracing/test_trace_api.py`

### Phase 2: Agent Tools (1 file)
1. Add 4 new tool classes in `backend/app/services/agent/tools.py`:
   - `UpdateTraceLinkArguments` + handler
   - `DeleteTraceLinkArguments` + handler  
   - `QueryTraceLinksArguments` + handler
   - `GetTraceLinkArguments` + handler
2. Register in `AVAILABLE_TOOLS` dict
3. Update conversation agent system prompt to document the tools
4. Tests in `backend/tests/agent/test_trace_tools.py` (new file)

### Phase 3: Frontend State Management (1-2 files)
1. Extend `frontend/src/stores/workspace.ts` (or create `annotation.ts`):
   - `annotationMode: boolean`
   - `selectedPaperRef: string | null`
   - `selectedCodeRef: string | null`
   - `enterAnnotationMode()` / `exitAnnotationMode()`
   - `selectPaperBlock(ref)` / `selectCodeSymbol(ref)`
   - `clearSelection()`
2. Add `createManualTraceLink()` action that calls trace API + updates local state

### Phase 4: UI Components (3-4 files)
1. **Activity bar button** in `ProjectWorkspaceView.vue`:
   - Add button below trace button with `EditPen` icon
   - Bind click to `workspace.toggleAnnotationMode()`
   - Show `.active` class when in annotation mode
   
2. **Selection overlays** in `PaperReader.vue` and `CodeEditor.vue`:
   - Add `.annotation-mode-active` class to root when mode is on
   - CSS: `.annotation-mode-active .paper-block:hover { outline: 2px solid #409eff; cursor: crosshair; }`
   - Click handler: call `workspace.selectPaperBlock(blockId)` if in annotation mode
   - Show selected state: `.paper-block.selected { outline: 3px solid #67c23a; }`
   
3. **Annotation dialog** (new component `AnnotationDialog.vue`):
   - Opens when both paper and code are selected
   - Form: relation type (select), confidence (slider), rationale (textarea)
   - Preview selected refs at top
   - Submit → calls `workspace.createManualTraceLink(payload)` → closes dialog
   
4. **Fresh link highlight** in `TraceMatrix.vue`:
   - Add `fresh` boolean to `TraceRowView` interface
   - CSS: `.trace-row.fresh { animation: flash-yellow 3s ease-out; }`
   - Remove `fresh` flag after 3s timeout

### Phase 5: Integration & Testing
1. End-to-end test: enter annotation mode → select paper → select code → fill dialog → verify link in matrix
2. Agent test: send message "delete the trace link between sec-3 and model.py::forward" → verify confirmation → verify deletion
3. Highlight test: create manual link → verify yellow flash → verify trace decorations update in paper/code editors

## Open Questions for User

1. **Deletion behavior**: When Agent or user deletes a trace link, should it:
   - (A) Hard delete (remove from database)
   - (B) Soft delete (set `status: "rejected"`, keep in database)
   - **Recommendation**: (B) for audit trail, but filter rejected links from matrix by default

2. **Multi-select**: Should annotation mode support:
   - (A) One paper block → multiple code symbols (creates N links in batch)
   - (B) Only 1-to-1 selection per creation
   - **Recommendation**: Start with (B), add (A) in Phase 2 if needed

3. **Paper block granularity**: Can user select:
   - (A) Only pre-parsed blocks (paragraphs, formulas, figures)
   - (B) Custom text ranges (free selection with mouse drag)
   - **Recommendation**: (A) — custom ranges require new evidence anchoring logic

4. **Evidence auto-generation**: When user creates manual link, should evidence:
   - (A) Use full block text + full symbol signature/body as quotes
   - (B) Open a second dialog to let user highlight specific quotes
   - **Recommendation**: (A) for MVP, evidence quotes = entire block/symbol content

## Estimated Scope
- **Backend**: ~200 lines (CRUD endpoints + Agent tools + tests)
- **Frontend**: ~400 lines (store logic + dialog component + selection handlers + CSS)
- **Testing**: ~150 lines (API tests + Agent tool tests)
- **Total**: ~750 lines, 3-5 hours for implementation + testing

## Files to Create/Modify

### New Files (6)
1. `backend/tests/agent/test_trace_tools.py` — Agent CRUD tool tests
2. `frontend/src/features/tracing/AnnotationDialog.vue` — Annotation creation dialog
3. `frontend/src/stores/annotation.ts` — Annotation mode state (or extend workspace.ts)
4. `frontend/src/composables/useAnnotation.ts` — Annotation mode composable (optional)

### Modified Files (8)
1. `backend/app/api/routes/traces.py` — Add PATCH/DELETE handlers
2. `backend/app/schemas/traces.py` — Add `TraceLinkUpdate` schema
3. `backend/app/services/agent/tools.py` — Add 4 new tools
4. `backend/tests/tracing/test_trace_api.py` — Add update/delete tests
5. `frontend/src/views/ProjectWorkspaceView.vue` — Add annotation mode button
6. `frontend/src/features/papers/PaperReader.vue` — Add selection handlers
7. `frontend/src/features/repository/CodeEditor.vue` — Add selection handlers
8. `frontend/src/features/tracing/TraceMatrix.vue` — Add fresh link highlight

## Risk Mitigation
- **Selection state confusion**: Clear selection on mode exit, show persistent chip
- **Evidence validation**: Backend must validate evidence array has both sides (already exists)
- **Agent permission bypass**: All write tools require confirmation (already pattern)
- **Race conditions**: Manual creation uses optimistic update + rollback on API error
