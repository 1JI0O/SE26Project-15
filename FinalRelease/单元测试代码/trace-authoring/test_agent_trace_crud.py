import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.core.config import settings
from app.models.entities import (
    CodeRepository,
    PaperDocument,
    Project,
    RagIndexState,
    TraceLink,
    utc_now,
)
from app.models.sync import LocalSyncOutbox, LocalSyncState
from app.schemas.agent import AgentQueryRequest
from app.services.agent.provider import AgentProviderStep
from app.services.agent.service import decide_confirmation, query_agent, read_confirmation
from app.services.agent.tools import execute_read_tool, validate_tool_arguments


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
        # List schema requires provider/name/prompt_version; provenance is stored separately.
        assert created.model_info_json["provider"]
        assert created.model_info_json["name"]
        assert created.model_info_json["prompt_version"] == "chat-create-trace-v1"
        assert created.provenance_json.get("source") == "agent_tool"
        assert (
            created.provenance_json.get("confirmation_id")
            == response.confirmation.confirmation_id
        )


def test_agent_trace_crud_filters_validates_and_invalidates_dependents(
    tmp_path: Path,
) -> None:
    with _session() as session:
        project, _, trace = _fixture(session, tmp_path)
        workspace_id = "11111111-1111-1111-1111-111111111111"
        project.sync_mode = "cloud_enabled"
        project.cloud_workspace_id = workspace_id
        session.add(project)
        session.add(
            LocalSyncState(
                workspace_id=workspace_id,
                device_id="22222222-2222-2222-2222-222222222222",
            )
        )
        session.add(
            RagIndexState(
                project_id=project.id or 0,
                scope="trace",
                status="ready",
                source_key="old-reviewed-corpus",
            )
        )
        other = Project(name="Other project")
        session.add(other)
        session.commit()

        queried = execute_read_tool(
            session,
            project.id or 0,
            "query_trace_links",
            {
                "paper_ref": "p1",
                "code_ref": "models/net.py::Net",
                "status": "proposed",
                "source": "static",
            },
        )
        assert queried["count"] == 1
        assert queried["items"][0]["id"] == trace.trace_id
        assert execute_read_tool(
            session,
            other.id or 0,
            "get_trace_link",
            {"trace_id": trace.trace_id},
        ) == {"found": False, "trace_id": trace.trace_id}

        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Refine this relation"),
            provider=StepProvider(
                [
                    _write_step(
                        "update_trace_link",
                        {
                            "trace_id": trace.trace_id,
                            "relation_type": "computes",
                            "confidence": 0.95,
                            "rationale": "The implementation computes the described network.",
                        },
                    )
                ]
            ),
        )
        assert response.confirmation is not None
        updated = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "accept",
        )
        session.refresh(trace)
        state = session.exec(
            select(RagIndexState).where(
                RagIndexState.project_id == project.id,
                RagIndexState.scope == "trace",
            )
        ).one()
        outbox = session.exec(
            select(LocalSyncOutbox).where(LocalSyncOutbox.entity_type == "trace_link")
        ).all()

        assert updated is not None and updated.status == "executed"
        assert updated.result_json["updated_fields"] == [
            "relation_type",
            "confidence",
            "rationale",
        ]
        assert (trace.relation_type, trace.confidence, trace.version) == ("computes", 0.95, 2)
        assert state.status == "pending"
        assert len(outbox) == 1
        assert outbox[0].base_version == 1
        assert outbox[0].payload_json["confidence"] == 0.95

        response = query_agent(
            session,
            project.id or 0,
            AgentQueryRequest(message="Remove this relation"),
            provider=StepProvider(
                [
                    _write_step(
                        "delete_trace_link",
                        {"trace_id": trace.trace_id, "reason": "Superseded by review."},
                    )
                ]
            ),
        )
        assert response.confirmation is not None
        deleted = decide_confirmation(
            session,
            project.id or 0,
            response.confirmation.confirmation_id,
            "accept",
        )
        session.refresh(trace)
        assert deleted is not None and deleted.status == "executed"
        assert trace.status == "rejected"
        assert trace.version == 3
        assert len(
            session.exec(
                select(LocalSyncOutbox).where(LocalSyncOutbox.entity_type == "trace_link")
            ).all()
        ) == 2


def test_agent_trace_mutation_schema_rejects_empty_patch_and_normalizes_relation() -> None:
    with pytest.raises(ValidationError, match="at_least_one_trace_field_required"):
        validate_tool_arguments("update_trace_link", {"trace_id": "trace-1"})

    updated = validate_tool_arguments(
        "update_trace_link",
        {"trace_id": "trace-1", "relation_type": "hallucinates"},
    )
    assert updated.relation_type == "mentions"

    created = validate_tool_arguments(
        "create_trace_link",
        {
            "paper_ref": "p1",
            "code_ref": "net.py:1",
            "relation_type": "hallucinates",
            "confidence": 0.8,
            "rationale": "Unknown model label is normalized.",
        },
    )
    assert created.relation_type == "mentions"


