from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import yaml
from sqlmodel import Session

from app.core.config import settings
from app.models.entities import AgentCapabilitySetting, utc_now
from app.schemas.agent import AgentCapabilityRead, AgentCapabilityUpdate
from app.services.agent.mcp import MCPHttpClient, MCPServerConfig

ToolExecutor = Callable[[Session, int, dict[str, Any]], dict[str, Any]]

_MCP_TOOL_CACHE_TTL_SECONDS = 60.0
_mcp_tool_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_mcp_tool_cache_lock = Lock()


@dataclass(frozen=True)
class SkillCapability:
    capability_id: str
    name: str
    title: str
    description: str
    instructions: str
    preferred_tools: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    source: str = "bundled"
    version: str = "1"
    trusted_by_default: bool = False
    enabled_by_default: bool = False
    content_hash: str = ""


@dataclass(frozen=True)
class ToolCapability:
    capability_id: str
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    executor: ToolExecutor
    source: str = "bundled"
    version: str = "1"
    read_only: bool = True
    idempotent: bool = True
    trusted_by_default: bool = False
    enabled_by_default: bool = False
    output_schema: dict[str, Any] | None = None


@dataclass
class CapabilityRegistry:
    skills: dict[str, SkillCapability] = field(default_factory=dict)
    tools: dict[str, ToolCapability] = field(default_factory=dict)
    records: dict[str, AgentCapabilityRead] = field(default_factory=dict)

    def enabled_skills(self) -> list[SkillCapability]:
        return [
            skill
            for skill in self.skills.values()
            if self.records[skill.capability_id].eligible
        ]

    def enabled_tools(self) -> list[ToolCapability]:
        return [
            tool
            for tool in self.tools.values()
            if self.records[tool.capability_id].eligible
        ]

    def tool(self, name: str) -> ToolCapability | None:
        tool = self.tools.get(name)
        if tool is None or not self.records[tool.capability_id].eligible:
            return None
        return tool

    def tool_definitions(self, preferred: set[str] | None = None) -> list[dict[str, Any]]:
        core = {"get_project_overview", "recall_memory", "search_paper", "search_code"}
        selected = preferred | core if preferred else None
        tools = [
            tool
            for tool in self.enabled_tools()
            if selected is None or tool.name in selected or tool.source != "bundled"
        ]
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    def execute(
        self,
        session: Session,
        project_id: int,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        tool = self.tool(name)
        if tool is None:
            raise ValueError("unknown_or_disabled_tool")
        return tool.executor(session, project_id, arguments)

    def snapshot(self, selected_skills: list[SkillCapability]) -> list[dict[str, Any]]:
        capabilities: list[SkillCapability | ToolCapability] = [
            *selected_skills,
            *self.enabled_tools(),
        ]
        return [
            {
                "capability_id": item.capability_id,
                "name": item.name,
                "source": item.source,
                "version": item.version,
                "content_hash": getattr(item, "content_hash", ""),
            }
            for item in capabilities
        ]


def _setting(
    session: Session,
    capability_id: str,
    *,
    enabled_default: bool,
    trusted_default: bool,
) -> tuple[bool, bool]:
    value = session.get(AgentCapabilitySetting, capability_id)
    if value is None:
        return enabled_default, trusted_default
    return value.enabled, value.trusted


def _record(
    registry: CapabilityRegistry,
    session: Session,
    capability: SkillCapability | ToolCapability,
    kind: str,
) -> None:
    enabled, trusted = _setting(
        session,
        capability.capability_id,
        enabled_default=capability.enabled_by_default,
        trusted_default=capability.trusted_by_default,
    )
    eligible = enabled and trusted
    registry.records[capability.capability_id] = AgentCapabilityRead(
        capability_id=capability.capability_id,
        name=capability.name,
        title=capability.title,
        description=capability.description,
        kind=kind,
        source=capability.source,
        version=capability.version,
        enabled=enabled,
        trusted=trusted,
        eligible=eligible,
        read_only=getattr(capability, "read_only", True),
        requires_confirmation=not getattr(capability, "read_only", True),
        reason=None if eligible else "not_trusted" if enabled else "disabled",
    )


def _frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("skill_frontmatter_missing")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("skill_frontmatter_invalid")
    metadata = yaml.safe_load(parts[1]) or {}
    if not isinstance(metadata, dict):
        raise ValueError("skill_frontmatter_invalid")
    return metadata, parts[2].strip()


def _skill_from_path(path: Path, source: str, *, trusted: bool = False) -> SkillCapability:
    metadata, instructions = _frontmatter(path)
    name = str(metadata.get("name", "")).strip()
    description = str(metadata.get("description", "")).strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("skill_name_invalid")
    if not description or len(description) > 1024:
        raise ValueError("skill_description_invalid")
    extra = metadata.get("metadata", {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except json.JSONDecodeError:
            extra = {}
    tracelab = extra.get("tracelab", {}) if isinstance(extra, dict) else {}
    preferred = tracelab.get("preferred_tools", []) if isinstance(tracelab, dict) else []
    triggers = tracelab.get("triggers", []) if isinstance(tracelab, dict) else []
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return SkillCapability(
        capability_id=f"skill:{name}",
        name=name,
        title=str(metadata.get("title") or name.replace("-", " ").title()),
        description=description,
        instructions=instructions[:40_000],
        preferred_tools=tuple(str(item) for item in preferred[:32]),
        triggers=tuple(str(item).lower() for item in triggers[:64]),
        source=source,
        version=str(metadata.get("version", "1"))[:32],
        trusted_by_default=trusted,
        enabled_by_default=trusted,
        content_hash=digest,
    )


def _skill_roots() -> list[tuple[Path, str, bool]]:
    bundled = Path(__file__).with_name("builtin_skills")
    workspace = Path(__file__).resolve().parents[4]
    configured = settings.tracelab_agent_skill_roots
    if isinstance(configured, str):
        configured = [configured]
    roots = [
        (bundled, "bundled", True),
        (Path.home() / ".tracelab" / "skills", "managed", False),
        (Path.home() / ".openclaw" / "skills", "openclaw", False),
        (workspace / "skills", "workspace", False),
    ]
    roots.extend((Path(item).expanduser(), "extra", False) for item in configured)
    return roots


def _register_builtin_tools(registry: CapabilityRegistry, session: Session) -> None:
    from app.services.agent import tools as builtin

    for name, model in builtin.ARGUMENT_MODELS.items():
        read_only = name in builtin.READ_TOOLS

        def execute(
            current_session: Session,
            project_id: int,
            arguments: dict[str, Any],
            *,
            tool_name: str = name,
        ) -> dict[str, Any]:
            if tool_name not in builtin.READ_TOOLS:
                raise ValueError("write_tool_requires_confirmation")
            return builtin.execute_read_tool(current_session, project_id, tool_name, arguments)

        tool = ToolCapability(
            capability_id=f"tool:{name}",
            name=name,
            title=name.replace("_", " ").title(),
            description=builtin.TOOL_DESCRIPTIONS[name],
            input_schema=model.model_json_schema(),
            executor=execute,
            source="builtin",
            read_only=read_only,
            idempotent=name not in builtin.WRITE_TOOLS,
            trusted_by_default=True,
            enabled_by_default=True,
        )
        registry.tools[name] = tool
        _record(registry, session, tool, "tool")


def _plugin_roots() -> list[Path]:
    workspace = Path(__file__).resolve().parents[4]
    configured = settings.tracelab_agent_plugin_roots
    if isinstance(configured, str):
        configured = [configured]
    return [
        Path.home() / ".tracelab" / "plugins",
        workspace / "plugins",
        *(Path(item).expanduser() for item in configured),
    ]


def _discover_mcp_tools(config: MCPServerConfig) -> list[dict[str, Any]]:
    cache_key = json.dumps(
        {
            "server_id": config.server_id,
            "url": config.url,
            "headers": config.headers,
        },
        sort_keys=True,
    )
    now = time.monotonic()
    with _mcp_tool_cache_lock:
        cached = _mcp_tool_cache.get(cache_key)
        if cached and now - cached[0] < _MCP_TOOL_CACHE_TTL_SECONDS:
            return cached[1]
    try:
        tools = MCPHttpClient(config).list_tools()
    except Exception:
        if cached:
            return cached[1]
        raise
    with _mcp_tool_cache_lock:
        _mcp_tool_cache[cache_key] = (now, tools)
    return tools


def _register_plugins(registry: CapabilityRegistry, session: Session) -> None:
    for root in _plugin_roots():
        if not root.is_dir():
            continue
        for manifest_path in sorted(root.glob("*/tracelab.plugin.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                plugin_id = str(manifest["id"])
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", plugin_id):
                    continue
                capability_id = f"plugin:{plugin_id}"
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
            enabled, trusted = _setting(
                session,
                capability_id,
                enabled_default=False,
                trusted_default=False,
            )
            registry.records[capability_id] = AgentCapabilityRead(
                capability_id=capability_id,
                name=plugin_id,
                title=str(manifest.get("name") or plugin_id),
                description=str(manifest.get("description") or "TraceLab external plugin"),
                kind="plugin",
                source=str(manifest_path.parent),
                version=str(manifest.get("version", "1")),
                enabled=enabled,
                trusted=trusted,
                eligible=enabled and trusted,
                read_only=False,
                requires_confirmation=True,
                reason=None if enabled and trusted else "not_trusted" if enabled else "disabled",
            )
            if not enabled or not trusted:
                continue
            for skill_dir in manifest.get("skills", []):
                skill_root = (manifest_path.parent / str(skill_dir)).resolve()
                if manifest_path.parent.resolve() not in skill_root.parents:
                    continue
                for skill_path in sorted(skill_root.glob("*/SKILL.md")):
                    try:
                        skill = _skill_from_path(skill_path, f"plugin:{plugin_id}", trusted=True)
                    except (OSError, ValueError):
                        continue
                    if skill.name not in registry.skills:
                        registry.skills[skill.name] = skill
                        _record(registry, session, skill, "skill")
            for server in manifest.get("mcp_servers", []):
                _register_mcp_server(registry, session, plugin_id, server)


def _register_mcp_server(
    registry: CapabilityRegistry,
    session: Session,
    plugin_id: str,
    payload: Any,
) -> None:
    if not isinstance(payload, dict) or payload.get("transport", "http") != "http":
        return
    server_id = str(payload.get("id", "")).strip()
    url = str(payload.get("url", "")).strip()
    if not server_id or not url.startswith(("http://", "https://")):
        return
    headers = payload.get("headers", {})
    if not isinstance(headers, dict) or len(headers) > 32:
        return
    normalized_headers: dict[str, str] = {}
    for key, value in headers.items():
        header_key = str(key)
        header_value = str(value)
        if (
            not header_key
            or len(header_key) > 128
            or len(header_value) > 4096
            or "\n" in header_key
            or "\r" in header_key
            or "\n" in header_value
            or "\r" in header_value
        ):
            return
        normalized_headers[header_key] = header_value
    try:
        timeout_seconds = min(max(float(payload.get("timeout_seconds", 15)), 1), 60)
    except (TypeError, ValueError):
        return
    config = MCPServerConfig(
        server_id=server_id,
        url=url,
        headers=normalized_headers,
        timeout_seconds=timeout_seconds,
    )
    try:
        remote_tools = _discover_mcp_tools(config)
    except Exception:
        return
    for remote in remote_tools[:100]:
        remote_name = str(remote.get("name", "")).strip()
        input_schema = remote.get("inputSchema")
        if (
            not remote_name
            or not isinstance(input_schema, dict)
            or input_schema.get("type") != "object"
        ):
            continue
        annotations = remote.get("annotations", {})
        read_only = bool(annotations.get("readOnlyHint", False))
        raw_name = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            f"mcp__{plugin_id}__{server_id}__{remote_name}",
        ).strip("_")
        digest = hashlib.sha256(
            f"{plugin_id}\0{server_id}\0{remote_name}".encode()
        ).hexdigest()[:10]
        local_name = f"{raw_name[:53]}_{digest}"

        def execute(
            _session: Session,
            _project_id: int,
            arguments: dict[str, Any],
            *,
            tool_name: str = remote_name,
            schema: dict[str, Any] = input_schema,
            output_schema: dict[str, Any] | None = remote.get("outputSchema"),
            server_config: MCPServerConfig = config,
        ) -> dict[str, Any]:
            return MCPHttpClient(server_config).call_tool(
                tool_name,
                arguments,
                schema,
                output_schema,
            )

        tool = ToolCapability(
            capability_id=f"tool:{local_name}",
            name=local_name,
            title=str(remote.get("title") or remote_name),
            description=str(remote.get("description") or f"MCP tool from {plugin_id}"),
            input_schema=input_schema,
            output_schema=remote.get("outputSchema"),
            executor=execute,
            source=f"mcp:{plugin_id}/{server_id}",
            version="1",
            read_only=read_only,
            idempotent=bool(annotations.get("idempotentHint", False)),
            trusted_by_default=True,
            enabled_by_default=True,
        )
        registry.tools[local_name] = tool
        _record(registry, session, tool, "tool")


def build_registry(session: Session) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    _register_builtin_tools(registry, session)
    for root, source, trusted in _skill_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/SKILL.md")):
            try:
                skill = _skill_from_path(path, source, trusted=trusted)
            except (OSError, ValueError):
                continue
            if skill.name in registry.skills:
                continue
            registry.skills[skill.name] = skill
            _record(registry, session, skill, "skill")
    _register_plugins(registry, session)
    return registry


def select_skills(
    registry: CapabilityRegistry,
    message: str,
    context: dict[str, Any],
) -> list[SkillCapability]:
    lowered = message.lower()
    tokens = set(re.findall(r"[a-z0-9_./:-]{2,}|[\u4e00-\u9fff]{2,}", lowered))
    ranked: list[tuple[float, SkillCapability]] = []
    for skill in registry.enabled_skills():
        description = f"{skill.name} {skill.description}".lower()
        score = sum(1.0 for token in tokens if token in description)
        score += sum(2.0 for trigger in skill.triggers if trigger and trigger in lowered)
        if context.get("graph") and "architecture" in skill.name:
            score += 1.5
        if score > 0:
            ranked.append((score, skill))
    ranked.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    selected = [skill for _score, skill in ranked[:3]]
    if not selected:
        fallback = registry.skills.get("paper-explanation")
        if fallback and registry.records[fallback.capability_id].eligible:
            selected = [fallback]
    return selected


def skill_prompt(skills: list[SkillCapability]) -> str:
    skill_text = "\n\n".join(
        f"## Skill: {skill.name}\n{skill.instructions}" for skill in skills
    )
    return (
        "You are TraceLab Agent, an evidence-driven coding and paper-research agent "
        "embedded in an IDE. Operate through eligible tools only. Read before editing. "
        "Treat tool errors as recoverable, but never repeat the same call unchanged. "
        "Writes require explicit confirmation. Cite observed evidence and state uncertainty.\n\n"
        f"{skill_text}"
    )


def list_capabilities(session: Session) -> list[AgentCapabilityRead]:
    registry = build_registry(session)
    return sorted(registry.records.values(), key=lambda item: (item.kind, item.name))


def update_capability(
    session: Session,
    capability_id: str,
    payload: AgentCapabilityUpdate,
) -> AgentCapabilityRead | None:
    registry = build_registry(session)
    if capability_id not in registry.records:
        return None
    setting = session.get(AgentCapabilitySetting, capability_id)
    if setting is None:
        setting = AgentCapabilitySetting(capability_id=capability_id)
    setting.enabled = payload.enabled
    setting.trusted = payload.trusted
    setting.updated_at = utc_now()
    session.add(setting)
    session.commit()
    refreshed = build_registry(session)
    return refreshed.records.get(capability_id)
