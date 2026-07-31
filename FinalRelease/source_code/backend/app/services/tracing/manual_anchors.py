"""Derive evidence anchors for relations a human or the chat Agent creates by reference.

Both the annotation-mode endpoint and the Agent's ``create_trace_link`` tool identify a
relation by *reference* (a paper block id plus either a ``path:start-end`` line range or a
symbol id) rather than by quoted evidence. The stored link still has to carry full evidence,
because the reader's decoration layer is driven entirely by it:

``useTraceIndex`` keys its paper/code decoration maps by **target id** and silently skips any
link whose id is null. A link with no evidence therefore shows up in the matrix and jumps
correctly — the matrix uses ``paper_ref``/``code_ref`` — while leaving both panes unhighlighted
and unclickable. That asymmetry is exactly the bug this module exists to prevent.

Anchor ids are content-derived rather than random so that:

* a reload resolves to the same ids, keeping selection and hover state stable, and
* fan-out collapses correctly — one paper block linked to several code sites must yield ONE
  paper target, or the reader would stack duplicate highlights on the same text.

Agent-authored *analysis* links get real ``paper_target``/``code_target`` rows instead. Those
tables require an ``agent_analysis_artifact`` foreign key, which a manual relation has no
business inventing, so these ids are derived and never persisted as target rows.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlmodel import Session

from app.models.entities import CodeRepository, PaperDocument

MAX_QUOTE_CHARS = 3000
# "losses.py:42" or "losses.py:42-58" — annotation mode's line-range form.
CODE_RANGE_RE = re.compile(r"^(?P<path>.+):(?P<start>\d+)(?:-(?P<end>\d+))?$")


def manual_target_id(prefix: str, ref: str, quote: str) -> str:
    """Stable anchor id for one side of a by-reference relation."""

    normalized = " ".join(quote.split())
    digest = hashlib.sha256(f"{prefix}\x00{ref}\x00{normalized}".encode()).hexdigest()
    return f"{prefix}-manual-{digest[:24]}"


class UnresolvableAnchorError(ValueError):
    """A reference names something the current paper or repository does not contain.

    Raised instead of quietly storing the reference string as its own quote: such a relation
    can never be highlighted or quoted, and only surfaces as "it shows in the matrix but the
    panes stay blank" long after the fact.
    """

    def __init__(self, side: str, ref: str) -> None:
        super().__init__(f"{side}_reference_not_found: {ref}")
        self.side = side
        self.ref = ref


def paper_block_text(paper: PaperDocument, paper_ref: str) -> str:
    """Body text for a block id, searching page blocks before flat paragraphs."""

    for page in paper.pages_json or []:
        for block in page.get("blocks", []) or []:
            if isinstance(block, dict) and str(block.get("id")) == paper_ref:
                return str(block.get("text", "")).strip()
    for paragraph in paper.paragraphs_json or []:
        if str(paragraph.get("id")) == paper_ref:
            return str(paragraph.get("text", "")).strip()
    return ""


def _symbol_span(code: CodeRepository, code_ref: str) -> tuple[str, int, int] | None:
    """Resolve an indexed symbol id to (path, line_start, line_end)."""

    for symbol in code.symbols_json or []:
        if str(symbol.get("id")) != code_ref:
            continue
        path = str(symbol.get("path", ""))
        start = int(symbol.get("line_start") or symbol.get("line") or 1)
        end = int(symbol.get("line_end") or start)
        return path, start, max(start, end)
    return None


def code_span_quote(
    session: Session,
    project_id: int,
    code: CodeRepository,
    code_ref: str,
) -> tuple[str, str | None, int | None, int | None]:
    """Resolve a code reference to (quote, path, line_start, line_end).

    Accepts either a ``path:start-end`` line range (annotation mode, where a user may select
    rows no indexed symbol covers) or an indexed symbol id (what the Agent tool passes).
    Returns an empty quote and a null path when the reference is neither, leaving the caller
    to fall back to quoting the reference itself.
    """

    from app.services import workspace_service

    path: str | None = None
    start: int | None = None
    end: int | None = None

    match = CODE_RANGE_RE.match(code_ref)
    if match is not None:
        path = match.group("path")
        start = int(match.group("start"))
        end = int(match.group("end") or start)
    else:
        resolved = _symbol_span(code, code_ref)
        if resolved is not None:
            path, start, end = resolved
        elif any(str(entry.get("path")) == code_ref for entry in code.file_tree_json or []):
            # A bare file path: anchor the whole file's first line rather than nothing.
            path, start, end = code_ref, 1, 1
        else:
            return "", None, None, None

    payload = workspace_service.get_code_file(session, project_id, path)
    if payload is None:
        return "", path, start, end
    lines = str(payload.get("content", "")).splitlines()
    if not lines:
        return "", path, start, end
    start = max(1, min(start or 1, len(lines)))
    end = max(start, min(end or start, len(lines)))
    return "\n".join(lines[start - 1 : end]).strip(), path, start, end


def build_reference_evidence(
    session: Session,
    project_id: int,
    paper: PaperDocument,
    code: CodeRepository,
    paper_ref: str,
    code_ref: str,
) -> list[dict[str, Any]]:
    """Both evidence sides for a by-reference relation, ready for ``evidence_json``.

    Returned as plain dicts so callers can either store them directly or validate them
    through ``TraceEvidence`` first.

    Raises :class:`UnresolvableAnchorError` when either reference names nothing that exists.
    """

    paper_quote = paper_block_text(paper, paper_ref)[:MAX_QUOTE_CHARS]
    if not paper_quote:
        raise UnresolvableAnchorError("paper", paper_ref)
    code_quote, path, line_start, line_end = code_span_quote(
        session, project_id, code, code_ref
    )
    if path is None:
        raise UnresolvableAnchorError("code", code_ref)
    # An empty quote is tolerated here (blank or unreadable line span); the path and line
    # window are what the code pane actually needs to place a mark.
    code_quote = (code_quote or code_ref)[:MAX_QUOTE_CHARS]
    return [
        {
            "side": "paper",
            "ref": paper_ref,
            "quote": paper_quote,
            # The decorator wraps the Nth raw match inside the block; a by-reference relation
            # always means the first (and for a whole-block quote, the only) one.
            "occurrence": 1,
            "target_id": manual_target_id("ptarget", paper_ref, paper_quote),
            "target_type": "method_text",
        },
        {
            "side": "code",
            "ref": code_ref,
            "quote": code_quote,
            "path": path,
            "line_start": line_start,
            "line_end": line_end,
            "occurrence": 1,
            "target_id": manual_target_id("ctarget", code_ref, code_quote),
            "role": "model_component",
        },
    ]
