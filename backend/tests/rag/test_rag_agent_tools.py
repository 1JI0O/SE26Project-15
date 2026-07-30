"""RAG exposure through the analysis agent, the conversation agent, and the HTTP API."""

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.entities import (
    AgentAnalysisJob,
    CodeRepository,
    IntegrationConfig,
    Project,
    TraceLink,
)
from app.services.agent.analysis_jobs import _system_prompt, _trace_precedents
from app.services.agent.analysis_tools import execute_tool, tool_definitions
from app.services.agent.tools import execute_read_tool
from app.services.rag import build_index

client = TestClient(app)


def _tool_names(kind: str, role: str = "parent") -> set[str]:
    return {item["function"]["name"] for item in tool_definitions(kind, role=role)}


SEMANTIC_TOOLS = {"semantic_search_paper", "semantic_search_code", "recall_trace_cases"}


def test_semantic_tools_are_offered_to_trace_agent_and_its_subagents() -> None:
    assert SEMANTIC_TOOLS <= _tool_names("trace")
    # Region sub-agents keep retrieval; they only lose finish/dispatch/artifact.
    subagent = _tool_names("trace", "subagent")
    assert SEMANTIC_TOOLS <= subagent
    assert "finish_analysis" not in subagent


def test_architecture_agent_gets_code_retrieval_but_not_paper_retrieval() -> None:
    names = _tool_names("architecture")
    assert "semantic_search_code" in names
    assert "semantic_search_paper" not in names


