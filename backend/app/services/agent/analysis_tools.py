from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, select

from app.models.entities import AgentAnalysisArtifact, CodeRepository, PaperDocument
from app.services.analysis_jobs import repository_edits_root
from app.services.code_analysis.editor import FileAccessError, read_repository_file
from app.services.tracing.anchoring import AnchorError, resolve_anchor


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


class TolerantModel(BaseModel):
    """Publish models tolerate unknown keys and coerce enum-like fields.

    DeepSeek-class models frequently add stray keys or slightly-off enum values. Rejecting
    the whole payload for that wastes the run; instead we ignore extras and coerce unknown
    enum values to a safe default, while still hard-validating the evidence (quote/occurrence/
    hash) that hover correctness depends on.
    """

    model_config = ConfigDict(extra="ignore")


_PAPER_TARGET_TYPES = {"formula", "variable", "constraint", "algorithm", "figure", "method_text"}
_CODE_TARGET_ROLES = {
    "model_component",
    "loss",
    "tensor_transform",
    "update_rule",
    "constraint",
    "algorithm_step",
    "config",
    "invocation",
}
_RELATION_TYPES = {
    "implements",
    "computes",
    "defines",
    "constrains",
    "updates",
    "configures",
    "invokes",
    "mentions",
}


class TracePaperEvidence(TolerantModel):
    block_id: str = Field(min_length=1, max_length=255)
    quote: str = Field(min_length=1, max_length=3000)
    # Which occurrence of ``quote`` inside the block this target refers to (1-based).
    occurrence: int = Field(default=1, ge=1, le=200)
    target_type: str = Field(default="method_text", max_length=32)

    @field_validator("target_type", mode="before")
    @classmethod
    def _coerce_target_type(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in _PAPER_TARGET_TYPES else "method_text"


class TraceCodeEvidence(TolerantModel):
    path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=3000)
    symbol_id: str | None = Field(default=None, max_length=500)
    # Which occurrence of ``quote`` inside the cited line range this target refers to.
    occurrence: int = Field(default=1, ge=1, le=200)
    role: str = Field(default="model_component", max_length=64)

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in _CODE_TARGET_ROLES else "model_component"


