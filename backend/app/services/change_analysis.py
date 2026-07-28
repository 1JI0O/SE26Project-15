from __future__ import annotations

import difflib
import hashlib
from typing import Any

from sqlmodel import Session, select

from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    CodeRepository,
    CodeTarget,
    TraceLink,
)
from app.services.analysis_jobs import analysis_is_current, repository_edits_root
from app.services.code_analysis.editor import FileAccessError, read_repository_file


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


def get_file_change(repository: CodeRepository, path: str) -> dict[str, Any]:
    changes = collect_repository_changes(repository)
    item = next((item for item in changes["files"] if item["path"] == path), None)
    if item is None:
        raise ValueError("changed_file_not_found")
    return item


def get_change_impact(repository: CodeRepository, path: str) -> dict[str, Any]:
    change = get_file_change(repository, path)
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
) -> list[dict[str, Any]]:
    changes = collect_repository_changes(repository)
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
