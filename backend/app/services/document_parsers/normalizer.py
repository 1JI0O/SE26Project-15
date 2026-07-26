from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.services.document_parsers.geometry import (
    PageGeometry,
    assign_line_boxes,
    extract_page_geometry,
)
from app.services.document_parsers.models import PaperBlock, PaperPage, ParsedDocument

_AUXILIARY_TYPES = {
    "header",
    "footer",
    "page_header",
    "page_footer",
    "page_number",
    "page_aside_text",
}


def _span_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(_span_text(item) for item in value).strip()
    if isinstance(value, dict):
        if isinstance(value.get("content"), str):
            return str(value["content"]).strip()
        if "children" in value:
            return _span_text(value["children"])
        for key in ("text", "value"):
            if key in value:
                return _span_text(value[key])
    return ""


def _entry_text(entry: dict[str, Any]) -> str:
    content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
    block_type = str(entry.get("type", "text"))
    candidates: tuple[str, ...]
    if block_type == "title":
        candidates = ("title_content", "text")
    elif block_type == "paragraph":
        candidates = ("paragraph_content", "text")
    elif block_type in {"equation", "equation_interline"}:
        candidates = ("math_content", "text")
    elif block_type == "table":
        candidates = ("table_caption", "html", "table_body", "content", "text")
    elif block_type in {"image", "chart"}:
        candidates = ("image_caption", "chart_caption", "content", "text")
    elif block_type in {"code", "algorithm"}:
        candidates = ("code_content", "algorithm_content", "code_body", "text")
    elif block_type in {"list", "index"}:
        candidates = ("list_items", "text")
    else:
        candidates = ("text", "content")
    for key in candidates:
        if key in content:
            text = _span_text(content[key])
            if text:
                return text
    return ""


def _normalized_bbox(value: Any) -> list[float] | None:
    """Rescale a ``content_list`` block box into 0-1 of the page.

    MinerU documents these boxes as "mapped to a range of 0-1000" per axis, with a
    top-left origin — so the page's real dimensions are neither available here nor
    needed. The ``<= 1`` branch keeps already-normalised payloads (and test fixtures)
    passing through untouched.

    Note this is a *different* space from ``middle.json``, whose line boxes are in raw
    PDF points; those are normalised separately in ``geometry``.
    """

    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        coords = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    scale = 1000.0 if any(abs(item) > 1 for item in coords) else 1.0
    return [round(max(0.0, min(1.0, item / scale)), 6) for item in coords]


def _flatten_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        flattened: list[dict[str, Any]] = []
        for index, item in enumerate(payload):
            if isinstance(item, list):
                for child in _flatten_entries(item):
                    copy = dict(child)
                    copy.setdefault("page_idx", index)
                    flattened.append(copy)
                continue
            if not isinstance(item, dict):
                continue
            nested = item.get("content_list") or item.get("blocks") or item.get("items")
            if isinstance(nested, list):
                for child in nested:
                    if isinstance(child, dict):
                        copy = dict(child)
                        if "page_idx" in item:
                            copy.setdefault("page_idx", item["page_idx"])
                        else:
                            copy.setdefault("page_number", item.get("page_number", index + 1))
                        flattened.append(copy)
            else:
                flattened.append(item)
        return flattened
    if isinstance(payload, dict):
        for key in (
            "content_list_v2",
            "content_list",
            "result",
            "results",
            "data",
            "pages",
        ):
            if key in payload:
                entries = _flatten_entries(payload[key])
                if entries:
                    return entries
    return []


def _page_geometry(payload: Any) -> dict[int, PageGeometry]:
    """Line/page geometry from the ``middle.json`` the parser folded into the payload.

    Absent for documents parsed before geometry capture, and for the JSON (non-archive)
    MinerU response shape, in which case blocks simply keep no line boxes.
    """

    if isinstance(payload, dict):
        return extract_page_geometry(payload.get("middle_json"))
    return {}


