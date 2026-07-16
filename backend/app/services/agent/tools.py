from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink
from app.services import workspace_service

MAX_TOOL_CONTENT_CHARS = 512_000
READ_TOOLS = {
    "get_project_overview",
    "search_paper",
    "get_paper_block",
    "search_code",
    "read_code_file",
    "get_code_symbol",
    "get_architecture",
    "get_graph_node",
    "list_trace_links",
    "get_trace_detail",
    "recall_memory",
    "propose_code_patch",
    "analyze_change_risk",
    "open_code_location",
    "focus_architecture",
}
WRITE_TOOLS = {
    "save_code_file",
    "rerun_analysis",
    "update_trace_status",
    "create_trace_link",
}


class StrictArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectOverviewArguments(StrictArguments):
    pass


class SearchPaperArguments(StrictArguments):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


class PaperBlockArguments(StrictArguments):
    block_id: str = Field(min_length=1, max_length=255)


class CodeSymbolArguments(StrictArguments):
    symbol_id: str = Field(min_length=1, max_length=500)


class SearchCodeArguments(StrictArguments):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=12, ge=1, le=30)


class ReadCodeFileArguments(StrictArguments):
    path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(default=1, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class ArchitectureArguments(StrictArguments):
    view: Literal["architecture", "debug"] = "architecture"
    root_symbol: str | None = Field(default=None, max_length=500)


class GraphNodeArguments(StrictArguments):
    node_id: str = Field(min_length=1, max_length=255)


class ListTraceArguments(StrictArguments):
    status: str | None = Field(default=None, pattern="^(proposed|accepted|rejected|stale)$")


class TraceDetailArguments(StrictArguments):
    trace_id: str = Field(min_length=1, max_length=64)


class RecallMemoryArguments(StrictArguments):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=20)


class PatchArguments(StrictArguments):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=MAX_TOOL_CONTENT_CHARS)


class RiskAnalysisArguments(StrictArguments):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=MAX_TOOL_CONTENT_CHARS)


class OpenCodeLocationArguments(StrictArguments):
    path: str = Field(min_length=1, max_length=1000)
    line: int = Field(default=1, ge=1)


class FocusArchitectureArguments(StrictArguments):
    root_symbol: str | None = Field(default=None, max_length=500)
    view: Literal["architecture", "debug"] = "architecture"


class SaveCodeArguments(PatchArguments):
    base_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


class RerunAnalysisArguments(StrictArguments):
    targets: list[str] = Field(default_factory=list, max_length=50)


class UpdateTraceArguments(StrictArguments):
    trace_id: str = Field(min_length=1, max_length=64)
    status: Literal["accepted", "rejected"]


class CreateTraceArguments(StrictArguments):
    paper_ref: str = Field(min_length=1, max_length=255)
    code_ref: str = Field(min_length=1, max_length=500)
    relation_type: str = Field(default="implements", min_length=1, max_length=64)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=4000)


ARGUMENT_MODELS = {
    "get_project_overview": ProjectOverviewArguments,
    "search_paper": SearchPaperArguments,
    "get_paper_block": PaperBlockArguments,
    "search_code": SearchCodeArguments,
    "read_code_file": ReadCodeFileArguments,
    "get_code_symbol": CodeSymbolArguments,
    "get_architecture": ArchitectureArguments,
    "get_graph_node": GraphNodeArguments,
    "list_trace_links": ListTraceArguments,
    "get_trace_detail": TraceDetailArguments,
    "recall_memory": RecallMemoryArguments,
    "propose_code_patch": PatchArguments,
    "analyze_change_risk": RiskAnalysisArguments,
    "open_code_location": OpenCodeLocationArguments,
    "focus_architecture": FocusArchitectureArguments,
    "save_code_file": SaveCodeArguments,
    "rerun_analysis": RerunAnalysisArguments,
    "update_trace_status": UpdateTraceArguments,
    "create_trace_link": CreateTraceArguments,
}

