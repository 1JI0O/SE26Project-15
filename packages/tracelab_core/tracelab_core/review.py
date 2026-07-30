"""Trace link persistence and review in `.tracelab/traces/links.json`."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from tracelab_core.workspace import TraceLabPaths, read_json, write_json

_CODE_REF_RE = re.compile(r"^(?P<path>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?$")


def load_links(paths: TraceLabPaths) -> list[dict[str, Any]]:
    payload = read_json(paths.links_json, {"links": []}) or {"links": []}
    return list(payload.get("links") or [])


def save_links(paths: TraceLabPaths, links: list[dict[str, Any]]) -> None:
    write_json(
        paths.links_json,
        {
            "links": links,
            "updated_at": _now_iso(),
        },
    )


def _parse_code_target(code_ref: str, code_symbol_id: str) -> tuple[str, int, int]:
    match = _CODE_REF_RE.match(code_ref.strip())
    if match:
        path = match.group("path")
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        return path, start, end

    # Fallbacks: "file.py::Symbol", bare symbol id, or plain path.
    if "::" in code_symbol_id:
        path = code_symbol_id.split("::", 1)[0]
        return path or code_symbol_id, 1, 1
    if "::" in code_ref:
        return code_ref.split("::", 1)[0] or code_symbol_id, 1, 1
    if code_ref.endswith(".py") or "/" in code_ref:
        return code_ref, 1, 1
    return code_symbol_id.split("::", 1)[0] or code_ref or "unknown.py", 1, 1


def candidates_to_links(candidates: list[Any], *, source: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for candidate in candidates:
        if hasattr(candidate, "__dataclass_fields__"):
            paper_block_id = candidate.paper_block_id
            code_symbol_id = candidate.code_symbol_id
            relation_type = candidate.relation_type
            confidence = candidate.confidence
            rationale = candidate.rationale
            evidence = candidate.evidence
        else:
            paper_block_id = candidate["paper_block_id"]
            code_symbol_id = candidate["code_symbol_id"]
            relation_type = candidate.get("relation_type", "mentions")
            confidence = candidate.get("confidence", 0.0)
            rationale = candidate.get("rationale", "")
            evidence = candidate.get("evidence", [])

        paper_evidence = next((item for item in evidence if item.get("side") == "paper"), {})
        code_evidence = next((item for item in evidence if item.get("side") == "code"), {})
        code_ref = str(code_evidence.get("ref") or code_symbol_id)
        path, line_start, line_end = _parse_code_target(code_ref, str(code_symbol_id))

        links.append(
            {
                "id": str(uuid.uuid4()),
                "status": "proposed",
                "source": source,
                "relation_type": relation_type,
                "confidence": confidence,
                "rationale": rationale,
                "paper_target": {
                    "block_id": paper_block_id,
                    "quote": paper_evidence.get("quote", ""),
                },
                "code_target": {
                    "symbol_id": code_symbol_id,
                    "path": path,
                    "line_start": line_start,
                    "line_end": line_end,
                    "quote": code_evidence.get("quote", ""),
                },
            }
        )
    return links


def update_link_status(
    paths: TraceLabPaths,
    link_id: str,
    status: str,
) -> dict[str, Any] | None:
    links = load_links(paths)
    updated: dict[str, Any] | None = None
    for link in links:
        if link.get("id") == link_id:
            link["status"] = status
            link["reviewed_at"] = _now_iso()
            updated = link
            break
    if updated is None:
        return None
    save_links(paths, links)
    return updated


def update_links_batch(
    paths: TraceLabPaths,
    status: str,
    *,
    link_ids: list[str] | None = None,
    all_proposed: bool = False,
) -> dict[str, Any]:
    links = load_links(paths)
    id_set = {item.strip() for item in (link_ids or []) if item.strip()}
    updated: list[dict[str, Any]] = []
    skipped = 0
    for link in links:
        if all_proposed:
            if link.get("status") != "proposed":
                continue
        elif link.get("id") not in id_set:
            continue
        link["status"] = status
        link["reviewed_at"] = _now_iso()
        updated.append(link)
    if not updated and id_set and not all_proposed:
        skipped = len(id_set)
    save_links(paths, links)
    return {"updated_count": len(updated), "skipped_count": skipped, "updated": updated}


def mark_stale(paths: TraceLabPaths, revision: str) -> int:
    links = load_links(paths)
    changed = 0
    for link in links:
        if link.get("status") == "proposed" and link.get("revision") not in {None, revision}:
            link["status"] = "stale"
            changed += 1
        link["revision"] = revision
    if changed or links:
        save_links(paths, links)
    return changed


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
