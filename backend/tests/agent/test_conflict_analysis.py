import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    CodeRepository,
    CodeTarget,
    PaperDocument,
    Project,
    TraceLink,
    utc_now,
)
from app.schemas.agent import AgentAnalysisJobCreate
from app.services.agent import analysis_jobs
from app.services.agent.analysis_jobs import cancel_analysis_job, create_analysis_job
from app.services.agent.analysis_tools import execute_tool
from app.services.agent.provider import AgentProviderStep
from app.services.analysis_jobs import ANALYZER_VERSION, repository_edits_root
from app.services.change_analysis import (
    build_change_summary,
    collect_repository_changes,
    get_change_impact,
    list_affected_traces,
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
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Project, PaperDocument, CodeRepository]:
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    project = Project(name="Conflict fixture")
    session.add(project)
    session.commit()
    session.refresh(project)

    before = "def transform(x):\n    return x + 1\n"
    archive_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo/model.py", before)
        archive.writestr("repo/unchanged.py", "VALUE = 1\n")
    symbol = {
        "id": "model.py::transform",
        "path": "model.py",
        "name": "transform",
        "kind": "function",
        "line_start": 1,
        "line_end": 2,
    }
    code = CodeRepository(
        project_id=project.id or 0,
        filename="repo.zip",
        storage_path=str(archive_path),
        file_tree_json=[
            {"path": "model.py", "language": "python", "editable": True},
            {"path": "unchanged.py", "language": "python", "editable": True},
        ],
        symbols_json=[symbol],
        imports_json=[],
        pytorch_candidates_json=[],
        analysis_json={
            "symbols": [symbol],
            "calls": [
                {
                    "caller_symbol_id": "train.py::run",
                    "callee": "transform",
                    "path": "train.py",
                    "line_start": 8,
                }
            ],
        },
        analysis_revision=1,
        analysis_version=ANALYZER_VERSION,
        analysis_status="ready",
    )
    block = {
        "id": "paper-method",
        "kind": "paragraph",
        "text": "The transform adds one to the input.",
        "page_number": 2,
        "section_path": ["Method"],
    }
    paper = PaperDocument(
        project_id=project.id or 0,
        filename="paper.pdf",
        storage_path="paper.pdf",
        sections_json=[],
        paragraphs_json=[block],
        pages_json=[{"page_number": 2, "blocks": [block]}],
    )
    session.add(code)
    session.add(paper)
    session.commit()
    session.refresh(code)
    session.refresh(paper)

    edits = repository_edits_root(code)
    edits.mkdir(parents=True)
    (edits / "model.py").write_text(
        "def transform(x):\n    return x * 2\n",
        encoding="utf-8",
    )
    (edits / "unchanged.py").write_text("VALUE = 1\n", encoding="utf-8")
    return project, paper, code


def test_collect_changes_ignores_unchanged_overlay_and_maps_impact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session() as session:
        project, _paper, code = _artifacts(session, tmp_path, monkeypatch)
        changes = collect_repository_changes(code)
        impact = get_change_impact(code, "model.py")
        summary = build_change_summary(session, project.id or 0)

    assert changes["changed_file_count"] == 1
    assert changes["files"][0]["path"] == "model.py"
    assert changes["files"][0]["before_sha256"] != changes["files"][0]["after_sha256"]
    assert "return x + 1" in changes["files"][0]["diff"]
    assert impact["affected_symbols"][0]["id"] == "model.py::transform"
    assert impact["callers"][0]["caller_symbol_id"] == "train.py::run"
    assert summary["has_changes"] is True
    assert summary["analysis_current"] is True


def test_affected_traces_prefers_precise_target_and_preserves_review_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session() as session:
        project, paper, code = _artifacts(session, tmp_path, monkeypatch)
        target = CodeTarget(
            project_id=project.id or 0,
            artifact_id="artifact-old",
            code_repository_id=code.id or 0,
            code_revision=1,
            path="model.py",
            line_start=2,
            line_end=2,
            quote="return x + 1",
            code_quote_hash="a" * 64,
            role="tensor_transform",
            fingerprint="b" * 64,
        )
        session.add(target)
        session.flush()
        link = TraceLink(
            project_id=project.id or 0,
            paper_document_id=paper.id,
            paper_ref="paper-method",
            code_repository_id=code.id,
            code_revision=1,
            code_ref="model.py::transform",
            code_target_id=target.target_id,
            relation_type="implements",
            confidence=0.9,
            status="stale",
            stale_reason="code_revision_changed",
            decided_at=utc_now(),
        )
        session.add(link)
        session.commit()
        affected = list_affected_traces(session, code)

    assert affected[0]["trace_id"] == link.trace_id
    assert affected[0]["matched_by"] == "code_target"
    assert affected[0]["previously_accepted"] is True


