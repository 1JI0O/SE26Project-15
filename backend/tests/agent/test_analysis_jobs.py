import threading
import time
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.services.agent.provider import AgentProviderStep

from app.models.entities import (
    AgentAnalysisJob,
    AgentConversation,
    AgentRun,
    CodeRepository,
    CodeTarget,
    PaperDocument,
    PaperTarget,
    Project,
    TraceLink,
)
from app.schemas.agent import AgentAnalysisJobCreate
from app.services import workspace_service
from app.services.agent.analysis_jobs import (
    _persist_artifact,
    cancel_analysis_job,
    create_analysis_job,
)
from app.services.agent.analysis_tools import execute_tool
from app.services.analysis_jobs import ANALYZER_VERSION
from app.services.code_analysis.analyzer import analyze_code_archive
from app.services.paper_markdown import inject_block_anchors


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _artifacts(session: Session, tmp_path: Path) -> tuple[Project, PaperDocument, CodeRepository]:
    project = Project(name="Agent analysis fixture")
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
        analysis_json={
            "calls": [
                {
                    "caller_symbol_id": "models/net.py::Model.forward",
                    "callee": "self.encode",
                    "path": "models/net.py",
                    "line_start": 3,
                    "line_end": 3,
                },
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


def _architecture_payload() -> dict:
    return {
        "schema_version": "architecture-agent-v1",
        "root_symbol": "models/net.py::Model.forward",
        "root_label": "Model.forward",
        "requested_depth": 2,
        "nodes": [
            {
                "id": "forward",
                "label": "Model.forward",
                "kind": "component",
                "depth": 0,
                "description": "Model entry",
                "symbol_id": "models/net.py::Model.forward",
                "callee": "forward",
                "source_path": "models/net.py",
                "line_start": 2,
                "line_end": 3,
                "component_symbol_id": "models/net.py::Model.forward",
                "expandable": True,
                "external": False,
                "evidence": [
                    {
                        "path": "models/net.py",
                        "line_start": 2,
                        "line_end": 3,
                        "quote": "def forward(self, x):",
                    }
                ],
            },
            {
                "id": "encode",
                "label": "self.encode",
                "kind": "component",
                "depth": 1,
                "description": "Project encoder call",
                "symbol_id": "models/net.py::Model.encode",
                "callee": "self.encode",
                "source_path": "models/net.py",
                "line_start": 3,
                "line_end": 3,
                "component_symbol_id": "models/net.py::Model.encode",
                "expandable": True,
                "external": False,
                "evidence": [
                    {
                        "path": "models/net.py",
                        "line_start": 3,
                        "line_end": 3,
                        "quote": "return self.encode(x)",
                    }
                ],
            },
            {
                "id": "proj",
                "label": "self.proj",
                "kind": "operation",
                "depth": 2,
                "description": "Projection operation",
                "symbol_id": "models/net.py::Model.encode",
                "callee": "self.proj",
                "source_path": "models/net.py",
                "line_start": 6,
                "line_end": 6,
                "component_symbol_id": None,
                "expandable": False,
                "external": True,
                "evidence": [
                    {
                        "path": "models/net.py",
                        "line_start": 6,
                        "line_end": 6,
                        "quote": "return self.proj(x)",
                    }
                ],
            },
        ],
        "edges": [
            {"id": "e1", "source": "forward", "target": "encode", "kind": "call", "label": "x"},
            {"id": "e2", "source": "encode", "target": "proj", "kind": "call", "label": "x"},
        ],
        "unresolved": [],
    }


def test_publish_architecture_validates_evidence_and_depth(tmp_path: Path) -> None:
    with _session() as session:
        project, paper, code = _artifacts(session, tmp_path)
        result = execute_tool(
            session,
            project.id or 0,
            code.id or 0,
            paper.id,
            2,
            "publish_architecture_graph",
            {"payload": _architecture_payload()},
        )
        invalid = _architecture_payload()
        invalid["nodes"][2]["evidence"][0]["quote"] = "nn.Conv2d(3, 64, 7)"
        with pytest.raises(ValueError, match="code_evidence_quote_invalid"):
            execute_tool(
                session,
                project.id or 0,
                code.id or 0,
                paper.id,
                2,
                "publish_architecture_graph",
                {"payload": invalid},
            )
    assert result["published"] is True
    assert result["payload"]["nodes"][2]["depth"] == 2


def test_agent_architecture_artifact_does_not_override_local_workspace_graph(
    tmp_path: Path,
) -> None:
    with _session() as session:
        project, _paper, code = _artifacts(session, tmp_path)
        conversation = AgentConversation(project_id=project.id or 0, kind="analysis")
        session.add(conversation)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.conversation_id,
            project_id=project.id or 0,
            provider_name="fake",
            model_name="fake",
        )
        session.add(run)
        session.flush()
        job = AgentAnalysisJob(
            project_id=project.id or 0,
            kind="architecture",
            code_repository_id=code.id or 0,
            code_revision=code.revision,
            requested_depth=2,
            agent_run_id=run.run_id,
            fingerprint="a" * 64,
        )
        session.add(job)
        session.flush()
        artifact = _persist_artifact(session, job, run, _architecture_payload())
        job.artifact_id = artifact.artifact_id
        job.status = "succeeded"
        session.add(job)
        analysis = analyze_code_archive(code.storage_path)
        code.analysis_json = analysis
        code.tensor_graph_json = analysis["tensor_graph"]
        code.analysis_revision = code.revision
        code.analysis_version = ANALYZER_VERSION
        code.analysis_status = "ready"
        session.add(code)
        session.commit()
        graph = workspace_service.get_tensor_flow(session, project.id or 0)

    assert graph["renderer"] == "architecture-dag-v2"
    assert graph["analysis_status"] == "ready"
    assert graph["root_symbol"] == "models/net.py::Model"
    assert "Model.forward" not in [node["label"] for node in graph["nodes"]]


def test_agent_trace_publish_creates_only_proposed_evidence_backed_link(tmp_path: Path) -> None:
    with _session() as session:
        project, paper, code = _artifacts(session, tmp_path)
        trace_payload = {
            "schema_version": "trace-agent-v2",
            "candidates": [
                {
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
                    "graph_node_ids": ["encode", "proj"],
                }
            ],
            "unresolved": [],
        }
        published = execute_tool(
            session,
            project.id or 0,
            code.id or 0,
            paper.id,
            2,
            "publish_trace_candidates",
            {"payload": trace_payload},
        )
        conversation = AgentConversation(project_id=project.id or 0, kind="analysis")
        session.add(conversation)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.conversation_id,
            project_id=project.id or 0,
            provider_name="fake",
            model_name="fake",
        )
        session.add(run)
        session.flush()
        job = AgentAnalysisJob(
            project_id=project.id or 0,
            kind="trace",
            paper_document_id=paper.id,
            code_repository_id=code.id or 0,
            code_revision=code.revision,
            requested_depth=2,
            agent_run_id=run.run_id,
            fingerprint="b" * 64,
        )
        session.add(job)
        session.flush()
        _persist_artifact(session, job, run, published["payload"])
        session.commit()
        link = session.exec(select(TraceLink)).one()
        paper_target = session.exec(select(PaperTarget)).one()
        code_target = session.exec(select(CodeTarget)).one()

    assert link.status == "proposed"
    assert link.source == "agent"
    assert {item["side"] for item in link.evidence_json} == {"paper", "code"}
    assert link.evidence_json[1]["line_start"] == 5
    # Fragment-level anchoring is persisted on both the link and the target rows.
    assert link.relevance == 0.85
    assert link.paper_target_id == paper_target.target_id
    assert link.code_target_id == code_target.target_id
    assert paper_target.occurrence == 1
    assert paper_target.quote_hash
    assert paper_target.salience == 0.8
    assert code_target.code_quote_hash
    assert code_target.role == "tensor_transform"
    # "return self.proj(x)" lives on line 6 inside the declared 5-6 symbol range.
    assert code_target.line_start == 6


