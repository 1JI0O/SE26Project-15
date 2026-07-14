from __future__ import annotations

from app.services.tracing.static_candidates import StaticCandidate


def build_contexts(
    candidates: list[StaticCandidate], *, max_candidates: int, max_chars: int
) -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    used = 0
    for candidate in candidates[:max_candidates]:
        context: dict[str, object] = {
            "candidate_id": candidate.candidate_id,
            "paper": {
                "ref": candidate.paper_block_id,
                "text": candidate.paper_text[:2000],
            },
            "code": {
                "ref": candidate.code_symbol_id,
                "text": candidate.code_text[:2000],
            },
            "static_relation_type": candidate.relation_type,
            "static_confidence": candidate.confidence,
        }
        size = len(str(context))
        if contexts and used + size > max_chars:
            break
        contexts.append(context)
        used += size
    return contexts