def test_analysis_agent_semantic_paper_search_returns_ranked_block_ids(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    build_index(rag_session, project_id, "paper")
    result = execute_tool(
        rag_session,
        project_id,
        0,
        None,
        2,
        "semantic_search_paper",
        {"query": "loss that down-weights easy examples", "limit": 2},
    )
    assert result["found"] is True
    assert result["items"][0]["ref"] == "p1-b1"
    assert len(result["items"]) <= 2
    # The tool must tell the model that a rank is not a verdict.
    assert "before quoting" in result["instruction"]


def test_analysis_agent_semantic_code_search_returns_path_and_lines(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    add_repository: Callable[[Session, Project, Path], CodeRepository],
    tmp_path: Path,
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    repository = add_repository(rag_session, project, tmp_path)
    build_index(rag_session, project_id, "code")
    result = execute_tool(
        rag_session,
        project_id,
        repository.id or 0,
        None,
        2,
        "semantic_search_code",
        {"query": "focal loss down-weighting"},
    )
    assert result["found"] is True
    top = result["items"][0]
    assert top["ref"] == "losses.py::FocalLoss.forward"
    assert (top["path"], top["line_start"], top["line_end"]) == ("losses.py", 4, 7)


def test_semantic_search_without_index_instructs_fallback_instead_of_failing(
    rag_session: Session,
) -> None:
    project = Project(name="No paper")
    rag_session.add(project)
    rag_session.commit()
    rag_session.refresh(project)
    result = execute_tool(
        rag_session, project.id or 0, 0, None, 2, "semantic_search_paper", {"query": "anything"}
    )
    assert result["found"] is False
    assert result["items"] == []
    assert "instead" in result["instruction"]


def test_recall_trace_cases_marks_precedents_as_non_evidence(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    reviewed_link: Callable[..., TraceLink],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    rag_session.add(
        reviewed_link(
            project_id, "accepted", "focal loss down-weights", "losses.py::FocalLoss.forward"
        )
    )
    rag_session.commit()
    build_index(rag_session, project_id, "trace")
    result = execute_tool(
        rag_session, project_id, 0, None, 2, "recall_trace_cases", {"query": "focal loss"}
    )
    assert result["found"] is True
    assert result["items"][0]["status"] == "accepted"
    assert "Do not cite them as evidence" in result["instruction"]


def test_conversation_agent_semantic_paper_search_works(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    build_index(rag_session, project_id, "paper")
    result = execute_read_tool(
        rag_session,
        project_id,
        "semantic_search_paper",
        {"query": "scaled dot product attention", "limit": 3},
    )
    assert result["found"] is True
    assert result["items"][0]["ref"] == "p2-b1"


def test_conversation_agent_unavailable_index_suggests_keyword_tools(
    rag_session: Session,
) -> None:
    project = Project(name="Bare")
    rag_session.add(project)
    rag_session.commit()
    rag_session.refresh(project)
    result = execute_read_tool(
        rag_session, project.id or 0, "semantic_search_code", {"query": "loss"}
    )
    assert result["found"] is False
    assert "search_code" in result["instruction"]


def _trace_job(project_id: int, job_id: str) -> AgentAnalysisJob:
    return AgentAnalysisJob(
        job_id=job_id,
        project_id=project_id,
        kind="trace",
        code_repository_id=0,
        code_revision=1,
        paper_document_id=1,
        fingerprint=f"fp-{job_id}",
    )


def test_trace_precedents_block_is_injected_into_the_trace_prompt(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
    reviewed_link: Callable[..., TraceLink],
) -> None:
    project = project_with_paper(rag_session)
    project_id = project.id or 0
    rag_session.add(
        reviewed_link(
            project_id,
            "accepted",
            "focal loss down-weights easy negatives",
            "losses.py::FocalLoss.forward",
        )
    )
    rag_session.commit()
    build_index(rag_session, project_id, "trace")
    job = _trace_job(project_id, "job-precedent")

    precedents = _trace_precedents(rag_session, job)
    assert "REVIEWED PRECEDENTS" in precedents
    assert "ACCEPTED by reviewer" in precedents
    assert "NOT evidence for this run" in precedents

    _system, request = _system_prompt(job, 40, precedents)
    assert "REVIEWED PRECEDENTS" in request
    assert "semantic_search_paper" in request


def test_trace_prompt_has_no_precedent_block_before_any_review(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    project = project_with_paper(rag_session)
    job = _trace_job(project.id or 0, "job-empty")
    assert _trace_precedents(rag_session, job) == ""
    _system, request = _system_prompt(job, 40, "")
    assert "REVIEWED PRECEDENTS" not in request


def _create_project(name: str) -> int:
    response = client.post("/api/v1/projects", json={"name": name, "description": ""})
    assert response.status_code == 201
    return int(response.json()["id"])


def test_rag_status_endpoint_lists_pending_scopes_on_a_new_project() -> None:
    project_id = _create_project("RAG status")
    response = client.get(f"/api/v1/projects/{project_id}/rag/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert {scope["scope"] for scope in body["scopes"]} == {"paper", "code", "trace"}
    assert all(scope["status"] == "pending" for scope in body["scopes"])


def test_rag_rebuild_endpoint_returns_a_result_per_scope() -> None:
    project_id = _create_project("RAG rebuild")
    response = client.post(f"/api/v1/projects/{project_id}/rag/rebuild", json={})
    assert response.status_code == 200
    results = response.json()["results"]
    assert {item["scope"] for item in results} == {"paper", "code", "trace"}


def test_rag_search_endpoint_rejects_an_unknown_scope() -> None:
    project_id = _create_project("RAG scope")
    response = client.get(
        f"/api/v1/projects/{project_id}/rag/search", params={"query": "x", "scope": "bogus"}
    )
    assert response.status_code == 422


def test_integration_settings_expose_and_persist_rag_configuration() -> None:
    read = client.get("/api/v1/settings/integrations")
    assert read.status_code == 200
    payload = read.json()
    assert payload["rag"]["enabled"] is True
    assert payload["rag"]["embedder"] == "local"
    assert payload["rag"]["api_key_configured"] is False

    update = {
        "agent": {
            "enabled": False,
            "base_url": "",
            "model": "",
            "analysis_model": "",
            "thinking_mode": "",
            "timeout_seconds": payload["agent"]["timeout_seconds"],
        },
        "mineru": {
            key: payload["mineru"][key]
            for key in (
                "provider",
                "local_url",
                "backend",
                "language",
                "parse_method",
                "official_api_url",
                "official_api_model",
                "ocr",
                "formula_enable",
                "table_enable",
                "request_timeout_seconds",
                "request_retries",
                "task_timeout_seconds",
                "poll_interval_seconds",
            )
        },
        "rag": {
            "enabled": True,
            "embedder": "remote",
            "base_url": "https://embeddings.example.com/v1",
            "api_key": "secret-key",
            "model": "text-embedding-3-small",
            "dimensions": 1024,
            "timeout_seconds": 45.0,
        },
    }
    saved = client.put("/api/v1/settings/integrations", json=update)
    assert saved.status_code == 200
    stored = saved.json()["rag"]
    assert stored["embedder"] == "remote"
    assert stored["model"] == "text-embedding-3-small"
    assert stored["dimensions"] == 1024
    assert stored["api_key_configured"] is True
    # The key itself is never echoed back.
    assert "secret-key" not in saved.text


def test_switching_embedder_dimensions_invalidates_existing_indexes(
    rag_session: Session,
    project_with_paper: Callable[[Session], Project],
) -> None:
    from app.schemas.integration_settings import (
        AgentIntegrationUpdate,
        IntegrationSettingsUpdate,
        MinerUIntegrationUpdate,
        RagIntegrationUpdate,
    )
    from app.services.integration_settings import save_integration_config
    from app.services.rag.service import _state

    project = project_with_paper(rag_session)
    project_id = project.id or 0
    # A stored config must exist, otherwise the first save has no previous generation to
    # compare against and there is correctly nothing to invalidate.
    rag_session.add(IntegrationConfig(id=1))
    rag_session.commit()
    build_index(rag_session, project_id, "paper")
    assert _state(rag_session, project_id, "paper").status == "ready"

    save_integration_config(
        rag_session,
        IntegrationSettingsUpdate(
            agent=AgentIntegrationUpdate(),
            mineru=MinerUIntegrationUpdate(),
            rag=RagIntegrationUpdate(enabled=True, embedder="local", dimensions=1024),
        ),
    )
    # Vectors of a different dimension are not comparable; the index must rebuild.
    assert _state(rag_session, project_id, "paper").status == "pending"


def test_review_verdict_through_the_api_invalidates_the_trace_index() -> None:
    from app.db.session import get_session
    from app.services.rag.service import _state

    project_id = _create_project("RAG review")
    session_factory = app.dependency_overrides[get_session]

    generator = session_factory()
    session: Session = next(generator)
    try:
        link = TraceLink(
            project_id=project_id,
            paper_ref="p1-b1",
            code_ref="losses.py::FocalLoss.forward",
            relation_type="implements",
            confidence=0.7,
            status="proposed",
            evidence_json=[
                {"side": "paper", "ref": "p1-b1", "quote": "focal loss"},
                {"side": "code", "ref": "losses.py::FocalLoss.forward", "quote": "gamma"},
            ],
        )
        session.add(link)
        session.commit()
        session.refresh(link)
        trace_id = link.trace_id
        state = _state(session, project_id, "trace")
        state.status = "ready"
        state.chunk_count = 1
        session.add(state)
        session.commit()
    finally:
        generator.close()

    response = client.patch(
        f"/api/v1/projects/{project_id}/trace-links/{trace_id}/status",
        json={"status": "accepted"},
    )
    assert response.status_code == 200

    generator = session_factory()
    session = next(generator)
    try:
        assert _state(session, project_id, "trace").status == "pending"
    finally:
        generator.close()
