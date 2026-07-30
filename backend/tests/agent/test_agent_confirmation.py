import zipfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink, utc_now
from app.schemas.agent import AgentQueryRequest
from app.services.agent.provider import AgentProviderStep
from app.services.agent.service import decide_confirmation, query_agent, read_confirmation


class StepProvider:
    provider_name = "fake"
    model_name = "fake-agent-model"

    def __init__(self, steps: list[AgentProviderStep]) -> None:
        self.steps = steps

    def next_step(
        self,
        message: str,
        context: dict[str, object],
        tool_results: list[dict[str, object]],
    ) -> AgentProviderStep:
        return self.steps.pop(0)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _fixture(session: Session, tmp_path: Path) -> tuple[Project, CodeRepository, TraceLink]:
    archive_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo/models/net.py", "class Net:\n    pass\n")
    project = Project(name="Agent fixture")
    session.add(project)
    session.commit()
    session.refresh(project)
    paper = PaperDocument(
        project_id=project.id or 0,
        filename="paper.pdf",
        storage_path="paper.pdf",
        sections_json=[],
        paragraphs_json=[{"id": "p1", "text": "A network implementation."}],
    )
    code = CodeRepository(
        project_id=project.id or 0,
        filename="repo.zip",
        storage_path=str(archive_path),
        file_tree_json=[{"path": "models/net.py", "language": "python"}],
        symbols_json=[
            {
                "id": "models/net.py::Net",
                "path": "models/net.py",
                "name": "Net",
            }
        ],
        imports_json=[],
        pytorch_candidates_json=[],
    )
    session.add(paper)
    session.add(code)
    session.commit()
    session.refresh(paper)
    session.refresh(code)
    trace = TraceLink(
        project_id=project.id or 0,
        paper_document_id=paper.id,
        paper_ref="p1",
        code_repository_id=code.id,
        code_ref="models/net.py::Net",
        relation_type="implements",
        confidence=0.7,
        static_confidence=0.7,
        evidence_json=[
            {"side": "paper", "ref": "p1", "quote": "A network implementation."},
            {"side": "code", "ref": "models/net.py:1", "quote": "class Net"},
        ],
        fingerprint="fixture-trace",
    )
    session.add(trace)
    session.commit()
    session.refresh(trace)
    return project, code, trace


def _write_step(tool_name: str, arguments: dict[str, object]) -> AgentProviderStep:
    return AgentProviderStep(
        action="tool",
        answer="Please confirm this operation.",
        tool_name=tool_name,
        arguments=arguments,
    )


def test_update_trace_has_no_effect_before_confirmation_and_executes_once(
    tmp_path: Path,
) -> None:
    with _session() as session:
        project, _, trace = _fixture(session, tmp_path)
        provider = StepProvider(
            [_write_step("update_trace_status", {"trace_id": trace.trace_id, "status": "accepted"})]
        )
        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Accept the trace"),
            provider=provider,
        )
        session.refresh(trace)
        assert trace.status == "proposed"
        assert response.confirmation is not None
        assert response.confirmation.status == "pending"

        decided = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "accept",
        )
        repeated = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "accept",
        )
        session.refresh(trace)

    assert decided is not None and decided.status == "executed"
    assert repeated is not None and repeated.status == "executed"
    assert trace.status == "accepted"


def test_rejected_and_expired_requests_never_execute(tmp_path: Path) -> None:
    with _session() as session:
        project, _, trace = _fixture(session, tmp_path)
        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Reject trace"),
            provider=StepProvider(
                [
                    _write_step(
                        "update_trace_status",
                        {"trace_id": trace.trace_id, "status": "rejected"},
                    )
                ]
            ),
        )
        assert response.confirmation is not None
        rejected = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "reject",
        )
        session.refresh(trace)
        assert rejected is not None and rejected.status == "rejected"
        assert trace.status == "proposed"

        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Accept trace later"),
            provider=StepProvider(
                [
                    _write_step(
                        "update_trace_status",
                        {"trace_id": trace.trace_id, "status": "accepted"},
                    )
                ]
            ),
        )
        assert response.confirmation is not None
        request = read_confirmation(session, project.id or 0, response.confirmation.confirmation_id)
        assert request is not None
        request.expires_at = utc_now() - timedelta(seconds=1)
        session.add(request)
        session.commit()
        expired = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "accept",
        )
        session.refresh(trace)

    assert expired is not None and expired.status == "expired"
    assert trace.status == "proposed"


