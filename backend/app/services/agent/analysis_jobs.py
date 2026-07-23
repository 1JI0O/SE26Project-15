from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlmodel import Session, select

from app.db.session import engine
from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    AgentConversation,
    AgentRun,
    CodeRepository,
    CodeTarget,
    PaperDocument,
    PaperTarget,
    TraceLink,
    utc_now,
)
from app.schemas.agent import AgentAnalysisJobCreate, AgentAnalysisJobRead
from app.services.agent.analysis_tools import execute_tool, tool_definitions
from app.services.agent.provider import AgentProviderFailure
from app.services.agent.run_events import RunEventEmitter
from app.services.agent.service import _provider_from_settings
from app.services.tracing.service import trace_fingerprint

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tracelab-agent-analysis")
_lock = Lock()
_submitted: set[str] = set()


def _latest_code(session: Session, project_id: int) -> CodeRepository | None:
    return session.exec(
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    ).first()


def _latest_paper(session: Session, project_id: int) -> PaperDocument | None:
    return session.exec(
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    ).first()


def job_to_read(job: AgentAnalysisJob) -> AgentAnalysisJobRead:
    return AgentAnalysisJobRead(
        job_id=job.job_id,
        project_id=job.project_id,
        kind=job.kind,
        status=job.status,
        paper_document_id=job.paper_document_id,
        code_repository_id=job.code_repository_id,
        code_revision=job.code_revision,
        root_symbol=job.root_symbol,
        requested_depth=job.requested_depth,
        run_id=job.agent_run_id,
        artifact_id=job.artifact_id,
        progress=job.progress_json,
        error_code=job.error_code,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


def _base_fingerprint(
    project_id: int,
    kind: str,
    paper_id: int | None,
    repository_id: int,
    revision: int,
    root_symbol: str | None,
    depth: int,
) -> str:
    raw = json.dumps(
        [project_id, kind, paper_id, repository_id, revision, root_symbol, depth],
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def create_analysis_job(
    session: Session,
    project_id: int,
    payload: AgentAnalysisJobCreate,
) -> AgentAnalysisJob:
    repository = (
        session.get(CodeRepository, payload.code_repository_id)
        if payload.code_repository_id is not None
        else _latest_code(session, project_id)
    )
    if repository is None or repository.project_id != project_id:
        raise ValueError("code_repository_not_found")
    paper: PaperDocument | None = None
    if payload.kind == "trace":
        paper = (
            session.get(PaperDocument, payload.paper_document_id)
            if payload.paper_document_id is not None
            else _latest_paper(session, project_id)
        )
        if paper is None or paper.project_id != project_id:
            raise ValueError("paper_document_not_found")
    base = _base_fingerprint(
        project_id,
        payload.kind,
        paper.id if paper else None,
        repository.id or 0,
        repository.revision,
        payload.root_symbol,
        payload.depth,
    )
    existing = session.exec(
        select(AgentAnalysisJob)
        .where(AgentAnalysisJob.fingerprint == base)
        .order_by(AgentAnalysisJob.created_at.desc())
    ).first()
    if not payload.force:
        if existing is not None and existing.status in {
            "queued",
            "running",
            "validating",
            "succeeded",
        }:
            if existing.status in {"queued", "running", "validating"}:
                _submit(existing.job_id)
            return existing
    fingerprint = (
        base
        if not payload.force and existing is None
        else hashlib.sha256(f"{base}:{uuid4()}".encode()).hexdigest()
    )
    job = AgentAnalysisJob(
        project_id=project_id,
        kind=payload.kind,
        paper_document_id=paper.id if paper else None,
        code_repository_id=repository.id or 0,
        code_revision=repository.revision,
        root_symbol=payload.root_symbol,
        requested_depth=payload.depth,
        fingerprint=fingerprint,
        progress_json={"message": "等待 Agent 分析"},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    _submit(job.job_id)
    return job


def _submit(job_id: str) -> None:
    with _lock:
        if job_id in _submitted:
            return
        _submitted.add(job_id)
    _executor.submit(_execute_job, job_id)


def _system_prompt(job: AgentAnalysisJob, soft_target: int = 40) -> tuple[str, str]:
    common = (
        "You are TraceLab's autonomous evidence analysis agent. You are the only semantic "
        "decision-maker. Local indexes are navigation aids, not conclusions. Inspect actual "
        "paper/code evidence through tools. Never invent a path, symbol, line, quote, node, or "
        "relation. If something cannot be resolved, record it as unresolved instead of guessing."
    )
    if job.kind == "architecture":
        request = (
            f"Analyze repository revision {job.code_revision}. Select or verify the model entry "
            f"{job.root_symbol or 'autonomously'}, and trace calls to depth {job.requested_depth}. "
            "Depth 0 is the entry, depth 1 its direct meaningful calls, and depth 2 expands "
            "project calls to actual torch/nn/external operations. Read source and calls before "
            "claims. "
            "Call publish_architecture_graph exactly once with the complete graph."
        )
    else:
        request = (
            f"Trace paper document {job.paper_document_id} against repository revision "
            f"{job.code_revision}. Work in four stages inside this single run, publishing "
            f"candidates in batches as you confirm them. Aim to finish within about "
            f"{soft_target} tool steps.\n\n"
            "STAGE 1 — SCOUT (paper focus). Read the abstract and section structure first "
            "(list_paper_blocks, get_paper_block). Identify 3-8 core contributions / method "
            "components and the sections that implement them. Mark method-chapter formulas, "
            "algorithms/pseudocode, and figures as must-inspect. Deliberately EXCLUDE background, "
            "related work, and experiment/result tables from tracing.\n\n"
            "STAGE 2 — MAP (code responsibilities). Skim the repository (list_repository_files, "
            "list_code_symbols, get_symbol_source) to locate where the model, losses, tensor "
            "transforms, main train/inference loops, constraints, and update rules live. Treat "
            "this as navigation only, not a conclusion.\n\n"
            "STAGE 3 — REGION EVIDENCE. For each core paper target, turn its meaning into a code "
            "search intent (what computation must happen), then read the actual source. Do a "
            "counter-check: is a same-named symbol merely config, a wrapper, or a test? Only keep "
            "a relation when the real computation happens. A paper target implemented across "
            "several places yields several candidates (one-to-many).\n\n"
            "STAGE 4 — MERGE & SELF-CHECK. Keep only targets that matter: a core contribution, a "
            "must-inspect formula/algorithm, a defining variable/constraint, or something with a "
            "direct important implementation. Merge adjacent synonymous targets; do not stack "
            "overlapping highlights. For every candidate give THREE separate scores: salience "
            "(target importance), relevance (how much the code implements it), confidence "
            "(certainty). Set paper_evidence.occurrence and code_evidence.occurrence correctly "
            "when a quote repeats.\n\n"
            "Tooling rules: to read code, either call get_symbol_source with an exact id from "
            "list_code_symbols, or call read_source_lines(path, line_start, line_end) for any "
            "file window — do NOT guess symbol ids. code_symbol_id may be a file path plus a line "
            "range. Copy every paper and code quote VERBATIM from get_paper_block / "
            "get_symbol_source / read_source_lines (exact characters) so it can be located; set "
            "occurrence when the quote repeats.\n"
            "Rules: never let keyword overlap be the verdict; read real code before publishing; if "
            "a must-inspect target has no defensible implementation, list it in unresolved with "
            "code regions you searched. Read the current architecture artifact when useful. Prefer "
            "few high-value relations over dense low-value ones.\n"
            "Finishing: call publish_trace_candidates as many times as needed (each batch is "
            "saved and shown immediately); NEVER publish an empty payload. When every defensible "
            "candidate is published and every must-inspect target is linked or listed in "
            "unresolved, call finish_analysis exactly once to end. If nothing at all is "
            "defensible, call finish_analysis directly."
        )
    return common, request


def _trace_step(run: AgentRun, item: dict[str, Any], session: Session) -> None:
    trace = list(run.trace_json)
    trace.append(item)
    run.trace_json = trace
    run.step_count = sum(entry.get("type") == "model_step" for entry in trace)
    run.updated_at = utc_now()
    session.add(run)
    session.commit()


def _activity(tool_name: str, arguments: dict[str, Any]) -> str:
    """Human-readable description of the current agent action for the progress UI."""

    args = arguments or {}
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
    match tool_name:
        case "list_paper_blocks":
            return "浏览论文结构"
        case "get_paper_block":
            return f"阅读论文片段 {args.get('block_id', '')}".strip()
        case "list_repository_files":
            return "浏览代码文件"
        case "list_code_symbols":
            return "枚举代码符号"
        case "get_symbol_source":
            return f"阅读代码 {args.get('symbol_id', '')}".strip()
        case "get_symbol_calls":
            return f"分析调用关系 {args.get('symbol_id', '')}".strip()
        case "search_repository_text":
            return f"检索代码 “{args.get('query', '')}”"
        case "read_source_lines":
            return f"阅读代码 {args.get('path', '')}:{args.get('line_start', '')}"
        case "get_analysis_artifact":
            return "读取已有分析结果"
        case "publish_trace_candidates":
            count = len(payload.get("candidates", []) or [])
            return f"发布 {count} 条追溯候选并校验证据"
        case "publish_architecture_graph":
            return "发布架构图"
        case "finish_analysis":
            return "整理并结束追溯"
    return "分析中"


def _safe_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool_name.startswith("publish_"):
        return {"published": result.get("published", False)}
    safe = dict(result)
    if isinstance(safe.get("content"), str):
        safe["content"] = safe["content"][:40_000]
    if isinstance(safe.get("items"), list):
        safe["items"] = safe["items"][:100]
    return safe


def _upsert_paper_target(
    session: Session,
    job: AgentAnalysisJob,
    artifact: AgentAnalysisArtifact,
    candidate: dict[str, Any],
    section_path: list[str],
) -> PaperTarget:
    evidence = candidate["paper_evidence"]
    anchor = candidate["paper_anchor"]
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                job.project_id,
                job.paper_document_id,
                candidate["paper_block_id"],
                anchor["quote_hash"],
                anchor["occurrence"],
            ]
        ).encode()
    ).hexdigest()
    target = session.exec(
        select(PaperTarget).where(PaperTarget.fingerprint == fingerprint)
    ).first()
    values = {
        "artifact_id": artifact.artifact_id,
        "paper_document_id": job.paper_document_id,
        "target_type": anchor.get("target_type", evidence.get("target_type", "method_text")),
        "block_id": candidate["paper_block_id"],
        "section_path_json": section_path,
        "quote": evidence["quote"],
        "occurrence": anchor["occurrence"],
        "char_start": anchor.get("char_start"),
        "char_end": anchor.get("char_end"),
        "quote_hash": anchor["quote_hash"],
        "salience": candidate.get("salience", 0.0),
        "salience_reason": candidate.get("salience_reason", ""),
        "anchor_status": anchor.get("level", "normalized"),
    }
    if target is None:
        target = PaperTarget(project_id=job.project_id, fingerprint=fingerprint, **values)
    else:
        for key, value in values.items():
            setattr(target, key, value)
        target.version += 1
    session.add(target)
    session.flush()
    return target