class TraceCandidate(TolerantModel):
    paper_block_id: str = Field(min_length=1, max_length=255)
    code_symbol_id: str = Field(min_length=1, max_length=255)
    relation_type: str = Field(default="implements", max_length=32)
    # Three independent scores (see architecture doc §8.2):
    #   salience   = how important the paper target is (target-level)
    #   relevance  = how much this code fragment implements the target (edge-level)
    #   confidence = how sure the agent is the relation is correct (edge-level)
    salience: float = Field(default=0.6, ge=0, le=1)
    relevance: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=0.6, ge=0, le=1)
    salience_reason: str = Field(default="", max_length=600)
    rationale: str = Field(min_length=1, max_length=5000)
    uncertainty_level: str = Field(default="medium", max_length=16)
    uncertainty_reasons: list[str] = Field(default_factory=list, max_length=8)
    paper_evidence: TracePaperEvidence
    code_evidence: TraceCodeEvidence
    graph_node_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("relation_type", mode="before")
    @classmethod
    def _coerce_relation(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in _RELATION_TYPES else "implements"

    @field_validator("uncertainty_level", mode="before")
    @classmethod
    def _coerce_uncertainty(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"low", "medium", "high"} else "medium"


class TracePayload(TolerantModel):
    schema_version: str = Field(default="trace-agent-v2", max_length=64)
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
        "to complete trace analysis. Each candidate needs: paper_evidence (block_id, exact quote, "
        "occurrence = which match inside the block when the quote repeats, target_type), "
        "code_evidence (path, line_start, line_end, exact quote, occurrence, role), a "
        "relation_type, and three separate scores in [0,1]: salience (importance of the target), "
        "relevance (how much this code implements it), confidence (certainty the relation is "
        "correct). Quotes are re-verified against real content at the declared occurrence; a "
        "mismatch is rejected."
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
    raise ValueError(
        "code_symbol_not_found: use an exact id from list_code_symbols (page through it), "
        "or cite a file path + line range directly instead of a symbol id"
    )


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


def _offset_to_linecol(content: str, offset: int) -> tuple[int, int]:
    prefix = content[:offset]
    line = prefix.count("\n") + 1
    col = offset - (prefix.rfind("\n") + 1)
    return line, col


def _resolve_paper_anchor(block_text: str, evidence: TracePaperEvidence) -> dict[str, Any]:
    try:
        anchor = resolve_anchor(block_text, evidence.quote, evidence.occurrence)
    except AnchorError as exc:
        raise ValueError(
            f"paper_evidence_quote_invalid: quote not found in block {evidence.block_id} "
            f"at occurrence {evidence.occurrence}; copy the quote verbatim from get_paper_block"
        ) from exc
    anchor["target_type"] = evidence.target_type
    return anchor


def _resolve_code_anchor(repository: CodeRepository, evidence: TraceCodeEvidence) -> dict[str, Any]:
    content = _read_file(repository, evidence.path)
    lines = content.splitlines(keepends=True)
    total = len(lines)
    line_ok = 1 <= evidence.line_start <= evidence.line_end <= total
    slice_start = sum(len(line) for line in lines[: evidence.line_start - 1]) if line_ok else 0
    anchor: dict[str, Any] | None = None
    if line_ok:
        raw_slice = "".join(lines[evidence.line_start - 1 : evidence.line_end])
        try:
            anchor = resolve_anchor(raw_slice, evidence.quote, evidence.occurrence)
        except AnchorError:
            anchor = None
    if anchor is None:
        # The cited line range may be slightly off; verify the quote exists anywhere in the
        # file and correct the range from the real match instead of rejecting the relation.
        try:
            anchor = resolve_anchor(content, evidence.quote, evidence.occurrence)
        except AnchorError as exc:
            raise ValueError(
                f"code_evidence_quote_invalid: quote not found anywhere in {evidence.path}; "
                "copy it verbatim from get_symbol_source or search_repository_text"
            ) from exc
        slice_start = 0  # anchor char offsets are already file-relative here
    default_start = evidence.line_start if line_ok else 1
    default_end = evidence.line_end if line_ok else min(total, default_start)
    result: dict[str, Any] = {
        "occurrence": anchor["occurrence"],
        "code_quote_hash": anchor["quote_hash"],
        "role": evidence.role,
        "level": anchor.get("level", "normalized"),
        "line_start": default_start,
        "line_end": default_end,
        "char_start": None,
        "char_end": None,
        "match_line_start": default_start,
        "match_line_end": default_end,
        "column_start": None,
        "column_end": None,
    }
    if anchor.get("char_start") is not None:
        file_start = slice_start + int(anchor["char_start"])
        file_end = slice_start + int(anchor["char_end"])
        line_start, col_start = _offset_to_linecol(content, file_start)
        line_end, col_end = _offset_to_linecol(content, file_end)
        result.update(
            char_start=file_start,
            char_end=file_end,
            line_start=line_start,
            line_end=line_end,
            match_line_start=line_start,
            match_line_end=line_end,
            column_start=col_start,
            column_end=col_end,
        )
    return result


def _validate_traces(
    repository: CodeRepository,
    paper: PaperDocument,
    payload: TracePayload,
) -> list[dict[str, Any]]:
    """Validate every candidate against real evidence and return per-candidate anchors.

    Each returned entry is ``{"paper": <anchor>, "code": <anchor>}`` with resolved
    occurrence, char range, and content hash so persistence can build precise targets.
    """

    blocks = {str(item.get("id")): item for item in _paper_blocks(paper)}
    symbols = {str(item.get("id")) for item in repository.symbols_json if item.get("id")}
    paths = {str(item.get("path")) for item in repository.file_tree_json if item.get("path")}
    anchors: list[dict[str, Any]] = []
    for candidate in payload.candidates:
        block = blocks.get(candidate.paper_block_id)
        if block is None or candidate.paper_evidence.block_id != candidate.paper_block_id:
            raise ValueError("paper_evidence_ref_invalid")
        paper_anchor = _resolve_paper_anchor(str(block.get("text", "")), candidate.paper_evidence)
        if candidate.code_symbol_id not in symbols and candidate.code_symbol_id not in paths:
            raise ValueError("code_reference_invalid")
        if (
            candidate.code_evidence.symbol_id
            and candidate.code_evidence.symbol_id != candidate.code_symbol_id
        ):
            raise ValueError("code_evidence_ref_invalid")
        code_anchor = _resolve_code_anchor(repository, candidate.code_evidence)
        anchors.append({"paper": paper_anchor, "code": code_anchor})
    return anchors


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
        anchors = _validate_traces(repository, paper, validated.payload)
        payload = validated.payload.model_dump()
        for candidate, anchor in zip(payload["candidates"], anchors, strict=True):
            candidate["paper_anchor"] = anchor["paper"]
            candidate["code_anchor"] = anchor["code"]
        return {"published": True, "payload": payload}
    raise ValueError("unsupported_analysis_tool")
