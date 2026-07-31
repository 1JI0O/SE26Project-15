"""Export MinerU markdown + assets for the VS Code paper reader."""

from __future__ import annotations

import hashlib
import html
import io
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from tracelab_core.workspace import TraceLabPaths, write_json

_HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_MARKUP_PATTERN = re.compile(r"(?:[*_`~]|<[^>]+>)")
_NUMBERED_HEADING_PATTERN = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")


def _plain_heading(value: str) -> str:
    return html.unescape(_MARKUP_PATTERN.sub("", value)).strip()


def build_fallback_markdown(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "Paper")
    lines = [f"# {title}", ""]
    abstract = str(document.get("abstract") or "").strip()
    if abstract:
        lines.extend(["## Abstract", "", abstract, ""])

    sections_by_page: dict[int, list[dict[str, Any]]] = {}
    for section in document.get("sections") or []:
        page = int(section.get("page", 1))
        sections_by_page.setdefault(page, []).append(section)

    paragraphs_by_page: dict[int, list[dict[str, Any]]] = {}
    for paragraph in document.get("paragraphs") or []:
        page = int(paragraph.get("page", 1))
        paragraphs_by_page.setdefault(page, []).append(paragraph)

    for page in sorted(set(sections_by_page) | set(paragraphs_by_page)):
        for section in sections_by_page.get(page, []):
            heading = str(section.get("title", "")).strip()
            if heading and heading != title:
                level = max(2, min(6, int(section.get("level", 2) or 2)))
                lines.extend([f"{'#' * level} {heading}", ""])
        for paragraph in paragraphs_by_page.get(page, []):
            text = str(paragraph.get("text", "")).strip()
            if text and text != abstract:
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
    offsets.append(len(markdown))
    return "".join(chars), offsets


def _math_safe_line_start(markdown: str, start: int) -> int:
    line_start = markdown.rfind("\n", 0, start) + 1
    prev_end = line_start - 1
    if prev_end > 0:
        prev_start = markdown.rfind("\n", 0, prev_end) + 1
        if markdown[prev_start:prev_end].strip() == "$$":
            return prev_start
    return line_start


def inject_block_anchors(
    markdown: str,
    pages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    blocks = [
        dict(block)
        for page in pages
        for block in page.get("blocks", [])
        if isinstance(block, dict) and block.get("id") and block.get("text")
    ]
    if not blocks:
        # Fall back to paragraphs as blocks when pages lack geometry blocks.
        for paragraph in []:
            pass
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
        prefixes = [needle, needle[:120], needle[:60], needle[:40], needle[:24]] if needle else []
        np = -1
        match_len = 0
        for prefix in prefixes:
            if len(prefix) < 12:
                break
            np = norm_md.find(prefix, norm_cursor)
            if np < 0:
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


def extract_markdown_and_assets(raw_archive: bytes | None, assets_dir: Path) -> str | None:
    if not raw_archive:
        return None
    assets_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(raw_archive)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            md_candidates = [name for name in names if name.lower().endswith(".md")]
            markdown = None
            if md_candidates:
                preferred = min(md_candidates, key=lambda name: (name.count("/"), len(name)))
                markdown = archive.read(preferred).decode("utf-8", errors="replace")
            for name in names:
                lower = name.lower()
                if not lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")):
                    continue
                posix = name.replace("\\", "/")
                filename = Path(posix).name
                if "images/" in posix:
                    # Keep relative path after images/ when possible
                    rel = posix.split("images/", 1)[-1]
                    out = assets_dir / "images" / rel
                else:
                    out = assets_dir / "images" / filename
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(archive.read(name))
            return markdown
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, KeyError):
        return None


def paragraphs_as_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for page in document.get("pages") or []:
        page_blocks = page.get("blocks") or []
        if page_blocks:
            for block in page_blocks:
                if isinstance(block, dict) and block.get("id"):
                    blocks.append(dict(block))
            continue
        for anchor in page.get("anchors") or []:
            if isinstance(anchor, dict) and anchor.get("id"):
                blocks.append(
                    {
                        "id": anchor["id"],
                        "kind": anchor.get("type", "paragraph"),
                        "text": anchor.get("text", ""),
                        "page_number": anchor.get("page", page.get("page_number", 1)),
                        "bbox": anchor.get("bbox"),
                        "lines": [],
                        "page_size": None,
                    }
                )
    if blocks:
        return blocks
    for paragraph in document.get("paragraphs") or []:
        blocks.append(
            {
                "id": paragraph.get("id") or f"paragraph:{len(blocks) + 1}",
                "kind": "paragraph",
                "text": paragraph.get("text", ""),
                "page_number": paragraph.get("page", 1),
                "bbox": paragraph.get("bbox"),
                "lines": [],
                "page_size": None,
            }
        )
    return blocks


def export_paper_reader_artifacts(
    paths: TraceLabPaths,
    document: dict[str, Any],
    *,
    raw_archive: bytes | None = None,
    source: str = "normalized-fallback",
) -> dict[str, Any]:
    """Write document.md, assets/, paper_document.json for the VS Code reader."""
    if paths.paper_assets_dir.exists():
        shutil.rmtree(paths.paper_assets_dir)
    paths.paper_assets_dir.mkdir(parents=True, exist_ok=True)

    markdown = extract_markdown_and_assets(raw_archive, paths.paper_assets_dir)
    if not markdown:
        markdown = build_fallback_markdown(document)
        source = "normalized-fallback"

    pages = document.get("pages") or []
    # Ensure pages carry blocks for anchor injection.
    if pages and not any(page.get("blocks") for page in pages):
        by_page: dict[int, list[dict[str, Any]]] = {}
        for block in paragraphs_as_blocks(document):
            page_no = int(block.get("page_number") or block.get("page") or 1)
            by_page.setdefault(page_no, []).append(block)
        for page in pages:
            page_no = int(page.get("page_number", 1))
            page["blocks"] = by_page.get(page_no, [])

    markdown, blocks = inject_block_anchors(markdown, pages)
    if not blocks:
        blocks = paragraphs_as_blocks(document)
        for block in blocks:
            block_id = str(block["id"])
            safe = re.sub(r"[^A-Za-z0-9_-]+", "-", block_id).strip("-")
            block["render_anchor"] = f"paper-block-{safe}"
            block["anchor_resolved"] = False
            block["page"] = block.get("page_number", block.get("page", 1))

    sections = extract_markdown_sections(markdown, list(document.get("sections") or []))
    paths.document_md.write_text(markdown, encoding="utf-8")
    paper_document = {
        "title": document.get("title") or "Paper",
        "markdown": markdown,
        "sections": sections,
        "blocks": blocks,
        "source": source,
        "parser": document.get("parser"),
        "parser_version": document.get("parser_version"),
    }
    write_json(paths.paper_document_json, paper_document)
    return paper_document