def test_agent_created_trace_survives_list_endpoint(tmp_path: Path) -> None:
    """After chat-tool create, GET /trace-links must return 200 (not schema-crash 500)."""

    from fastapi.testclient import TestClient

    from app.db.session import get_session
    from app.main import app

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with Session(engine) as session:
            project, _, _ = _fixture(session, tmp_path)
            project_id = project.id or 0
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
                project_id,
                AgentQueryRequest(message="Link p1 to Net"),
                provider=provider,
            )
            assert response.confirmation is not None
            decided = decide_confirmation(
                session,
                project_id,
                response.confirmation.confirmation_id,
                "accept",
            )
            assert decided is not None and decided.status == "executed", decided.error_summary
            created_id = decided.result_json["trace_id"]

        with TestClient(app) as client:
            listed = client.get(f"/api/v1/projects/{project_id}/trace-links")
            assert listed.status_code == 200, listed.text
            ids = {item["id"] for item in listed.json()}
            assert created_id in ids
            created = next(item for item in listed.json() if item["id"] == created_id)
            assert created["model"]["provider"]
            assert created["model"]["name"]
            assert created["model"]["prompt_version"] == "chat-create-trace-v1"
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_malformed_model_info_does_not_break_trace_list(tmp_path: Path) -> None:
    """Legacy chat-tool rows that stuffed provenance into model_info must still list."""

    from fastapi.testclient import TestClient

    from app.db.session import get_session
    from app.main import app
    from app.services.tracing.service import trace_to_read

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project, code, _ = _fixture(session, tmp_path)
        paper = session.exec(
            select(PaperDocument).where(PaperDocument.project_id == project.id)
        ).one()
        bad = TraceLink(
            project_id=project.id or 0,
            paper_document_id=paper.id,
            paper_ref="p1",
            code_repository_id=code.id,
            code_ref="models/net.py::Net",
            relation_type="implements",
            confidence=0.8,
            static_confidence=0,
            source="agent",
            rationale="legacy bad shape",
            model_info_json={
                "source": "agent_tool",
                "confirmation_id": "confirm-deadbeef",
            },
            provenance_json={},
            evidence_json=[
                {"side": "paper", "ref": "p1", "quote": "A network implementation."},
                {"side": "code", "ref": "models/net.py:1", "quote": "class Net"},
            ],
            fingerprint="legacy-bad-model-info",
            status="accepted",
        )
        session.add(bad)
        session.commit()
        session.refresh(bad)
        bad_id = bad.trace_id
        project_id = project.id or 0

        # Read-side defense: never raise; drop invalid model.
        read = trace_to_read(bad)
        assert read.model is None

    def session_override():
        with Session(engine) as scoped:
            yield scoped

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            listed = client.get(f"/api/v1/projects/{project_id}/trace-links")
            assert listed.status_code == 200, listed.text
            assert any(item["id"] == bad_id for item in listed.json())
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_prepare_write_accepts_page_block_and_line_range(tmp_path: Path) -> None:
    """Confirmation prep must accept the same refs execution / annotation mode use."""

    from app.services.agent.tools import prepare_write_request

    archive_path = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("repo/models/net.py", "class Net:\n    pass\n")

    with _session() as session:
        project = Project(name="Anchor prep fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        block = {
            "id": "p1-b6",
            "kind": "paragraph",
            "page": 1,
            "text": "We explore a new class of diffusion models.",
        }
        session.add(
            PaperDocument(
                project_id=project.id or 0,
                filename="paper.pdf",
                storage_path="paper.pdf",
                sections_json=[],
                paragraphs_json=[],  # Intentionally empty: only pages carry the block id.
                pages_json=[{"page_number": 1, "blocks": [block]}],
            )
        )
        session.add(
            CodeRepository(
                project_id=project.id or 0,
                filename="repo.zip",
                storage_path=str(archive_path),
                file_tree_json=[{"path": "models/net.py", "language": "python"}],
                symbols_json=[],
                imports_json=[],
                pytorch_candidates_json=[],
            )
        )
        session.commit()

        payload, summary = prepare_write_request(
            session,
            project.id or 0,
            "create_trace_link",
            {
                "paper_ref": "p1-b6",
                "code_ref": "models/net.py:1-2",
                "relation_type": "implements",
                "confidence": 0.85,
                "rationale": "Abstract maps to the Net class lines.",
            },
        )
        assert payload["paper_ref"] == "p1-b6"
        assert payload["code_ref"] == "models/net.py:1-2"
        assert summary["paper_ref"] == "p1-b6"


def test_create_trace_coerces_llm_relation_aliases(tmp_path: Path) -> None:
    """LLM often invents 'references'; store/list must use a schema enum value."""

    from fastapi.testclient import TestClient

    from app.db.session import get_session
    from app.main import app
    from app.schemas.traces import normalize_relation_type
    from app.services.agent.tools import CreateTraceArguments

    assert normalize_relation_type("references").value == "mentions"
    args = CreateTraceArguments(
        paper_ref="p1",
        code_ref="models/net.py::Net",
        relation_type="references",
        confidence=0.8,
        rationale="Abstract references the Net class.",
    )
    assert args.relation_type == "mentions"

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project, code, _ = _fixture(session, tmp_path)
        paper = session.exec(
            select(PaperDocument).where(PaperDocument.project_id == project.id)
        ).one()
        bad = TraceLink(
            project_id=project.id or 0,
            paper_document_id=paper.id,
            paper_ref="p1",
            code_repository_id=code.id,
            code_ref="models/net.py::Net",
            relation_type="references",
            confidence=0.8,
            static_confidence=0,
            source="agent",
            rationale="alias",
            model_info_json={
                "provider": "openai-compatible",
                "name": "fake",
                "prompt_version": "chat-create-trace-v1",
            },
            evidence_json=[
                {"side": "paper", "ref": "p1", "quote": "A network implementation."},
                {"side": "code", "ref": "models/net.py:1", "quote": "class Net"},
            ],
            fingerprint="alias-relation-type",
            status="accepted",
        )
        session.add(bad)
        session.commit()
        session.refresh(bad)
        bad_id = bad.trace_id
        project_id = project.id or 0

    def session_override():
        with Session(engine) as scoped:
            yield scoped

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            listed = client.get(f"/api/v1/projects/{project_id}/trace-links")
            assert listed.status_code == 200, listed.text
            created = next(item for item in listed.json() if item["id"] == bad_id)
            assert created["relation_type"] == "mentions"
    finally:
        app.dependency_overrides.pop(get_session, None)
