import hashlib
import html
import re
from typing import Any

from app.models.entities import PaperDocument

_HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_MARKUP_PATTERN = re.compile(r"(?:[*_`~]|<[^>]+>)")
_NUMBERED_HEADING_PATTERN = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")


def _plain_heading(value: str) -> str:
    return html.unescape(_MARKUP_PATTERN.sub("", value)).strip()


def build_fallback_markdown(document: PaperDocument) -> str:
    lines = [f"# {document.title or document.filename}", ""]
    if document.abstract:
        lines.extend(["## Abstract", "", document.abstract, ""])

    sections_by_page: dict[int, list[dict[str, Any]]] = {}
    for section in document.sections_json:
        page = int(section.get("page", 1))
        sections_by_page.setdefault(page, []).append(section)

    paragraphs_by_page: dict[int, list[dict[str, Any]]] = {}
    for paragraph in document.paragraphs_json:
        page = int(paragraph.get("page", 1))
        paragraphs_by_page.setdefault(page, []).append(paragraph)

    pages = sorted(set(sections_by_page) | set(paragraphs_by_page))
    for page in pages:
        for section in sections_by_page.get(page, []):
            title = str(section.get("title", "")).strip()
            if title and title != document.title:
                level = max(2, min(6, int(section.get("level", 2) or 2)))
                lines.extend([f"{'#' * level} {title}", ""])
        for paragraph in paragraphs_by_page.get(page, []):
            text = str(paragraph.get("text", "")).strip()
            if text and text != document.abstract:
                lines.extend([text, ""])
    return "\n".join(lines).strip()


def extract_markdown_sections(
    markdown: str,
    fallback_sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fallback_pages: dict[str, int] = {}
    for section in fallback_sections:
        title = _plain_heading(str(section.get("title", "")))
        if title:
            fallback_pages.setdefault(title.casefold(), int(section.get("page", 1)))

    sections: list[dict[str, Any]] = []
    for index, match in enumerate(_HEADING_PATTERN.finditer(markdown), start=1):
        title = _plain_heading(match.group(2))
        if not title:
            continue
        markdown_level = len(match.group(1))
        numbered = _NUMBERED_HEADING_PATTERN.match(title)
        inferred_level = numbered.group(1).count(".") + 2 if numbered else markdown_level
        sections.append(
            {
                "id": f"section-{index}",
                "title": title[:300],
                "level": max(markdown_level, min(6, inferred_level)),
                "page": fallback_pages.get(title.casefold()),
            }
        )
    return sections


def _normalized_index(markdown: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to single spaces, keeping each kept char's original offset.

    Lets block text be located in the served markdown even when spacing, line wrapping, or
    indentation differ from the normalized block ``text`` — the exact ``str.find`` used before
    missed those blocks, leaving them without a DOM anchor for hover/scroll.
    """

    chars: list[str] = []
    offsets: list[int] = []
    prev_space = False
    for index, char in enumerate(markdown):
        if char.isspace():
            if prev_space:
                continue
            chars.append(" ")
            offsets.append(index)
            prev_space = True
        else:
            chars.append(char)
            offsets.append(index)
            prev_space = False
    offsets.append(len(markdown))  # sentinel for end-of-match mapping
    return "".join(chars), offsets


def _math_safe_line_start(markdown: str, start: int) -> int:
    """Return an insertion offset at a line boundary that is never inside a math region.

    Snaps back to the start of ``start``'s line; if the immediately preceding line is a lone
    display-math opener (``$$``), snaps above that too, so a display formula rendered as::

        $$
        \\frac{a}{b}
        $$

    keeps its delimiters intact instead of receiving the anchor span between ``$$`` and the
    LaTeX (which breaks KaTeX and destroys the anchor).
    """

    line_start = markdown.rfind("\n", 0, start) + 1
    prev_end = line_start - 1  # index of the newline terminating the previous line
    if prev_end > 0:
        prev_start = markdown.rfind("\n", 0, prev_end) + 1
        if markdown[prev_start:prev_end].strip() == "$$":
            return prev_start
    return line_start


def inject_block_anchors(
    markdown: str,
    pages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Inject stable anchors before MinerU block text (whitespace-tolerant match)."""

    blocks = [
        dict(block)
        for page in pages
        for block in page.get("blocks", [])
        if isinstance(block, dict) and block.get("id") and block.get("text")
    ]
    if not blocks:
        return markdown, []
    norm_md, offsets = _normalized_index(markdown)
    insertions: list[tuple[int, str]] = []
    norm_cursor = 0
    enriched: list[dict[str, Any]] = []
    used_anchors: set[str] = set()
    for block in blocks:
        block_id = str(block["id"])
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", block_id).strip("-")
        anchor = f"paper-block-{safe or hashlib.sha256(block_id.encode()).hexdigest()[:12]}"
        if anchor in used_anchors:
            anchor = f"{anchor}-{hashlib.sha256(block_id.encode()).hexdigest()[:8]}"
        used_anchors.add(anchor)
        needle = " ".join(str(block.get("text", "")).split())
        # The anchor only needs the block's START offset. Block text often embeds inline math
        # (raw LaTeX in `text`, but `$…$` in the markdown), so the full string rarely matches;
        # progressively shorter leading prefixes locate the plain-text start of the block.
        prefixes = [needle, needle[:120], needle[:60], needle[:40], needle[:24]] if needle else []
        np = -1
        match_len = 0
        for prefix in prefixes:
            if len(prefix) < 12:
                break
            np = norm_md.find(prefix, norm_cursor)
            if np < 0:  # out-of-order block: search from the top
                np = norm_md.find(prefix, 0)
            if np >= 0:
                match_len = len(prefix)
                break
        resolved = np >= 0
        if resolved:
            match_len = min(match_len, len(norm_md) - np)
            start = offsets[np]
            end = offsets[min(np + match_len, len(offsets) - 1)]
            if block.get("kind") == "title":
                anchor_position = end
            else:
                # Place the anchor at the start of the block's markdown line, on its own line,
                # so it is never injected inside inline `$…$` or display `$$…$$` math (which
                # KaTeX would otherwise swallow, breaking both the formula and the anchor).
                anchor_position = _math_safe_line_start(markdown, start)
            insertions.append(
                (
                    anchor_position,
                    f'<span id="{anchor}" data-paper-block-id="{html.escape(block_id)}"></span>\n',
                )
            )
            norm_cursor = np + max(match_len, 1)
        block.update(
            render_anchor=anchor,
            anchor_resolved=resolved,
            page=block.get("page_number", block.get("page", 1)),
        )
        enriched.append(block)
    for position, value in sorted(insertions, key=lambda item: item[0], reverse=True):
        markdown = f"{markdown[:position]}{value}{markdown[position:]}"
    return markdown, enriched
