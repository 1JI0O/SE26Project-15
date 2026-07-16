from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.schemas.agent import AgentCapabilityUpdate
from app.services.agent.capabilities import (
    build_registry,
    select_skills,
    update_capability,
)
from app.services.agent.mcp import MCPError, validate_json_schema


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_bundled_skills_and_tools_are_discovered() -> None:
    with _session() as session:
        registry = build_registry(session)
        selected = select_skills(registry, "分析模型架构和张量流", {"graph": {}})

    assert registry.tool("get_architecture") is not None
    assert registry.records["tool:get_architecture"].source == "builtin"
    assert any(skill.name == "architecture-analysis" for skill in selected)


def test_external_skill_requires_explicit_enable_and_trust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = tmp_path / "skills" / "explain-custom-model"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: explain-custom-model
description: Explain AcmeNet model internals when users mention AcmeNet.
metadata:
  tracelab:
    triggers: [acmenet]
    preferred_tools: [search_code]
---
# Workflow
Read the implementation before explaining AcmeNet.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "tracelab_agent_skill_roots", [str(tmp_path / "skills")])

    with _session() as session:
        registry = build_registry(session)
        record = registry.records["skill:explain-custom-model"]
        assert record.enabled is False
        assert record.trusted is False
        assert all(
            skill.name != "explain-custom-model"
            for skill in select_skills(registry, "Explain AcmeNet", {})
        )

        updated = update_capability(
            session,
            "skill:explain-custom-model",
            AgentCapabilityUpdate(enabled=True, trusted=True),
        )
        registry = build_registry(session)
        selected = select_skills(registry, "Explain AcmeNet", {})

    assert updated is not None and updated.eligible is True
    assert selected[0].name == "explain-custom-model"


def test_mcp_schema_validation_is_fail_closed() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "minLength": 1}},
        "required": ["path"],
        "additionalProperties": False,
    }
    validate_json_schema({"path": "model.py"}, schema)
    with pytest.raises(MCPError, match="schema_extra_fields"):
        validate_json_schema({"path": "model.py", "unsafe": True}, schema)
    with pytest.raises(MCPError, match="unsupported_schema_keywords"):
        validate_json_schema({"path": "model.py"}, {**schema, "anyOf": []})

    nested_schema: dict[str, object] = {"type": "string"}
    nested_value: object = "leaf"
    for _index in range(22):
        nested_schema = {
            "type": "object",
            "properties": {"child": nested_schema},
            "required": ["child"],
        }
        nested_value = {"child": nested_value}
    with pytest.raises(MCPError, match="schema_depth_exceeded"):
        validate_json_schema(nested_value, nested_schema)


def test_mcp_tools_receive_unique_openai_safe_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir = tmp_path / "plugins" / "example"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "tracelab.plugin.json").write_text(
        """{
  "id": "acme.plugin",
  "mcp_servers": [
    {"id": "analysis.server", "url": "http://127.0.0.1:9010/mcp"}
  ]
}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "tracelab_agent_plugin_roots", [str(tmp_path / "plugins")])
    monkeypatch.setattr(
        "app.services.agent.capabilities._discover_mcp_tools",
        lambda _config: [
            {
                "name": "read/model:with-a-very-long-name-that-must-be-truncated-safely",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True},
            }
        ],
    )

    with _session() as session:
        build_registry(session)
        update_capability(
            session,
            "plugin:acme.plugin",
            AgentCapabilityUpdate(enabled=True, trusted=True),
        )
        registry = build_registry(session)
        external_names = [
            tool.name for tool in registry.enabled_tools() if tool.source.startswith("mcp:")
        ]

    assert len(external_names) == 1
    assert len(external_names[0]) <= 64
    assert all(character.isalnum() or character in "_-" for character in external_names[0])


def test_capability_api_exposes_bundled_registry() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Capability API"}).json()
        response = client.get(f"/api/v1/projects/{project['id']}/agent/capabilities")

    assert response.status_code == 200
    assert any(item["capability_id"] == "skill:paper-explanation" for item in response.json())