def test_analysis_job_is_idempotent_and_paper_markdown_gets_block_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session() as session:
        project, paper, code = _artifacts(session, tmp_path)
        monkeypatch.setattr("app.services.agent.analysis_jobs._submit", lambda _job_id: None)
        payload = AgentAnalysisJobCreate(kind="trace")
        first = create_analysis_job(session, project.id or 0, payload)
        second = create_analysis_job(session, project.id or 0, payload)
        markdown, blocks = inject_block_anchors(
            "# Method\n\nThe model uses an encoder projection.",
            paper.pages_json,
        )

    assert first.job_id == second.job_id
    assert code.revision == first.code_revision
    assert blocks[0]["anchor_resolved"] is True
    assert f'id="{blocks[0]["render_anchor"]}"' in markdown


def test_cancel_never_started_job_finishes_without_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session() as session:
        project, _paper, _code = _artifacts(session, tmp_path)
        monkeypatch.setattr("app.services.agent.analysis_jobs._submit", lambda _job_id: None)
        job = create_analysis_job(session, project.id or 0, AgentAnalysisJobCreate(kind="trace"))
        assert job.status == "queued" and job.agent_run_id is None

        cancelled = cancel_analysis_job(session, project.id or 0, job.job_id)
        assert cancelled is not None
        # Never started → finishes directly (no worker will pick it up).
        assert cancelled.status == "succeeded"
        assert cancelled.progress_json.get("code") == "analysis_cancelled"

        # Idempotent: cancelling a terminal job returns it unchanged.
        again = cancel_analysis_job(session, project.id or 0, job.job_id)
        assert again is not None and again.status == "succeeded"


