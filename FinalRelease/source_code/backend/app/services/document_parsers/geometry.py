"""Page geometry recovered from MinerU's ``middle.json``.

MinerU emits block boxes in two different coordinate spaces, and keeping them apart
is the whole point of this module:

* ``content_list.json`` / ``content_list_v2.json`` carry a **block-level** ``bbox``
  that MinerU documents as "mapped to a range of 0-1000" per axis. That is enough to
  highlight a whole paragraph, but it cannot address a single sentence, and it does
  not include page dimensions.
* ``middle.json`` additionally carries ``page_size`` (``[width, height]``) plus the
  line and span boxes MinerU recovered, expressed in **raw PDF points** in that same
  page space.

Normalising the point-space line boxes against ``page_size`` puts both sources into
one 0-1 space, so the reader can multiply either by a rendered page's viewport and
get a rectangle that lands in the right place.

Origin: MinerU does not document the origin for ``middle.json``, but its own samples
put the first text block of a 792pt-tall page at ``y0 ≈ 62`` — i.e. top-left origin
with y increasing downward, matching PyMuPDF and matching the 0-1000 block boxes.
Both spaces are therefore treated as top-left/y-down.
"""

import re
from dataclasses import dataclass, field
from typing import Any

# Comparison key: keep only letters, digits and CJK. This deliberately discards the
# `$`, backslashes and whitespace that differ between a block's ``content_list`` text
# (which renders inline maths as `$x$`) and the raw span content in ``middle.json``,
# so the two can still be matched against each other.
_KEY_PATTERN = re.compile(r"[^0-9a-z一-鿿]+")

# How far ahead of the cursor we may look to re-sync when a block does not start at
# the expected line (captions, footnotes and table bodies reorder between the two files).
_RESYNC_WINDOW = 8

# A partial match is accepted only when it covers this much of the block's text;
# below it we prefer no line boxes at all and let the caller fall back to the block box.
_MIN_COVERAGE = 0.6


def text_key(value: str) -> str:
    """Reduce text to a comparison key that survives MinerU's formatting differences."""

    return _KEY_PATTERN.sub("", value.lower())


@dataclass(slots=True)
class LineBox:
    """One text line, with its box already normalised to 0-1 of the page."""

    text: str
    bbox: list[float]
    #: Cached ``text_key(text)``. Matching re-walks the same lines from several starting
    #: points, and re-running the regex each time dominated the cost on dense pages.
    key: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            self.key = text_key(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "bbox": self.bbox}


@dataclass(slots=True)
class PageGeometry:
    page_number: int
    width: float
    height: float
    lines: list[LineBox] = field(default_factory=list)


def _normalized_point_bbox(
    value: Any,
    width: float,
    height: float,
) -> list[float] | None:
    """Scale a point-space ``[x0, y0, x1, y1]`` into 0-1 of the page."""

    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    if width <= 0 or height <= 0:
        return None
    try:
        x0, y0, x1, y1 = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    # MinerU span boxes can slightly exceed their parent line box, so clamp rather
    # than assume containment.
    left, right = sorted((x0 / width, x1 / width))
    top, bottom = sorted((y0 / height, y1 / height))
    box = [left, top, right, bottom]
    return [round(min(1.0, max(0.0, item)), 6) for item in box]


def _span_content(span: Any) -> str:
    """Text of one span. Not every span has ``content`` (image/table spans do not)."""

    if not isinstance(span, dict):
        return ""
    content = span.get("content")
    if isinstance(content, str):
        return content
    return ""


def _line_text(line: dict[str, Any]) -> str:
    spans = line.get("spans")
    if not isinstance(spans, list):
        return ""
    return "".join(_span_content(span) for span in spans)


def _iter_lines(block: Any) -> list[dict[str, Any]]:
    """Collect lines from a ``para_blocks`` entry, descending into nested blocks.

    Level-1 blocks (table/image/chart, and list/code on the VLM backend) hold their
    lines inside a nested ``blocks`` list rather than directly.
    """

    if not isinstance(block, dict):
        return []
    collected: list[dict[str, Any]] = []
    lines = block.get("lines")
    if isinstance(lines, list):
        collected.extend(line for line in lines if isinstance(line, dict))
    nested = block.get("blocks")
    if isinstance(nested, list):
        for child in nested:
            collected.extend(_iter_lines(child))
    return collected


