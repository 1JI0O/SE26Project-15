from __future__ import annotations

from typing import Protocol

from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.models.entities import Project

_CONFIDENCE_WEIGHTS = {
    "change_directness": 0.20,
    "causal_reachability": 0.25,
    "requirement_support": 0.20,
    "trace_support": 0.15,
    "verification_support": 0.10,
    "context_coverage": 0.10,
}

_CONFIDENCE_PENALTIES = {
    "paper_association_inferred": -0.10,
    "no_call_entry": -0.20,
    "alternate_implementation": -0.20,
    "config_or_caller_unread": -0.15,
    "context_truncated": -0.15,
    "runtime_condition_unverified": -0.15,
}


class ConfidenceCandidate(Protocol):
    confidence: float
    confidence_penalties: list[str]
    model_fields_set: set[str]
    change_directness: float
    causal_reachability: float
    requirement_support: float
    trace_support: float
    verification_support: float
    context_coverage: float


def is_deep_thinking_enabled(session: Session, project_id: int) -> bool:
    """Return the project confidence mode, falling back to direct scoring on old schemas."""

    try:
        project = session.get(Project, project_id)
    except OperationalError:
        return False
    return bool(project is not None and project.agent_deep_thinking)


def compute_trace_confidence(candidate: ConfidenceCandidate) -> float:
    """Compute the weighted six-dimension score with each penalty flag applied once."""

    dimensions_supplied = bool(_CONFIDENCE_WEIGHTS.keys() & candidate.model_fields_set)
    if not dimensions_supplied and not candidate.confidence_penalties:
        return round(max(0.0, min(1.0, candidate.confidence)), 4)

    base = sum(
        weight * getattr(candidate, dimension)
        for dimension, weight in _CONFIDENCE_WEIGHTS.items()
    )
    penalty = sum(
        _CONFIDENCE_PENALTIES.get(flag, 0.0)
        for flag in dict.fromkeys(candidate.confidence_penalties)
    )
    return round(max(0.0, min(1.0, base + penalty)), 4)
