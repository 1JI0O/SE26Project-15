from __future__ import annotations

import difflib
import hashlib
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.models.entities import CodeRepository, PaperDocument, TraceLink
from app.services import workspace_service

MAX_TOOL_CONTENT_CHARS = 512_000
READ_TOOLS = {
    "get_paper_block",
    "get_code_symbol",
    "get_graph_node",
    "list_trace_links",
    "propose_code_patch",
}
WRITE_TOOLS = {"save_code_file", "rerun_analysis", "update_trace_status"}


class StrictArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperBlockArguments(StrictArguments):
    block_id: str = Field(min_length=1, max_length=255)


class CodeSymbolArguments(StrictArguments):
    symbol_id: str = Field(min_length=1, max_length=500)


class GraphNodeArguments(StrictArguments):
    node_id: str = Field(min_length=1, max_length=255)


class ListTraceArguments(StrictArguments):
    status: str | None = Field(default=None, pattern="^(proposed|accepted|rejected|stale)$")


class PatchArguments(StrictArguments):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=MAX_TOOL_CONTENT_CHARS)


class SaveCodeArguments(PatchArguments):
    base_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


class RerunAnalysisArguments(StrictArguments):
    targets: list[str] = Field(default_factory=list, max_length=50)


class UpdateTraceArguments(StrictArguments):
    trace_id: str = Field(min_length=1, max_length=64)
    status: Literal["accepted", "rejected"]


ARGUMENT_MODELS = {
    "get_paper_block": PaperBlockArguments,
    "get_code_symbol": CodeSymbolArguments,
    "get_graph_node": GraphNodeArguments,
    "list_trace_links": ListTraceArguments,
    "propose_code_patch": PatchArguments,
    "save_code_file": SaveCodeArguments,
    "rerun_analysis": RerunAnalysisArguments,
    "update_trace_status": UpdateTraceArguments,
}


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
    snapshot: dict[str, Any] = {}
    if context.paper_block_id:
        snapshot["paper"] = execute_read_tool(
            session, project_id, "get_paper_block", {"block_id": context.paper_block_id}
        )
    if context.code_symbol_id:
        snapshot["code"] = execute_read_tool(
            session, project_id, "get_code_symbol", {"symbol_id": context.code_symbol_id}
        )
    if context.graph_node_id:
        snapshot["graph"] = execute_read_tool(
            session, project_id, "get_graph_node", {"node_id": context.graph_node_id}
        )
    return snapshot


def execute_read_tool(
    session: Session, project_id: int, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    validated = validate_tool_arguments(tool_name, arguments)
    paper = latest_paper(session, project_id)
    code = latest_code(session, project_id)
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
    if isinstance(validated, GraphNodeArguments):
        if code is None:
            return {"found": False}
        for node in code.tensor_graph_json.get("nodes", []):
            if str(node.get("id")) == validated.node_id:
                return {"found": True, "ref": validated.node_id, "node": node}
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
    raise ValueError("read_tool_does_not_require_confirmation")
