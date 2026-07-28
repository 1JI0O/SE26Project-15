from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import AgentAnalysisArtifact, CodeRepository, PaperDocument
from app.services.analysis_jobs import repository_edits_root
from app.services.change_analysis import (
    build_conflict_context,
    collect_repository_changes,
    get_change_impact,
    get_file_change,
    list_affected_traces,
)
from app.services.code_analysis.editor import FileAccessError, read_repository_file
from app.services.tracing.anchoring import AnchorError, locate_approximate_span, resolve_anchor


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


class ReadSourceLinesArguments(StrictModel):
    path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)


class PaperBlockArguments(StrictModel):
    block_id: str = Field(min_length=1, max_length=255)


class ArtifactArguments(StrictModel):
    kind: Literal["architecture", "trace", "conflict"]


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


class ChangedFilesArguments(PageArguments):
    pass


class ConflictContextArguments(StrictModel):
    pass


class ChangedPathArguments(StrictModel):
    path: str = Field(min_length=1, max_length=1000)


class AffectedTracesArguments(StrictModel):
    path: str | None = Field(default=None, max_length=1000)


class TolerantConflictModel(BaseModel):
    """Ignore model-added presentation fields while validating every trusted evidence field."""

    model_config = ConfigDict(extra="ignore")


class ConflictCodeEvidence(TolerantConflictModel):
    side: Literal["before", "after"]
    path: str = Field(min_length=1, max_length=1000)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=6000)

    @field_validator("side", mode="before")
    @classmethod
    def _coerce_side(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return {
            "修改前": "before",
            "变更前": "before",
            "修改后": "after",
            "变更后": "after",
        }.get(text, text)


class ConflictPaperEvidence(TolerantConflictModel):
    block_id: str = Field(min_length=1, max_length=255)
    quote: str = Field(min_length=1, max_length=3000)
    page: int | None = Field(default=None, ge=1)
    association: Literal["trace", "inferred"] = "trace"

    @field_validator("association", mode="before")
    @classmethod
    def _coerce_association(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return {
            "追溯": "trace",
            "已有追溯": "trace",
            "推测": "inferred",
            "推测关联": "inferred",
        }.get(text, text)


class ConflictTraceReference(TolerantConflictModel):
    trace_id: str = Field(min_length=1, max_length=64)


class ConflictItem(TolerantConflictModel):
    category: Literal[
        "paper_consistency",
        "behavior_regression",
        "trace_invalidation",
        "trace_coverage",
        "configuration_risk",
    ]
    severity: Literal["high", "medium", "low"]
    confidence: float = Field(ge=0, le=1)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=5000)
    change_evidence: list[ConflictCodeEvidence] = Field(min_length=1, max_length=12)
    affected_symbols: list[str] = Field(default_factory=list, max_length=100)
    callers: list[str] = Field(default_factory=list, max_length=100)
    graph_node_ids: list[str] = Field(default_factory=list, max_length=100)
    trace_refs: list[ConflictTraceReference] = Field(default_factory=list, max_length=30)
    paper_evidence: list[ConflictPaperEvidence] = Field(default_factory=list, max_length=20)
    recommendations: list[str] = Field(default_factory=list, max_length=20)
    verification_steps: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return {
            "高": "high",
            "高风险": "high",
            "中": "medium",
            "中风险": "medium",
            "低": "low",
            "低风险": "low",
        }.get(text, text)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            try:
                number = float(text.removesuffix("%"))
            except ValueError:
                return value
            return number / 100 if text.endswith("%") or 1 < number <= 100 else number
        if isinstance(value, (int, float)) and 1 < value <= 100:
            return value / 100
        return value


class ConflictPayload(TolerantConflictModel):
    schema_version: Literal["conflict-agent-v1"] = "conflict-agent-v1"
    language: Literal["zh-CN"] = "zh-CN"
    repository_revision: int = Field(ge=1)
    overall_risk: Literal["high", "medium", "low"] = "low"
    items: list[ConflictItem] = Field(default_factory=list, max_length=100)
    unresolved: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("overall_risk", mode="before")
    @classmethod
    def _coerce_overall_risk(cls, value: object) -> str:
        return ConflictItem._coerce_severity(value)


class PublishConflictArguments(TolerantConflictModel):
    payload: ConflictPayload


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


class FinishAnalysisArguments(TolerantModel):
    """Declare exploration complete. Tolerant so a bare `{}` or an extra summary both work."""

    summary: str = Field(default="", max_length=2000)


class DispatchRegion(TolerantModel):
    """One trace region for a parallel sub-agent. Hints are navigation aids, not conclusions."""

    name: str = Field(min_length=1, max_length=80)
    paper_target_hints: list[str] = Field(default_factory=list, max_length=12)
    code_hints: list[str] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=600)


