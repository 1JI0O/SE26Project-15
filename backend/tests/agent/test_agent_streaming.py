from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.entities import AgentRun
from app.services.agent import conversations
from app.services.agent.provider import AgentProviderFailure, AgentProviderStep


class FinalProvider:
    provider_name = "fake-stream"
    model_name = "fake-stream-model"

    def next_step(self, message, context, tool_results):
        return AgentProviderStep(action="final", answer=f"Completed: {message}")


class RetryStreamProvider(FinalProvider):
    def __init__(self) -> None:
        self.calls = 0

    def next_step_stream(self, message, context, tool_results, on_event):
        self.calls += 1
        on_event("message.delta", {"delta": "partial" if self.calls == 1 else "complete"})
        if self.calls == 1:
            raise AgentProviderFailure("llm_timeout")
        return AgentProviderStep(action="final", answer="complete")


def test_submitted_run_persists_events_and_final_message(monkeypatch) -> None:
    monkeypatch.setattr(
        conversations,
        "_provider_from_settings",
        lambda _session: (FinalProvider(), None),
    )
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Streaming Agent"}).json()
        project_id = project["id"]
        conversation = client.post(
            f"/api/v1/projects/{project_id}/agent/conversations",
            json={"title": "新对话"},
        ).json()
        conversation_id = conversation["conversation_id"]
        submission = client.post(
            f"/api/v1/projects/{project_id}/agent/conversations/{conversation_id}/runs",
            json={"message": "Explain the project", "context": {}},
        )
        assert submission.status_code == 202
        run_id = submission.json()["run_id"]
        stream = client.get(f"/api/v1/projects/{project_id}/agent/runs/{run_id}/events")
        detail = client.get(
            f"/api/v1/projects/{project_id}/agent/conversations/{conversation_id}"
        )

    assert stream.status_code == 200
    assert "event: run.started" in stream.text
    assert "event: reasoning.summary" in stream.text
    assert "event: message.completed" in stream.text
    assert detail.json()["messages"][-1]["content"] == "Completed: Explain the project"


def test_provider_retry_resets_partial_stream() -> None:
    provider = RetryStreamProvider()
    events: list[tuple[str, dict[str, object]]] = []
    trace: list[dict[str, object]] = []

    step = conversations._provider_step(
        provider,
        "Explain",
        {},
        [],
        trace,
        lambda event_type, payload: events.append((event_type, payload)),
    )

    assert step.answer == "complete"
    assert [event_type for event_type, _payload in events] == [
        "message.delta",
        "message.reset",
        "message.delta",
    ]


def test_interrupted_run_recovers_once(monkeypatch) -> None:
    monkeypatch.setattr(
        conversations._agent_executor,
        "submit",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        conversations,
        "_provider_from_settings",
        lambda _session: (FinalProvider(), None),
    )
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Recovery Agent"}).json()
        project_id = project["id"]
        conversation = client.post(
            f"/api/v1/projects/{project_id}/agent/conversations",
            json={"title": "Recovery"},
        ).json()
        conversation_id = conversation["conversation_id"]
        submission = client.post(
            f"/api/v1/projects/{project_id}/agent/conversations/{conversation_id}/runs",
            json={"message": "Resume me", "context": {}},
        ).json()
        conversations._execute_submitted_run(submission["run_id"])
        conversations._execute_submitted_run(submission["run_id"])
        detail = client.get(
            f"/api/v1/projects/{project_id}/agent/conversations/{conversation_id}"
        ).json()
        with Session(conversations.engine) as session:
            run = session.get(AgentRun, submission["run_id"])

    assistants = [message for message in detail["messages"] if message["role"] == "assistant"]
    assert len(assistants) == 1
    assert run is not None and run.status == "completed"
