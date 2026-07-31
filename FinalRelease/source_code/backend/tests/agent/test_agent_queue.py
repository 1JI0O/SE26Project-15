from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    AgentConversation,
    AgentRun,
    CodeRepository,
    Project,
    utc_now,
)
from app.services.agent import analysis_jobs


def _running_run() -> tuple[int, str]:
    with Session(analysis_jobs.engine) as session:
        project = Project(name="Queue fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        conversation = AgentConversation(
            project_id=project.id or 0,
            kind="interactive",
            title="检查追溯结果",
        )
        session.add(conversation)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.conversation_id,
            project_id=project.id or 0,
            status="running",
            model_name="test-model",
        )
        session.add(run)
        session.commit()
        return project.id or 0, run.run_id


def test_global_agent_queue_lists_running_runs() -> None:
    _running_run()

    response = TestClient(app).get("/api/v1/agent/queue")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_count"] == 1
    assert payload["items"][0]["project_name"] == "Queue fixture"
    assert payload["items"][0]["category"] == "agent_run"
    assert payload["items"][0]["summary"] == "检查追溯结果"
    updated_at = payload["items"][0]["updated_at"]
    assert updated_at.endswith("Z") or updated_at.endswith("+00:00")


def test_queue_item_delete_hides_running_run() -> None:
    _, run_id = _running_run()
    client = TestClient(app)

    response = client.delete(f"/api/v1/agent/queue/agent_run/{run_id}")

    assert response.status_code == 204
    queue = client.get("/api/v1/agent/queue").json()
    assert queue["active_count"] == 0
    with Session(analysis_jobs.engine) as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.degraded_reason == "queue_delete_requested"

def test_queue_reconciles_completed_run_for_running_analysis_job() -> None:
    with Session(analysis_jobs.engine) as session:
        project = Project(name="Finished analysis fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        repository = CodeRepository(
            project_id=project.id or 0,
            filename="repo.zip",
            storage_path="repo.zip",
            file_tree_json=[],
            symbols_json=[],
            imports_json=[],
            pytorch_candidates_json=[],
            analysis_json={},
        )
        session.add(repository)
        session.flush()
        conversation = AgentConversation(
            project_id=project.id or 0,
            kind="analysis",
            title="trace analysis",
        )
        session.add(conversation)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.conversation_id,
            project_id=project.id or 0,
            status="completed",
            model_name="test-model",
        )
        session.add(run)
        session.flush()
        job = AgentAnalysisJob(
            project_id=project.id or 0,
            kind="architecture",
            code_repository_id=repository.id or 0,
            code_revision=1,
            agent_run_id=run.run_id,
            fingerprint="queue-reconcile-finished-run",
            status="running",
            progress_json={"message": "Agent 正在检查证据"},
        )
        session.add(job)
        session.commit()
        job_id = job.job_id

    queue = TestClient(app).get("/api/v1/agent/queue").json()

    assert queue["active_count"] == 0
    with Session(analysis_jobs.engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        assert job is not None
        assert job.status == "succeeded"


def test_queue_reconciles_stale_published_analysis_job() -> None:
    with Session(analysis_jobs.engine) as session:
        project = Project(name="Stale published fixture")
        session.add(project)
        session.commit()
        session.refresh(project)
        repository = CodeRepository(
            project_id=project.id or 0,
            filename="repo.zip",
            storage_path="repo.zip",
            file_tree_json=[],
            symbols_json=[],
            imports_json=[],
            pytorch_candidates_json=[],
            analysis_json={},
        )
        session.add(repository)
        session.flush()
        conversation = AgentConversation(
            project_id=project.id or 0,
            kind="analysis",
            title="trace analysis",
        )
        session.add(conversation)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.conversation_id,
            project_id=project.id or 0,
            status="running",
            model_name="test-model",
        )
        session.add(run)
        session.flush()
        run_id = run.run_id
        stale_at = utc_now().replace(year=2020)
        job = AgentAnalysisJob(
            project_id=project.id or 0,
            kind="trace",
            code_repository_id=repository.id or 0,
            code_revision=1,
            agent_run_id=run_id,
            fingerprint="queue-reconcile-stale-published",
            status="running",
            progress_json={"message": "Agent 正在检查证据"},
            updated_at=stale_at,
        )
        session.add(job)
        session.flush()
        artifact = AgentAnalysisArtifact(
            job_id=job.job_id,
            project_id=project.id or 0,
            kind="trace",
            schema_version="trace-agent-v2",
            payload_json={"candidates": []},
            code_repository_id=repository.id or 0,
            code_revision=1,
            agent_run_id=run_id,
            model_info_json={},
            capability_snapshot_json=[],
            fingerprint="queue-reconcile-stale-published-artifact",
        )
        session.add(artifact)
        session.commit()
        job_id = job.job_id
        artifact_id = artifact.artifact_id

    queue = TestClient(app).get("/api/v1/agent/queue").json()

    assert queue["active_count"] == 0
    with Session(analysis_jobs.engine) as session:
        job = session.get(AgentAnalysisJob, job_id)
        run = session.get(AgentRun, run_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.artifact_id == artifact_id
        assert run is not None
        assert run.status == "completed"