def _upsert_code_target(
    session: Session,
    job: AgentAnalysisJob,
    artifact: AgentAnalysisArtifact,
    candidate: dict[str, Any],
) -> CodeTarget:
    evidence = candidate["code_evidence"]
    anchor = candidate["code_anchor"]
    symbol_id = candidate["code_symbol_id"] if "::" in candidate["code_symbol_id"] else None
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                job.project_id,
                job.code_repository_id,
                job.code_revision,
                evidence["path"],
                anchor["code_quote_hash"],
                anchor["occurrence"],
            ]
        ).encode()
    ).hexdigest()
    target = session.exec(
        select(CodeTarget).where(CodeTarget.fingerprint == fingerprint)
    ).first()
    values = {
        "artifact_id": artifact.artifact_id,
        "code_repository_id": job.code_repository_id,
        "code_revision": job.code_revision,
        "path": evidence["path"],
        "symbol_id": symbol_id,
        "line_start": anchor.get("match_line_start", evidence["line_start"]),
        "line_end": anchor.get("match_line_end", evidence["line_end"]),
        "column_start": anchor.get("column_start"),
        "column_end": anchor.get("column_end"),
        "quote": evidence["quote"],
        "occurrence": anchor["occurrence"],
        "code_quote_hash": anchor["code_quote_hash"],
        "role": anchor.get("role", evidence.get("role", "model_component")),
        "salience": candidate.get("salience", 0.0),
        "anchor_status": anchor.get("level", "normalized"),
    }
    if target is None:
        target = CodeTarget(project_id=job.project_id, fingerprint=fingerprint, **values)
    else:
        for key, value in values.items():
            setattr(target, key, value)
        target.version += 1
    session.add(target)
    session.flush()
    return target


