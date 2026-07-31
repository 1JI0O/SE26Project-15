from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.routes.agent import router
from app.db.session import get_session
from app.models.entities import (
    AgentAnalysisJob,
    AgentConversation,
    AgentRun,
    AgentRunEvent,
    Project,
)


def _fixture() -> tuple[object, int, str]:
    """A failed trace job with a run, a degraded reason, recorded events and a step trace."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name="Diagnostics fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id or 0
        conversation = AgentConversation(project_id=project_id, kind="analysis", title="t")
        session.add(conversation)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.conversation_id,
            project_id=project_id,
            status="failed",
            provider_name="openai-compatible",
            model_name="example-chat",
            degraded_reason="llm_invalid_json",
            step_count=2,
            trace_json=[
                {"type": "model_step", "action": "tool", "tool_name": "get_paper_block"},
                {"type": "tool_result", "tool": "get_paper_block", "ok": False},
            ],
        )
        session.add(run)
        session.flush()
        session.add(
            AgentRunEvent(
                run_id=run.run_id,
                conversation_id=conversation.conversation_id,
                project_id=project_id,
                sequence=1,
                event_type="analysis.tool.failed",
                payload_json={"tool_name": "get_paper_block", "code": "quote_not_found"},
            )
        )
        job = AgentAnalysisJob(
            project_id=project_id,
            kind="trace",
            code_repository_id=1,
            code_revision=1,
            requested_depth=2,
            status="failed",
            error_code="analysis_internal_error:OperationalError:database is locked",
            progress_json={"message": "Agent 分析失败"},
            agent_run_id=run.run_id,
            fingerprint="diagnostics-fixture",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.job_id
    return engine, project_id, job_id


def _client(engine: object) -> TestClient:
    def session_override() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override
    return TestClient(app)


def test_diagnostics_expose_the_real_failure_cause_not_just_a_code() -> None:
    engine, project_id, job_id = _fixture()
    with _client(engine) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/agent/analysis-jobs/{job_id}/diagnostics"
        )

    assert response.status_code == 200
    body = response.json()
    # The bare error_code hides the underlying reason; the run's degraded_reason, its recorded
    # tool failure and its step trace are what actually explain the failure.
    assert body["status"] == "failed"
    assert "database is locked" in body["error_code"]
    assert body["degraded_reason"] == "llm_invalid_json"
    assert body["provider_name"] == "openai-compatible"
    assert body["model_name"] == "example-chat"
    assert [event["event_type"] for event in body["events"]] == ["analysis.tool.failed"]
    assert body["events"][0]["payload"]["code"] == "quote_not_found"
    assert len(body["steps"]) == 2


def test_diagnostics_for_an_unknown_job_is_404() -> None:
    engine, project_id, _ = _fixture()
    with _client(engine) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/agent/analysis-jobs/missing/diagnostics"
        )

    assert response.status_code == 404
