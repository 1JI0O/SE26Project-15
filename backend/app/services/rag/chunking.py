"""Turn papers, code, and confirmed traces into retrieval chunks.

Each builder returns plain dicts (``ref``, ``text``, ``metadata``) so the indexer stays
agnostic about where a chunk came from. Two rules apply everywhere:

* ``ref`` must be an id the agent can feed straight back into an existing read tool
  (``get_paper_block``, ``get_symbol_source``, a trace id). Retrieval is a navigation aid —
  the agent still reads and quotes the real evidence before publishing.
* ``text`` is the *embedding surface*, which is not the same as the text shown back. Section
  path and symbol signature are folded into it because they carry topical signal.
"""

from __future__ import annotations

from typing import Any

# Paper blocks below this length ("Figure 3.", a stray header) carry no retrievable meaning.
MIN_BLOCK_CHARS = 24
MAX_CHUNK_CHARS = 2000
# Long blocks are split into overlapping windows so a match near a boundary is not lost.
WINDOW_OVERLAP_CHARS = 200


def _section_path(block: dict[str, Any]) -> list[str]:
    raw = block.get("section_path")
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    title = block.get("section_title") or block.get("section")
    return [str(title)] if title else []


def _windows(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    windows: list[str] = []
    start = 0
    while start < len(text):
        windows.append(text[start : start + MAX_CHUNK_CHARS])
        start += MAX_CHUNK_CHARS - WINDOW_OVERLAP_CHARS
    return windows


def paper_chunks(paper: Any) -> list[dict[str, Any]]:
    """Chunk a parsed paper, preferring MinerU page blocks over flat paragraphs.

    MinerU blocks are already semantically segmented (paragraph / equation / table / figure
    caption) and carry page and bbox metadata, which is exactly the granularity retrieval
    wants — so no re-segmentation is done beyond windowing over-long blocks.
    """

    blocks: list[dict[str, Any]] = []
    for page in paper.pages_json or []:
        for block in page.get("blocks", []) or []:
            if isinstance(block, dict) and block.get("id"):
                blocks.append(block)
    if not blocks:
        blocks = [dict(item) for item in (paper.paragraphs_json or []) if item.get("id")]

    chunks: list[dict[str, Any]] = []
    for block in blocks:
        text = str(block.get("text", "")).strip()
        if len(text) < MIN_BLOCK_CHARS:
            continue
        ref = str(block.get("id", ""))
        if not ref:
            continue
        section_path = _section_path(block)
        kind = str(block.get("kind") or block.get("type") or "text")
        section_label = " / ".join(section_path)
        for index, window in enumerate(_windows(text)):
            chunks.append(
                {
                    "ref": ref,
                    # Section path is prepended so a query about "the loss function" reaches
                    # blocks inside a "Loss" section even when the body never repeats the word.
                    "text": f"{section_label}\n{window}" if section_label else window,
                    "metadata": {
                        "kind": kind,
                        "page": block.get("page"),
                        "section_path": section_path,
                        "window": index,
                        "preview": window[:600],
                    },
                }
            )
    return chunks


def _symbol_signature(symbol: dict[str, Any]) -> str:
    parts = [
        str(symbol.get("qualified_name") or symbol.get("name") or ""),
        str(symbol.get("signature", "")),
        str(symbol.get("docstring", "")),
    ]
    calls = symbol.get("calls", [])
    if isinstance(calls, list):
        names = [
            str(call.get("name", "")) if isinstance(call, dict) else str(call)
            for call in calls[:20]
        ]
        parts.append(" ".join(name for name in names if name))
    return "\n".join(part for part in parts if part)


def code_chunks(repository: Any, read_source: Any = None) -> list[dict[str, Any]]:
    """Chunk indexed code symbols, enriching each with call context.

    A bare function body embeds poorly: the identifying signal for "is this the attention
    implementation" is spread across name, signature, docstring, callees, and file path. All
    of it goes into one chunk per symbol. When ``read_source`` is supplied, a slice of real
    source is appended — that is where tensor ops and formulas actually appear.
    """

    chunks: list[dict[str, Any]] = []
    for symbol in repository.symbols_json or []:
        ref = str(symbol.get("id", ""))
        if not ref:
            continue
        kind = str(symbol.get("kind", ""))
        if kind in {"import", "variable"}:
            continue
        path = str(symbol.get("path", ""))
        line_start = int(symbol.get("line_start") or symbol.get("line") or 1)
        line_end = int(symbol.get("line_end") or line_start)
        body = ""
        if read_source is not None and line_end >= line_start:
            try:
                body = read_source(path, line_start, line_end)
            except Exception:  # noqa: BLE001 - unreadable file must not fail the whole index
                body = ""
        surface = "\n".join(part for part in (path, _symbol_signature(symbol), body) if part)
        if len(surface.strip()) < 8:
            continue
        chunks.append(
            {
                "ref": ref,
                "text": surface[:MAX_CHUNK_CHARS],
                "metadata": {
                    "path": path,
                    "kind": kind,
                    "name": symbol.get("qualified_name") or symbol.get("name"),
                    "line_start": line_start,
                    "line_end": line_end,
                    "preview": _symbol_signature(symbol)[:600],
                },
            }
        )
    return chunks


def trace_chunks(links: list[Any]) -> list[dict[str, Any]]:
    """Chunk reviewed trace links into reusable few-shot cases.

    Only human-reviewed links are worth recalling as precedent, and both verdicts are useful:
    an accepted case shows what a defensible relation looks like, a rejected one shows a
    lexical near-miss that did *not* hold up. The embedding surface is the paper side plus
    the code side, so recall works from either direction.
    """

    chunks: list[dict[str, Any]] = []
    for link in links:
        paper_quote = ""
        code_quote = ""
        for evidence in link.evidence_json or []:
            if not isinstance(evidence, dict):
                continue
            side = evidence.get("side")
            quote = str(evidence.get("quote", "")).strip()
            if side == "paper" and not paper_quote:
                paper_quote = quote
            elif side == "code" and not code_quote:
                code_quote = quote
        if not paper_quote and not code_quote:
            continue
        surface = "\n".join(
            part
            for part in (
                paper_quote,
                str(link.code_ref or ""),
                code_quote,
                str(link.rationale or ""),
            )
            if part
        )
        chunks.append(
            {
                "ref": str(link.trace_id),
                "text": surface[:MAX_CHUNK_CHARS],
                "metadata": {
                    "status": link.status,
                    "relation_type": link.relation_type,
                    "paper_ref": link.paper_ref,
                    "code_ref": link.code_ref,
                    "paper_quote": paper_quote[:600],
                    "code_quote": code_quote[:600],
                    "rationale": str(link.rationale or "")[:600],
                    "confidence": link.confidence,
                },
            }
        )
    return chunks
