from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.models.entities import AgentAnalysisArtifact, CodeRepository, PaperDocument
from app.services.analysis_jobs import repository_edits_root
from app.services.code_analysis.editor import FileAccessError, read_repository_file


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageArguments(StrictModel):
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class RepositoryFilesArguments(PageArguments):
    prefix: str = Field(default="", max_length=500)
    language: str | None = Field(default=None, max_length=32)


class RepositorySearchArguments(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=50)


class CodeSymbolsArguments(PageArguments):
    path: str | None = Field(default=None, max_length=1000)
    kind: str | None = Field(default=None, max_length=32)


class SymbolArguments(StrictModel):
    symbol_id: str = Field(min_length=1, max_length=500)


class PaperBlocksArguments(PageArguments):
    section: str | None = Field(default=None, max_length=300)
    kind: str | None = Field(default=None, max_length=64)


class PaperBlockArguments(StrictModel):
    block_id: str = Field(min_length=1, max_length=255)


class ArtifactArguments(StrictModel):
    kind: Literal["architecture", "trace"]


class CodeEvidence(StrictModel):
    path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=3000)


class ArchitectureNode(StrictModel):
    id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=200)
    kind: Literal["input", "component", "operation", "branch", "merge", "output"]
    depth: int = Field(ge=0, le=3)
    description: str = Field(default="", max_length=1000)
    symbol_id: str = Field(default="", max_length=500)
    callee: str = Field(default="", max_length=500)
    source_path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    component_symbol_id: str | None = Field(default=None, max_length=500)
    expandable: bool = False
    external: bool = False
    evidence: list[CodeEvidence] = Field(min_length=1, max_length=4)


class ArchitectureEdge(StrictModel):
    id: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=255)
    target: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="call", max_length=64)
    label: str = Field(default="", max_length=160)


class UnresolvedCall(StrictModel):
    callee: str = Field(min_length=1, max_length=500)
    path: str = Field(min_length=1, max_length=1000)
    line: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class ArchitecturePayload(StrictModel):
    schema_version: Literal["architecture-agent-v1"] = "architecture-agent-v1"
    root_symbol: str = Field(min_length=1, max_length=500)
    root_label: str = Field(min_length=1, max_length=200)
    requested_depth: int = Field(ge=1, le=3)
    nodes: list[ArchitectureNode] = Field(min_length=1, max_length=300)
    edges: list[ArchitectureEdge] = Field(default_factory=list, max_length=600)
    unresolved: list[UnresolvedCall] = Field(default_factory=list, max_length=100)


class PublishArchitectureArguments(StrictModel):
    payload: ArchitecturePayload


class TracePaperEvidence(StrictModel):
    block_id: str = Field(min_length=1, max_length=255)
    quote: str = Field(min_length=1, max_length=3000)


class TraceCodeEvidence(CodeEvidence):
    symbol_id: str | None = Field(default=None, max_length=500)


class TraceCandidate(StrictModel):
    paper_block_id: str = Field(min_length=1, max_length=255)
    code_symbol_id: str = Field(min_length=1, max_length=255)
    relation_type: Literal["implements", "invokes", "configures", "tests", "mentions"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=5000)
    uncertainty_level: Literal["low", "medium", "high"]
    uncertainty_reasons: list[str] = Field(default_factory=list, max_length=8)
    paper_evidence: TracePaperEvidence
    code_evidence: TraceCodeEvidence
    graph_node_ids: list[str] = Field(default_factory=list, max_length=20)


class TracePayload(StrictModel):
    schema_version: Literal["trace-agent-v1"] = "trace-agent-v1"
    candidates: list[TraceCandidate] = Field(default_factory=list, max_length=100)
    unresolved: list[str] = Field(default_factory=list, max_length=100)


class PublishTraceArguments(StrictModel):
    payload: TracePayload


TOOL_MODELS: dict[str, type[StrictModel]] = {
    "list_repository_files": RepositoryFilesArguments,
    "search_repository_text": RepositorySearchArguments,
    "list_code_symbols": CodeSymbolsArguments,
    "get_symbol_source": SymbolArguments,
    "get_symbol_calls": SymbolArguments,
    "list_paper_blocks": PaperBlocksArguments,
    "get_paper_block": PaperBlockArguments,
    "get_analysis_artifact": ArtifactArguments,
    "publish_architecture_graph": PublishArchitectureArguments,
    "publish_trace_candidates": PublishTraceArguments,
}

TOOL_DESCRIPTIONS = {
    "list_repository_files": (
        "Page through readable repository files. Discover the repository without relying on AST "
        "symbols."
    ),
    "search_repository_text": (
        "Search repository text and return exact path, line range, and quote evidence."
    ),
    "list_code_symbols": (
        "Page through locally indexed symbols. Treat this as navigation, not a semantic conclusion."
    ),
    "get_symbol_source": "Read the exact source and line range for one indexed symbol.",
    "get_symbol_calls": (
        "List call sites inside one symbol and any uniquely resolved project targets."
    ),
    "list_paper_blocks": (
        "Page through structured paper blocks with stable IDs, page, kind, and section path."
    ),
    "get_paper_block": "Read one exact paper block and its location metadata.",
    "get_analysis_artifact": (
        "Read the latest Agent-generated architecture or trace artifact for the current revision."
    ),
    "publish_architecture_graph": (
        "Publish the final evidence-backed depth-limited architecture graph. This must be called "
        "to complete architecture analysis."
    ),
    "publish_trace_candidates": (
        "Publish all evidence-backed proposed paper-code trace candidates. This must be called "
        "to complete trace analysis."
    ),
}


