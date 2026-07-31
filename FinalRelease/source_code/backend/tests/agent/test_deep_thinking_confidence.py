"""The per-project deep-thinking toggle decides how ``confidence`` is produced.

Off (the default): the agent's own ``confidence`` is stored verbatim. On: the server
recomputes it from the six weighted dimensions minus any penalty flags.
"""

import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.models.entities import (
    AgentAnalysisJob,
    CodeRepository,
    PaperDocument,
    Project,
)
from app.services.agent.analysis_jobs import _SCORING_DEEP, _SCORING_DIRECT, _system_prompt
from app.services.agent.analysis_tools import (
    TraceCandidate,
    compute_trace_confidence,
    execute_tool,
    is_deep_thinking_enabled,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _artifacts(
    session: Session, tmp_path: Path, *, deep_thinking: bool = False
) -> tuple[Project, PaperDocument, CodeRepository]:
    project = Project(name="Deep thinking fixture", agent_deep_thinking=deep_thinking)
    session.add(project)
    session.commit()
    session.refresh(project)
    source = (
        "class Model:\n"
        "    def forward(self, x):\n"
        "        return self.encode(x)\n"
        "\n"
        "    def encode(self, x):\n"
        "        return self.proj(x)\n"
    )
    archive_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo/models/net.py", source)
    code = CodeRepository(
        project_id=project.id or 0,
        filename="repo.zip",
        storage_path=str(archive_path),
        file_tree_json=[{"path": "models/net.py", "language": "python", "editable": True}],
        symbols_json=[
            {
                "id": "models/net.py::Model.encode",
                "path": "models/net.py",
                "name": "encode",
                "kind": "method",
                "line_start": 5,
                "line_end": 6,
            },
        ],
        imports_json=[],
        pytorch_candidates_json=[],
        analysis_json={
            "calls": [
                {
                    "caller_symbol_id": "models/net.py::Model.encode",
                    "callee": "self.proj",
                    "path": "models/net.py",
                    "line_start": 6,
                    "line_end": 6,
                },
            ]
        },
    )
    block = {
        "id": "p1-b1",
        "kind": "paragraph",
        "text": "The model uses an encoder projection.",
        "page_number": 1,
        "bbox": None,
        "section_path": ["Method"],
    }
    paper = PaperDocument(
        project_id=project.id or 0,
        filename="paper.pdf",
        storage_path="paper.pdf",
        sections_json=[],
        paragraphs_json=[block],
        pages_json=[{"page_number": 1, "blocks": [block]}],
    )
    session.add(code)
    session.add(paper)
    session.commit()
    session.refresh(code)
    session.refresh(paper)
    return project, paper, code


def _candidate() -> dict:
    return {
        "paper_block_id": "p1-b1",
        "code_symbol_id": "models/net.py::Model.encode",
        "relation_type": "implements",
        "salience": 0.8,
        "relevance": 0.85,
        "confidence": 0.91,
        "salience_reason": "Core encoder projection contribution.",
        "rationale": "The encoder projection is implemented by Model.encode.",
        "uncertainty_level": "low",
        "uncertainty_reasons": [],
        "paper_evidence": {
            "block_id": "p1-b1",
            "quote": "uses an encoder projection",
            "occurrence": 1,
            "target_type": "method_text",
        },
        "code_evidence": {
            "symbol_id": "models/net.py::Model.encode",
            "path": "models/net.py",
            "line_start": 5,
            "line_end": 6,
            "quote": "return self.proj(x)",
            "occurrence": 1,
            "role": "tensor_transform",
        },
    }


def _publish(
    session: Session,
    tmp_path: Path,
    *,
    deep: bool,
    candidate: dict,
    run_mode: bool | None = None,
) -> float:
    project, paper, code = _artifacts(session, tmp_path, deep_thinking=deep)
    published = execute_tool(
        session,
        project.id or 0,
        code.id or 0,
        paper.id,
        2,
        "publish_trace_candidates",
        {"payload": {"candidates": [candidate], "unresolved": []}},
        deep_thinking=run_mode,
    )
    return published["payload"]["candidates"][0]["confidence"]


def test_default_project_keeps_the_agent_supplied_confidence(tmp_path: Path) -> None:
    candidate = _candidate()
    # Dimensions that would compute to a very different number are ignored while off.
    candidate.update({"causal_reachability": 0.1, "confidence_penalties": ["no_call_entry"]})
    with _session() as session:
        assert _publish(session, tmp_path, deep=False, candidate=candidate) == 0.91


def test_deep_thinking_project_recomputes_confidence_from_dimensions(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate.update(
        {
            "change_directness": 1.0,
            "causal_reachability": 1.0,
            "requirement_support": 1.0,
            "trace_support": 1.0,
            "verification_support": 1.0,
            "context_coverage": 1.0,
        }
    )
    with _session() as session:
        # All dimensions at 1.0 and no penalties: the weights sum to 1.0, so the raw 0.91 is
        # replaced by a full score.
        assert _publish(session, tmp_path, deep=True, candidate=candidate) == 1.0


def test_deep_thinking_applies_penalties(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate.update(
        {
            "change_directness": 1.0,
            "causal_reachability": 1.0,
            "requirement_support": 1.0,
            "trace_support": 1.0,
            "verification_support": 1.0,
            "context_coverage": 1.0,
            "confidence_penalties": ["no_call_entry", "context_truncated"],
        }
    )
    with _session() as session:
        # 1.0 - 0.20 - 0.15
        assert _publish(session, tmp_path, deep=True, candidate=candidate) == 0.65


def test_running_analysis_uses_its_frozen_scoring_mode(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate.update(
        {
            "change_directness": 1.0,
            "causal_reachability": 1.0,
            "requirement_support": 1.0,
            "trace_support": 1.0,
            "verification_support": 1.0,
            "context_coverage": 1.0,
        }
    )
    with _session() as session:
        # Project was switched on after a direct-scoring run started.
        assert (
            _publish(
                session,
                tmp_path,
                deep=True,
                candidate=candidate,
                run_mode=False,
            )
            == 0.91
        )
    with _session() as session:
        # Project was switched off after a six-dimension run started.
        assert (
            _publish(
                session,
                tmp_path,
                deep=False,
                candidate=candidate,
                run_mode=True,
            )
            == 1.0
        )


def test_missing_project_is_treated_as_deep_thinking_off(tmp_path: Path) -> None:
    with _session() as session:
        assert is_deep_thinking_enabled(session, 4242) is False


def test_toggle_is_per_project(tmp_path: Path) -> None:
    with _session() as session:
        plain = Project(name="plain")
        deep = Project(name="deep", agent_deep_thinking=True)
        session.add(plain)
        session.add(deep)
        session.commit()
        assert is_deep_thinking_enabled(session, plain.id or 0) is False
        assert is_deep_thinking_enabled(session, deep.id or 0) is True


def test_unfilled_dimensions_fall_back_to_the_raw_confidence() -> None:
    candidate = TraceCandidate.model_validate(_candidate())
    # No dimension was moved off its default and no penalty flagged, so the model's own
    # number is kept rather than the ~0.63 default baseline.
    assert compute_trace_confidence(candidate) == 0.91


def test_penalties_alone_engage_the_formula() -> None:
    raw = _candidate()
    raw["confidence_penalties"] = ["alternate_implementation"]
    candidate = TraceCandidate.model_validate(raw)
    # Defaults 0.7/0.6/0.7/0.5/0.5/0.7 weight out to 0.625, minus 0.20.
    assert compute_trace_confidence(candidate) == 0.425


def test_confidence_is_clamped_into_range() -> None:
    raw = _candidate()
    raw["confidence_penalties"] = [
        "no_call_entry",
        "alternate_implementation",
        "config_or_caller_unread",
        "context_truncated",
        "runtime_condition_unverified",
        "paper_association_inferred",
    ]
    candidate = TraceCandidate.model_validate(raw)
    assert compute_trace_confidence(candidate) == 0.0


def test_unknown_penalty_keys_are_ignored() -> None:
    raw = _candidate()
    raw["confidence_penalties"] = ["agent_disagreement", "made_up_key"]
    candidate = TraceCandidate.model_validate(raw)
    # The removed agent_disagreement key must not silently subtract anything.
    assert compute_trace_confidence(candidate) == 0.625


def test_prompt_only_explains_the_dimensions_when_deep_thinking_is_on(tmp_path: Path) -> None:
    with _session() as session:
        project, paper, code = _artifacts(session, tmp_path)
        job = AgentAnalysisJob(
            project_id=project.id or 0,
            kind="trace",
            paper_document_id=paper.id,
            code_repository_id=code.id or 0,
            code_revision=code.revision,
            requested_depth=2,
            fingerprint="c" * 64,
        )
        _, plain = _system_prompt(job, 40, "", False)
        _, deep = _system_prompt(job, 40, "", True)

    assert _SCORING_DIRECT in plain
    assert "change_directness" not in plain
    assert _SCORING_DEEP in deep
    assert "causal_reachability" in deep
    # Keeping the default request shorter is the point of the toggle.
    assert len(plain) < len(deep)
