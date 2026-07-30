from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
from typing import Any

from sqlmodel import Session, select

from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    CodeRepository,
    CodeTarget,
    PaperDocument,
    TraceLink,
)
from app.services.analysis_jobs import analysis_is_current, repository_edits_root
from app.services.code_analysis.editor import FileAccessError, read_repository_file
from app.services.paper_evidence import build_evidence_spans, search_paper_blocks


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _ranges_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a <= end_b and start_b <= end_a


def _change_hunks(before: str, after: str) -> list[dict[str, Any]]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    hunks: list[dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        # Empty sides (pure insertion/deletion) still need a usable one-based anchor for
        # overlap checks and UI display. The quote remains empty on the absent side.
        before_line_start = max(1, before_start + 1)
        before_line_end = max(before_line_start, before_end)
        after_line_start = max(1, after_start + 1)
        after_line_end = max(after_line_start, after_end)
        hunks.append(
            {
                "kind": tag,
                "before_start": before_line_start,
                "before_end": before_line_end,
                "after_start": after_line_start,
                "after_end": after_line_end,
                "before_quote": "\n".join(before_lines[before_start:before_end])[:12_000],
                "after_quote": "\n".join(after_lines[after_start:after_end])[:12_000],
                "removed_lines": before_end - before_start,
                "added_lines": after_end - after_start,
            }
        )
    return hunks


def collect_repository_changes(repository: CodeRepository) -> dict[str, Any]:
    """Compare saved edit overlays against the immutable imported archive."""

    root = repository_edits_root(repository)
    files: list[dict[str, Any]] = []
    if root.is_dir():
        for edited in sorted(root.rglob("*")):
            if not edited.is_file() or edited.is_symlink():
                continue
            try:
                path = edited.relative_to(root).as_posix()
                before = read_repository_file(repository.storage_path, path)
                after = read_repository_file(
                    repository.storage_path,
                    path,
                    edits_root=root,
                )
            except (FileAccessError, ValueError):
                continue
            if before == after:
                continue
            hunks = _change_hunks(before, after)
            files.append(
                {
                    "path": path,
                    "before_sha256": _sha256(before),
                    "after_sha256": _sha256(after),
                    "changed_lines": sum(
                        int(item["removed_lines"]) + int(item["added_lines"])
                        for item in hunks
                    ),
                    "hunks": hunks,
                    "diff": "".join(
                        difflib.unified_diff(
                            before.splitlines(keepends=True),
                            after.splitlines(keepends=True),
                            fromfile=f"a/{path}",
                            tofile=f"b/{path}",
                        )
                    )[:80_000],
                }
            )
    return {
        "baseline": "imported",
        "repository_id": repository.id or 0,
        "repository_revision": repository.revision,
        "has_changes": bool(files),
        "changed_file_count": len(files),
        "changed_line_count": sum(int(item["changed_lines"]) for item in files),
        "files": files,
    }


def get_file_change(
    repository: CodeRepository,
    path: str,
    changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    changes = changes or collect_repository_changes(repository)
    item = next((item for item in changes["files"] if item["path"] == path), None)
    if item is None:
        raise ValueError("changed_file_not_found")
    return item


def get_change_impact(
    repository: CodeRepository,
    path: str,
    changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    change = get_file_change(repository, path, changes)
    after_ranges = [
        (int(hunk["after_start"]), int(hunk["after_end"])) for hunk in change["hunks"]
    ]
    affected_symbols: list[dict[str, Any]] = []
    for symbol in repository.symbols_json:
        if str(symbol.get("path", "")) != path:
            continue
        start = int(symbol.get("line_start") or symbol.get("line") or 1)
        end = int(symbol.get("line_end") or start)
        if any(
            _ranges_overlap(start, end, hunk_start, hunk_end)
            for hunk_start, hunk_end in after_ranges
        ):
            affected_symbols.append(dict(symbol))

    symbol_ids = {str(item.get("id", "")) for item in affected_symbols}
    symbol_names = {
        str(item.get("name") or str(item.get("id", "")).rsplit(".", 1)[-1])
        for item in affected_symbols
    }
    callers: list[dict[str, Any]] = []
    for call in repository.analysis_json.get("calls", []):
        resolved = str(call.get("resolved_symbol_id") or "")
        callee = str(call.get("callee") or "").rsplit(".", 1)[-1]
        if resolved in symbol_ids or callee in symbol_names:
            callers.append(dict(call))

    graph = repository.tensor_graph_json or repository.analysis_json.get("tensor_graph", {})
    graph_nodes = []
    for node in graph.get("nodes", []):
        if str(node.get("source_path", "")) != path:
            continue
        start = int(node.get("line_start") or 1)
        end = int(node.get("line_end") or start)
        if any(
            _ranges_overlap(start, end, hunk_start, hunk_end)
            for hunk_start, hunk_end in after_ranges
        ):
            graph_nodes.append(dict(node))

    return {
        "path": path,
        "changed_lines": change["changed_lines"],
        "affected_symbols": affected_symbols[:100],
        "callers": callers[:100],
        "graph_nodes": graph_nodes[:100],
    }


def list_affected_traces(
    session: Session,
    repository: CodeRepository,
    path: str | None = None,
    changes: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    changes = changes or collect_repository_changes(repository)
    changed_by_path = {
        str(item["path"]): item
        for item in changes["files"]
        if path is None or item["path"] == path
    }
    if not changed_by_path:
        return []

    links = list(
        session.exec(
            select(TraceLink).where(
                TraceLink.project_id == repository.project_id,
                TraceLink.code_repository_id == (repository.id or 0),
            )
        ).all()
    )
    target_ids = {link.code_target_id for link in links if link.code_target_id}
    targets = (
        {
            target.target_id: target
            for target in session.exec(
                select(CodeTarget).where(CodeTarget.target_id.in_(target_ids))
            ).all()
        }
        if target_ids
        else {}
    )
    affected: list[dict[str, Any]] = []
    for link in links:
        matched_path: str | None = None
        matched_by = ""
        target = targets.get(link.code_target_id or "")
        if target is not None and target.path in changed_by_path:
            change = changed_by_path[target.path]
            if any(
                _ranges_overlap(
                    target.line_start,
                    target.line_end,
                    int(hunk["before_start"]),
                    int(hunk["before_end"]),
                )
                or _ranges_overlap(
                    target.line_start,
                    target.line_end,
                    int(hunk["after_start"]),
                    int(hunk["after_end"]),
                )
                for hunk in change["hunks"]
            ):
                matched_path = target.path
                matched_by = "code_target"
        if matched_path is None:
            for evidence in link.evidence_json:
                evidence_path = str(evidence.get("path") or "")
                if evidence.get("side") == "code" and evidence_path in changed_by_path:
                    matched_path = evidence_path
                    matched_by = "evidence_path"
                    break
        if matched_path is None:
            matched_path = next(
                (candidate for candidate in changed_by_path if candidate in link.code_ref),
                None,
            )
            if matched_path:
                matched_by = "code_ref"
        if matched_path is None:
            continue
        affected.append(
            {
                "trace_id": link.trace_id,
                "paper_block_id": link.paper_ref,
                "code_ref": link.code_ref,
                "status": link.status,
                "previously_accepted": link.status == "stale" and link.decided_at is not None,
                "confidence": link.confidence,
                "rationale": link.rationale,
                "evidence": link.evidence_json,
                "matched_path": matched_path,
                "matched_by": matched_by,
            }
        )
    return affected


def _paper_blocks(paper: PaperDocument | None) -> list[dict[str, Any]]:
    if paper is None:
        return []
    blocks = [
        block
        for page in paper.pages_json
        for block in page.get("blocks", [])
        if isinstance(block, dict) and block.get("id")
    ]
    return blocks or [
        dict(block)
        for block in paper.paragraphs_json
        if isinstance(block, dict) and block.get("id")
    ]


def _serialized_chars(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))


def _minimal_file_context(
    change: dict[str, Any],
    impact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "path": change["path"],
        "before_sha256": change["before_sha256"],
        "after_sha256": change["after_sha256"],
        "changed_lines": change["changed_lines"],
        "hunks": [
            {
                key: value
                for key, value in hunk.items()
                if key not in {"before_quote", "after_quote"}
            }
            for hunk in change["hunks"]
        ],
        "impact_summary": {
            "affected_symbol_count": len(impact["affected_symbols"]),
            "caller_count": len(impact["callers"]),
            "graph_node_count": len(impact["graph_nodes"]),
        },
    }


def _minimal_trace_context(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        key: trace.get(key)
        for key in (
            "trace_id",
            "paper_block_id",
            "code_ref",
            "status",
            "previously_accepted",
            "confidence",
            "matched_path",
            "matched_by",
        )
    }


def _minimal_paper_context(block: dict[str, Any]) -> dict[str, Any]:
    return {
        key: block.get(key)
        for key in ("id", "page_number", "section_path", "kind", "trace_ids")
    }


_PAPER_HINT_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_PAPER_HINT_STOPWORDS = {
    "after",
    "before",
    "class",
    "const",
    "false",
    "from",
    "import",
    "none",
    "return",
    "self",
    "true",
}


def _paper_search_hints(
    changes: list[dict[str, Any]],
    impacts: dict[str, dict[str, Any]],
) -> list[str]:
    """Derive deterministic navigation terms without making a semantic paper claim."""

    ranked: list[str] = []

    def add(value: object) -> None:
        for raw in _PAPER_HINT_TOKEN.findall(str(value or "")):
            parts = [
                part
                for chunk in raw.split("_")
                for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", chunk)
            ] or [raw]
            for part in parts:
                normalized = part.casefold()[:64]
                if (
                    normalized not in _PAPER_HINT_STOPWORDS
                    and len(normalized) >= 3
                    and normalized not in ranked
                    and sum(len(item) + 1 for item in ranked) + len(normalized) <= 600
                ):
                    ranked.append(normalized)

    for change in changes:
        add(change.get("path"))
        impact = impacts.get(str(change.get("path") or ""), {})
        for symbol in impact.get("affected_symbols", [])[:12]:
            add(symbol.get("name"))
            add(symbol.get("qualified_name"))
            add(symbol.get("id"))
        for hunk in change.get("hunks", [])[:8]:
            add(str(hunk.get("before_quote") or "")[:1500])
            add(str(hunk.get("after_quote") or "")[:1500])
    return ranked[:32]


def build_conflict_context(
    session: Session,
    repository: CodeRepository,
    paper: PaperDocument | None,
    max_chars: int,
) -> dict[str, Any]:
    """Build one revision-fixed, size-bounded evidence package for conflict analysis."""

    changes = collect_repository_changes(repository)
    impacts = {
        str(change["path"]): get_change_impact(
            repository,
            str(change["path"]),
            changes,
        )
        for change in changes["files"]
    }
    traces = list_affected_traces(session, repository, changes=changes)
    traces_by_path: dict[str, list[dict[str, Any]]] = {}
    for trace in traces:
        traces_by_path.setdefault(str(trace.get("matched_path") or ""), []).append(trace)

    def file_priority(change: dict[str, Any]) -> tuple[int, int, int, int, str]:
        path = str(change["path"])
        related = traces_by_path.get(path, [])
        impact = impacts[path]
        return (
            -int(any(bool(item.get("previously_accepted")) for item in related)),
            -int(bool(related)),
            -int(bool(impact["affected_symbols"] or impact["graph_nodes"])),
            -int(change["changed_lines"]),
            path,
        )

    ordered_changes = sorted(changes["files"], key=file_priority)
    ordered_paths = [str(change["path"]) for change in ordered_changes]
    path_rank = {path: index for index, path in enumerate(ordered_paths)}
    ordered_traces = sorted(
        traces,
        key=lambda item: (
            -int(bool(item.get("previously_accepted"))),
            path_rank.get(str(item.get("matched_path") or ""), len(path_rank)),
            -float(item.get("confidence") or 0),
            str(item.get("trace_id") or ""),
        ),
    )

    block_map = {str(block["id"]): block for block in _paper_blocks(paper)}
    trace_ids_by_block: dict[str, list[str]] = {}
    for trace in ordered_traces:
        block_id = str(trace.get("paper_block_id") or "")
        if block_id in block_map:
            trace_ids_by_block.setdefault(block_id, []).append(str(trace["trace_id"]))
    paper_blocks = [
        {
            **copy.deepcopy(block_map[block_id]),
            "trace_ids": list(dict.fromkeys(trace_ids)),
            "evidence_spans": build_evidence_spans(block_map[block_id]),
        }
        for block_id, trace_ids in trace_ids_by_block.items()
    ]
    paper_search_hints = _paper_search_hints(ordered_changes, impacts)
    inferred_paper_candidates = (
        search_paper_blocks(
            list(block_map.values()),
            " ".join(paper_search_hints),
            limit=3,
        )
        if not ordered_traces and block_map and paper_search_hints
        else []
    )
    full_files = [
        {
            **copy.deepcopy(change),
            "impact": copy.deepcopy(impacts[str(change["path"])]),
        }
        for change in ordered_changes
    ]
    summary = {
        "changed_file_count": changes["changed_file_count"],
        "changed_line_count": changes["changed_line_count"],
        "affected_trace_count": len(ordered_traces),
        "paper_block_count": len(paper_blocks),
        "paper_candidate_count": len(inferred_paper_candidates),
    }
    full_context = {
        "schema_version": "conflict-context-v1",
        "repository_revision": repository.revision,
        "baseline": changes["baseline"],
        "summary": summary,
        "files": full_files,
        "affected_traces": copy.deepcopy(ordered_traces),
        "paper_blocks": paper_blocks,
        "paper_search_hints": paper_search_hints,
        "inferred_paper_candidates": inferred_paper_candidates,
        "coverage": {
            "complete": True,
            "included_file_count": len(full_files),
            "complete_file_count": len(full_files),
            "total_file_count": len(full_files),
            "included_trace_count": len(ordered_traces),
            "complete_trace_count": len(ordered_traces),
            "total_trace_count": len(ordered_traces),
            "included_paper_block_count": len(paper_blocks),
            "complete_paper_block_count": len(paper_blocks),
            "total_paper_block_count": len(paper_blocks),
            "included_paper_candidate_count": len(inferred_paper_candidates),
            "total_paper_candidate_count": len(inferred_paper_candidates),
            "truncated_sections": [],
            "truncated_paths": [],
            "omitted_paths": [],
            "omitted_trace_ids": [],
            "omitted_paper_block_ids": [],
            "omitted_paper_candidate_ids": [],
        },
    }
    max_chars = max(1000, max_chars)
    if _serialized_chars(full_context) <= max_chars:
        return full_context

    bounded: dict[str, Any] = {
        "schema_version": "conflict-context-v1",
        "repository_revision": repository.revision,
        "baseline": changes["baseline"],
        "summary": summary,
        "files": [],
        "affected_traces": [],
        "paper_blocks": [],
        "paper_search_hints": paper_search_hints,
        "inferred_paper_candidates": [],
        "coverage": {
            "complete": False,
            "included_file_count": 0,
            "complete_file_count": 0,
            "total_file_count": len(full_files),
            "included_trace_count": 0,
            "complete_trace_count": 0,
            "total_trace_count": len(ordered_traces),
            "included_paper_block_count": 0,
            "complete_paper_block_count": 0,
            "total_paper_block_count": len(paper_blocks),
            "included_paper_candidate_count": 0,
            "total_paper_candidate_count": len(inferred_paper_candidates),
            "truncated_sections": [],
            "truncated_paths": [],
            "omitted_paths": [],
            "omitted_trace_ids": [],
            "omitted_paper_block_ids": [],
            "omitted_paper_candidate_ids": [],
        },
    }

    def append_if_fits(section: str, value: dict[str, Any]) -> bool:
        items = bounded[section]
        items.append(value)
        if _serialized_chars(bounded) <= max_chars:
            return True
        items.pop()
        return False

    complete_paths: set[str] = set()
    truncated_paths: list[str] = []
    omitted_paths: list[str] = []
    for change, full in zip(ordered_changes, full_files, strict=True):
        path = str(change["path"])
        if append_if_fits("files", full):
            complete_paths.add(path)
        elif append_if_fits("files", _minimal_file_context(change, impacts[path])):
            truncated_paths.append(path)
        else:
            omitted_paths.append(path)

    complete_trace_ids: set[str] = set()
    omitted_trace_ids: list[str] = []
    for trace in ordered_traces:
        trace_id = str(trace["trace_id"])
        if append_if_fits("affected_traces", copy.deepcopy(trace)):
            complete_trace_ids.add(trace_id)
        elif append_if_fits("affected_traces", _minimal_trace_context(trace)):
            pass
        else:
            omitted_trace_ids.append(trace_id)

    complete_block_ids: set[str] = set()
    omitted_block_ids: list[str] = []
    for block in paper_blocks:
        block_id = str(block["id"])
        if append_if_fits("paper_blocks", copy.deepcopy(block)):
            complete_block_ids.add(block_id)
        elif append_if_fits("paper_blocks", _minimal_paper_context(block)):
            pass
        else:
            omitted_block_ids.append(block_id)

    omitted_candidate_ids: list[str] = []
    for candidate in inferred_paper_candidates:
        block_id = str(candidate.get("block_id") or "")
        if not append_if_fits("inferred_paper_candidates", copy.deepcopy(candidate)):
            omitted_candidate_ids.append(block_id)

    coverage = bounded["coverage"]
    coverage.update(
        {
            "included_file_count": len(bounded["files"]),
            "complete_file_count": len(complete_paths),
            "included_trace_count": len(bounded["affected_traces"]),
            "complete_trace_count": len(complete_trace_ids),
            "included_paper_block_count": len(bounded["paper_blocks"]),
            "complete_paper_block_count": len(complete_block_ids),
            "included_paper_candidate_count": len(bounded["inferred_paper_candidates"]),
            "truncated_sections": [
                section
                for section, truncated in (
                    ("files.diff", len(complete_paths) < len(full_files)),
                    ("files.hunks", len(complete_paths) < len(full_files)),
                    ("files.impact", len(complete_paths) < len(full_files)),
                    (
                        "affected_traces",
                        len(complete_trace_ids) < len(ordered_traces),
                    ),
                    ("paper_blocks", len(complete_block_ids) < len(paper_blocks)),
                    (
                        "inferred_paper_candidates",
                        len(bounded["inferred_paper_candidates"])
                        < len(inferred_paper_candidates),
                    ),
                )
                if truncated
            ],
            "truncated_paths": truncated_paths[:100],
            "omitted_paths": omitted_paths[:100],
            "omitted_trace_ids": omitted_trace_ids[:100],
            "omitted_paper_block_ids": omitted_block_ids[:100],
            "omitted_paper_candidate_ids": omitted_candidate_ids[:100],
        }
    )
    while _serialized_chars(bounded) > max_chars:
        if bounded["inferred_paper_candidates"]:
            removed = bounded["inferred_paper_candidates"].pop()
            block_id = str(removed.get("block_id") or "")
            if block_id and block_id not in coverage["omitted_paper_candidate_ids"]:
                coverage["omitted_paper_candidate_ids"].append(block_id)
        elif bounded["paper_blocks"]:
            removed = bounded["paper_blocks"].pop()
            block_id = str(removed.get("id") or "")
            complete_block_ids.discard(block_id)
            if block_id and block_id not in coverage["omitted_paper_block_ids"]:
                coverage["omitted_paper_block_ids"].append(block_id)
        elif bounded["affected_traces"]:
            removed = bounded["affected_traces"].pop()
            trace_id = str(removed.get("trace_id") or "")
            complete_trace_ids.discard(trace_id)
            if trace_id and trace_id not in coverage["omitted_trace_ids"]:
                coverage["omitted_trace_ids"].append(trace_id)
        elif bounded["files"]:
            removed = bounded["files"].pop()
            path = str(removed.get("path") or "")
            complete_paths.discard(path)
            if path in truncated_paths:
                truncated_paths.remove(path)
            if path and path not in coverage["omitted_paths"]:
                coverage["omitted_paths"].append(path)
        else:
            shrinkable = next(
                (
                    coverage[key]
                    for key in (
                        "omitted_paths",
                        "omitted_trace_ids",
                        "omitted_paper_block_ids",
                        "omitted_paper_candidate_ids",
                        "truncated_paths",
                    )
                    if coverage[key]
                ),
                None,
            )
            if shrinkable is None:
                break
            shrinkable.pop()
    coverage.update(
        {
            "included_file_count": len(bounded["files"]),
            "complete_file_count": len(complete_paths),
            "included_trace_count": len(bounded["affected_traces"]),
            "complete_trace_count": len(complete_trace_ids),
            "included_paper_block_count": len(bounded["paper_blocks"]),
            "complete_paper_block_count": len(complete_block_ids),
            "included_paper_candidate_count": len(bounded["inferred_paper_candidates"]),
            "truncated_sections": [
                section
                for section, truncated in (
                    ("files.diff", len(complete_paths) < len(full_files)),
                    ("files.hunks", len(complete_paths) < len(full_files)),
                    ("files.impact", len(complete_paths) < len(full_files)),
                    (
                        "affected_traces",
                        len(complete_trace_ids) < len(ordered_traces),
                    ),
                    ("paper_blocks", len(complete_block_ids) < len(paper_blocks)),
                    (
                        "inferred_paper_candidates",
                        len(bounded["inferred_paper_candidates"])
                        < len(inferred_paper_candidates),
                    ),
                )
                if truncated
            ],
            "truncated_paths": truncated_paths[:100],
        }
    )
    return bounded


def latest_conflict_artifact(
    session: Session,
    project_id: int,
) -> AgentAnalysisArtifact | None:
    return session.exec(
        select(AgentAnalysisArtifact)
        .where(
            AgentAnalysisArtifact.project_id == project_id,
            AgentAnalysisArtifact.kind == "conflict",
        )
        .order_by(AgentAnalysisArtifact.created_at.desc())
    ).first()


def build_change_summary(session: Session, project_id: int) -> dict[str, Any]:
    repository = session.exec(
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    ).first()
    if repository is None:
        return {
            "repository_revision": 0,
            "analysis_status": "missing",
            "analysis_current": False,
            "has_changes": False,
            "changed_file_count": 0,
            "changed_line_count": 0,
            "latest_conflict_job_id": None,
            "latest_conflict_artifact_id": None,
            "analyzed_revision": None,
            "report_stale": False,
        }
    changes = collect_repository_changes(repository)
    artifact = latest_conflict_artifact(session, project_id)
    job = session.get(AgentAnalysisJob, artifact.job_id) if artifact is not None else None
    stale = bool(
        artifact is not None
        and (
            not artifact.is_current
            or artifact.code_repository_id != (repository.id or 0)
            or artifact.code_revision != repository.revision
        )
    )
    return {
        "repository_revision": repository.revision,
        "analysis_status": repository.analysis_status,
        "analysis_current": analysis_is_current(repository),
        "has_changes": changes["has_changes"],
        "changed_file_count": changes["changed_file_count"],
        "changed_line_count": changes["changed_line_count"],
        "latest_conflict_job_id": job.job_id if job is not None else None,
        "latest_conflict_artifact_id": artifact.artifact_id if artifact is not None else None,
        "analyzed_revision": artifact.code_revision if artifact is not None else None,
        "report_stale": stale,
    }


def conflict_items_from_artifact(artifact: AgentAnalysisArtifact | None) -> list[dict[str, Any]]:
    if artifact is None or not artifact.is_current:
        return []
    severity_labels = {"high": "高风险", "medium": "中风险", "low": "低风险"}
    tag_types = {"high": "danger", "medium": "warning", "low": "info"}
    items: list[dict[str, Any]] = []
    for raw in artifact.payload_json.get("items", []):
        severity = str(raw.get("severity", "low"))
        evidence = raw.get("change_evidence", [])
        files = list(
            dict.fromkeys(
                str(item.get("path"))
                for item in evidence
                if isinstance(item, dict) and item.get("path")
            )
        )
        items.append(
            {
                "id": str(raw.get("id", "")),
                "category": str(raw.get("category", "behavior_regression")),
                "severity": severity,
                "confidence": float(raw.get("confidence", 0)),
                "level": severity_labels.get(severity, "低风险"),
                "type": tag_types.get(severity, "info"),
                "title": str(raw.get("title", "未命名风险")),
                "description": str(raw.get("description", "")),
                "affected_files": files,
                "status": "ready",
            }
        )
    return items