class DispatchSubagentsArguments(StrictModel):
    regions: list[DispatchRegion] = Field(min_length=1, max_length=8)


TOOL_MODELS: dict[str, type[StrictModel]] = {
    "list_repository_files": RepositoryFilesArguments,
    "search_repository_text": RepositorySearchArguments,
    "list_code_symbols": CodeSymbolsArguments,
    "get_symbol_source": SymbolArguments,
    "get_symbol_calls": SymbolArguments,
    "read_source_lines": ReadSourceLinesArguments,
    "list_paper_blocks": PaperBlocksArguments,
    "get_paper_block": PaperBlockArguments,
    "get_analysis_artifact": ArtifactArguments,
    "publish_architecture_graph": PublishArchitectureArguments,
    "publish_trace_candidates": PublishTraceArguments,
    "finish_analysis": FinishAnalysisArguments,
    "dispatch_trace_subagents": DispatchSubagentsArguments,
    "get_conflict_context": ConflictContextArguments,
    "list_changed_files": ChangedFilesArguments,
    "get_change_diff": ChangedPathArguments,
    "get_change_impact": ChangedPathArguments,
    "list_affected_traces": AffectedTracesArguments,
    "publish_conflict_report": PublishConflictArguments,
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
    "read_source_lines": (
        "Read an exact line window from any repository file by path (no symbol id needed). "
        "Use this to read and quote code precisely when you only know a path and line range."
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
        "Publish evidence-backed proposed paper-code trace candidates. You MAY call this multiple "
        "times to publish in batches as you confirm them — each call is persisted and shown to "
        "the user immediately. Each candidate needs: paper_evidence (block_id, exact quote, "
        "occurrence = which match inside the block when the quote repeats, target_type), "
        "code_evidence (path, line_start, line_end, exact quote, occurrence, role), a "
        "relation_type, and three separate scores in [0,1]: salience (importance of the target), "
        "relevance (how much this code implements it), confidence (certainty the relation is "
        "correct). Quotes are re-verified against real content at the declared occurrence; a "
        "mismatch is rejected. Never call it with an empty payload."
    ),
    "finish_analysis": (
        "Call this exactly once when you have published every defensible trace candidate and "
        "checked each must-inspect target. It ends the analysis. Do NOT call it before your "
        "first successful publish unless no defensible relation exists at all."
    ),
    "dispatch_trace_subagents": (
        "Fan out the STAGE 3 region evidence work to parallel sub-agents. Call this once after "
        "SCOUT and MAP: group the core paper targets into 2-6 coherent regions and give each a "
        "name, paper_target_hints (block ids or short quotes), code_hints (paths or symbol ids), "
        "and notes on what computation must exist. Each region is investigated independently and "
        "its confirmed candidates are published directly; you receive a per-region summary to "
        "verify coverage against. Hints are navigation aids, not conclusions. At most 2 dispatch "
        "calls per analysis."
    ),
    "get_conflict_context": (
        "Read the revision-fixed conflict-context-v1 evidence package prepared from saved "
        "changes. It combines exact diffs and hunks, affected symbols/callers/graph nodes, "
        "affected traces, and trace-linked paper blocks. Inspect coverage before using granular "
        "tools; only fetch sections explicitly marked truncated or evidence that is genuinely "
        "missing."
    ),
    "list_changed_files": (
        "List saved files that differ from the immutable imported repository, with hashes, "
        "changed-line counts, and hunk locations."
    ),
    "get_change_diff": (
        "Read the exact imported-vs-current unified diff and before/after hunk quotes for one "
        "changed file."
    ),
    "get_change_impact": (
        "Read symbols overlapping one changed file's hunks, their callers, and affected graph "
        "nodes from the current static analysis."
    ),
    "list_affected_traces": (
        "List existing paper-code traces affected by changed paths or precise CodeTarget ranges. "
        "Includes stale links and whether they were accepted before the edit."
    ),
    "publish_conflict_report": (
        "Publish the final conflict-agent-v1 report exactly once. Every item must cite exact "
        "before/after code copied from get_change_diff. Paper claims need exact block quotes; "
        "For a pure insertion or deletion, cite only the non-empty side of the hunk; never send "
        "a change_evidence entry whose quote is empty. "
        "use association=inferred when no existing trace supports the paper association. Set "
        "language=zh-CN and write every user-visible title, description, recommendation, "
        "verification step, and unresolved item in Simplified Chinese. Keep paths, identifiers, "
        "symbols, and verbatim code/paper quotes in their original form."
    ),
}