def tool_definitions(kind: str) -> list[dict[str, Any]]:
    allowed = {
        "architecture": {
            "list_repository_files",
            "search_repository_text",
            "list_code_symbols",
            "get_symbol_source",
            "get_symbol_calls",
            "get_analysis_artifact",
            "publish_architecture_graph",
        },
        "trace": {
            "list_repository_files",
            "search_repository_text",
            "list_code_symbols",
            "get_symbol_source",
            "get_symbol_calls",
            "list_paper_blocks",
            "get_paper_block",
            "get_analysis_artifact",
            "publish_trace_candidates",
        },
    }[kind]
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": TOOL_MODELS[name].model_json_schema(),
            },
        }
        for name in TOOL_MODELS
        if name in allowed
    ]


def _repository(session: Session, project_id: int, repository_id: int) -> CodeRepository:
    repository = session.get(CodeRepository, repository_id)
    if repository is None or repository.project_id != project_id:
        raise ValueError("code_repository_not_found")
    return repository


def _paper(session: Session, project_id: int, paper_id: int | None) -> PaperDocument:
    paper = session.get(PaperDocument, paper_id) if paper_id is not None else None
    if paper is None or paper.project_id != project_id:
        raise ValueError("paper_document_not_found")
    return paper


def _read_file(repository: CodeRepository, path: str) -> str:
    try:
        return read_repository_file(
            repository.storage_path,
            path,
            edits_root=repository_edits_root(repository),
        )
    except FileAccessError as exc:
        raise ValueError("code_file_unavailable") from exc


def _symbol(repository: CodeRepository, symbol_id: str) -> dict[str, Any]:
    for symbol in repository.symbols_json:
        if str(symbol.get("id")) == symbol_id:
            return symbol
    raise ValueError("code_symbol_not_found")


def _paper_blocks(paper: PaperDocument) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for page in paper.pages_json:
        for block in page.get("blocks", []):
            if isinstance(block, dict) and block.get("id"):
                blocks.append(block)
    if blocks:
        return blocks
    return [dict(item) for item in paper.paragraphs_json]


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _validate_code_evidence(repository: CodeRepository, evidence: CodeEvidence) -> None:
    content = _read_file(repository, evidence.path)
    lines = content.splitlines()
    if evidence.line_end < evidence.line_start or evidence.line_end > len(lines):
        raise ValueError("code_evidence_line_invalid")
    selected = "\n".join(lines[evidence.line_start - 1 : evidence.line_end])
    if _normalize(evidence.quote) not in _normalize(selected):
        raise ValueError("code_evidence_quote_invalid")


