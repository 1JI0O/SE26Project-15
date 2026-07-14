from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.routes.agent import router
from app.db.session import get_session
from app.models.entities import AgentToolRequest, Project, utc_now


def test_agent_router_degrades_and_confirmation_rejection_is_audited() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Agent API fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        request = AgentToolRequest(
            project_id=project.id or 0,
            tool_name="rerun_analysis",
            private_arguments_json={"targets": []},
            parameter_summary_json={"targets": [], "target_count": 0},
            expires_at=utc_now(),
        )
        request.expires_at = request.expires_at.replace(year=request.expires_at.year + 1)
        session.add(request)
        session.commit()
        session.refresh(request)
        project_id = project.id or 0
        confirmation_id = request.confirmation_id

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        query = client.post(
            f"/api/v1/projects/{project_id}/agent/query",
            json={"message": "Change the code"},
        )
        rejected = client.post(
            f"/api/v1/projects/{project_id}/agent/confirmations/"
            f"{confirmation_id}/decision",
            json={"decision": "reject"},
        )

    assert query.status_code == 200
    assert query.json()["degraded_reason"] == "llm_disabled"
    assert query.json()["confirmation"] is None
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["user_decision"] == "reject"
