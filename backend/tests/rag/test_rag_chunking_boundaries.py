"""Defensive chunking checks for malformed external block identifiers."""

from types import SimpleNamespace

from app.services.rag.chunking import paper_chunks


class _TruthyEmptyId:
    def __bool__(self) -> bool:
        return True

    def __str__(self) -> str:
        return ""


def test_paper_chunks_reject_identifier_that_stringifies_to_empty() -> None:
    paper = SimpleNamespace(
        pages_json=[
            {
                "blocks": [
                    {
                        "id": _TruthyEmptyId(),
                        "text": "A malformed identifier must not create an unusable chunk.",
                    }
                ]
            }
        ],
        paragraphs_json=[],
    )

    assert paper_chunks(paper) == []