def _persist_trace_links(
    session: Session,
    job: AgentAnalysisJob,
    artifact: AgentAnalysisArtifact,
    payload: dict[str, Any],
) -> None:
    if job.paper_document_id is None:
        raise ValueError("paper_document_not_found")
    paper = session.get(PaperDocument, job.paper_document_id)
    section_paths: dict[str, list[str]] = {}
    if paper is not None:
        for page in paper.pages_json:
            for block in page.get("blocks", []):
                if isinstance(block, dict) and block.get("id"):
                    section_paths[str(block["id"])] = list(block.get("section_path", []))
    for candidate in payload.get("candidates", []):
        if "paper_anchor" not in candidate or "code_anchor" not in candidate:
            # Only anchored candidates (validated by publish_trace_candidates) are persisted.
            continue
        paper_target = _upsert_paper_target(
            session, job, artifact, candidate, section_paths.get(candidate["paper_block_id"], [])
        )
        code_target = _upsert_code_target(session, job, artifact, candidate)
        fingerprint = trace_fingerprint(
            job.paper_document_id,
            job.code_repository_id,
            job.code_revision,
            candidate["paper_block_id"],
            candidate["code_symbol_id"],
            candidate["relation_type"],
        )
        link = session.exec(select(TraceLink).where(TraceLink.fingerprint == fingerprint)).first()
        if link is not None and link.status in {"accepted", "rejected"}:
            continue
        paper_evidence = candidate["paper_evidence"]
        code_evidence = candidate["code_evidence"]
        paper_anchor = candidate["paper_anchor"]
        code_anchor = candidate["code_anchor"]
        values = {
            "project_id": job.project_id,
            "paper_document_id": job.paper_document_id,
            "paper_ref": candidate["paper_block_id"],
            "code_repository_id": job.code_repository_id,
            "code_revision": job.code_revision,
            "code_ref": candidate["code_symbol_id"],
            "relation_type": candidate["relation_type"],
            "confidence": candidate["confidence"],
            "relevance": candidate.get("relevance", 0.0),
            "static_confidence": 0.0,
            "llm_confidence": candidate["confidence"],
            "source": "agent",
            "artifact_id": artifact.artifact_id,
            "paper_target_id": paper_target.target_id,
            "code_target_id": code_target.target_id,
            "evidence_json": [
                {
                    "side": "paper",
                    "ref": candidate["paper_block_id"],
                    "quote": paper_evidence["quote"],
                    "target_id": paper_target.target_id,
                    "target_type": paper_target.target_type,
                    "occurrence": paper_anchor["occurrence"],
                    "char_start": paper_anchor.get("char_start"),
                    "char_end": paper_anchor.get("char_end"),
                    "quote_hash": paper_anchor["quote_hash"],
                    "salience": paper_target.salience,
                },
                {
                    "side": "code",
                    "ref": candidate["code_symbol_id"],
                    "quote": code_evidence["quote"],
                    "path": code_evidence["path"],
                    # Declared symbol/citation range (context) ...
                    "line_start": code_evidence["line_start"],
                    "line_end": code_evidence["line_end"],
                    # ... plus the precise matched range for decoration.
                    "match_line_start": code_anchor.get("match_line_start"),
                    "match_line_end": code_anchor.get("match_line_end"),
                    "target_id": code_target.target_id,
                    "role": code_target.role,
                    "occurrence": code_anchor["occurrence"],
                    "char_start": code_anchor.get("char_start"),
                    "char_end": code_anchor.get("char_end"),
                    "column_start": code_anchor.get("column_start"),
                    "column_end": code_anchor.get("column_end"),
                    "code_quote_hash": code_anchor["code_quote_hash"],
                },
            ],
            "rationale": candidate["rationale"],
            "uncertainty_json": {
                "level": candidate["uncertainty_level"],
                "reasons": candidate.get("uncertainty_reasons", []),
            },
            "score_basis_json": {
                "salience": candidate.get("salience", 0.0),
                "relevance": candidate.get("relevance", 0.0),
                "confidence": candidate["confidence"],
                "salience_reason": candidate.get("salience_reason", ""),
            },
            "provenance_json": {
                "job_id": job.job_id,
                "run_id": artifact.agent_run_id,
                "artifact_id": artifact.artifact_id,
                "prompt_version": "trace-agent-v2",
                "graph_node_ids": candidate.get("graph_node_ids", []),
            },
            "model_info_json": {
                **artifact.model_info_json,
                "prompt_version": "trace-agent-v2",
                "run_id": artifact.agent_run_id,
                "artifact_id": artifact.artifact_id,
            },
            "fingerprint": fingerprint,
            "status": "proposed",
            "stale_reason": None,
            "updated_at": utc_now(),
        }
        if link is None:
            link = TraceLink(**values)
        else:
            for key, value in values.items():
                setattr(link, key, value)
            link.version += 1
        session.add(link)


