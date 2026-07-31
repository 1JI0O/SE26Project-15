from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.api.routes.traces import router
from app.db.session import get_session
from app.models.entities import (
    CodeRepository,
    PaperDocument,
    Project,
    RagIndexState,
    TraceLink,
)


def test_trace_api_generation_and_review_contract() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Trace API fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        session.add(
            PaperDocument(
                project_id=project.id or 0,
                filename="paper.pdf",
                storage_path="paper.pdf",
                sections_json=[],
                paragraphs_json=[
                    {
                        "id": "p1",
                        "text": "The BasicBlock implements a residual shortcut.",
                    }
                ],
            )
        )
        session.add(
            CodeRepository(
                project_id=project.id or 0,
                filename="repo.zip",
                storage_path="repo.zip",
                file_tree_json=[],
                symbols_json=[
                    {
                        "id": "models/net.py::BasicBlock",
                        "path": "models/net.py",
                        "name": "BasicBlock",
                        "line": 1,
                        "docstring": "Residual shortcut block.",
                    }
                ],
                imports_json=[],
                pytorch_candidates_json=[],
            )
        )
        session.commit()
        project_id = project.id or 0

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        # The legacy /suggest keyword path is retired: it never generates candidates.
        generated = client.post(
            f"/api/v1/projects/{project_id}/trace-links/suggest",
            json={"use_llm": False},
        )
        assert generated.status_code == 200
        payload = generated.json()
        assert payload["degraded"]
        assert payload["degraded_reason"] == "static_candidates_retired"
        assert payload["items"] == []

        # The review contract is exercised against a directly-created proposed link.
        created = client.post(
            f"/api/v1/projects/{project_id}/trace-links",
            json={
                "paper_ref": "p1",
                "code_ref": "models/net.py::BasicBlock",
                "relation_type": "implements",
                "confidence": 0.8,
                "rationale": "BasicBlock implements the residual shortcut.",
                "evidence": [
                    {"side": "paper", "ref": "p1", "quote": "residual shortcut"},
                    {
                        "side": "code",
                        "ref": "models/net.py::BasicBlock",
                        "quote": "class BasicBlock",
                        "path": "models/net.py",
                        "line_start": 1,
                        "line_end": 1,
                    },
                ],
            },
        )
        assert created.status_code == 201
        trace_id = created.json()["id"]

        accepted = client.patch(
            f"/api/v1/projects/{project_id}/trace-links/{trace_id}/status",
            json={"status": "accepted"},
        )
        repeated = client.patch(
            f"/api/v1/projects/{project_id}/trace-links/{trace_id}/status",
            json={"status": "rejected"},
        )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert repeated.status_code == 409


def test_batch_status_reviews_subset_then_all_remaining_proposed() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Batch review fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id or 0
        for index in range(3):
            session.add(
                TraceLink(
                    project_id=project_id,
                    paper_ref=f"p{index}",
                    code_ref=f"models/net.py::S{index}",
                    relation_type="implements",
                    confidence=0.8,
                    source="agent",
                    evidence_json=[],
                    rationale="fixture",
                    uncertainty_json={"level": "medium", "reasons": []},
                    fingerprint=f"batch-fixture-{index}",
                    status="proposed",
                )
            )
        session.commit()
        ids = [link.trace_id for link in session.exec(select(TraceLink)).all()]

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        # Accept a two-id subset (plus one already-decided-in-request id is not present).
        subset = client.post(
            f"/api/v1/projects/{project_id}/trace-links/batch-status",
            json={"status": "accepted", "trace_ids": ids[:2] + ["missing-id"]},
        )
        assert subset.status_code == 200
        body = subset.json()
        assert body["updated_count"] == 2
        assert body["skipped_count"] == 1  # the missing id is not proposed
        assert {item["status"] for item in body["updated"]} == {"accepted"}

        # Reject everything still proposed (no ids → all remaining proposed links).
        rest = client.post(
            f"/api/v1/projects/{project_id}/trace-links/batch-status",
            json={"status": "rejected"},
        )
        assert rest.status_code == 200
        assert rest.json()["updated_count"] == 1

        # Idempotent: nothing proposed remains.
        empty = client.post(
            f"/api/v1/projects/{project_id}/trace-links/batch-status",
            json={"status": "rejected"},
        )
        assert empty.status_code == 200
        assert empty.json()["updated_count"] == 0

        # Invalid target status is rejected.
        bad = client.post(
            f"/api/v1/projects/{project_id}/trace-links/batch-status",
            json={"status": "stale"},
        )
        assert bad.status_code == 422


def _link_fixture(project_id: int, index: int, status: str) -> TraceLink:
    return TraceLink(
        project_id=project_id,
        paper_ref=f"p{index}",
        code_ref=f"models/net.py::S{index}",
        relation_type="implements",
        confidence=0.8,
        source="agent",
        evidence_json=[],
        rationale="fixture",
        uncertainty_json={"level": "medium", "reasons": []},
        fingerprint=f"revert-fixture-{status}-{index}",
        status=status,
    )