def _validate_architecture(
    repository: CodeRepository, payload: ArchitecturePayload, depth: int
) -> None:
    if payload.requested_depth != depth:
        raise ValueError("architecture_depth_mismatch")
    node_ids = [node.id for node in payload.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("architecture_node_id_duplicate")
    known = set(node_ids)
    for node in payload.nodes:
        if node.depth > depth or node.line_end < node.line_start:
            raise ValueError("architecture_node_location_invalid")
        for evidence in node.evidence:
            _validate_code_evidence(repository, evidence)
    edge_ids: set[str] = set()
    for edge in payload.edges:
        if edge.id in edge_ids:
            raise ValueError("architecture_edge_id_duplicate")
        edge_ids.add(edge.id)
        if edge.source not in known or edge.target not in known:
            raise ValueError("architecture_edge_endpoint_invalid")


def _validate_traces(
    repository: CodeRepository,
    paper: PaperDocument,
    payload: TracePayload,
) -> None:
    blocks = {str(item.get("id")): item for item in _paper_blocks(paper)}
    symbols = {str(item.get("id")) for item in repository.symbols_json if item.get("id")}
    paths = {str(item.get("path")) for item in repository.file_tree_json if item.get("path")}
    for candidate in payload.candidates:
        block = blocks.get(candidate.paper_block_id)
        if block is None or candidate.paper_evidence.block_id != candidate.paper_block_id:
            raise ValueError("paper_evidence_ref_invalid")
        if _normalize(candidate.paper_evidence.quote) not in _normalize(str(block.get("text", ""))):
            raise ValueError("paper_evidence_quote_invalid")
        if candidate.code_symbol_id not in symbols and candidate.code_symbol_id not in paths:
            raise ValueError("code_reference_invalid")
        if (
            candidate.code_evidence.symbol_id
            and candidate.code_evidence.symbol_id != candidate.code_symbol_id
        ):
            raise ValueError("code_evidence_ref_invalid")
        _validate_code_evidence(repository, candidate.code_evidence)


def execute_tool(
    session: Session,
    project_id: int,
    repository_id: int,
    paper_id: int | None,
    depth: int,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    model = TOOL_MODELS.get(tool_name)
    if model is None:
        raise ValueError("unknown_analysis_tool")
    validated = model.model_validate(arguments)
    repository = _repository(session, project_id, repository_id)

    if isinstance(validated, RepositoryFilesArguments):
        items = [
            item
            for item in repository.file_tree_json
            if str(item.get("path", "")).startswith(validated.prefix)
            and (validated.language is None or item.get("language") == validated.language)
        ]
        page = items[validated.cursor : validated.cursor + validated.limit]
        return {
            "items": page,
            "next_cursor": validated.cursor + len(page)
            if validated.cursor + len(page) < len(items)
            else None,
            "total": len(items),
        }
    if isinstance(validated, RepositorySearchArguments):
        query = validated.query.casefold()
        matches: list[dict[str, Any]] = []
        for item in repository.file_tree_json[:500]:
            path = str(item.get("path", ""))
            if not path or item.get("editable") is False:
                continue
            try:
                lines = _read_file(repository, path).splitlines()
            except ValueError:
                continue
            for index, line in enumerate(lines, start=1):
                if query in line.casefold():
                    matches.append(
                        {"path": path, "line_start": index, "line_end": index, "quote": line[:1000]}
                    )
                    if len(matches) >= validated.limit:
                        return {"found": True, "items": matches}
        return {"found": bool(matches), "items": matches}
    if isinstance(validated, CodeSymbolsArguments):
        items = [
            item
            for item in repository.symbols_json
            if (validated.path is None or item.get("path") == validated.path)
            and (validated.kind is None or item.get("kind") == validated.kind)
        ]
        page = items[validated.cursor : validated.cursor + validated.limit]
        return {
            "items": page,
            "next_cursor": validated.cursor + len(page)
            if validated.cursor + len(page) < len(items)
            else None,
            "total": len(items),
        }
    if isinstance(validated, SymbolArguments):
        symbol = _symbol(repository, validated.symbol_id)
        path = str(symbol.get("path", ""))
        start = int(symbol.get("line_start") or symbol.get("line") or 1)
        end = int(symbol.get("line_end") or start)
        if tool_name == "get_symbol_source":
            lines = _read_file(repository, path).splitlines()
            end = min(end, len(lines))
            return {
                "ref": validated.symbol_id,
                "path": path,
                "line_start": start,
                "line_end": end,
                "content": "\n".join(
                    f"{number:>5} | {line}"
                    for number, line in enumerate(lines[start - 1 : end], start)
                ),
            }
        calls = [
            dict(item)
            for item in repository.analysis_json.get("calls", [])
            if item.get("caller_symbol_id") == validated.symbol_id
        ]
        by_name: dict[str, list[str]] = {}
        for item in repository.symbols_json:
            by_name.setdefault(str(item.get("name", "")), []).append(str(item.get("id", "")))
        for call in calls:
            targets = by_name.get(str(call.get("callee", "")).rsplit(".", 1)[-1], [])
            call["resolved_symbol_id"] = targets[0] if len(targets) == 1 else None
        return {"ref": validated.symbol_id, "items": calls[:100]}
    if isinstance(validated, PaperBlocksArguments):
        paper = _paper(session, project_id, paper_id)
        items = [
            item
            for item in _paper_blocks(paper)
            if (validated.kind is None or item.get("kind") == validated.kind)
            and (
                validated.section is None
                or validated.section.casefold()
                in " / ".join(item.get("section_path", [])).casefold()
            )
        ]
        page = items[validated.cursor : validated.cursor + validated.limit]
        return {
            "items": page,
            "next_cursor": validated.cursor + len(page)
            if validated.cursor + len(page) < len(items)
            else None,
            "total": len(items),
        }
    if isinstance(validated, PaperBlockArguments):
        paper = _paper(session, project_id, paper_id)
        item = next(
            (item for item in _paper_blocks(paper) if str(item.get("id")) == validated.block_id),
            None,
        )
        return {"found": item is not None, "ref": validated.block_id, "block": item}
    if isinstance(validated, ArtifactArguments):
        artifact = session.exec(
            select(AgentAnalysisArtifact)
            .where(
                AgentAnalysisArtifact.project_id == project_id,
                AgentAnalysisArtifact.code_repository_id == repository_id,
                AgentAnalysisArtifact.code_revision == repository.revision,
                AgentAnalysisArtifact.kind == validated.kind,
                AgentAnalysisArtifact.is_current == True,  # noqa: E712
            )
            .order_by(AgentAnalysisArtifact.created_at.desc())
        ).first()
        return {
            "found": artifact is not None,
            "payload": artifact.payload_json if artifact else None,
        }
    if isinstance(validated, PublishArchitectureArguments):
        _validate_architecture(repository, validated.payload, depth)
        return {"published": True, "payload": validated.payload.model_dump()}
    if isinstance(validated, PublishTraceArguments):
        paper = _paper(session, project_id, paper_id)
        _validate_traces(repository, paper, validated.payload)
        return {"published": True, "payload": validated.payload.model_dump()}
    raise ValueError("unsupported_analysis_tool")
