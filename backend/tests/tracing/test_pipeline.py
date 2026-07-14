from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.db.migration_runner import upgrade_database
from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink
from app.services.tracing.lifecycle import record_artifact_revision_change
from app.services.tracing.provider import (
    CompatibleRESTProvider,
    LLMExplanation,
    LLMUncertainty,
    ProviderFailure,
)
from app.services.tracing.service import suggest_and_persist


class ValidProvider:
    provider_name = "fake"
    model_name = "fake-trace-model"

    def explain(self, contexts: list[dict[str, object]]) -> list[LLMExplanation]:
        context = contexts[0]
        paper = context["paper"]
        code = context["code"]
        assert isinstance(paper, dict)
        assert isinstance(code, dict)
        return [
            LLMExplanation(
                candidate_id=str(context["candidate_id"]),
                relation_type="implements",
                confidence=0.9,
                rationale="The code implements the residual block described by the paper.",
                evidence=[
                    {
                        "side": "paper",
                        "ref": str(paper["ref"]),
                        "quote": str(paper["text"]),
                    },
                    {
                        "side": "code",
                        "ref": str(code["ref"]),
                        "quote": str(code["text"]),
                    },
                ],
                uncertainty=LLMUncertainty(level="low", reasons=[]),
            )
        ]


class InvalidEvidenceProvider(ValidProvider):
    def explain(self, contexts: list[dict[str, object]]) -> list[LLMExplanation]:
        result = super().explain(contexts)
        result[0].evidence[0]["quote"] = "hallucinated paper quote"
        return result


class FailingProvider(ValidProvider):
    def explain(self, contexts: list[dict[str, object]]) -> list[LLMExplanation]:
        raise ProviderFailure("llm_timeout")


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


def test_static_pipeline_persists_double_sided_evidence() -> None:
    with _session() as session:
        project, paper, code = _artifacts(session)
        items, mode, degraded, reason = suggest_and_persist(
            session,
            project.id or 0,
            paper,
            code,
            use_llm=False,
        )

    assert items
    assert mode == "static"
    assert not degraded
    assert reason is None
    assert {evidence.side for evidence in items[0].evidence} == {"paper", "code"}
    assert items[0].status == "proposed"


def test_valid_llm_explanation_is_fused_and_manual_status_is_preserved() -> None:
    with _session() as session:
        project, paper, code = _artifacts(session)
        items, mode, degraded, _ = suggest_and_persist(
            session,
            project.id or 0,
            paper,
            code,
            use_llm=True,
            provider=ValidProvider(),
        )
        assert mode == "static+llm"
        assert not degraded
        assert items[0].model is not None
        link = session.get(TraceLink, 1)
        assert link is not None
        link.status = "accepted"
        session.add(link)
        session.commit()

        rerun, _, _, _ = suggest_and_persist(
            session,
            project.id or 0,
            paper,
            code,
            use_llm=True,
            provider=ValidProvider(),
        )

    assert rerun[0].status == "accepted"


def test_invalid_or_failed_llm_output_degrades_without_persisting_it() -> None:
    for provider, expected_reason in [
        (InvalidEvidenceProvider(), "llm_evidence_invalid"),
        (FailingProvider(), "llm_timeout"),
    ]:
        with _session() as session:
            project, paper, code = _artifacts(session)
            items, mode, degraded, reason = suggest_and_persist(
                session,
                project.id or 0,
                paper,
                code,
                use_llm=True,
                provider=provider,
            )
            assert items[0].source == "static"
            assert "hallucinated" not in str(items[0].evidence)
        assert mode == "static"
        assert degraded
        assert reason == expected_reason


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
        suggest_and_persist(
            session,
            project.id or 0,
            paper,
            code,
            use_llm=False,
        )
        link = session.get(TraceLink, 1)
        assert link is not None
        link.status = "accepted"
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
