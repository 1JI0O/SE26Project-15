from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.db.migration_runner import upgrade_database
from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink
from app.services.tracing.lifecycle import record_artifact_revision_change
from app.services.tracing.provider import CompatibleRESTProvider, ProviderFailure
from app.services.tracing.service import suggest_and_persist


def _accepted_link(project: Project, paper: PaperDocument, code: CodeRepository) -> TraceLink:
    return TraceLink(
        project_id=project.id or 0,
        paper_document_id=paper.id,
        paper_ref="p3-b12",
        code_repository_id=code.id,
        code_revision=code.revision,
        code_ref="models/resnet.py::BasicBlock.forward",
        relation_type="implements",
        source="agent",
        status="accepted",
        fingerprint="fixed-accepted-fp",
    )


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _artifacts(session: Session) -> tuple[Project, PaperDocument, CodeRepository]:
    project = Project(name="Trace fixture")
    session.add(project)
    session.commit()
    session.refresh(project)
    paper = PaperDocument(
        project_id=project.id or 0,
        filename="paper.pdf",
        storage_path="paper.pdf",
        title="Residual Networks",
        abstract="",
        sections_json=[{"title": "Residual Block", "page": 3}],
        paragraphs_json=[
            {
                "id": "p3-b12",
                "page": 3,
                "text": "A residual BasicBlock adds the shortcut input to the learned branch.",
            }
        ],
    )
    code = CodeRepository(
        project_id=project.id or 0,
        filename="repo.zip",
        storage_path="repo.zip",
        file_tree_json=[{"path": "models/resnet.py"}],
        symbols_json=[
            {
                "id": "models/resnet.py::BasicBlock.forward",
                "kind": "method",
                "path": "models/resnet.py",
                "name": "forward",
                "qualified_name": "BasicBlock.forward",
                "line_start": 24,
                "line_end": 31,
                "signature": "def forward(self, x)",
                "docstring": "Apply the residual shortcut and learned branch.",
                "calls": [{"name": "shortcut"}],
            }
        ],
        imports_json=[],
        pytorch_candidates_json=[],
        tensor_graph_json={
            "nodes": [
                {
                    "id": "add",
                    "symbol_id": "models/resnet.py::BasicBlock.forward",
                }
            ],
            "edges": [],
        },
    )
    session.add(paper)
    session.add(code)
    session.commit()
    session.refresh(paper)
    session.refresh(code)
    return project, paper, code


def test_static_pipeline_is_retired_and_persists_nothing() -> None:
    """The local keyword-overlap path must never write TraceLinks (architecture doc §15)."""

    with _session() as session:
        project, paper, code = _artifacts(session)
        items, mode, degraded, reason = suggest_and_persist(
            session,
            project.id or 0,
            paper,
            code,
            use_llm=False,
        )

        assert items == []
        assert mode == "static"
        assert degraded
        assert reason == "static_candidates_retired"
        assert session.exec(select(TraceLink)).all() == []


def test_retired_suggest_preserves_existing_accepted_link() -> None:
    with _session() as session:
        project, paper, code = _artifacts(session)
        link = _accepted_link(project, paper, code)
        session.add(link)
        session.commit()

        suggest_and_persist(session, project.id or 0, paper, code, use_llm=True, provider=None)

        session.refresh(link)
        assert link.status == "accepted"


@pytest.mark.parametrize(
    ("status_code", "body", "reason"),
    [
        (429, {}, "llm_rate_limited"),
        (503, {}, "llm_upstream_error"),
        (400, {}, "llm_request_rejected"),
        (200, {"choices": []}, "llm_invalid_json"),
    ],
)
def test_compatible_provider_maps_failures_to_safe_reason_codes(
    monkeypatch,
    status_code: int,
    body: dict[str, object],
    reason: str,
) -> None:
    class Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self) -> dict[str, object]:
            return body

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Response())
    provider = CompatibleRESTProvider("https://example.invalid/v1", "secret", "fake", 1)
    with pytest.raises(ProviderFailure) as caught:
        provider.explain([])
    assert caught.value.reason == reason


def test_compatible_provider_maps_timeout_without_exposing_request(
    monkeypatch,
) -> None:
    def timeout(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", timeout)
    provider = CompatibleRESTProvider("https://example.invalid/v1", "secret", "fake", 1)
    with pytest.raises(ProviderFailure) as caught:
        provider.explain([])
    assert caught.value.reason == "llm_timeout"


def test_code_revision_marks_accepted_trace_stale() -> None:
    with _session() as session:
        project, paper, code = _artifacts(session)
        link = _accepted_link(project, paper, code)
        session.add(link)
        session.commit()

        changed = record_artifact_revision_change(
            session,
            project.id or 0,
            "code",
            code.id or 0,
            "code_saved",
        )
        session.commit()
        session.refresh(link)
        session.refresh(code)

    assert changed == 1
    assert code.revision == 2
    assert link.status == "stale"
    assert link.stale_reason == "code_saved"


def test_legacy_sqlite_schema_is_upgraded_and_old_trace_is_stale(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE project (id INTEGER PRIMARY KEY, name TEXT, "
                "description TEXT, created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE paper_document (id INTEGER PRIMARY KEY, "
                "project_id INTEGER, filename TEXT, storage_path TEXT, title TEXT, "
                "abstract TEXT, sections_json JSON, paragraphs_json JSON, "
                "created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE code_repository (id INTEGER PRIMARY KEY, "
                "project_id INTEGER, filename TEXT, storage_path TEXT, "
                "file_tree_json JSON, symbols_json JSON, imports_json JSON, "
                "pytorch_candidates_json JSON, created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE trace_link (id INTEGER PRIMARY KEY, project_id INTEGER, "
                "paper_ref TEXT, code_ref TEXT, relation_type TEXT, confidence FLOAT, "
                "rationale TEXT, created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO trace_link VALUES "
                "(1, 1, 'p1', 'a.py::f', 'implements', 0.5, '', CURRENT_TIMESTAMP)"
            )
        )

    upgrade_database(engine, SQLModel.metadata)

    assert "trace_id" in {column["name"] for column in inspect(engine).get_columns("trace_link")}
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT trace_id, source, status FROM trace_link WHERE id = 1")
        ).one()
    assert tuple(row) == ("trace-legacy-1", "legacy", "stale")
