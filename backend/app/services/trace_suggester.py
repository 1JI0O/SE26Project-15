from typing import Any

from app.services.tracing.static_candidates import generate_static_candidates


def suggest_trace_links(
    sections: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    pytorch_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compatibility adapter used by the iteration 1 workspace aggregator."""

    candidates = generate_static_candidates(
        sections,
        paragraphs,
        symbols,
        pytorch_candidates,
    )
    return [
        {
            "paper_ref": candidate.paper_block_id,
            "code_ref": candidate.code_symbol_id,
            "relation_type": candidate.relation_type,
            "confidence": candidate.confidence,
            "rationale": candidate.rationale,
        }
        for candidate in candidates[:10]
    ]
