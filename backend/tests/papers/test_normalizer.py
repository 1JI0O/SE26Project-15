from app.services.document_parsers.normalizer import normalize_mineru_payload


def test_normalize_mineru_content_list_preserves_pages_sections_and_anchors() -> None:
    payload = [
        {
            "type": "title",
            "content": {"title_content": [{"content": "Residual Learning"}], "level": 1},
            "bbox": [100, 50, 900, 120],
            "page_idx": 0,
        },
        {
            "type": "title",
            "content": {"title_content": "Abstract", "level": 2},
            "bbox": [100, 150, 300, 190],
            "page_idx": 0,
        },
        {
            "type": "paragraph",
            "content": {"paragraph_content": "We study residual learning."},
            "bbox": [100, 210, 900, 300],
            "page_idx": 0,
        },
        {
            "type": "equation_interline",
            "content": {"math_content": "y = F(x) + x", "math_type": "latex"},
            "bbox": [200, 100, 800, 180],
            "page_idx": 1,
        },
        {
            "type": "table",
            "table_caption": ["Table 1 Accuracy"],
            "table_body": "<table></table>",
            "bbox": [100, 220, 900, 700],
            "page_idx": 1,
        },
    ]

    document = normalize_mineru_payload(
        payload,
        filename="paper.pdf",
        parser_version="3-test",
    )
    result = document.to_dict()

    assert result["title"] == "Residual Learning"
    assert "residual learning" in result["abstract"].lower()
    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert result["pages"][0]["blocks"][0]["bbox"] == [0.1, 0.05, 0.9, 0.12]
    assert any(anchor["type"] == "equation_interline" for anchor in result["pages"][1]["anchors"])
    assert any(anchor["type"] == "table" for anchor in result["pages"][1]["anchors"])
    assert result["paragraphs"][0]["section_path"] == ["Residual Learning", "Abstract"]


def test_normalize_rejects_empty_or_unknown_payload() -> None:
    try:
        normalize_mineru_payload({}, filename="paper.pdf", parser_version="test")
    except ValueError as exc:
        assert "content list" in str(exc)
    else:
        raise AssertionError("Expected unsupported MinerU payload to fail")


def test_normalize_real_content_list_v2_page_arrays() -> None:
    payload = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "TraceLab Paper"}],
                    "level": 1,
                },
                "bbox": [100, 50, 900, 120],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [{"type": "text", "content": "First page paragraph."}]
                },
                "bbox": [100, 160, 900, 240],
            },
        ],
        [
            {
                "type": "table",
                "content": {
                    "table_caption": [{"type": "text", "content": "Table 1"}],
                    "html": "<table><tr><td>value</td></tr></table>",
                },
                "bbox": [100, 200, 900, 600],
            }
        ],
    ]

    result = normalize_mineru_payload(
        payload,
        filename="paper.pdf",
        parser_version="3.4.4",
    ).to_dict()

    assert result["title"] == "TraceLab Paper"
    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert result["pages"][1]["blocks"][0]["kind"] == "table"
