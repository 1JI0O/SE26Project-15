"""Tests for the parallel trace sub-agent runtime (dispatch tool, sink, event bus).

All tests use a file-based SQLite engine: sub-agents run in real threads, and the
StaticPool in-memory engine from conftest shares one connection across threads, which
does not represent production (one connection per session under WAL).
"""

import threading
import time
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    AgentRun,
    AgentRunEvent,
    CodeRepository,
    PaperDocument,
    Project,
    TraceLink,
)
from app.schemas.agent import AgentAnalysisJobCreate
from app.services.agent import subagents
from app.services.agent.provider import AgentProviderFailure, AgentProviderStep
from app.services.agent.subagents import backoff_seconds


def _fixture(session: Session, tmp_path: Path) -> tuple[Project, PaperDocument, CodeRepository]:
    project = Project(name="Subagent fixture")
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
                "id": "models/net.py::Model.forward",
                "path": "models/net.py",
                "name": "forward",
                "kind": "method",
                "line_start": 2,
                "line_end": 3,
            },
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
        analysis_json={"calls": []},
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


_CAND_A = {
    "paper_block_id": "p1-b1",
    "code_symbol_id": "models/net.py::Model.encode",
    "relation_type": "implements",
    "salience": 0.8,
    "relevance": 0.85,
    "confidence": 0.9,
    "rationale": "Model.encode implements the encoder projection.",
    "paper_evidence": {
        "block_id": "p1-b1",
        "quote": "uses an encoder projection",
        "occurrence": 1,
    },
    "code_evidence": {
        "path": "models/net.py",
        "line_start": 5,
        "line_end": 6,
        "quote": "return self.proj(x)",
        "occurrence": 1,
    },
}

_CAND_B = {
    "paper_block_id": "p1-b1",
    "code_symbol_id": "models/net.py::Model.forward",
    "relation_type": "invokes",
    "salience": 0.7,
    "relevance": 0.7,
    "confidence": 0.8,
    "rationale": "forward invokes the encoder.",
    "paper_evidence": {"block_id": "p1-b1", "quote": "The model uses", "occurrence": 1},
    "code_evidence": {
        "path": "models/net.py",
        "line_start": 2,
        "line_end": 3,
        "quote": "return self.encode(x)",
        "occurrence": 1,
    },
}


def _publish(candidates: list[dict]) -> AgentProviderStep:
    return AgentProviderStep(
        action="tool",
        tool_name="publish_trace_candidates",
        arguments={"payload": {"candidates": candidates}},
    )


def _dispatch(regions: list[dict]) -> AgentProviderStep:
    return AgentProviderStep(
        action="tool", tool_name="dispatch_trace_subagents", arguments={"regions": regions}
    )


_FINISH = AgentProviderStep(action="tool", tool_name="finish_analysis", arguments={})
_FINAL = AgentProviderStep(action="final", answer="region done")
_READ = AgentProviderStep(action="tool", tool_name="list_paper_blocks", arguments={})


class _ScriptedProvider:
    """Steps keyed by sub-agent region name ("parent" for the main loop); thread-safe.

    Script entries may be AgentProviderStep values or zero-arg callables (to raise
    provider failures or block). An exhausted script repeats its last entry.
    """

    provider_name = "stub"
    model_name = "stub"

    def __init__(self, scripts: dict[str, list]) -> None:
        self._scripts = scripts
        self._cursor: dict[str, int] = {}
        self._lock = threading.Lock()

    def next_step(self, message, context, tool_results):  # noqa: ANN001, ANN201
        key = context.get("active_context", {}).get("region") or "parent"
        with self._lock:
            steps = self._scripts[key]
            index = min(self._cursor.get(key, 0), len(steps) - 1)
            self._cursor[key] = index + 1
        entry = steps[index]
        return entry() if callable(entry) else entry


def _make_engine(tmp_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'subagents.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _prepare_job(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider
) -> tuple[int, str]:
    from app.services.agent import analysis_jobs as aj
    from app.services.agent.analysis_jobs import create_analysis_job

    with Session(engine) as session:
        project, _paper, _code = _fixture(session, tmp_path)
        project_id = project.id or 0
        monkeypatch.setattr(aj, "_submit", lambda _job_id: None)
        job = create_analysis_job(session, project_id, AgentAnalysisJobCreate(kind="trace"))
        job_id = job.job_id
    monkeypatch.setattr(aj, "engine", engine)
    monkeypatch.setattr(
        aj,
        "_provider_from_settings",
        lambda _session, for_analysis=False: (provider, None),
    )
    return project_id, job_id


def _events(engine: Engine, job_id: str) -> list[AgentRunEvent]:
    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.agent_run_id
        return session.exec(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == job.agent_run_id)
            .order_by(AgentRunEvent.sequence.asc())
        ).all()


