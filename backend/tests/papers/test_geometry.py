"""Geometry recovered from MinerU's middle.json.

The two MinerU coordinate spaces are easy to confuse — content_list boxes are 0-1000 per
axis, middle.json boxes are raw PDF points — so these tests pin the conversion and the
block-to-line matching that sentence-level PDF highlighting depends on.
"""

from app.services.document_parsers.geometry import (
    LineBox,
    PageGeometry,
    assign_line_boxes,
    extract_page_geometry,
    text_key,
)
from app.services.document_parsers.models import PaperBlock
from app.services.document_parsers.normalizer import normalize_mineru_payload


def _line(text: str, bbox: list[float]) -> dict[str, object]:
    return {"bbox": bbox, "spans": [{"type": "text", "content": text, "bbox": bbox}]}


def _middle_json() -> dict[str, object]:
    # US Letter, matching MinerU's own documentation sample.
    return {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [612.0, 792.0],
                "para_blocks": [
                    {
                        "type": "text",
                        "bbox": [61.2, 79.2, 550.8, 158.4],
                        "lines": [
                            _line("We study residual ", [61.2, 79.2, 550.8, 118.8]),
                            _line("learning for images.", [61.2, 118.8, 550.8, 158.4]),
                        ],
                    }
                ],
            }
        ]
    }


def test_extract_normalizes_point_boxes_against_page_size() -> None:
    geometry = extract_page_geometry(_middle_json())

    page = geometry[1]
    assert (page.width, page.height) == (612.0, 792.0)
    # 61.2/612 = 0.1, 79.2/792 = 0.1, 550.8/612 = 0.9, 118.8/792 = 0.15
    assert page.lines[0].bbox == [0.1, 0.1, 0.9, 0.15]
    assert page.lines[1].bbox == [0.1, 0.15, 0.9, 0.2]


def test_extract_clamps_and_orders_degenerate_boxes() -> None:
    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [100.0, 100.0],
                # Reversed corners and an overshoot: MinerU span boxes can exceed their
                # parent line box, so values are ordered and clamped rather than trusted.
                "para_blocks": [{"type": "text", "lines": [_line("x", [90, 60, 10, 120])]}],
            }
        ]
    }

    assert extract_page_geometry(payload)[1].lines[0].bbox == [0.1, 0.6, 0.9, 1.0]


def test_extract_page_number_is_one_based_from_page_idx() -> None:
    payload = {
        "pdf_info": [
            {
                "page_idx": 4,
                "page_size": [10.0, 10.0],
                "para_blocks": [{"lines": [_line("a", [0, 0, 5, 5])]}],
            }
        ]
    }

    assert list(extract_page_geometry(payload)) == [5]


def test_extract_descends_into_nested_table_blocks() -> None:
    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [100.0, 100.0],
                "para_blocks": [
                    {
                        "type": "table",
                        "bbox": [0, 0, 100, 100],
                        "blocks": [
                            {
                                "type": "table_caption",
                                "lines": [_line("Table 1", [10, 10, 90, 20])],
                            },
                        ],
                    }
                ],
            }
        ]
    }

    assert [line.text for line in extract_page_geometry(payload)[1].lines] == ["Table 1"]


def test_extract_ignores_discarded_blocks() -> None:
    """Headers/footers live in discarded_blocks and are dropped by the normalizer too.

    Including them would shift the cursor the block matcher walks, misaligning every
    subsequent block on the page.
    """

    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [100.0, 100.0],
                "para_blocks": [{"lines": [_line("body", [10, 50, 90, 60])]}],
                "discarded_blocks": [{"lines": [_line("running header", [10, 5, 90, 12])]}],
            }
        ]
    }

    assert [line.text for line in extract_page_geometry(payload)[1].lines] == ["body"]


def test_extract_tolerates_malformed_payloads() -> None:
    # Geometry is an enhancement; a bad middle.json must degrade, never raise.
    assert extract_page_geometry(None) == {}
    assert extract_page_geometry({"pdf_info": "nope"}) == {}
    assert extract_page_geometry({"pdf_info": [{"page_idx": 0}]}) == {}
    assert extract_page_geometry({"pdf_info": [{"page_size": [0, 0], "para_blocks": []}]}) == {}


def test_text_key_bridges_markdown_and_span_formatting() -> None:
    # The same sentence as MinerU renders it in markdown vs. in raw spans.
    assert text_key("We show $\\alpha$ = 1.") == text_key("We  show \\alpha = 1 .")


def test_assign_line_boxes_matches_blocks_in_reading_order() -> None:
    geometry = extract_page_geometry(_middle_json())[1]
    block = PaperBlock(
        id="p1-b1",
        kind="paragraph",
        text="We study residual learning for images.",
        page_number=1,
    )

    assign_line_boxes([block], geometry)

    assert [line["bbox"] for line in block.lines] == [
        [0.1, 0.1, 0.9, 0.15],
        [0.1, 0.15, 0.9, 0.2],
    ]