def _page_size(page: dict[str, Any]) -> tuple[float, float] | None:
    size = page.get("page_size")
    if not isinstance(size, list | tuple) or len(size) != 2:
        return None
    try:
        width, height = float(size[0]), float(size[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def extract_page_geometry(middle_json: Any) -> dict[int, PageGeometry]:
    """Build ``{1-based page number: PageGeometry}`` from a ``middle.json`` payload.

    Returns an empty mapping for anything unrecognised — geometry is an enhancement,
    never a parse requirement, so a missing or malformed ``middle.json`` must not
    fail the document.
    """

    if not isinstance(middle_json, dict):
        return {}
    pages = middle_json.get("pdf_info")
    if not isinstance(pages, list):
        return {}

    geometry: dict[int, PageGeometry] = {}
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        size = _page_size(page)
        if size is None:
            continue
        width, height = size
        try:
            page_number = int(page.get("page_idx", index)) + 1
        except (TypeError, ValueError):
            page_number = index + 1

        # Only ``para_blocks`` — ``discarded_blocks`` holds headers/footers/page numbers,
        # which the normalizer drops as auxiliary, so including them would desynchronise
        # the cursor used to match blocks to lines.
        blocks = page.get("para_blocks")
        if not isinstance(blocks, list):
            continue
        boxes: list[LineBox] = []
        for block in blocks:
            for line in _iter_lines(block):
                bbox = _normalized_point_bbox(line.get("bbox"), width, height)
                if bbox is None:
                    continue
                boxes.append(LineBox(text=_line_text(line), bbox=bbox))
        if boxes:
            geometry[page_number] = PageGeometry(
                page_number=page_number,
                width=width,
                height=height,
                lines=boxes,
            )
    return geometry


def _match_run(
    lines: list[LineBox],
    cursor: int,
    needle: str,
) -> tuple[int, int] | None:
    """Find the contiguous run of lines whose text spells out ``needle``.

    Both files list content in reading order, so matching walks forward from a cursor
    rather than searching the whole page — that keeps repeated boilerplate (a heading
    that recurs, a short caption) from binding to the wrong occurrence.
    """

    limit = min(len(lines), cursor + _RESYNC_WINDOW + 1)
    threshold = max(8, int(len(needle) * _MIN_COVERAGE))
    # A block cannot need more lines than its text has characters; the slack absorbs
    # interleaved image/table spans that carry no text.
    max_run = len(needle) + _RESYNC_WINDOW
    best: tuple[int, int, int] | None = None  # (coverage, start, end)

    for start in range(cursor, limit):
        accumulated = ""
        end = start
        while end < len(lines) and end - start < max_run:
            key = lines[end].key
            if not key:
                # Image/table spans carry no text; absorb them so they do not split a run.
                end += 1
                continue
            candidate = accumulated + key
            if not needle.startswith(candidate):
                break
            accumulated = candidate
            end += 1
            # An exact match is unambiguous — take it over any partial found earlier.
            if accumulated == needle:
                return start, end
        coverage = len(accumulated)
        if coverage >= threshold and (best is None or coverage > best[0]):
            best = (coverage, start, end)

    # No exact match anywhere in the window: fall back to the best partial rather than the
    # first one, so a block sharing a prefix with a preceding caption cannot capture it and
    # drag the cursor past the lines the block actually occupies.
    if best is not None:
        return best[1], best[2]
    return None


def assign_line_boxes(blocks: list[Any], geometry: PageGeometry | None) -> None:
    """Attach line boxes to each block of one page, in place.

    ``blocks`` must be the page's blocks in reading order. Blocks that cannot be
    matched keep an empty ``lines`` list, and the reader falls back to their
    block-level box.
    """

    if geometry is None:
        return
    for block in blocks:
        # Recorded even when no lines match, so the reader can still verify that the page
        # it rendered has the dimensions these boxes were measured against.
        block.page_size = [geometry.width, geometry.height]
    if not geometry.lines:
        return
    cursor = 0
    for block in blocks:
        needle = text_key(getattr(block, "text", "") or "")
        if not needle:
            continue
        matched = _match_run(geometry.lines, cursor, needle)
        if matched is None:
            continue
        start, end = matched
        block.lines = [line.to_dict() for line in geometry.lines[start:end]]
        cursor = end