def _page_number(entry: dict[str, Any]) -> int:
    raw = entry.get("page_idx", entry.get("page_number", 0))
    try:
        number = int(raw)
    except (TypeError, ValueError):
        number = 0
    if "page_idx" in entry:
        return number + 1
    return max(1, number)


def _title_level(entry: dict[str, Any]) -> int | None:
    content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
    raw = content.get("level", entry.get("text_level"))
    try:
        return max(1, int(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _section_path(current: list[str], title: str, level: int) -> list[str]:
    prefix = current[: max(0, level - 1)]
    prefix.append(title)
    return prefix


def normalize_mineru_payload(
    payload: Any,
    *,
    filename: str,
    parser_version: str,
) -> ParsedDocument:
    entries = _flatten_entries(payload)
    if not entries:
        raise ValueError("MinerU result does not contain a supported content list")

    blocks_by_page: dict[int, list[PaperBlock]] = {}
    sections: list[dict[str, Any]] = []
    paragraphs: list[dict[str, Any]] = []
    current_section: list[str] = []
    document_title = ""

    for index, entry in enumerate(entries, start=1):
        kind = str(entry.get("type", "text"))
        if kind in _AUXILIARY_TYPES:
            continue
        text = _entry_text(entry)
        if not text and kind not in {"image", "chart"}:
            continue
        page_number = _page_number(entry)
        level = _title_level(entry)
        if kind in {"title", "text"} and level is not None and text:
            current_section = _section_path(current_section, text, level)
            sections.append(
                {
                    "id": f"section:{len(sections) + 1}",
                    "title": text,
                    "level": level,
                    "page": page_number,
                }
            )
            if not document_title and level == 1:
                document_title = text

        block = PaperBlock(
            id=f"p{page_number}-b{index}",
            kind=kind,
            text=text,
            page_number=page_number,
            bbox=_normalized_bbox(entry.get("bbox")),
            section_path=list(current_section),
            metadata={
                key: entry[key] for key in ("sub_type", "text_format", "img_path") if key in entry
            },
        )
        blocks_by_page.setdefault(page_number, []).append(block)
        if kind in {"text", "paragraph", "list", "code", "algorithm"} and text:
            paragraphs.append(
                {
                    "id": block.id,
                    "page": page_number,
                    "text": text,
                    "kind": kind,
                    "bbox": block.bbox,
                    "section_path": block.section_path,
                }
            )

    if not blocks_by_page:
        raise ValueError("MinerU result contains no readable document blocks")

    # Blocks are in reading order within a page, as are middle.json's lines, so the
    # matcher can walk both forward together.
    geometry = _page_geometry(payload)
    for page_number, page_blocks in blocks_by_page.items():
        assign_line_boxes(page_blocks, geometry.get(page_number))

    title = document_title or next(
        (block.text for blocks in blocks_by_page.values() for block in blocks if block.text),
        Path(filename).stem,
    )
    abstract = _extract_abstract(paragraphs, sections)
    pages = [
        PaperPage(
            page_number=page_number,
            title=next(
                (section["title"] for section in sections if section["page"] == page_number),
                title if page_number == 1 else f"Page {page_number}",
            ),
            blocks=blocks_by_page[page_number],
        )
        for page_number in sorted(blocks_by_page)
    ]
    return ParsedDocument(
        parser="mineru",
        parser_version=parser_version,
        title=title[:500],
        abstract=abstract,
        pages=pages,
        sections=sections,
        paragraphs=paragraphs,
    )


def _extract_abstract(paragraphs: list[dict[str, Any]], sections: Iterable[dict[str, Any]]) -> str:
    abstract_pages = {
        int(section["page"])
        for section in sections
        if str(section.get("title", "")).strip().lower() == "abstract"
    }
    if abstract_pages:
        selected = [
            str(paragraph["text"])
            for paragraph in paragraphs
            if int(paragraph["page"]) in abstract_pages
        ]
        if selected:
            return " ".join(selected)[:2000]
    return " ".join(str(item["text"]) for item in paragraphs[:2])[:1000]
