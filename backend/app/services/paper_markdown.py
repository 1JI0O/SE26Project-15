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