def test_single_review_revert_roundtrip() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Revert fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id or 0
        session.add(_link_fixture(project_id, 0, "proposed"))
        session.add(_link_fixture(project_id, 1, "stale"))
        session.commit()
        links = session.exec(select(TraceLink).order_by(TraceLink.id)).all()
        trace_id, stale_id = links[0].trace_id, links[1].trace_id

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        url = f"/api/v1/projects/{project_id}/trace-links/{trace_id}/status"
        assert client.patch(url, json={"status": "accepted"}).status_code == 200

        # Revert the decision: back to proposed with decided_at cleared.
        reverted = client.patch(url, json={"status": "proposed"})
        assert reverted.status_code == 200
        assert reverted.json()["status"] == "proposed"
        with Session(engine) as session:
            stored = session.exec(
                select(TraceLink).where(TraceLink.trace_id == trace_id)
            ).one()
            assert stored.decided_at is None

        # A reverted link can be reviewed again (now the other way).
        assert client.patch(url, json={"status": "rejected"}).status_code == 200
        assert client.patch(url, json={"status": "proposed"}).status_code == 200

        # Reverting an already-proposed link is a state conflict.
        assert client.patch(url, json={"status": "proposed"}).status_code == 409

        # Stale links belong to an outdated revision and cannot be reverted.
        stale_url = f"/api/v1/projects/{project_id}/trace-links/{stale_id}/status"
        assert client.patch(stale_url, json={"status": "proposed"}).status_code == 409


def test_batch_status_revert_decided_links() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Batch revert fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id or 0
        for index, status in enumerate(["accepted", "rejected", "proposed", "stale"]):
            session.add(_link_fixture(project_id, index, status))
        session.commit()
        links = session.exec(select(TraceLink).order_by(TraceLink.id)).all()
        ids = [link.trace_id for link in links]

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        # Revert an explicit id set: only the accepted/rejected ones flip; the proposed
        # one and the unknown id are skipped.
        subset = client.post(
            f"/api/v1/projects/{project_id}/trace-links/batch-status",
            json={"status": "proposed", "trace_ids": ids[:3] + ["missing-id"]},
        )
        assert subset.status_code == 200
        body = subset.json()
        assert body["updated_count"] == 2
        assert body["skipped_count"] == 2
        assert {item["status"] for item in body["updated"]} == {"proposed"}
        with Session(engine) as session:
            reverted_rows = session.exec(
                select(TraceLink).where(TraceLink.trace_id.in_(ids[:2]))
            ).all()
            assert all(row.decided_at is None for row in reverted_rows)

        # Nothing decided remains: an id-less revert is an idempotent no-op, and the
        # stale link is never touched.
        empty = client.post(
            f"/api/v1/projects/{project_id}/trace-links/batch-status",
            json={"status": "proposed"},
        )
        assert empty.status_code == 200
        assert empty.json()["updated_count"] == 0


def _clear_fixture_engine() -> tuple[object, int]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Clear fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id or 0
        rows = [
            ("agent", "proposed"),
            ("agent", "accepted"),
            ("agent", "rejected"),
            ("manual", "proposed"),
        ]
        for index, (source, link_status) in enumerate(rows):
            session.add(
                TraceLink(
                    project_id=project_id,
                    paper_ref=f"p{index}",
                    code_ref=f"models/net.py::S{index}",
                    relation_type="implements",
                    confidence=0.8,
                    source=source,
                    evidence_json=[],
                    rationale="fixture",
                    uncertainty_json={"level": "medium", "reasons": []},
                    fingerprint=f"clear-fixture-{index}",
                    status=link_status,
                )
            )
        session.commit()
    return engine, project_id


def _clear_client(engine: object) -> TestClient:
    def session_override() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    return TestClient(app)


def test_clear_defaults_to_proposed_and_keeps_reviewed_decisions() -> None:
    engine, project_id = _clear_fixture_engine()
    with _clear_client(engine) as client:
        cleared = client.delete(f"/api/v1/projects/{project_id}/trace-links")
        assert cleared.status_code == 200
        body = cleared.json()
        # Both proposed links (agent + manual) go; accepted and rejected survive.
        assert body == {"scope": "proposed", "deleted_count": 2, "kept_count": 2}

        remaining = client.get(f"/api/v1/projects/{project_id}/trace-links")
        assert {item["status"] for item in remaining.json()} == {"accepted", "rejected"}

        # Repeating the clear is a no-op rather than an error.
        again = client.delete(f"/api/v1/projects/{project_id}/trace-links")
        assert again.json()["deleted_count"] == 0


def test_clear_agent_scope_spares_manual_relations() -> None:
    engine, project_id = _clear_fixture_engine()
    with _clear_client(engine) as client:
        cleared = client.delete(
            f"/api/v1/projects/{project_id}/trace-links", params={"scope": "agent"}
        )
        assert cleared.status_code == 200
        assert cleared.json()["deleted_count"] == 3

        remaining = client.get(f"/api/v1/projects/{project_id}/trace-links").json()
        assert [item["source"] for item in remaining] == ["manual"]


def test_clear_all_scope_empties_the_project() -> None:
    engine, project_id = _clear_fixture_engine()
    with Session(engine) as session:
        session.add(
            RagIndexState(
                project_id=project_id,
                scope="trace",
                status="ready",
                source_key="reviewed-generation",
                chunk_count=2,
            )
        )
        session.commit()
    with _clear_client(engine) as client:
        cleared = client.delete(
            f"/api/v1/projects/{project_id}/trace-links", params={"scope": "all"}
        )
        assert cleared.json() == {"scope": "all", "deleted_count": 4, "kept_count": 0}
        assert client.get(f"/api/v1/projects/{project_id}/trace-links").json() == []
    with Session(engine) as session:
        state = session.exec(
            select(RagIndexState).where(
                RagIndexState.project_id == project_id,
                RagIndexState.scope == "trace",
            )
        ).one()
        assert state.status == "pending"


def test_clear_rejects_unknown_scope() -> None:
    engine, project_id = _clear_fixture_engine()
    with _clear_client(engine) as client:
        response = client.delete(
            f"/api/v1/projects/{project_id}/trace-links", params={"scope": "everything"}
        )
        assert response.status_code == 422