TOOL_DESCRIPTIONS = {
    "get_project_overview": (
        "Read the current project, paper, repository, trace, and architecture summary."
    ),
    "search_paper": "Search structured paper paragraphs by keyword before making paper claims.",
    "get_paper_block": "Read one exact structured paper block by ID.",
    "search_code": "Search repository paths and indexed symbols.",
    "read_code_file": "Read an editable repository file or a bounded line range.",
    "get_code_symbol": "Read indexed metadata for one code symbol.",
    "get_architecture": "Read the module architecture or low-level debug graph for one model root.",
    "get_graph_node": "Read one selected architecture or debug graph node.",
    "list_trace_links": "List paper-code trace links, optionally filtered by review status.",
    "get_trace_detail": "Read evidence, rationale, confidence, and uncertainty for one trace.",
    "recall_memory": "Search project and cross-project Agent memory.",
    "propose_code_patch": (
        "Compare complete proposed file content against the current file without saving."
    ),
    "analyze_change_risk": (
        "Analyze a complete proposed file change for affected symbols, callers, and traces."
    ),
    "open_code_location": (
        "Ask the IDE to open a repository file at a line; this is a safe UI action."
    ),
    "focus_architecture": "Ask the IDE to open a model architecture root or debug graph.",
    "save_code_file": (
        "Save complete file content after patch and risk analysis; requires confirmation."
    ),
    "rerun_analysis": "Rerun repository analysis for selected paths; requires confirmation.",
    "update_trace_status": "Accept or reject a proposed trace; requires confirmation.",
    "create_trace_link": (
        "Create a paper-code trace with evidence rationale; requires confirmation."
    ),
}


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": model.model_json_schema(),
            },
        }
        for name, model in ARGUMENT_MODELS.items()
    ]


def validate_relative_path(path: str) -> str:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
        raise ValueError("invalid_relative_path")
    normalized = parsed.as_posix()
    if normalized.startswith("./") or "\\" in path:
        raise ValueError("invalid_relative_path")
    return normalized


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def latest_paper(session: Session, project_id: int) -> PaperDocument | None:
    return session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()


def latest_code(session: Session, project_id: int) -> CodeRepository | None:
    return session.exec(
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    ).first()


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> StrictArguments:
    model = ARGUMENT_MODELS.get(tool_name)
    if model is None:
        raise ValueError("unknown_tool")
    validated = model.model_validate(arguments)
    if hasattr(validated, "path"):
        validated.path = validate_relative_path(validated.path)
    if isinstance(validated, RerunAnalysisArguments):
        validated.targets = [validate_relative_path(path) for path in validated.targets]
    return validated