def _links(engine: Engine, project_id: int) -> list[TraceLink]:
    with Session(engine) as session:
        return session.exec(
            select(TraceLink).where(
                TraceLink.project_id == project_id, TraceLink.source == "agent"
            )
        ).all()


def test_dispatch_two_regions_parallel_publishes_and_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import analysis_jobs as aj

    provider = _ScriptedProvider(
        {
            "parent": [
                _dispatch(
                    [
                        {"name": "Region A", "paper_target_hints": ["p1-b1"], "notes": ""},
                        {"name": "Region B", "code_hints": ["models/net.py"]},
                    ]
                ),
                _FINISH,
            ],
            "Region A": [_publish([_CAND_A]), _FINAL],
            "Region B": [_publish([_CAND_B]), _FINAL],
        }
    )
    engine = _make_engine(tmp_path)
    project_id, job_id = _prepare_job(engine, tmp_path, monkeypatch, provider)
    aj._execute_job(job_id)

    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.status == "succeeded"
        artifacts = session.exec(
            select(AgentAnalysisArtifact).where(AgentAnalysisArtifact.job_id == job_id)
        ).all()
    assert len(artifacts) == 1 and artifacts[0].is_current
    assert len(artifacts[0].payload_json.get("candidates", [])) == 2
    links = _links(engine, project_id)
    assert len(links) == 2

    events = _events(engine, job_id)
    types = [event.event_type for event in events]
    assert "analysis.subagents.started" in types
    assert types.count("analysis.subagents.progress") == 2
    published = [event for event in events if event.event_type == "analysis.published"]
    assert len(published) == 2
    assert {event.payload_json.get("subagent") for event in published} == {
        "Region A",
        "Region B",
    }
    assert "analysis.completed" in types
    # Sequences must be strictly increasing and unique (SSE cursor correctness).
    sequences = [event.sequence for event in events]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


def test_dispatch_sequential_fallback_when_parallelism_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import analysis_jobs as aj

    monkeypatch.setattr(settings, "tracelab_trace_subagent_parallelism", 1)
    provider = _ScriptedProvider(
        {
            "parent": [
                _dispatch([{"name": "Region A"}, {"name": "Region B"}]),
                _FINISH,
            ],
            "Region A": [_publish([_CAND_A]), _FINAL],
            "Region B": [_publish([_CAND_B]), _FINAL],
        }
    )
    engine = _make_engine(tmp_path)
    project_id, job_id = _prepare_job(engine, tmp_path, monkeypatch, provider)
    aj._execute_job(job_id)

    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.status == "succeeded"
    assert len(_links(engine, project_id)) == 2


def test_dispatch_same_fingerprint_regions_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import analysis_jobs as aj

    provider = _ScriptedProvider(
        {
            "parent": [
                _dispatch([{"name": "Region A"}, {"name": "Region B"}]),
                _FINISH,
            ],
            # Both regions publish the SAME candidate: the link upsert must dedupe.
            "Region A": [_publish([_CAND_A]), _FINAL],
            "Region B": [_publish([_CAND_A]), _FINAL],
        }
    )
    engine = _make_engine(tmp_path)
    project_id, job_id = _prepare_job(engine, tmp_path, monkeypatch, provider)
    aj._execute_job(job_id)

    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.status == "succeeded"
    assert len(_links(engine, project_id)) == 1


def test_cancel_during_dispatch_keeps_published_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import analysis_jobs as aj
    from app.services.agent.analysis_jobs import cancel_analysis_job

    # Fast cancel probes so the region notices the cancel within a step or two.
    original_probe = subagents._CancelProbe
    monkeypatch.setattr(
        subagents,
        "_CancelProbe",
        lambda engine, job_id, cancel_event: original_probe(
            engine, job_id, cancel_event, interval=0.05
        ),
    )

    def _slow_read() -> AgentProviderStep:
        time.sleep(0.1)
        return _READ

    provider = _ScriptedProvider(
        {
            "parent": [_dispatch([{"name": "Region A"}]), _FINISH],
            # Publish once, then keep reading slowly until cancelled.
            "Region A": [_publish([_CAND_A]), _slow_read],
        }
    )
    engine = _make_engine(tmp_path)
    project_id, job_id = _prepare_job(engine, tmp_path, monkeypatch, provider)

    worker = threading.Thread(target=aj._execute_job, args=(job_id,))
    worker.start()
    try:
        published = False
        for _ in range(100):
            if _links(engine, project_id):
                published = True
                break
            time.sleep(0.05)
        assert published, "region never published its first batch"
        with Session(engine) as session:
            cancelled = cancel_analysis_job(session, project_id, job_id)
            assert cancelled is not None and cancelled.status == "cancelling"
    finally:
        worker.join(timeout=30)
    assert not worker.is_alive(), "worker did not stop after cancel"

    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.status == "succeeded"
        assert job.progress_json.get("code") == "analysis_cancelled"
    assert len(_links(engine, project_id)) >= 1
    progress = [
        event
        for event in _events(engine, job_id)
        if event.event_type == "analysis.subagents.progress"
    ]
    assert progress and progress[-1].payload_json.get("status") == "cancelled"


