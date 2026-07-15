import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.models.entities import AgentRun, CodeRepository, PaperDocument, Project
from app.schemas.agent import (
    AgentConversationCreate,
    AgentMemoryCreate,
    AgentTurnRequest,
)
from app.services.agent.conversations import (
    create_conversation,
    get_conversation_detail,
    run_conversation_turn,
)
from app.services.agent.memory import create_memory, retrieve_memories
from app.services.agent.provider import AgentProviderStep


class StepProvider:
    provider_name = "fake"
    model_name = "fake-agent-model"

    def __init__(self, steps: list[AgentProviderStep]) -> None:
        self.steps = steps
        self.contexts: list[dict[str, object]] = []

    def next_step(
        self,
        message: str,
        context: dict[str, object],
        tool_results: list[dict[str, object]],
    ) -> AgentProviderStep:
        self.contexts.append(context)
        return self.steps.pop(0)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _project(session: Session, tmp_path: Path | None = None) -> Project:
    project = Project(name="Persistent Agent fixture")
    session.add(project)
    session.commit()
    session.refresh(project)
    paper = PaperDocument(
        project_id=project.id or 0,
        filename="paper.pdf",
        storage_path="paper.pdf",
        sections_json=[],
        paragraphs_json=[{"id": "p1", "text": "The encoder uses a residual attention block."}],
    )
    session.add(paper)
    if tmp_path is not None:
        archive_path = tmp_path / "repo.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("repo/models/net.py", "class Net:\n    pass\n")
        session.add(
            CodeRepository(
                project_id=project.id or 0,
                filename="repo.zip",
                storage_path=str(archive_path),
                file_tree_json=[{"path": "models/net.py", "language": "python"}],
                symbols_json=[
                    {
                        "id": "models/net.py::Net",
                        "path": "models/net.py",
                        "name": "Net",
                        "line": 1,
                    }
                ],
                imports_json=[],
                pytorch_candidates_json=[],
            )
        )
    session.commit()
    return project


def test_conversation_persists_multi_turn_history(tmp_path: Path) -> None:
    with _session() as session:
        project = _project(session, tmp_path)
        conversation = create_conversation(session, project.id or 0, AgentConversationCreate())
        first_provider = StepProvider(
            [AgentProviderStep(action="final", answer="The encoder is residual.")]
        )
        second_provider = StepProvider(
            [AgentProviderStep(action="final", answer="It is described in the paper.")]
        )

        first = run_conversation_turn(
            session,
            project.id or 0,
            conversation.conversation_id,
            AgentTurnRequest(message="Explain the encoder"),
            provider=first_provider,
        )
        second = run_conversation_turn(
            session,
            project.id or 0,
            conversation.conversation_id,
            AgentTurnRequest(message="Where is that stated?"),
            provider=second_provider,
        )
        detail = get_conversation_detail(session, project.id or 0, conversation.conversation_id)

    assert first is not None and second is not None
    assert detail is not None and len(detail.messages) == 4
    assert detail.title == "Explain the encoder"
    assert any(
        item["content"] == "The encoder is residual."
        for item in second_provider.contexts[0]["history"]
    )


def test_loop_recovers_from_invalid_tool_arguments(tmp_path: Path) -> None:
    with _session() as session:
        project = _project(session, tmp_path)
        conversation = create_conversation(session, project.id or 0, AgentConversationCreate())
        provider = StepProvider(
            [
                AgentProviderStep(
                    action="tool",
                    tool_name="get_paper_block",
                    arguments={},
                ),
                AgentProviderStep(
                    action="tool",
                    tool_name="get_paper_block",
                    arguments={"block_id": "p1"},
                ),
                AgentProviderStep(action="final", answer="Recovered with paper evidence."),
            ]
        )
        response = run_conversation_turn(
            session,
            project.id or 0,
            conversation.conversation_id,
            AgentTurnRequest(message="Read the encoder evidence"),
            provider=provider,
        )

    assert response is not None
    assert response.status == "completed"
    assert [event.status for event in response.assistant_message.tool_events] == [
        "failed",
        "succeeded",
    ]
    assert response.assistant_message.citations[0].ref == "p1"