def test_assign_line_boxes_advances_cursor_between_blocks() -> None:
    """Repeated text must bind to its own occurrence, not the first one on the page."""

    geometry = PageGeometry(
        page_number=1,
        width=100,
        height=100,
        lines=[
            LineBox("Introduction", [0, 0, 1, 0.1]),
            LineBox("Introduction", [0, 0.5, 1, 0.6]),
        ],
    )
    first = PaperBlock(id="a", kind="title", text="Introduction", page_number=1)
    second = PaperBlock(id="b", kind="title", text="Introduction", page_number=1)

    assign_line_boxes([first, second], geometry)

    assert first.lines[0]["bbox"] == [0, 0, 1, 0.1]
    assert second.lines[0]["bbox"] == [0, 0.5, 1, 0.6]


def test_assign_line_boxes_resyncs_past_unmatched_lines() -> None:
    geometry = PageGeometry(
        page_number=1,
        width=100,
        height=100,
        lines=[
            LineBox("unrelated caption text", [0, 0, 1, 0.1]),
            LineBox("the paragraph we want", [0, 0.2, 1, 0.3]),
        ],
    )
    block = PaperBlock(id="a", kind="paragraph", text="the paragraph we want", page_number=1)

    assign_line_boxes([block], geometry)

    assert block.lines[0]["bbox"] == [0, 0.2, 1, 0.3]


def test_assign_line_boxes_leaves_unmatched_blocks_empty() -> None:
    """No match must mean no lines, so the reader falls back to the block box."""

    geometry = PageGeometry(
        page_number=1,
        width=100,
        height=100,
        lines=[LineBox("completely different content", [0, 0, 1, 0.1])],
    )
    block = PaperBlock(id="a", kind="paragraph", text="nothing like the line above", page_number=1)

    assign_line_boxes([block], geometry)

    assert block.lines == []


def test_assign_line_boxes_prefers_an_exact_match_over_an_earlier_partial() -> None:
    """A caption sharing a long prefix must not capture the paragraph's lines.

    Binding to the earlier partial would also drag the cursor past the real lines, so
    every later block on the page would be misplaced too.
    """

    wanted = "results for the residual network"
    geometry = PageGeometry(
        page_number=1,
        width=100,
        height=100,
        lines=[
            # A strong partial: a prefix of the block, but the run dies on the next line.
            LineBox("results for the residual", [0, 0, 1, 0.1]),
            LineBox("unrelated caption tail", [0, 0.1, 1, 0.2]),
            LineBox(wanted, [0, 0.5, 1, 0.6]),
        ],
    )
    block = PaperBlock(id="a", kind="paragraph", text=wanted, page_number=1)

    assign_line_boxes([block], geometry)

    assert [line["bbox"] for line in block.lines] == [[0, 0.5, 1, 0.6]]


def test_assign_line_boxes_records_page_size_even_without_a_line_match() -> None:
    """The reader needs the page shape to validate geometry, match or no match."""

    geometry = PageGeometry(
        page_number=1,
        width=612,
        height=792,
        lines=[LineBox("something else entirely", [0, 0, 1, 0.1])],
    )
    block = PaperBlock(id="a", kind="paragraph", text="unmatchable block text", page_number=1)

    assign_line_boxes([block], geometry)

    assert block.lines == []
    assert block.page_size == [612, 792]


def test_assign_line_boxes_without_geometry_is_a_noop() -> None:
    block = PaperBlock(id="a", kind="paragraph", text="text", page_number=1)

    assign_line_boxes([block], None)

    assert block.lines == []
    assert block.page_size is None


def test_normalizer_attaches_line_boxes_from_folded_middle_json() -> None:
    """End to end: the two coordinate spaces must agree after normalization.

    The block box arrives as 0-1000 and the line boxes as PDF points, yet both must come
    out as fractions of the same page.
    """

    payload = {
        "content_list": [
            {
                "type": "paragraph",
                "content": {"paragraph_content": "We study residual learning for images."},
                "bbox": [100, 100, 900, 200],
                "page_idx": 0,
            }
        ],
        "middle_json": _middle_json(),
    }

    result = normalize_mineru_payload(
        payload,
        filename="paper.pdf",
        parser_version="test",
    ).to_dict()

    block = result["pages"][0]["blocks"][0]
    assert block["bbox"] == [0.1, 0.1, 0.9, 0.2]
    assert [line["bbox"] for line in block["lines"]] == [
        [0.1, 0.1, 0.9, 0.15],
        [0.1, 0.15, 0.9, 0.2],
    ]


def test_normalizer_without_middle_json_keeps_blocks_line_free() -> None:
    payload = [
        {
            "type": "paragraph",
            "content": {"paragraph_content": "Only a content list here."},
            "bbox": [100, 100, 900, 200],
            "page_idx": 0,
        }
    ]

    result = normalize_mineru_payload(payload, filename="p.pdf", parser_version="test").to_dict()

    assert result["pages"][0]["blocks"][0]["lines"] == []