def tool_definitions(kind: str, *, role: str = "parent") -> list[dict[str, Any]]:
    allowed = {
        "architecture": {
            "list_repository_files",
            "search_repository_text",
            "list_code_symbols",
            "get_symbol_source",
            "get_symbol_calls",
            "read_source_lines",
            "get_analysis_artifact",
            "publish_architecture_graph",
        },
        "trace": {
            "list_repository_files",
            "search_repository_text",
            "list_code_symbols",
            "get_symbol_source",
            "get_symbol_calls",
            "read_source_lines",
            "list_paper_blocks",
            "get_paper_block",
            "get_analysis_artifact",
            "publish_trace_candidates",
            "finish_analysis",
            "dispatch_trace_subagents",
        },
        "conflict": {
            "get_conflict_context",
            "list_changed_files",
            "get_change_diff",
            "get_change_impact",
            "list_affected_traces",
            "list_repository_files",
            "search_repository_text",
            "list_code_symbols",
            "get_symbol_source",
            "get_symbol_calls",
            "read_source_lines",
            "list_paper_blocks",
            "get_paper_block",
            "get_analysis_artifact",
            "publish_conflict_report",
        },
    }[kind]
    if role == "subagent":
        # A region sub-agent reads evidence and publishes for its region only: it must not
        # end the whole analysis, fan out further, or read the aggregate artifact.
        allowed = allowed - {"finish_analysis", "dispatch_trace_subagents", "get_analysis_artifact"}
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


def _resolve_symbol(repository: CodeRepository, symbol_id: str) -> dict[str, Any]:
    """Exact id, else a *unique* fuzzy match by qualified name or trailing component.

    Small models often cite ``ClassName`` or ``ClassName.method`` instead of the full
    ``path::qualified`` id. Resolving a unique candidate avoids wasting steps on
    ``code_symbol_not_found`` while never guessing when the match is ambiguous.
    """

    for symbol in repository.symbols_json:
        if str(symbol.get("id")) == symbol_id:
            return symbol
    tail = symbol_id.rsplit("::", 1)[-1]
    matches = [
        symbol
        for symbol in repository.symbols_json
        if str(symbol.get("qualified_name", "")) == tail
        or str(symbol.get("id", "")).endswith(f"::{tail}")
        or str(symbol.get("name", "")) == tail.rsplit(".", 1)[-1]
    ]
    if len(matches) == 1:
        return matches[0]
    return _symbol(repository, symbol_id)


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
    # Normalized / approximate match: the quote is genuinely in the file but its exact character
    # range is unknown, so the declared line numbers are still the model's unverified claim.
    # Recover the range from the quote's alphanumeric signature so ":line" in the UI and the
    # editor decoration point at the code that actually matched, not at a guessed window.
    span = locate_approximate_span(content, evidence.quote)
    if span is not None:
        match_start, _ = _offset_to_linecol(content, span[0])
        match_end, _ = _offset_to_linecol(content, max(span[0], span[1] - 1))
        result.update(match_line_start=match_start, match_line_end=match_end)
        # A declared range that does not even contain the verified match is simply wrong; keep it
        # only when it still works as surrounding context.
        if not (result["line_start"] <= match_start and match_end <= result["line_end"]):
            result.update(line_start=match_start, line_end=match_end)
    return result


