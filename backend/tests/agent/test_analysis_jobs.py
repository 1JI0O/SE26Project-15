import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.models.entities import (
    AgentAnalysisJob,
    AgentConversation,
    AgentRun,
    CodeRepository,
    PaperDocument,
    Project,
    TraceLink,
)
from app.schemas.agent import AgentAnalysisJobCreate
from app.services import workspace_service
from app.services.agent.analysis_jobs import _persist_artifact, create_analysis_job
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
            "schema_version": "trace-agent-v1",
            "candidates": [
                {
                    "paper_block_id": "p1-b1",
                    "code_symbol_id": "models/net.py::Model.encode",
                    "relation_type": "implements",
                    "confidence": 0.91,
                    "rationale": "The encoder projection is implemented by Model.encode.",
                    "uncertainty_level": "low",
                    "uncertainty_reasons": [],
                    "paper_evidence": {"block_id": "p1-b1", "quote": "uses an encoder projection"},
                    "code_evidence": {
                        "symbol_id": "models/net.py::Model.encode",
                        "path": "models/net.py",
                        "line_start": 5,
                        "line_end": 6,
                        "quote": "return self.proj(x)",
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

    assert link.status == "proposed"
    assert link.source == "agent"
    assert {item["side"] for item in link.evidence_json} == {"paper", "code"}
    assert link.evidence_json[1]["line_start"] == 5


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
