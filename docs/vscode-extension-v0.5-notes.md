
## Performance (v0.5)

- Status checks no longer spawn CLI processes — `.tracelab/` files are read in-process, keeping the sidebar responsive even during long Agent runs.
- Paper panel artifacts arrive over `postMessage` instead of re-setting `webview.html` on every refresh, so the PDF never restarts mid-load.
- Highlight rectangles are precomputed in the extension host — the webview never receives the multi-MB `blocks` array with per-line bboxes.
- Markdown is rendered progressively across frames; large papers paint immediately instead of blocking for minutes.
- PDF.js range requests are disabled (`disableRange: true`) since the vscode-resource protocol doesn't support HTTP ranges; one plain fetch replaces the repeated partial requests.
- Tensor flow graph is computed lazily only when the panel is visible, not on every `refreshAll()`.
- Review actions patch rows in place via `postMessage` instead of rebuilding the matrix HTML and resetting scroll position.
- Bundled venv Python is used directly when available (~70ms) instead of `uv run` on every CLI call (~360ms).
- Progress events are coalesced: bursty `analysis.published` batches trigger one refresh after 400ms, not a refresh per event.

## UI & consistency (v0.5)

- Shared design system (`media/ui.css`) unifies colors, buttons, badges, and typography across all four webviews using VS Code theme variables.
- Agent analysis log displays newest-first with step numbering, matching the desktop workbench.
- Matrix panel has a docked **关系预览** pane (hover + pinned) instead of a floating tooltip that overlapped the list.
- Paper snippet extraction now balances math delimiters (`$...$` / `$$...$$`) — quotes that start mid-formula no longer emit unbalanced `$`.
- Toolbar buttons stay fixed when scrolling the matrix list (previously they scrolled away, causing overlap).
- Tensor panel uses theme-aware colors instead of hardcoded navy, so it renders correctly in light themes.