def _validate_one_trace(
    repository: CodeRepository,
    blocks: dict[str, Any],
    symbols: set[str],
    paths: set[str],
    candidate: TraceCandidate,
) -> dict[str, Any]:
    """Validate one candidate against real evidence; raise ValueError if unusable."""

    block = blocks.get(candidate.paper_block_id)
    if block is None or candidate.paper_evidence.block_id != candidate.paper_block_id:
        raise ValueError("paper_evidence_ref_invalid")
    paper_anchor = _resolve_paper_anchor(str(block.get("text", "")), candidate.paper_evidence)
    # code_symbol_id may be an indexed symbol id, a repo path, or a path with a line-range
    # suffix like ``file.py:186-275`` — accept all three as long as the real file exists and
    # the code evidence quote resolves against it.
    code_ref = candidate.code_symbol_id
    if code_ref not in symbols and code_ref not in paths:
        bare = re.sub(r":\d+(?:-\d+)?$", "", code_ref)
        if bare in paths or bare in symbols:
            code_ref = bare
        elif candidate.code_evidence.path in paths:
            code_ref = candidate.code_evidence.path
        else:
            raise ValueError("code_reference_invalid")
    code_anchor = _resolve_code_anchor(repository, candidate.code_evidence)
    return {"paper": paper_anchor, "code": code_anchor, "code_ref": code_ref}


def _validate_traces(
    repository: CodeRepository,
    paper: PaperDocument,
    payload: TracePayload,
) -> tuple[list[TraceCandidate], list[dict[str, Any]], list[str]]:
    """Validate candidates against real evidence, dropping only the individually invalid ones.

    Returns ``(kept_candidates, anchors, dropped_reasons)``. One malformed candidate must not
    reject an entire batch of otherwise-sound relations, so bad candidates are skipped and
    reported rather than raising. Raising only happens when the whole batch is empty/unusable,
    so the run keeps retrying instead of silently publishing nothing.
    """

    blocks = {str(item.get("id")): item for item in _paper_blocks(paper)}
    symbols = {str(item.get("id")) for item in repository.symbols_json if item.get("id")}
    paths = {str(item.get("path")) for item in repository.file_tree_json if item.get("path")}
    kept: list[TraceCandidate] = []
    anchors: list[dict[str, Any]] = []
    dropped: list[str] = []
    for candidate in payload.candidates:
        try:
            anchor = _validate_one_trace(repository, blocks, symbols, paths, candidate)
        except ValueError as exc:
            dropped.append(
                f"{candidate.paper_block_id}->{candidate.code_symbol_id}: {exc}"[:200]
            )
            continue
        kept.append(candidate)
        anchors.append(anchor)
    if payload.candidates and not kept:
        # Every candidate failed — surface the first reason so the model can correct and retry.
        raise ValueError(
            "all_candidates_invalid: " + "; ".join(dropped[:3])
            if dropped
            else "all_candidates_invalid"
        )
    return kept, anchors, dropped


def _validate_conflict_code_evidence(
    repository: CodeRepository,
    evidence: ConflictCodeEvidence,
) -> None:
    change = get_file_change(repository, evidence.path)
    if evidence.side == "before":
        content = read_repository_file(repository.storage_path, evidence.path)
        range_keys = ("before_start", "before_end")
    else:
        content = _read_file(repository, evidence.path)
        range_keys = ("after_start", "after_end")
    lines = content.splitlines()
    if (
        evidence.line_end < evidence.line_start
        or evidence.line_start > len(lines)
        or evidence.line_end > len(lines)
    ):
        raise ValueError("conflict_code_evidence_line_invalid")
    selected = "\n".join(lines[evidence.line_start - 1 : evidence.line_end])
    if _normalize(evidence.quote) not in _normalize(selected):
        raise ValueError("conflict_code_evidence_quote_invalid")
    if not any(
        evidence.line_start <= int(hunk[range_keys[1]])
        and int(hunk[range_keys[0]]) <= evidence.line_end
        for hunk in change["hunks"]
    ):
        raise ValueError("conflict_code_evidence_not_in_change")