def _persist_artifact(
    session: Session,
    job: AgentAnalysisJob,
    run: AgentRun,
    payload: dict[str, Any],
) -> AgentAnalysisArtifact:
    repository = session.get(CodeRepository, job.code_repository_id)
    if repository is None or repository.revision != job.code_revision:
        raise ValueError("repository_revision_changed")
    current = session.exec(
        select(AgentAnalysisArtifact).where(
            AgentAnalysisArtifact.project_id == job.project_id,
            AgentAnalysisArtifact.kind == job.kind,
            AgentAnalysisArtifact.code_repository_id == job.code_repository_id,
            AgentAnalysisArtifact.is_current == True,  # noqa: E712
        )
    ).all()
    for item in current:
        if (
            job.kind == "architecture"
            and item.payload_json.get("root_symbol") != payload.get("root_symbol")
        ):
            continue
        item.is_current = False
        session.add(item)
    artifact = AgentAnalysisArtifact(
        job_id=job.job_id,
        project_id=job.project_id,
        kind=job.kind,
        schema_version=str(payload.get("schema_version", "")),
        payload_json=payload,
        paper_document_id=job.paper_document_id,
        code_repository_id=job.code_repository_id,
        code_revision=job.code_revision,
        agent_run_id=run.run_id,
        model_info_json={
            "provider": run.provider_name,
            "name": run.model_name,
            "prompt_version": f"{job.kind}-agent-v1",
        },
        capability_snapshot_json=run.capability_snapshot_json,
        fingerprint=hashlib.sha256(f"{job.fingerprint}:{run.run_id}".encode()).hexdigest(),
    )
    session.add(artifact)
    session.flush()
    if job.kind == "trace":
        _persist_trace_links(session, job, artifact, payload)
    job.artifact_id = artifact.artifact_id
    return artifact