def test_loop_recovers_from_internal_read_tool_failure(tmp_path: Path, monkeypatch) -> None:
    with _session() as session:
        project = _project(session, tmp_path)
        conversation = create_conversation(session, project.id or 0, AgentConversationCreate())
        provider = StepProvider(
            [
                AgentProviderStep(
                    action="tool",
                    tool_name="search_code",
                    arguments={"query": "Net"},
                ),
                AgentProviderStep(
                    action="final",
                    answer="The code index failed, so no code claim was made.",
                ),
            ]
        )

        def fail_read(*_args, **_kwargs):
            raise RuntimeError("private backend detail")

        monkeypatch.setattr("app.services.agent.conversations.execute_read_tool", fail_read)
        response = run_conversation_turn(
            session,
            project.id or 0,
            conversation.conversation_id,
            AgentTurnRequest(message="Find Net"),
            provider=provider,
        )

    assert response is not None and response.status == "completed"
    assert response.assistant_message.tool_events[0].status == "failed"
    assert response.assistant_message.tool_events[0].result == {"error": "tool_execution_error"}


def test_code_write_requires_patch_and_risk_analysis(tmp_path: Path) -> None:
    target = "class Net:\n    value = 1\n"
    with _session() as session:
        project = _project(session, tmp_path)
        conversation = create_conversation(session, project.id or 0, AgentConversationCreate())
        provider = StepProvider(
            [
                AgentProviderStep(
                    action="tool",
                    tool_name="save_code_file",
                    arguments={"path": "models/net.py", "content": target},
                ),
                AgentProviderStep(
                    action="tool",
                    tool_name="propose_code_patch",
                    arguments={"path": "models/net.py", "content": target},
                ),
                AgentProviderStep(
                    action="tool",
                    tool_name="analyze_change_risk",
                    arguments={"path": "models/net.py", "content": target},
                ),
                AgentProviderStep(
                    action="tool",
                    tool_name="save_code_file",
                    arguments={"path": "models/net.py", "content": target},
                ),
            ]
        )
        response = run_conversation_turn(
            session,
            project.id or 0,
            conversation.conversation_id,
            AgentTurnRequest(message="Add a class value"),
            provider=provider,
        )
        runs = session.exec(select(AgentRun)).all()

    assert response is not None
    assert response.status == "waiting_confirmation"
    assert response.confirmation is not None
    assert response.confirmation.tool_name == "save_code_file"
    assert any(
        item.get("error") == "write_preconditions_missing"
        for item in runs[0].trace_json
        if item.get("type") == "tool_result"
    )


def test_memory_retrieval_combines_project_and_global_scope(tmp_path: Path) -> None:
    with _session() as session:
        first = _project(session, tmp_path)
        conversation = create_conversation(session, first.id or 0, AgentConversationCreate())
        conversation_id = conversation.conversation_id
        second = Project(name="Other project")
        session.add(second)
        session.commit()
        session.refresh(second)
        global_memory = create_memory(
            session,
            first.id or 0,
            AgentMemoryCreate(
                content="Always explain tensor shapes",
                scope="global",
                conversation_id=conversation_id,
            ),
            source={"conversation_id": conversation_id},
        )
        create_memory(
            session,
            first.id or 0,
            AgentMemoryCreate(content="This project uses MANO", scope="project"),
        )

        first_results = retrieve_memories(session, first.id or 0, "tensor shapes MANO")
        second_results = retrieve_memories(session, second.id or 0, "tensor shapes MANO")

    assert {item["scope"] for item in first_results} == {"project", "global"}
    assert [item["scope"] for item in second_results] == ["global"]
    assert global_memory.conversation_id is None
    assert global_memory.source_json["conversation_id"] == conversation_id