def _execute_publish_conflict(
    session: Session,
    project_id: int,
    repository_id: int,
    paper_id: int | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    validated = PublishConflictArguments.model_validate(arguments)
    repository = _repository(session, project_id, repository_id)
    payload = validated.payload
    if payload.repository_revision != repository.revision:
        raise ValueError("repository_revision_changed")
    chinese_fields = [
        *(value for item in payload.items for value in (item.title, item.description)),
        *(value for item in payload.items for value in item.recommendations),
        *(value for item in payload.items for value in item.verification_steps),
        *payload.unresolved,
    ]
    if any(
        value.strip() and re.search(r"[\u3400-\u9fff]", value) is None
        for value in chinese_fields
    ):
        raise ValueError("conflict_output_must_be_chinese")
    changes = collect_repository_changes(repository)
    if not changes["has_changes"]:
        raise ValueError("no_code_changes")

    paper = session.get(PaperDocument, paper_id) if paper_id is not None else None
    blocks = {
        str(item.get("id")): item
        for item in (_paper_blocks(paper) if paper is not None else [])
    }
    affected_trace_map = {
        item["trace_id"]: item
        for item in list_affected_traces(session, repository)
    }
    output_items: list[dict[str, Any]] = []
    for item in payload.items:
        for evidence in item.change_evidence:
            _validate_conflict_code_evidence(repository, evidence)
        for evidence in item.paper_evidence:
            block = blocks.get(evidence.block_id)
            if block is None:
                raise ValueError("conflict_paper_evidence_ref_invalid")
            if _normalize(evidence.quote) not in _normalize(str(block.get("text", ""))):
                raise ValueError("conflict_paper_evidence_quote_invalid")
            if evidence.association == "trace" and not any(
                affected_trace_map.get(reference.trace_id, {}).get("paper_block_id")
                == evidence.block_id
                for reference in item.trace_refs
            ):
                raise ValueError("conflict_paper_trace_association_invalid")
        for reference in item.trace_refs:
            if reference.trace_id not in affected_trace_map:
                raise ValueError("conflict_trace_reference_invalid")

        item_dump = item.model_dump()
        evidence_identity = [
            [
                evidence.path,
                evidence.side,
                evidence.line_start,
                evidence.line_end,
                hashlib.sha256(evidence.quote.encode()).hexdigest(),
            ]
            for evidence in item.change_evidence
        ]
        raw_id = repr(
            [
                project_id,
                repository_id,
                repository.revision,
                item.category,
                item.title,
                evidence_identity,
                [reference.trace_id for reference in item.trace_refs],
            ]
        )
        item_dump["id"] = f"conflict-{hashlib.sha256(raw_id.encode()).hexdigest()[:20]}"
        item_dump["affected_files"] = list(
            dict.fromkeys(evidence.path for evidence in item.change_evidence)
        )
        output_items.append(item_dump)

    counts = {
        severity: sum(item["severity"] == severity for item in output_items)
        for severity in ("high", "medium", "low")
    }
    payload_dump = payload.model_dump()
    payload_dump["items"] = output_items
    payload_dump["overall_risk"] = (
        "high" if counts["high"] else "medium" if counts["medium"] else "low"
    )
    payload_dump["summary"] = {
        **counts,
        "total": len(output_items),
        "changed_files": changes["changed_file_count"],
        "changed_lines": changes["changed_line_count"],
    }
    return {"published": True, "payload": payload_dump}


def _normalize_publish_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Wrap flattened publish arguments into the expected ``{"payload": {...}}`` shape.

    Models routinely call ``publish_trace_candidates({"candidates": [...]})`` instead of the
    schema-required ``publish_trace_candidates({"payload": {"candidates": [...]}})``. Rejecting
    that as ``payload: Field required`` wastes whole runs even when the evidence is sound, so we
    normalize the two equivalent shapes here rather than depending on the model getting the
    nesting right.
    """

    if tool_name not in {
        "publish_trace_candidates",
        "publish_architecture_graph",
        "publish_conflict_report",
    }:
        return arguments
    if not isinstance(arguments, dict):
        return arguments
    payload = arguments.get("payload")
    if isinstance(payload, dict):
        normalized = arguments
    else:
        # No usable payload wrapper: treat the top-level dict as the payload itself.
        flattened = {key: value for key, value in arguments.items() if key != "payload"}
        if not flattened:
            return arguments
        normalized = {"payload": flattened}
    if tool_name != "publish_conflict_report":
        return normalized

    # Pure insertions/deletions have one intentionally-empty hunk side. Models commonly copy
    # both sides into change_evidence, including quote="". That empty entry carries no evidence
    # and used to reject the entire otherwise-valid report at schema validation. Drop only those
    # empty entries; every remaining entry still goes through exact path/range/quote validation,
    # and an item with no non-empty evidence still fails ConflictItem.min_length.
    conflict_payload = normalized.get("payload")
    if not isinstance(conflict_payload, dict):
        return normalized
    items = conflict_payload.get("items")
    if not isinstance(items, list):
        return normalized
    normalized_items: list[Any] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            normalized_items.append(raw_item)
            continue
        item = dict(raw_item)
        evidence = item.get("change_evidence")
        if isinstance(evidence, list):
            item["change_evidence"] = [
                entry
                for entry in evidence
                if not isinstance(entry, dict)
                or bool(str(entry.get("quote") or "").strip())
            ]
        normalized_items.append(item)
    normalized_payload = dict(conflict_payload)
    normalized_payload["items"] = normalized_items
    return {**normalized, "payload": normalized_payload}


def _execute_publish_trace(
    session: Session,
    project_id: int,
    repository_id: int,
    paper_id: int | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Tolerant trace publish: drop individually-bad candidates instead of failing the batch.

    Two independent drop stages, both non-fatal unless *everything* fails:
    1. schema — a candidate missing/mistyping a field is dropped, not raised as
       ``invalid_tool_arguments`` for the whole call;
    2. evidence — a candidate whose quote/occurrence/reference cannot be verified is dropped.
    Raising only when the model sent candidates but none survive keeps the run retrying rather
    than silently publishing nothing.
    """

    repository = _repository(session, project_id, repository_id)
    payload_in = arguments.get("payload")
    if not isinstance(payload_in, dict):
        payload_in = {}
    raw_candidates = payload_in.get("candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []
    unresolved = payload_in.get("unresolved")
    unresolved = unresolved if isinstance(unresolved, list) else []
    # An empty publish (no candidates and no unresolved) is almost always a premature/malformed
    # call, not a genuine "nothing to trace". Reject it so the run retries with real candidates
    # instead of succeeding with zero links. A true empty result must justify itself via
    # ``unresolved``.
    if not raw_candidates and not unresolved:
        raise ValueError(
            "empty_publish: payload.candidates was empty. Put every defensible relation in "
            "payload.candidates, each with paper_evidence{block_id,quote} and "
            "code_evidence{path,line_start,line_end,quote}. If truly none exist, list the "
            "must-inspect targets you searched in payload.unresolved."
        )
    schema_kept: list[TraceCandidate] = []
    dropped: list[str] = []
    for raw in raw_candidates:
        try:
            schema_kept.append(TraceCandidate.model_validate(raw))
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            loc = ".".join(str(part) for part in first.get("loc", ()))
            dropped.append(f"schema:{loc}:{first.get('msg', 'invalid')}"[:160])
    if raw_candidates and not schema_kept:
        raise ValueError("all_candidates_schema_invalid: " + "; ".join(dropped[:3]))

    tp = TracePayload(candidates=schema_kept, unresolved=unresolved)
    paper = _paper(session, project_id, paper_id)
    kept, anchors, evidence_dropped = _validate_traces(repository, paper, tp)
    dropped.extend(evidence_dropped)

    candidates_out: list[dict[str, Any]] = []
    for candidate, anchor in zip(kept, anchors, strict=True):
        dump = candidate.model_dump()
        dump["code_symbol_id"] = anchor.get("code_ref", candidate.code_symbol_id)
        dump["paper_anchor"] = anchor["paper"]
        dump["code_anchor"] = anchor["code"]
        candidates_out.append(dump)
    payload = tp.model_dump()
    payload["candidates"] = candidates_out
    if dropped:
        payload["dropped"] = dropped
    return {"published": True, "payload": payload, "dropped": dropped}


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
    if tool_name == "dispatch_trace_subagents":
        # Dispatch needs the provider, thread pool, and event bus; the parent analysis loop
        # intercepts it before this function. Reaching here means a disallowed caller.
        raise ValueError("dispatch_not_available_here")
    arguments = _normalize_publish_arguments(tool_name, arguments)
    if tool_name == "publish_trace_candidates":
        return _execute_publish_trace(session, project_id, repository_id, paper_id, arguments)
    if tool_name == "publish_conflict_report":
        return _execute_publish_conflict(
            session,
            project_id,
            repository_id,
            paper_id,
            arguments,
        )
    if tool_name == "finish_analysis":
        summary = ""
        if isinstance(arguments, dict):
            summary = str(arguments.get("summary", ""))[:2000]
        return {"finished": True, "summary": summary}
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
    if isinstance(validated, ChangedFilesArguments):
        changes = collect_repository_changes(repository)
        items = [
            {
                **{
                    key: value
                    for key, value in item.items()
                    if key not in {"diff", "hunks"}
                },
                "hunks": [
                    {
                        key: value
                        for key, value in hunk.items()
                        if key not in {"before_quote", "after_quote"}
                    }
                    for hunk in item["hunks"]
                ],
            }
            for item in changes["files"]
        ]
        page = items[validated.cursor : validated.cursor + validated.limit]
        return {
            "baseline": changes["baseline"],
            "repository_revision": changes["repository_revision"],
            "items": page,
            "next_cursor": (
                validated.cursor + len(page)
                if validated.cursor + len(page) < len(items)
                else None
            ),
            "total": len(items),
            "changed_line_count": changes["changed_line_count"],
        }
    if isinstance(validated, ConflictContextArguments):
        paper = session.get(PaperDocument, paper_id) if paper_id is not None else None
        if paper is not None and paper.project_id != project_id:
            raise ValueError("paper_document_not_found")
        return build_conflict_context(
            session,
            repository,
            paper,
            settings.tracelab_llm_max_context_chars,
        )
    if isinstance(validated, ChangedPathArguments):
        if tool_name == "get_change_diff":
            return get_file_change(repository, validated.path)
        return get_change_impact(repository, validated.path)
    if isinstance(validated, AffectedTracesArguments):
        return {
            "items": list_affected_traces(session, repository, validated.path),
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
    if isinstance(validated, ReadSourceLinesArguments):
        lines = _read_file(repository, validated.path).splitlines()
        start = max(1, min(validated.line_start, len(lines) or 1))
        end = min(len(lines), max(start, validated.line_end))
        if end - start > 400:  # bound the window
            end = start + 400
        return {
            "path": validated.path,
            "line_start": start,
            "line_end": end,
            "content": "\n".join(
                f"{number:>5} | {line}"
                for number, line in enumerate(lines[start - 1 : end], start)
            ),
        }
    if isinstance(validated, SymbolArguments):
        symbol = _resolve_symbol(repository, validated.symbol_id)
        canonical_id = str(symbol.get("id", validated.symbol_id))
        path = str(symbol.get("path", ""))
        start = int(symbol.get("line_start") or symbol.get("line") or 1)
        end = int(symbol.get("line_end") or start)
        if tool_name == "get_symbol_source":
            lines = _read_file(repository, path).splitlines()
            end = min(end, len(lines))
            return {
                "ref": canonical_id,
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
            if item.get("caller_symbol_id") == canonical_id
        ]
        by_name: dict[str, list[str]] = {}
        for item in repository.symbols_json:
            by_name.setdefault(str(item.get("name", "")), []).append(str(item.get("id", "")))
        for call in calls:
            targets = by_name.get(str(call.get("callee", "")).rsplit(".", 1)[-1], [])
            call["resolved_symbol_id"] = targets[0] if len(targets) == 1 else None
        return {"ref": canonical_id, "items": calls[:100]}
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
    raise ValueError("unsupported_analysis_tool")