def test_save_code_confirmation_checks_hash_and_marks_trace_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    with _session() as session:
        project, code, trace = _fixture(session, tmp_path)
        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Save the edit"),
            provider=StepProvider(
                [
                    _write_step(
                        "save_code_file",
                        {"path": "models/net.py", "content": "class Net:\n    value = 1\n"},
                    )
                ]
            ),
        )
        assert response.confirmation is not None
        assert "content" not in response.confirmation.parameter_summary
        session.refresh(code)
        assert code.revision == 1

        decided = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "accept",
        )
        session.refresh(code)
        session.refresh(trace)

    assert decided is not None and decided.status == "executed"
    assert code.revision == 2
    assert trace.status == "stale"
    assert decided.result_json is not None
    assert decided.result_json["path"] == "models/net.py"


def test_read_tool_needs_no_confirmation_and_unknown_tool_is_rejected(
    tmp_path: Path,
) -> None:
    with _session() as session:
        project, _, _ = _fixture(session, tmp_path)
        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Read paper block"),
            provider=StepProvider(
                [
                    AgentProviderStep(
                        action="tool",
                        tool_name="get_paper_block",
                        arguments={"block_id": "p1"},
                    ),
                    AgentProviderStep(action="final", answer="Found it."),
                ]
            ),
        )
        assert response.answer == "Found it."
        assert response.confirmation is None

        unknown = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Run shell"),
            provider=StepProvider(
                [AgentProviderStep(action="tool", tool_name="shell", arguments={})]
            ),
        )

    assert unknown.degraded
    assert unknown.degraded_reason == "unknown_tool"


def test_invalid_save_path_creates_no_confirmation(tmp_path: Path) -> None:
    with _session() as session:
        project, _, _ = _fixture(session, tmp_path)
        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Escape repository"),
            provider=StepProvider(
                [
                    _write_step(
                        "save_code_file",
                        {"path": "../outside.py", "content": "bad"},
                    )
                ]
            ),
        )

    assert response.degraded
    assert response.degraded_reason == "invalid_tool_arguments"
    assert response.confirmation is None


def test_agent_without_llm_degrades_without_confirmation(tmp_path: Path) -> None:
    with _session() as session:
        project, _, _ = _fixture(session, tmp_path)
        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Change the code"),
        )

    assert response.degraded
    assert response.degraded_reason == "llm_disabled"
    assert response.confirmation is None


def test_agent_created_trace_carries_anchored_evidence(tmp_path: Path) -> None:
    """A link the Agent creates by reference must still be decorable in both panes.

    The reader's decoration index keys highlights by evidence target id and drops any link
    whose id is null, so a link stored without evidence appears in the matrix and jumps
    correctly while leaving the paper and code panes unhighlighted and unclickable.
    """

    with _session() as session:
        project, _, _ = _fixture(session, tmp_path)
        provider = StepProvider(
            [
                _write_step(
                    "create_trace_link",
                    {
                        "paper_ref": "p1",
                        "code_ref": "models/net.py::Net",
                        "relation_type": "implements",
                        "confidence": 0.9,
                        "rationale": "Net implements the described network.",
                    },
                )
            ]
        )
        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Link p1 to Net"),
            provider=provider,
        )
        assert response.confirmation is not None
        decided = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "accept",
        )
        assert decided is not None and decided.status == "executed", decided.error_summary
        created = session.exec(
            select(TraceLink).where(TraceLink.trace_id == decided.result_json["trace_id"])
        ).one()

        evidence = {item["side"]: item for item in created.evidence_json}
        assert set(evidence) == {"paper", "code"}
        assert evidence["paper"]["target_id"]
        assert evidence["code"]["target_id"]
        # Quotes come from the real block and the symbol's own lines.
        assert "network implementation" in evidence["paper"]["quote"]
        assert "class Net" in evidence["code"]["quote"]
        # The code pane filters targets by path and needs a line window to place the mark.
        assert evidence["code"]["path"] == "models/net.py"
        assert evidence["code"]["line_start"] == 1
