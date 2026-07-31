import pytest

from app.services.paper_evidence import (
    PaperEvidenceResolutionError,
    build_evidence_spans,
    resolve_paper_evidence,
    search_paper_blocks,
)

REAL_PDF_TEXT = (
    "Real images are captured from forward-facing cameras. "
    "We hold out\\frac{1}{8}of these for the test set. "
    "All images are1008 \\times 756pixels."
)


def _block(text: str = REAL_PDF_TEXT) -> dict:
    return {
        "id": "p10-b85",
        "kind": "paragraph",
        "text": text,
        "page_number": 10,
        "section_path": ["Experiments", "Real Forward-Facing"],
    }


def test_evidence_spans_are_stable_exact_source_ranges() -> None:
    spans = build_evidence_spans(_block())
    repeated = build_evidence_spans(_block())

    assert spans == repeated
    assert spans
    for span in spans:
        assert REAL_PDF_TEXT[span["char_start"] : span["char_end"]] == span["quote"]
        assert 0 < len(span["quote"]) <= 600
        assert span["span_id"].startswith("paper-span-")
        assert len(span["quote_hash"]) == 64


def test_legacy_layout_variants_resolve_to_exact_pdf_text() -> None:
    resolved = resolve_paper_evidence(
        _block(),
        quote=(
            "We hold out 1/8 of these for the test set. "
            "All images are 1008 × 756 pixels."
        ),
    )

    assert resolved["quote"] == (
        "We hold out\\frac{1}{8}of these for the test set. "
        "All images are1008 \\times 756pixels"
    )
    assert REAL_PDF_TEXT[
        resolved["char_start"] : resolved["char_end"]
    ] == resolved["quote"]


def test_pdf_word_gluing_maps_to_the_unique_exact_source() -> None:
    block = _block("We evaluate on a heldout testset with realimages.")
    resolved = resolve_paper_evidence(
        block,
        quote="heldout test set with real images",
    )

    assert resolved["quote"] == "heldout testset with realimages"


@pytest.mark.parametrize(
    "quote",
    [
        "We hold out 1/16 of these for the test set.",
        "We hold out 1/8 of these for the validation set.",
        "We report SSIM for the test set.",
    ],
)
def test_semantic_changes_are_rejected(quote: str) -> None:
    with pytest.raises(PaperEvidenceResolutionError, match="paper_quote_not_found"):
        resolve_paper_evidence(_block(), quote=quote)


def test_ambiguous_and_cross_block_quotes_are_rejected() -> None:
    with pytest.raises(PaperEvidenceResolutionError, match="paper_quote_ambiguous"):
        resolve_paper_evidence(
            _block("Repeated evidence. Repeated evidence."),
            quote="Repeated evidence",
        )
    with pytest.raises(PaperEvidenceResolutionError, match="paper_quote_not_found"):
        resolve_paper_evidence(_block("First block only."), quote="First block second block")


def test_span_and_quote_must_point_to_same_source_range() -> None:
    block = _block()
    span = build_evidence_spans(block)[0]
    with pytest.raises(PaperEvidenceResolutionError, match="paper_span_quote_mismatch"):
        resolve_paper_evidence(
            block,
            span_id=span["span_id"],
            quote="We hold out 1/8 of these for the test set.",
        )


def test_span_disambiguates_a_repeated_exact_quote() -> None:
    quote = (
        "Repeated evidence includes enough identical context to form one complete "
        "and independently addressable source span."
    )
    block = _block(f"{quote} {quote}")
    spans = build_evidence_spans(block)
    resolved = resolve_paper_evidence(
        block,
        span_id=spans[1]["span_id"],
        quote=quote,
    )

    assert resolved["char_start"] == spans[1]["char_start"]


def test_search_finds_latex_fraction_with_plain_text_query() -> None:
    unrelated = _block("The optimizer uses a fixed learning rate.")
    unrelated["id"] = "p2-b1"
    results = search_paper_blocks(
        [unrelated, _block()],
        "hold out 1/8 test set",
        limit=5,
    )

    assert results[0]["block_id"] == "p10-b85"
    assert results[0]["evidence_span"]["quote"] in REAL_PDF_TEXT
