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


def inject_block_anchors(
    markdown: str,
    pages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Inject stable anchors before exact MinerU block text without changing the text itself."""

    blocks = [
        dict(block)
        for page in pages
        for block in page.get("blocks", [])
        if isinstance(block, dict) and block.get("id") and block.get("text")
    ]
    if not blocks:
        return markdown, []
    insertions: list[tuple[int, str]] = []
    cursor = 0
    enriched: list[dict[str, Any]] = []
    used_anchors: set[str] = set()
    for block in blocks:
        block_id = str(block["id"])
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", block_id).strip("-")
        anchor = f"paper-block-{safe or hashlib.sha256(block_id.encode()).hexdigest()[:12]}"
        if anchor in used_anchors:
            anchor = f"{anchor}-{hashlib.sha256(block_id.encode()).hexdigest()[:8]}"
        used_anchors.add(anchor)
        text = str(block.get("text", "")).strip()
        position = markdown.find(text, cursor) if text else -1
        if position < 0 and len(text) >= 40:
            position = markdown.find(text[: min(120, len(text))], cursor)
        resolved = position >= 0
        if resolved:
            anchor_position = position + len(text) if block.get("kind") == "title" else position
            insertions.append(
                (
                    anchor_position,
                    f'<span id="{anchor}" data-paper-block-id="{html.escape(block_id)}"></span>\n',
                )
            )
            cursor = position + max(len(text), 1)
        block.update(
            render_anchor=anchor,
            anchor_resolved=resolved,
            page=block.get("page_number", block.get("page", 1)),
        )
        enriched.append(block)
    for position, value in reversed(insertions):
        markdown = f"{markdown[:position]}{value}{markdown[position:]}"
    return markdown, enriched