def test_publish_conflict_report_validates_and_assigns_stable_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session() as session:
        project, paper, code = _artifacts(session, tmp_path, monkeypatch)
        link = TraceLink(
            project_id=project.id or 0,
            paper_document_id=paper.id,
            paper_ref="paper-method",
            code_repository_id=code.id,
            code_revision=1,
            code_ref="model.py::transform",
            relation_type="implements",
            confidence=0.9,
        )
        session.add(link)
        session.commit()
        payload = {
            "repository_revision": 1,
            "overall_risk": "高风险",
            "summary": {"total": 999},
            "items": [
                {
                    "id": "model-generated-id",
                    "category": "paper_consistency",
                    "severity": "高风险",
                    "confidence": "95%",
                    "title": "转换语义发生变化",
                    "description": "乘法逻辑不再实现论文描述的加一运算。",
                    "change_evidence": [
                        {
                            "side": "修改后",
                            "path": "model.py",
                            "line_start": 2,
                            "line_end": 2,
                            "quote": "return x * 2",
                        }
                    ],
                    "affected_symbols": ["model.py::transform"],
                    "affected_files": ["invented.py"],
                    "trace_refs": [{"trace_id": link.trace_id}],
                    "paper_evidence": [
                        {
                            "block_id": "paper-method",
                            "quote": "The transform adds one to the input.",
                            "association": "trace",
                        }
                    ],
                    "recommendations": ["恢复加一运算，或在论文说明中记录这一偏差。"],
                    "verification_steps": ["运行转换函数的输入输出回归测试。"],
                }
            ],
        }
        result = execute_tool(
            session,
            project.id or 0,
            code.id or 0,
            paper.id,
            2,
            "publish_conflict_report",
            {"payload": payload},
        )
        payload["items"][0]["title"] = "English-only title"
        with pytest.raises(ValueError, match="conflict_output_must_be_chinese"):
            execute_tool(
                session,
                project.id or 0,
                code.id or 0,
                paper.id,
                2,
                "publish_conflict_report",
                {"payload": payload},
            )
        payload["items"][0]["title"] = "转换语义发生变化"
        payload["items"][0]["change_evidence"][0]["quote"] = "invented code"
        with pytest.raises(ValueError, match="conflict_code_evidence_quote_invalid"):
            execute_tool(
                session,
                project.id or 0,
                code.id or 0,
                paper.id,
                2,
                "publish_conflict_report",
                {"payload": payload},
            )

    assert result["payload"]["schema_version"] == "conflict-agent-v1"
    assert result["payload"]["language"] == "zh-CN"
    assert result["payload"]["items"][0]["confidence"] == 0.95
    assert result["payload"]["items"][0]["severity"] == "high"
    assert result["payload"]["items"][0]["id"].startswith("conflict-")
    assert result["payload"]["items"][0]["id"] != "model-generated-id"
    assert result["payload"]["items"][0]["affected_files"] == ["model.py"]
    assert result["payload"]["summary"]["high"] == 1


def test_conflict_job_preconditions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_jobs, "_submit", lambda _job_id: None)
    with _session() as session:
        project, _paper, code = _artifacts(session, tmp_path, monkeypatch)
        job = create_analysis_job(
            session,
            project.id or 0,
            AgentAnalysisJobCreate(kind="conflict"),
        )
        assert job.kind == "conflict"
        assert job.paper_document_id is not None
        cancelled = cancel_analysis_job(session, project.id or 0, job.job_id)
        assert cancelled is not None
        assert cancelled.status == "succeeded"
        assert cancelled.progress_json["code"] == "analysis_cancelled"

        (repository_edits_root(code) / "model.py").write_text(
            "def transform(x):\n    return x + 1\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="no_code_changes"):
            create_analysis_job(
                session,
                project.id or 0,
                AgentAnalysisJobCreate(kind="conflict", force=True),
            )

        (repository_edits_root(code) / "model.py").write_text(
            "def transform(x):\n    return x * 3\n",
            encoding="utf-8",
        )
        code.analysis_status = "stale"
        session.add(code)
        session.commit()
        with pytest.raises(ValueError, match="repository_analysis_pending"):
            create_analysis_job(
                session,
                project.id or 0,
                AgentAnalysisJobCreate(kind="conflict", force=True),
            )


class _ConflictProvider:
    provider_name = "stub"
    model_name = "stub"

    def next_step(self, message, context, tool_results):  # noqa: ANN001, ANN201
        revision = context["active_context"]["repository_revision"]
        return AgentProviderStep(
            action="tool",
            tool_name="publish_conflict_report",
            arguments={
                "payload": {
                    "repository_revision": revision,
                    "overall_risk": "high",
                    "items": [
                        {
                            "category": "paper_consistency",
                            "severity": "high",
                            "confidence": 0.95,
                            "title": "转换语义发生变化",
                            "description": "当前保存的乘法实现与论文描述不一致。",
                            "change_evidence": [
                                {
                                    "side": "after",
                                    "path": "model.py",
                                    "line_start": 2,
                                    "line_end": 2,
                                    "quote": "return x * 2",
                                }
                            ],
                            "paper_evidence": [
                                {
                                    "block_id": "paper-method",
                                    "quote": "The transform adds one to the input.",
                                    "association": "inferred",
                                }
                            ],
                            "recommendations": ["确认这一实现偏差是否为有意修改。"],
                            "verification_steps": ["执行转换函数的回归测试。"],
                        }
                    ],
                }
            },
        )


def test_conflict_worker_publishes_terminal_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'conflict-worker.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project, _paper, _code = _artifacts(session, tmp_path, monkeypatch)
        project_id = project.id or 0
        monkeypatch.setattr(analysis_jobs, "_submit", lambda _job_id: None)
        job = create_analysis_job(
            session,
            project_id,
            AgentAnalysisJobCreate(kind="conflict"),
        )
        job_id = job.job_id

    monkeypatch.setattr(analysis_jobs, "engine", engine)
    monkeypatch.setattr(
        analysis_jobs,
        "_provider_from_settings",
        lambda _session, for_analysis=False: (_ConflictProvider(), None),
    )
    analysis_jobs._execute_job(job_id)

    with Session(engine) as session:
        completed = session.get(AgentAnalysisJob, job_id)
        artifact = session.exec(
            select(AgentAnalysisArtifact).where(AgentAnalysisArtifact.job_id == job_id)
        ).one()

    assert completed is not None and completed.status == "succeeded"
    assert artifact.kind == "conflict"
    assert artifact.schema_version == "conflict-agent-v1"
    assert artifact.payload_json["summary"]["high"] == 1