def test_dispatch_validation_dedupe_and_call_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import analysis_jobs as aj

    provider = _ScriptedProvider(
        {
            "parent": [
                _dispatch([]),  # schema-invalid: min 1 region
                _dispatch([{"name": "Region A"}, {"name": "region a"}]),  # dedupes to 1
                _dispatch([{"name": "Region B"}]),  # second (last allowed) call
                _dispatch([{"name": "Region C"}]),  # over the 2-call limit
                _publish([_CAND_A]),  # parent can still publish itself
                _FINISH,
            ],
            "Region A": [_FINAL],
            "Region B": [_FINAL],
        }
    )
    engine = _make_engine(tmp_path)
    project_id, job_id = _prepare_job(engine, tmp_path, monkeypatch, provider)
    aj._execute_job(job_id)

    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.status == "succeeded"
        run = session.get(AgentRun, job.agent_run_id)
        assert run is not None
        entries = run.trace_json
    assert len(_links(engine, project_id)) == 1

    dispatch_results = [
        entry
        for entry in entries
        if entry.get("type") == "tool_result"
        and entry.get("tool") == "dispatch_trace_subagents"
    ]
    errors = [entry.get("error") for entry in dispatch_results if not entry.get("ok")]
    assert "invalid_tool_arguments" in errors
    assert "dispatch_limit_reached" in errors
    successes = [entry for entry in dispatch_results if entry.get("ok")]
    assert [entry.get("regions") for entry in successes] == [1, 1]  # dup name deduped

    started = [
        event
        for event in _events(engine, job_id)
        if event.event_type == "analysis.subagents.started"
    ]
    assert len(started) == 2


def test_backoff_seconds_ranges() -> None:
    for failures, low, high in [(1, 1.0, 2.0), (2, 2.0, 4.0), (3, 4.0, 8.0), (10, 15.0, 30.0)]:
        for _ in range(20):
            value = backoff_seconds(failures, "llm_rate_limited")
            assert low <= value <= high
            value = backoff_seconds(failures, "llm_timeout")
            assert low <= value <= high
    assert backoff_seconds(3, "llm_invalid_json") == 0.0
    assert backoff_seconds(3, "llm_transport_error") == 0.0


def test_parent_retry_applies_backoff_for_rate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import analysis_jobs as aj

    recorded: list[tuple[int, str]] = []

    def _fake_backoff(failures: int, reason: str) -> float:
        recorded.append((failures, reason))
        return 0.0

    monkeypatch.setattr(aj, "backoff_seconds", _fake_backoff)

    def _rate_limited() -> AgentProviderStep:
        raise AgentProviderFailure("llm_rate_limited")

    provider = _ScriptedProvider(
        {"parent": [_rate_limited, _rate_limited, _publish([_CAND_A]), _FINISH]}
    )
    engine = _make_engine(tmp_path)
    project_id, job_id = _prepare_job(engine, tmp_path, monkeypatch, provider)
    aj._execute_job(job_id)

    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.status == "succeeded"
    assert len(_links(engine, project_id)) == 1
    assert recorded == [(1, "llm_rate_limited"), (2, "llm_rate_limited")]


def test_parent_without_dispatch_behaves_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.agent import analysis_jobs as aj
    from app.services.agent.analysis_tools import tool_definitions

    provider = _ScriptedProvider({"parent": [_publish([_CAND_A]), _FINISH]})
    engine = _make_engine(tmp_path)
    project_id, job_id = _prepare_job(engine, tmp_path, monkeypatch, provider)
    aj._execute_job(job_id)

    with Session(engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None and job.status == "succeeded"
    assert len(_links(engine, project_id)) == 1
    types = [event.event_type for event in _events(engine, job_id)]
    assert "analysis.subagents.started" not in types

    parent_tools = {item["function"]["name"] for item in tool_definitions("trace")}
    assert "dispatch_trace_subagents" in parent_tools
    subagent_tools = {
        item["function"]["name"] for item in tool_definitions("trace", role="subagent")
    }
    assert "publish_trace_candidates" in subagent_tools
    assert "dispatch_trace_subagents" not in subagent_tools
    assert "finish_analysis" not in subagent_tools
    assert "get_analysis_artifact" not in subagent_tools