def _append_trace_links(
    session: Session,
    job: AgentAnalysisJob,
    artifact: AgentAnalysisArtifact,
    payload: dict[str, Any],
) -> None:
    """Append a later publish batch to the run's existing artifact (no new artifact row).

    Links are upserted by content fingerprint (idempotent), and the artifact payload
    accumulates candidates/unresolved so it reflects the whole run.
    """

    _persist_trace_links(session, job, artifact, payload)
    merged = dict(artifact.payload_json)
    merged["candidates"] = [*merged.get("candidates", []), *payload.get("candidates", [])]
    merged["unresolved"] = [*merged.get("unresolved", []), *payload.get("unresolved", [])]
    artifact.payload_json = merged
    session.add(artifact)


def _trace_soft_target(session: Session, job: AgentAnalysisJob) -> int:
    """Heuristic soft step target derived from the paper (not a hard cap).

    Scales with the number of formula/algorithm objects (each needs read+verify) plus a
    small allowance for document size, clamped to a sane band. Only nudges the model to wrap
    up; the hard cap is separate.
    """

    paper = session.get(PaperDocument, job.paper_document_id) if job.paper_document_id else None
    if paper is None:
        return 40
    blocks = [b for page in (paper.pages_json or []) for b in page.get("blocks", [])]
    n_formula = sum(
        1
        for b in blocks
        if isinstance(b, dict)
        and b.get("kind") in {"equation", "equation_interline", "algorithm"}
    )
    soft = 18 + 2 * n_formula + len(blocks) // 30
    return max(28, min(soft, 64))


def _finalize_trace_run(
    session: Session,
    job: AgentAnalysisJob,
    run: AgentRun,
    emitter: RunEventEmitter,
    artifact: AgentAnalysisArtifact | None,
    published_count: int,
) -> None:
    """Mark a (possibly multi-publish) trace run complete and emit terminal events."""

    now = utc_now()
    job.status = "succeeded"
    job.error_code = None
    if artifact is not None:
        job.artifact_id = artifact.artifact_id
    job.progress_json = {
        "message": "Agent 分析完成" if published_count else "Agent 未发现可靠追溯关系"
    }
    job.updated_at = now
    job.completed_at = now
    run.status = "completed"
    run.updated_at = now
    run.completed_at = now
    session.add(job)
    session.add(run)
    if artifact is not None:
        session.add(artifact)
    session.commit()
    emitter.emit(
        "analysis.completed",
        {
            "job_id": job.job_id,
            "artifact_id": artifact.artifact_id if artifact else None,
            "kind": job.kind,
        },
    )
    emitter.emit("run.completed", {"status": "completed"})


def _fail(session: Session, job: AgentAnalysisJob, run: AgentRun | None, code: str) -> None:
    now = utc_now()
    job.status = "failed"
    job.error_code = code[:128]
    job.progress_json = {"message": "Agent 分析失败", "code": code[:128]}
    job.updated_at = now
    job.completed_at = now
    session.add(job)
    if run is not None:
        run.status = "failed"
        run.degraded_reason = code[:128]
        run.updated_at = now
        run.completed_at = now
        session.add(run)
    session.commit()


