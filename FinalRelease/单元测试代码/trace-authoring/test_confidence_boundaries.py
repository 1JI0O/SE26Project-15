from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

from app.services.agent.analysis_tools import TraceCandidate
from app.services.agent.confidence import (
    compute_trace_confidence,
    is_deep_thinking_enabled,
)


def _candidate(**updates: object) -> TraceCandidate:
    raw: dict[str, object] = {
        "paper_block_id": "paper-block",
        "code_symbol_id": "model.py::forward",
        "confidence": 0.91,
        "rationale": "The cited implementation matches the paper requirement.",
        "paper_evidence": {
            "block_id": "paper-block",
            "quote": "encoder projection",
        },
        "code_evidence": {
            "path": "model.py",
            "line_start": 1,
            "line_end": 1,
            "quote": "return self.proj(x)",
        },
    }
    raw.update(updates)
    return TraceCandidate.model_validate(raw)


class _ProjectSession:
    def __init__(self, project: object = None, *, error: bool = False) -> None:
        self.project = project
        self.error = error

    def get(self, _model: object, _project_id: int) -> object:
        if self.error:
            raise OperationalError("SELECT project", {}, Exception("no such column"))
        return self.project


def test_project_mode_defaults_off_and_reads_both_values() -> None:
    assert is_deep_thinking_enabled(_ProjectSession(), 1) is False  # type: ignore[arg-type]
    assert (
        is_deep_thinking_enabled(
            _ProjectSession(SimpleNamespace(agent_deep_thinking=False)), 1  # type: ignore[arg-type]
        )
        is False
    )
    assert (
        is_deep_thinking_enabled(
            _ProjectSession(SimpleNamespace(agent_deep_thinking=True)), 1  # type: ignore[arg-type]
        )
        is True
    )


def test_old_schema_operational_error_falls_back_to_direct_scoring() -> None:
    session = _ProjectSession(error=True)
    assert is_deep_thinking_enabled(session, 1) is False  # type: ignore[arg-type]


def test_omitted_dimensions_keep_the_direct_agent_score() -> None:
    assert compute_trace_confidence(_candidate()) == 0.91


def test_explicit_default_dimensions_use_the_weighted_formula() -> None:
    candidate = _candidate(
        change_directness=0.7,
        causal_reachability=0.6,
        requirement_support=0.7,
        trace_support=0.5,
        verification_support=0.5,
        context_coverage=0.7,
    )
    assert compute_trace_confidence(candidate) == 0.625


def test_duplicate_and_unknown_penalties_are_applied_at_most_once() -> None:
    candidate = _candidate(
        confidence_penalties=["no_call_entry", "no_call_entry", "unknown"],
    )
    assert compute_trace_confidence(candidate) == 0.425


def test_formula_is_clamped_at_both_bounds() -> None:
    assert (
        compute_trace_confidence(
            _candidate(
                change_directness=1,
                causal_reachability=1,
                requirement_support=1,
                trace_support=1,
                verification_support=1,
                context_coverage=1,
            )
        )
        == 1.0
    )
    assert (
        compute_trace_confidence(
            _candidate(
                change_directness=0,
                causal_reachability=0,
                requirement_support=0,
                trace_support=0,
                verification_support=0,
                context_coverage=0,
                confidence_penalties=["no_call_entry"],
            )
        )
        == 0.0
    )
