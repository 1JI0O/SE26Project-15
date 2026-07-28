import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    AgentRunEvent,
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
    build_conflict_context,
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
    # Force the Windows-style line ending on every platform so CI locks the
    # newline-only false-positive regression.
    (edits / "unchanged.py").write_bytes(b"VALUE = 1\r\n")
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
        session.add(
            TraceLink(
                project_id=project.id or 0,
                paper_document_id=paper.id,
                paper_ref="paper-method",
                code_repository_id=code.id,
                code_revision=1,
                code_ref="model.py::transform-secondary",
                code_target_id=target.target_id,
                relation_type="mentions",
                confidence=0.7,
            )
        )
        session.commit()
        affected = list_affected_traces(session, code)
        context = build_conflict_context(session, code, paper, 12_000)

    assert affected[0]["trace_id"] == link.trace_id
    assert affected[0]["matched_by"] == "code_target"
    assert affected[0]["previously_accepted"] is True
    assert context["schema_version"] == "conflict-context-v1"
    assert context["coverage"]["complete"] is True
    assert context["files"][0]["impact"]["affected_symbols"][0]["id"] == "model.py::transform"
    assert len(context["affected_traces"]) == 2
    assert len(context["paper_blocks"]) == 1
    assert context["paper_blocks"][0]["id"] == "paper-method"
    assert len(context["paper_blocks"][0]["trace_ids"]) == 2


def test_conflict_context_is_bounded_and_reports_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session() as session:
        _project, paper, code = _artifacts(session, tmp_path, monkeypatch)
        context = build_conflict_context(session, code, paper, 1000)

    assert context["coverage"]["complete"] is False
    assert "files.diff" in context["coverage"]["truncated_sections"]
    assert context["coverage"]["total_file_count"] == 1
    assert context["summary"]["changed_file_count"] == 1
    assert len(json.dumps(context, ensure_ascii=False, separators=(",", ":"))) <= 1000


def test_get_conflict_context_tool_uses_single_change_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import change_analysis

    with _session() as session:
        project, paper, code = _artifacts(session, tmp_path, monkeypatch)
        original = change_analysis.collect_repository_changes
        calls = 0

        def counted(repository):  # noqa: ANN001, ANN202
            nonlocal calls
            calls += 1
            return original(repository)

        monkeypatch.setattr(change_analysis, "collect_repository_changes", counted)
        context = execute_tool(
            session,
            project.id or 0,
            code.id or 0,
            paper.id,
            2,
            "get_conflict_context",
            {},
        )

    assert calls == 1
    assert context["repository_revision"] == 1
    assert context["files"][0]["path"] == "model.py"


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
                        },
                        {
                            "side": "before",
                            "path": "model.py",
                            "line_start": 2,
                            "line_end": 2,
                            "quote": "",
                        },
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
        payload["items"][0]["change_evidence"] = [
            {
                "side": "after",
                "path": "model.py",
                "line_start": 2,
                "line_end": 2,
                "quote": "",
            }
        ]
        with pytest.raises(ValidationError):
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
    assert len(result["payload"]["items"][0]["change_evidence"]) == 1
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

    def __init__(self) -> None:
        self.calls = 0
        self.first_tool_results = None

    def next_step(self, message, context, tool_results):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.first_tool_results is None:
            self.first_tool_results = tool_results
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


class _RepeatContextProvider(_ConflictProvider):
    def next_step(self, message, context, tool_results):  # noqa: ANN001, ANN201
        if self.calls == 0:
            self.calls = 1
            self.first_tool_results = tool_results
            return AgentProviderStep(
                action="tool",
                tool_name="get_conflict_context",
                arguments={},
            )
        return super().next_step(message, context, tool_results)


def test_conflict_worker_reuses_prefetched_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'conflict-cache.db'}",
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

    provider = _RepeatContextProvider()
    original_execute = analysis_jobs.execute_tool
    context_calls = 0

    def counted_execute(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal context_calls
        tool_name = args[5] if len(args) > 5 else kwargs.get("tool_name")
        if tool_name == "get_conflict_context":
            context_calls += 1
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(analysis_jobs, "engine", engine)
    monkeypatch.setattr(analysis_jobs, "execute_tool", counted_execute)
    monkeypatch.setattr(
        analysis_jobs,
        "_provider_from_settings",
        lambda _session, for_analysis=False: (provider, None),
    )
    analysis_jobs._execute_job(job_id)

    with Session(engine) as session:
        completed = session.get(AgentAnalysisJob, job_id)

    assert completed is not None and completed.status == "succeeded"
    assert provider.calls == 2
    assert context_calls == 1


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
    provider = _ConflictProvider()
    monkeypatch.setattr(
        analysis_jobs,
        "_provider_from_settings",
        lambda _session, for_analysis=False: (provider, None),
    )
    analysis_jobs._execute_job(job_id)

    with Session(engine) as session:
        completed = session.get(AgentAnalysisJob, job_id)
        artifact = session.exec(
            select(AgentAnalysisArtifact).where(AgentAnalysisArtifact.job_id == job_id)
        ).one()
        prefetch_event = session.exec(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == completed.agent_run_id,
                AgentRunEvent.event_type == "analysis.tool.completed",
            )
        ).first()
        publish_event = session.exec(
            select(AgentRunEvent).where(
                AgentRunEvent.run_id == completed.agent_run_id,
                AgentRunEvent.event_type == "analysis.tool.started",
            )
        ).first()

    assert completed is not None and completed.status == "succeeded"
    assert provider.calls == 1
    assert provider.first_tool_results[0]["tool"] == "get_conflict_context"
    assert provider.first_tool_results[0]["prefetched"] is True
    assert prefetch_event is not None
    assert prefetch_event.payload_json["step"] == 0
    assert prefetch_event.payload_json["coverage_complete"] is True
    assert publish_event is not None
    assert publish_event.payload_json["budget"] == 32
    assert artifact.kind == "conflict"
    assert artifact.schema_version == "conflict-agent-v1"
    assert artifact.payload_json["summary"]["high"] == 1
