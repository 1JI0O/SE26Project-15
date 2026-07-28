from tracelab_core.review import _parse_code_target, candidates_to_links


def test_parse_code_target_line_range() -> None:
    path, start, end = _parse_code_target("nn.py:10-20", "nn.py::Foo")
    assert path == "nn.py"
    assert start == 10
    assert end == 20


def test_parse_code_target_symbol_fallback() -> None:
    path, start, end = _parse_code_target("nn.py::MultiHeadAttention", "nn.py::MultiHeadAttention")
    assert path == "nn.py"
    assert start == 1
    assert end == 1


def test_candidates_to_links_tolerates_llm_symbol_refs() -> None:
    links = candidates_to_links(
        [
            {
                "paper_block_id": "p1",
                "code_symbol_id": "nn.py::MultiHeadAttention",
                "relation_type": "implements",
                "confidence": 0.9,
                "rationale": "match",
                "evidence": [
                    {"side": "paper", "ref": "p1", "quote": "attention"},
                    {"side": "code", "ref": "nn.py::MultiHeadAttention", "quote": "class"},
                ],
            }
        ],
        source="llm",
    )
    assert len(links) == 1
    assert links[0]["code_target"]["path"] == "nn.py"
    assert links[0]["code_target"]["line_start"] == 1