def build_context_snapshot(session: Session, project_id: int, context: Any) -> dict[str, Any]:
    def read(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return execute_read_tool(session, project_id, tool_name, arguments)
        except Exception as exc:
            return {
                "found": False,
                "error": "context_read_failed",
                "tool": tool_name,
                "failure_type": exc.__class__.__name__,
            }

    snapshot: dict[str, Any] = {"environment": read("get_project_overview", {})}
    if context.paper_block_id:
        snapshot["paper"] = read("get_paper_block", {"block_id": context.paper_block_id})
    if context.code_symbol_id:
        snapshot["code"] = read("get_code_symbol", {"symbol_id": context.code_symbol_id})
    if context.graph_node_id:
        snapshot["graph"] = read("get_graph_node", {"node_id": context.graph_node_id})
    if context.file_path:
        start = max((context.line or 1) - 20, 1)
        snapshot["active_file"] = read(
            "read_code_file",
            {
                "path": context.file_path,
                "line_start": start,
                "line_end": start + 60,
            },
        )
    if context.trace_id:
        snapshot["trace"] = read("get_trace_detail", {"trace_id": context.trace_id})
    if context.graph_root_symbol and not context.graph_node_id:
        snapshot["graph"] = read(
            "get_architecture",
            {"root_symbol": context.graph_root_symbol, "view": "architecture"},
        )
    return snapshot


def execute_read_tool(
    session: Session, project_id: int, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    validated = validate_tool_arguments(tool_name, arguments)
    paper = latest_paper(session, project_id)
    code = latest_code(session, project_id)
    if isinstance(validated, ProjectOverviewArguments):
        project = session.get(Project, project_id)
        trace_links = session.exec(
            select(TraceLink).where(TraceLink.project_id == project_id)
        ).all()
        trace_statuses: dict[str, int] = {}
        for link in trace_links:
            trace_statuses[link.status] = trace_statuses.get(link.status, 0) + 1
        architecture = (
            workspace_service.get_tensor_flow(session, project_id)
            if code is not None
            else {"root_label": None, "nodes": [], "available_roots": []}
        )
        return {
            "found": project is not None,
            "ref": f"project:{project_id}",
            "project": {
                "id": project_id,
                "name": project.name if project else "",
                "description": project.description if project else "",
            },
            "paper": {
                "available": paper is not None,
                "title": paper.title if paper else "",
                "parser": paper.parser if paper else None,
                "section_count": len(paper.sections_json) if paper else 0,
            },
            "repository": {
                "available": code is not None,
                "revision": code.revision if code else None,
                "file_count": len(code.file_tree_json) if code else 0,
                "symbol_count": len(code.symbols_json) if code else 0,
            },
            "architecture": {
                "root": architecture.get("root_label"),
                "node_count": len(architecture.get("nodes", [])),
                "available_roots": [
                    root.get("label") for root in architecture.get("available_roots", [])[:12]
                ],
            },
            "traces": {"total": len(trace_links), "by_status": trace_statuses},
        }
    if isinstance(validated, SearchPaperArguments):
        if paper is None:
            return {"found": False, "items": []}
        query_tokens = {
            token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", validated.query)
        }
        ranked: list[tuple[int, dict[str, Any]]] = []
        for paragraph in paper.paragraphs_json:
            text = str(paragraph.get("text", ""))
            lowered = text.lower()
            score = sum(lowered.count(token) for token in query_tokens)
            if score:
                ranked.append((score, paragraph))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return {
            "found": bool(ranked),
            "query": validated.query,
            "items": [
                {
                    "ref": str(item.get("id", "")),
                    "text": str(item.get("text", ""))[:2400],
                    "page": item.get("page"),
                    "section": item.get("section_title") or item.get("section"),
                }
                for _score, item in ranked[: validated.limit]
            ],
        }
    if isinstance(validated, PaperBlockArguments):
        if paper is None:
            return {"found": False}
        for paragraph in paper.paragraphs_json:
            if str(paragraph.get("id")) == validated.block_id:
                return {
                    "found": True,
                    "ref": validated.block_id,
                    "text": str(paragraph.get("text", ""))[:2000],
                    "page": paragraph.get("page"),
                }
        return {"found": False, "ref": validated.block_id}
    if isinstance(validated, SearchCodeArguments):
        if code is None:
            return {"found": False, "items": []}
        query = validated.query.lower()
        terms = [term for term in re.split(r"\s+", query) if term]
        items: list[tuple[int, dict[str, Any]]] = []
        for symbol in code.symbols_json:
            value = " ".join(
                str(symbol.get(key, "")) for key in ("id", "qualified_name", "name", "path", "kind")
            ).lower()
            score = sum(value.count(term) for term in terms)
            if score:
                items.append(
                    (
                        score + 2,
                        {
                            "ref": str(symbol.get("id", "")),
                            "kind": "symbol",
                            "name": symbol.get("qualified_name") or symbol.get("name"),
                            "path": symbol.get("path"),
                            "line_start": symbol.get("line_start") or symbol.get("line"),
                            "line_end": symbol.get("line_end"),
                        },
                    )
                )
        for entry in code.file_tree_json:
            path = str(entry.get("path", ""))
            score = sum(path.lower().count(term) for term in terms)
            if score:
                items.append((score, {"ref": path, "kind": "file", "path": path}))
        items.sort(key=lambda item: item[0], reverse=True)
        return {
            "found": bool(items),
            "query": validated.query,
            "items": [item for _score, item in items[: validated.limit]],
        }
    if isinstance(validated, ReadCodeFileArguments):
        current = workspace_service.get_code_file(session, project_id, validated.path)
        if current is None:
            return {"found": False, "path": validated.path}
        content = str(current["content"])
        lines = content.splitlines()
        line_end = min(validated.line_end or len(lines), len(lines))
        if line_end < validated.line_start:
            raise ValueError("invalid_line_range")
        selected = lines[validated.line_start - 1 : line_end]
        return {
            "found": True,
            "ref": f"{validated.path}:{validated.line_start}-{line_end}",
            "path": validated.path,
            "line_start": validated.line_start,
            "line_end": line_end,
            "content": "\n".join(
                f"{line_number:>5} | {line}"
                for line_number, line in enumerate(selected, validated.line_start)
            )[:40_000],
            "base_sha256": content_sha256(content),
            "total_lines": len(lines),
        }
    if isinstance(validated, CodeSymbolArguments):
        if code is None:
            return {"found": False}
        for symbol in code.symbols_json:
            path = str(symbol.get("path", ""))
            name = str(symbol.get("qualified_name") or symbol.get("name", ""))
            symbol_id = str(symbol.get("id") or f"{path}::{name}")
            if symbol_id == validated.symbol_id:
                allowed = {
                    key: value
                    for key, value in symbol.items()
                    if key not in {"storage_path", "absolute_path"}
                }
                return {"found": True, "ref": symbol_id, "symbol": allowed}
        return {"found": False, "ref": validated.symbol_id}
    if isinstance(validated, ArchitectureArguments):
        graph = workspace_service.get_tensor_flow(
            session,
            project_id,
            view=validated.view,
            root_symbol=validated.root_symbol,
        )
        return {
            "found": bool(graph.get("nodes")),
            "ref": str(graph.get("root_symbol") or "architecture"),
            "view": graph.get("view"),
            "root_symbol": graph.get("root_symbol"),
            "root_label": graph.get("root_label"),
            "nodes": [
                {
                    key: node.get(key)
                    for key in (
                        "id",
                        "label",
                        "kind",
                        "description",
                        "source_path",
                        "line_start",
                        "line_end",
                        "component_symbol_id",
                        "expandable",
                        "external",
                    )
                }
                for node in graph.get("nodes", [])[:120]
            ],
            "edges": [
                {key: edge.get(key) for key in ("source", "target", "kind", "label")}
                for edge in graph.get("edges", [])[:180]
            ],
        }
    if isinstance(validated, GraphNodeArguments):
        if code is None:
            return {"found": False}
        for node in code.tensor_graph_json.get("nodes", []):
            if str(node.get("id")) == validated.node_id:
                return {"found": True, "ref": validated.node_id, "node": node}
        symbol = validated.node_id.split("#", 1)[0]
        root_symbol = symbol.rsplit(".", 1)[0] if "::" in symbol and "." in symbol else None
        for view in ("architecture", "debug"):
            graph = workspace_service.get_tensor_flow(
                session,
                project_id,
                view=view,
                root_symbol=root_symbol,
            )
            for node in graph.get("nodes", []):
                if str(node.get("id")) == validated.node_id:
                    return {"found": True, "ref": validated.node_id, "node": node, "view": view}
        return {"found": False, "ref": validated.node_id}
    if isinstance(validated, ListTraceArguments):
        statement = select(TraceLink).where(TraceLink.project_id == project_id)
        if validated.status:
            statement = statement.where(TraceLink.status == validated.status)
        links = session.exec(statement.order_by(TraceLink.id.desc()).limit(20)).all()
        return {
            "items": [
                {
                    "ref": link.trace_id,
                    "paper_block_id": link.paper_ref,
                    "code_symbol_id": link.code_ref,
                    "status": link.status,
                    "confidence": link.confidence,
                }
                for link in links
            ]
        }
    if isinstance(validated, TraceDetailArguments):
        link = session.exec(
            select(TraceLink).where(
                TraceLink.project_id == project_id,
                TraceLink.trace_id == validated.trace_id,
            )
        ).first()
        if link is None:
            return {"found": False, "ref": validated.trace_id}
        return {
            "found": True,
            "ref": link.trace_id,
            "paper_ref": link.paper_ref,
            "code_ref": link.code_ref,
            "relation_type": link.relation_type,
            "confidence": link.confidence,
            "status": link.status,
            "source": link.source,
            "rationale": link.rationale,
            "evidence": link.evidence_json,
            "uncertainty": link.uncertainty_json,
            "stale_reason": link.stale_reason,
        }
    if isinstance(validated, RecallMemoryArguments):
        from app.services.agent.memory import retrieve_memories

        items = retrieve_memories(session, project_id, validated.query, limit=validated.limit)
        return {"found": bool(items), "items": items}
    if isinstance(validated, PatchArguments):
        current = workspace_service.get_code_file(session, project_id, validated.path)
        if current is None:
            return {"found": False, "path": validated.path}
        old_content = str(current["content"])
        diff = "".join(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                validated.content.splitlines(keepends=True),
                fromfile=validated.path,
                tofile=validated.path,
            )
        )
        return {
            "found": True,
            "path": validated.path,
            "base_sha256": content_sha256(old_content),
            "target_sha256": content_sha256(validated.content),
            "diff": diff[:20_000],
        }
    if isinstance(validated, RiskAnalysisArguments):
        current = workspace_service.get_code_file(session, project_id, validated.path)
        if current is None:
            return {"found": False, "path": validated.path}
        old_content = str(current["content"])
        repository = session.exec(
            select(CodeRepository)
            .where(CodeRepository.project_id == project_id)
            .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
        ).first()
        from app.services.analysis_jobs import analysis_is_current

        if repository is None or not analysis_is_current(repository):
            return {
                "found": False,
                "error": "analysis_pending",
                "path": validated.path,
                "base_sha256": content_sha256(old_content),
                "target_sha256": content_sha256(validated.content),
            }
        diff_lines = list(
            difflib.unified_diff(
                old_content.splitlines(),
                validated.content.splitlines(),
                fromfile=validated.path,
                tofile=validated.path,
            )
        )
        analysis = repository.analysis_json
        symbols = [
            symbol for symbol in analysis.get("symbols", []) if symbol.get("path") == validated.path
        ]
        symbol_names = {str(symbol.get("name", "")) for symbol in symbols if symbol.get("name")}
        callers = [
            call
            for call in analysis.get("calls", [])
            if str(call.get("callee", "")).rsplit(".", 1)[-1] in symbol_names
        ][:30]
        trace_links = session.exec(
            select(TraceLink).where(TraceLink.project_id == project_id)
        ).all()
        affected_traces = [
            link
            for link in trace_links
            if validated.path in link.code_ref
            or any(name and name in link.code_ref for name in symbol_names)
        ]
        changed_lines = sum(
            1
            for line in diff_lines
            if (line.startswith("+") or line.startswith("-"))
            and not line.startswith("+++")
            and not line.startswith("---")
        )
        accepted = sum(link.status == "accepted" for link in affected_traces)
        core_model = any(part in validated.path.lower() for part in ("model", "backbone", "head"))
        risk_score = min(
            1.0,
            changed_lines / 180
            + len(callers) * 0.035
            + accepted * 0.18
            + (0.2 if core_model else 0),
        )
        risk_level = "high" if risk_score >= 0.65 else "medium" if risk_score >= 0.3 else "low"
        return {
            "found": True,
            "ref": validated.path,
            "path": validated.path,
            "base_sha256": content_sha256(old_content),
            "target_sha256": content_sha256(validated.content),
            "changed_lines": changed_lines,
            "risk_level": risk_level,
            "risk_score": round(risk_score, 3),
            "affected_symbols": [str(symbol.get("id")) for symbol in symbols[:30]],
            "caller_count": len(callers),
            "callers": [
                {
                    "ref": call.get("caller_symbol_id"),
                    "callee": call.get("callee"),
                    "path": call.get("path"),
                    "line_start": call.get("line_start"),
                }
                for call in callers
            ],
            "affected_traces": [
                {"ref": link.trace_id, "status": link.status, "confidence": link.confidence}
                for link in affected_traces[:20]
            ],
            "recommendations": [
                "重新运行静态分析和相关测试",
                "复核已接受追溯关系" if accepted else "检查新增代码与论文声明的一致性",
            ],
        }
    if isinstance(validated, OpenCodeLocationArguments):
        current = workspace_service.get_code_file(session, project_id, validated.path)
        if current is None:
            return {"found": False, "path": validated.path}
        return {
            "found": True,
            "ref": f"{validated.path}:{validated.line}",
            "ui_action": {"type": "open_code", "path": validated.path, "line": validated.line},
        }
    if isinstance(validated, FocusArchitectureArguments):
        graph = workspace_service.get_tensor_flow(
            session,
            project_id,
            view=validated.view,
            root_symbol=validated.root_symbol,
        )
        return {
            "found": bool(graph.get("nodes")),
            "ref": str(graph.get("root_symbol") or "architecture"),
            "ui_action": {
                "type": "focus_architecture",
                "root_symbol": graph.get("root_symbol"),
                "view": validated.view,
            },
        }
    raise ValueError("write_tool_requires_confirmation")


def prepare_write_request(
    session: Session, project_id: int, tool_name: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    validated = validate_tool_arguments(tool_name, arguments)
    payload = validated.model_dump()
    if isinstance(validated, SaveCodeArguments):
        current = workspace_service.get_code_file(session, project_id, validated.path)
        if current is None:
            raise ValueError("code_file_not_found_or_not_editable")
        base_hash = content_sha256(str(current["content"]))
        if validated.base_sha256 and validated.base_sha256 != base_hash:
            raise ValueError("base_content_changed")
        payload["base_sha256"] = base_hash
        summary = {
            "path": validated.path,
            "characters": len(validated.content),
            "base_sha256": base_hash,
            "target_sha256": content_sha256(validated.content),
        }
        return payload, summary
    if isinstance(validated, RerunAnalysisArguments):
        return payload, {"targets": validated.targets, "target_count": len(validated.targets)}
    if isinstance(validated, UpdateTraceArguments):
        link = session.exec(
            select(TraceLink).where(
                TraceLink.project_id == project_id,
                TraceLink.trace_id == validated.trace_id,
            )
        ).first()
        if link is None:
            raise ValueError("trace_not_found")
        if link.status != "proposed":
            raise ValueError("trace_not_proposed")
        return payload, {"trace_id": validated.trace_id, "status": validated.status}
    if isinstance(validated, CreateTraceArguments):
        paper = latest_paper(session, project_id)
        code = latest_code(session, project_id)
        if paper is None or not any(
            str(paragraph.get("id")) == validated.paper_ref for paragraph in paper.paragraphs_json
        ):
            raise ValueError("paper_block_not_found")
        if code is None:
            raise ValueError("code_repository_not_found")
        known_refs = {str(symbol.get("id")) for symbol in code.symbols_json if symbol.get("id")}
        known_refs.update(
            str(entry.get("path")) for entry in code.file_tree_json if entry.get("path")
        )
        if validated.code_ref not in known_refs:
            raise ValueError("code_reference_not_found")
        return payload, {
            "paper_ref": validated.paper_ref,
            "code_ref": validated.code_ref,
            "relation_type": validated.relation_type,
            "confidence": validated.confidence,
            "rationale": validated.rationale[:500],
        }
    raise ValueError("read_tool_does_not_require_confirmation")