def _execute_job(job_id: str) -> None:
    try:
        with Session(engine) as session:
            job = session.get(AgentAnalysisJob, job_id)
            if job is None or job.status == "succeeded":
                return
            repository = session.get(CodeRepository, job.code_repository_id)
            if repository is None or repository.revision != job.code_revision:
                _fail(session, job, None, "repository_revision_changed")
                return
            conversation = AgentConversation(
                project_id=job.project_id,
                kind="analysis",
                title=f"{job.kind} analysis {job.job_id[-8:]}",
            )
            session.add(conversation)
            session.flush()
            provider, reason = _provider_from_settings(session, for_analysis=True)
            run = AgentRun(
                conversation_id=conversation.conversation_id,
                project_id=job.project_id,
                status="running",
                provider_name=provider.provider_name if provider else "",
                model_name=provider.model_name if provider else "",
                capability_snapshot_json=[
                    {"capability_id": f"analysis:{job.kind}", "version": "1"},
                    *[
                        {"capability_id": f"tool:{item['function']['name']}", "version": "1"}
                        for item in tool_definitions(job.kind)
                    ],
                ],
            )
            session.add(run)
            session.flush()
            job.agent_run_id = run.run_id
            job.status = "running"
            job.progress_json = {"message": "Agent 正在检查证据"}
            job.updated_at = utc_now()
            session.add(job)
            session.commit()
            if provider is None:
                _fail(session, job, run, reason or "agent_not_configured")
                return
            emitter = RunEventEmitter(session, run)
            emitter.emit("analysis.started", {"job_id": job.job_id, "kind": job.kind})
            soft_target = _trace_soft_target(session, job) if job.kind == "trace" else 40
            system_prompt, request = _system_prompt(job, soft_target)
            context = {
                "system_prompt": system_prompt,
                "history": [],
                "active_context": {
                    "analysis_job_id": job.job_id,
                    "kind": job.kind,
                    "repository_id": job.code_repository_id,
                    "repository_revision": job.code_revision,
                    "paper_document_id": job.paper_document_id,
                    "root_symbol": job.root_symbol,
                    "requested_depth": job.requested_depth,
                },
                "environment": {
                    "repository_file_count": len(repository.file_tree_json),
                    "indexed_symbol_count": len(repository.symbols_json),
                },
                "memories": [],
                "skills": [{"name": f"{job.kind}-analysis", "instructions": system_prompt}],
                "tool_definitions": tool_definitions(job.kind),
            }
            tool_results: list[dict[str, Any]] = []
            # Transient provider hiccups (malformed/truncated JSON on a big publish payload,
            # empty responses, rate limits) should not kill an otherwise-successful run. Retry
            # them a bounded number of times before giving up.
            _RETRYABLE = {
                "llm_invalid_json",
                "llm_empty_response",
                "llm_rate_limited",
                "llm_timeout",
                "llm_transport_error",
                "llm_upstream_error",
            }
            provider_failures = 0
            # Hard safety cap on tool steps only. Normal termination is the model calling
            # finish_analysis (trace) or publishing once (architecture); soft_target just nudges.
            budget = 48 if job.kind == "architecture" else 100
            # Cache identical read results so the model does not burn steps/tokens re-reading the
            # same block or code window, and nudge it toward publishing once it has the evidence.
            seen_calls: dict[str, dict[str, Any]] = {}
            _READ_TOOLS = {
                "list_repository_files",
                "search_repository_text",
                "list_code_symbols",
                "get_symbol_source",
                "get_symbol_calls",
                "read_source_lines",
                "list_paper_blocks",
                "get_paper_block",
                "get_analysis_artifact",
            }
            converge_nudged = False
            run_artifact: AgentAnalysisArtifact | None = None
            published_count = 0
            publish_name = (
                "publish_architecture_graph"
                if job.kind == "architecture"
                else "publish_trace_candidates"
            )
            for step_number in range(1, budget + 1):
                emitter.emit(
                    "analysis.progress",
                    {"message": "Agent 正在规划并核对证据", "step": step_number},
                )
                try:
                    step = provider.next_step(request, context, tool_results)
                except AgentProviderFailure as exc:
                    if exc.reason in _RETRYABLE and provider_failures < 6:
                        provider_failures += 1
                        emitter.emit(
                            "analysis.tool.failed",
                            {
                                "tool_name": "provider",
                                "code": exc.reason,
                                "step": step_number,
                                "budget": budget,
                            },
                        )
                        # Nudge the model to re-emit strictly valid, smaller JSON, and keep going.
                        tool_results.append(
                            {
                                "tool": "runtime",
                                "ok": False,
                                "error": exc.reason,
                                "instruction": (
                                    "Your previous response was not valid JSON or was empty. "
                                    "Re-issue exactly one tool call with strict JSON. If "
                                    "publishing many candidates at once fails, publish fewer "
                                    "at a time."
                                ),
                            }
                        )
                        continue
                    emitter.emit("analysis.failed", {"code": exc.reason})
                    _fail(session, job, run, exc.reason)
                    return
                _trace_step(
                    run,
                    {
                        "type": "model_step",
                        "action": step.action,
                        "tool_name": step.tool_name,
                        "arguments": step.arguments,
                    },
                    session,
                )
                if step.action == "final":
                    feedback = {
                        "tool": "runtime",
                        "ok": False,
                        "error": "analysis_output_incomplete",
                        "instruction": (
                            f"You must call {publish_name}; a natural-language final answer "
                            "cannot complete this task."
                        ),
                    }
                    tool_results.append(feedback)
                    continue
                tool_name = step.tool_name or ""
                activity = _activity(tool_name, step.arguments)
                call_key = (
                    tool_name
                    + "|"
                    + json.dumps(step.arguments, sort_keys=True, ensure_ascii=False)[:2000]
                )
                if tool_name in _READ_TOOLS and call_key in seen_calls:
                    # Duplicate read: skip the environment hit and steer toward publishing.
                    feedback = {
                        "tool": tool_name,
                        "ok": True,
                        "reused": True,
                        "result": seen_calls[call_key],
                        "instruction": (
                            "You already retrieved this exact content — do not read it again. "
                            "Read anything still missing, then when ready call "
                            f"{publish_name} ONCE with all candidates filled in. Never call it "
                            "with an empty payload."
                        ),
                    }
                    tool_results.append(feedback)
                    _trace_step(
                        run,
                        {"type": "tool_result", "tool": tool_name, "ok": True, "reused": True},
                        session,
                    )
                    emitter.emit(
                        "analysis.tool.completed",
                        {
                            "tool_name": tool_name,
                            "activity": activity,
                            "step": step_number,
                            "budget": budget,
                            "reused": True,
                        },
                    )
                    continue
                if not converge_nudged and step_number >= soft_target:
                    converge_nudged = True
                    finish_hint = (
                        ", then call finish_analysis to end" if job.kind == "trace" else ""
                    )
                    tool_results.append(
                        {
                            "tool": "runtime",
                            "ok": False,
                            "error": "soft_target_reached",
                            "instruction": (
                                f"You have reached the soft step target (~{soft_target}). "
                                f"Publish any remaining defensible candidates now (never empty)"
                                f"{finish_hint}; put anything unconfirmed in unresolved instead "
                                "of reading more."
                            ),
                        }
                    )
                emitter.emit(
                    "analysis.tool.started",
                    {
                        "tool_name": tool_name,
                        "activity": activity,
                        "message": activity,
                        "step": step_number,
                        "budget": budget,
                    },
                )
                try:
                    result = execute_tool(
                        session,
                        job.project_id,
                        job.code_repository_id,
                        job.paper_document_id,
                        job.requested_depth,
                        tool_name,
                        step.arguments,
                    )
                except ValidationError as exc:
                    error = "invalid_tool_arguments"
                    details = "; ".join(
                        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                        for item in exc.errors()[:8]
                    )
                    feedback = {
                        "tool": tool_name,
                        "ok": False,
                        "error": error,
                        "details": details[:600],
                        "instruction": (
                            "Fix only the fields named in details and retry. Do not add fields "
                            "outside the schema; required fields per candidate are paper_block_id, "
                            "code_symbol_id, rationale, paper_evidence{block_id,quote}, "
                            "code_evidence{path,line_start,line_end,quote}."
                        ),
                    }
                    tool_results.append(feedback)
                    _trace_step(run, {"type": "tool_result", **feedback}, session)
                    emitter.emit(
                        "analysis.tool.failed",
                        {
                            "tool_name": tool_name,
                            "code": error,
                            "step": step_number,
                            "budget": budget,
                        },
                    )
                    continue
                except ValueError as exc:
                    error = str(exc)[:240] or "analysis_evidence_invalid"
                    feedback = {
                        "tool": tool_name,
                        "ok": False,
                        "error": error,
                        "instruction": (
                            "Correct the evidence or arguments and retry without guessing."
                        ),
                    }
                    tool_results.append(feedback)
                    _trace_step(run, {"type": "tool_result", **feedback}, session)
                    emitter.emit(
                        "analysis.tool.failed",
                        {
                            "tool_name": tool_name,
                            "code": error,
                            "step": step_number,
                            "budget": budget,
                        },
                    )
                    continue
                safe = _safe_result(tool_name, result)
                if tool_name in _READ_TOOLS:
                    seen_calls[call_key] = safe
                feedback = {"tool": tool_name, "ok": True, "result": safe}
                tool_results.append(feedback)
                _trace_step(run, {"type": "tool_result", **feedback}, session)
                emitter.emit(
                    "analysis.tool.completed",
                    {
                        "tool_name": tool_name,
                        "activity": activity,
                        "step": step_number,
                        "budget": budget,
                        "published": bool(result.get("published")),
                    },
                )
                if tool_name == "finish_analysis" and result.get("finished"):
                    # Explicit model-declared completion (trace).
                    _finalize_trace_run(
                        session, job, run, emitter, run_artifact, published_count
                    )
                    return
                if tool_name == publish_name and result.get("published"):
                    if job.kind == "architecture":
                        # Architecture publishes exactly once and terminates.
                        job.status = "validating"
                        job.progress_json = {"message": "正在校验并保存 Agent 结果"}
                        job.updated_at = utc_now()
                        session.add(job)
                        session.commit()
                        emitter.emit("analysis.validating", {"job_id": job.job_id})
                        try:
                            artifact = _persist_artifact(session, job, run, result["payload"])
                        except ValueError as exc:
                            emitter.emit("analysis.failed", {"code": str(exc)})
                            _fail(session, job, run, str(exc))
                            return
                        now = utc_now()
                        job.status = "succeeded"
                        job.error_code = None
                        job.progress_json = {"message": "Agent 分析完成"}
                        job.updated_at = now
                        job.completed_at = now
                        run.status = "completed"
                        run.updated_at = now
                        run.completed_at = now
                        session.add(job)
                        session.add(run)
                        session.add(artifact)
                        session.commit()
                        emitter.emit(
                            "analysis.completed",
                            {
                                "job_id": job.job_id,
                                "artifact_id": artifact.artifact_id,
                                "kind": job.kind,
                            },
                        )
                        emitter.emit("run.completed", {"status": "completed"})
                        return
                    # Trace: incremental, NON-terminal publish — persist and render now.
                    try:
                        if run_artifact is None:
                            emitter.emit("analysis.validating", {"job_id": job.job_id})
                            run_artifact = _persist_artifact(session, job, run, result["payload"])
                        else:
                            _append_trace_links(session, job, run_artifact, result["payload"])
                        session.add(job)
                        session.add(run_artifact)
                        session.commit()
                    except ValueError as exc:
                        feedback = {
                            "tool": tool_name,
                            "ok": False,
                            "error": str(exc)[:200],
                            "instruction": (
                                "Fix the flagged evidence and re-publish only the corrected "
                                "candidates."
                            ),
                        }
                        tool_results.append(feedback)
                        _trace_step(run, {"type": "tool_result", **feedback}, session)
                        emitter.emit(
                            "analysis.tool.failed",
                            {
                                "tool_name": tool_name,
                                "code": str(exc)[:120],
                                "step": step_number,
                                "budget": budget,
                            },
                        )
                        continue
                    new_links = len(result["payload"].get("candidates", []))
                    published_count += new_links
                    emitter.emit(
                        "analysis.published",
                        {
                            "job_id": job.job_id,
                            "artifact_id": run_artifact.artifact_id,
                            "new_links": new_links,
                            "total_links": published_count,
                            "code_revision": job.code_revision,
                            "step": step_number,
                        },
                    )
                    # Past the soft target with results in hand: push to wrap up so runs don't
                    # drift toward the hard cap re-publishing overlapping candidates.
                    if step_number >= soft_target:
                        tool_results.append(
                            {
                                "tool": "runtime",
                                "ok": False,
                                "error": "wrap_up",
                                "instruction": (
                                    f"You have published {published_count} relations and passed "
                                    "the soft target. If the core contributions and must-inspect "
                                    "targets are covered, call finish_analysis NOW to end. Only "
                                    "publish again for a genuinely new, defensible target."
                                ),
                            }
                        )
                    continue
            # Budget exhausted. If the run already produced results, finalize as succeeded;
            # otherwise nothing defensible was ever published.
            if run_artifact is not None or published_count > 0:
                _finalize_trace_run(session, job, run, emitter, run_artifact, published_count)
                return
            emitter.emit("analysis.failed", {"code": "agent_output_incomplete"})
            _fail(session, job, run, "agent_output_incomplete")
    except Exception as exc:
        with Session(engine) as session:
            job = session.get(AgentAnalysisJob, job_id)
            if job is not None:
                run = session.get(AgentRun, job.agent_run_id) if job.agent_run_id else None
                _fail(session, job, run, f"analysis_internal_error:{exc.__class__.__name__}")
    finally:
        with _lock:
            _submitted.discard(job_id)


def recover_analysis_jobs() -> None:
    with Session(engine) as session:
        jobs = list(
            session.exec(
                select(AgentAnalysisJob).where(
                    AgentAnalysisJob.status.in_(["queued", "running", "validating"])
                )
            ).all()
        )
        for job in jobs:
            if job.agent_run_id:
                run = session.get(AgentRun, job.agent_run_id)
                if run is not None and run.status in {"queued", "running"}:
                    run.status = "failed"
                    run.degraded_reason = "analysis_restarted"
                    run.updated_at = utc_now()
                    run.completed_at = run.updated_at
                    session.add(run)
            job.status = "queued"
            job.progress_json = {"message": "等待恢复 Agent 分析"}
            job.updated_at = utc_now()
            session.add(job)
        session.commit()
        # Capture ids before the session closes; committed instances expire and would
        # raise DetachedInstanceError if their attributes were read outside the session.
        job_ids = [job.job_id for job in jobs]
    for job_id in job_ids:
        _submit(job_id)
