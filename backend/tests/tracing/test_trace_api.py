from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.routes.traces import router
from app.db.session import get_session
from app.models.entities import CodeRepository, PaperDocument, Project


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
