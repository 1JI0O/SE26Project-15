"""The duplicate-fingerprint race on manual trace creation must answer 409, not 500.

``create_link`` checks for an existing fingerprint and then inserts. Two concurrent
requests for the same relation both pass the check, and one hits
``uq_trace_link_fingerprint``. Patching the fast-path helper reproduces the losing
request deterministically, without threads.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.routes import traces as traces_route
from app.db.session import get_session
from app.models.entities import CodeRepository, PaperDocument, Project

RELATION = {
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
}


@pytest.fixture()
def client_and_project() -> Iterator[tuple[TestClient, int]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Duplicate race fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id or 0
        session.add(
            PaperDocument(
                project_id=project_id,
                filename="paper.pdf",
                storage_path="paper.pdf",
                sections_json=[],
                paragraphs_json=[
                    {"id": "p1", "text": "The BasicBlock implements a residual shortcut."}
                ],
            )
        )
        session.add(
            CodeRepository(
                project_id=project_id,
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

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(traces_route.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client, project_id


def test_duplicate_fingerprint_returns_409(client_and_project) -> None:
    client, project_id = client_and_project
    url = f"/api/v1/projects/{project_id}/trace-links"

    assert client.post(url, json=RELATION).status_code == 201
    assert client.post(url, json=RELATION).status_code == 409


def test_lost_insert_race_returns_409_not_500(
    client_and_project, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, project_id = client_and_project
    url = f"/api/v1/projects/{project_id}/trace-links"
    assert client.post(url, json=RELATION).status_code == 201

    # Stand in for the concurrent request that passed the check before the other committed.
    monkeypatch.setattr(traces_route, "_fingerprint_exists", lambda *_args, **_kwargs: False)

    response = client.post(url, json=RELATION)
    assert response.status_code == 409
    assert response.json()["detail"] == "Trace relation already exists"