def test_cancel_running_job_marks_cancelling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session() as session:
        project, _paper, _code = _artifacts(session, tmp_path)
        monkeypatch.setattr("app.services.agent.analysis_jobs._submit", lambda _job_id: None)
        job = create_analysis_job(session, project.id or 0, AgentAnalysisJobCreate(kind="trace"))
        # Simulate a worker that has started the run.
        job.status = "running"
        job.agent_run_id = "run-fake"
        session.add(job)
        session.commit()

        cancelled = cancel_analysis_job(session, project.id or 0, job.job_id)
        assert cancelled is not None
        # A started run is signalled to stop; the worker finalizes it keeping published links.
        assert cancelled.status == "cancelling"

        assert cancel_analysis_job(session, project.id or 0, "missing-job") is None


_CANCEL_TRACE_CANDIDATE = {
    "paper_block_id": "p1-b1",
    "code_symbol_id": "models/net.py::Model.encode",
    "relation_type": "implements",
    "salience": 0.8,
    "relevance": 0.85,
    "confidence": 0.9,
    "rationale": "Model.encode implements the encoder projection.",
    "uncertainty_level": "low",
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


class _StubProvider:
    """Publishes one candidate on the first step, then loops on a read forever.

    The run never terminates on its own, so the test can interrupt it deterministically and
    assert the already-published link is preserved.
    """

    provider_name = "stub"
    model_name = "stub"

    def __init__(self) -> None:
        self.calls = 0

    def next_step(self, message, context, tool_results):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.calls == 1:
            return AgentProviderStep(
                action="tool",
                tool_name="publish_trace_candidates",
                arguments={"payload": {"candidates": [_CANCEL_TRACE_CANDIDATE]}},
            )
        return AgentProviderStep(action="tool", tool_name="list_paper_blocks", arguments={})


def test_cancel_running_worker_keeps_published_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.agent import analysis_jobs as aj

    engine = create_engine(
        f"sqlite:///{tmp_path / 'cancel.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project, _paper, _code = _artifacts(session, tmp_path)
        project_id = project.id or 0
        monkeypatch.setattr(aj, "_submit", lambda _job_id: None)
        job = create_analysis_job(session, project_id, AgentAnalysisJobCreate(kind="trace"))
        job_id = job.job_id

    # Point the worker at the test engine and a scripted provider.
    monkeypatch.setattr(aj, "engine", engine)
    monkeypatch.setattr(aj, "_provider_from_settings", lambda _session, for_analysis=False: (_StubProvider(), None))

    worker = threading.Thread(target=aj._execute_job, args=(job_id,))
    worker.start()
    try:
        # Wait until the first batch is published, then interrupt.
        published = False
        for _ in range(100):
            with Session(engine) as session:
                if session.exec(
                    select(TraceLink).where(
                        TraceLink.project_id == project_id, TraceLink.source == "agent"
                    )
                ).first():
                    published = True
                    break
            time.sleep(0.1)
        assert published, "worker never published the first batch"
        with Session(engine) as session:
            cancelled = cancel_analysis_job(session, project_id, job_id)
            assert cancelled is not None and cancelled.status == "cancelling"
    finally:
        worker.join(timeout=30)
    assert not worker.is_alive(), "worker did not stop after cancel"

    with Session(engine) as session:
        final = session.get(AgentAnalysisJob, job_id)
        links = session.exec(
            select(TraceLink).where(
                TraceLink.project_id == project_id, TraceLink.source == "agent"
            )
        ).all()
    # Finished by cancellation but marked succeeded, with the published link preserved.
    assert final is not None and final.status == "succeeded"
    assert final.progress_json.get("code") == "analysis_cancelled"
    assert "中止" in final.progress_json.get("message", "")
    assert len(links) >= 1
