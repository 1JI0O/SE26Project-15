from __future__ import annotations

import hashlib
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.config import settings
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
    Project,
    TraceLink,
    as_utc,
    utc_now,
)
from app.schemas.agent import AgentAnalysisJobCreate, AgentAnalysisJobRead
from app.services.agent.analysis_tools import (
    ConflictEvidenceError,
    DispatchSubagentsArguments,
    execute_tool,
    is_deep_thinking_enabled,
    tool_definitions,
)
from app.services.agent.provider import AgentProviderFailure
from app.services.agent.run_events import RunEventEmitter
from app.services.agent.service import _provider_from_settings
from app.services.agent.subagents import (
    MAX_DISPATCH_CALLS,
    MAX_TOTAL_REGIONS,
    RETRYABLE_PROVIDER_FAILURES,
    RegionJobContext,
    SharedRunEventBus,
    TracePublishSink,
    backoff_seconds,
    run_trace_subagents,
)
from app.services.analysis_jobs import analysis_is_current
from app.services.change_analysis import collect_repository_changes
from app.services.tracing.service import trace_fingerprint

logger = logging.getLogger("tracelab.agent.analysis")

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
    if payload.kind in {"trace", "conflict"}:
        paper = (
            session.get(PaperDocument, payload.paper_document_id)
            if payload.paper_document_id is not None
            else _latest_paper(session, project_id)
        )
        if payload.kind == "trace" and (paper is None or paper.project_id != project_id):
            raise ValueError("paper_document_not_found")
        if paper is not None and paper.project_id != project_id:
            raise ValueError("paper_document_not_found")
    if payload.kind == "conflict":
        if not collect_repository_changes(repository)["has_changes"]:
            raise ValueError("no_code_changes")
        if not analysis_is_current(repository):
            raise ValueError("repository_analysis_pending")
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


def cancel_analysis_job(session: Session, project_id: int, job_id: str) -> AgentAnalysisJob | None:
    """Request early interruption of an analysis job, keeping already-published links.

    A running worker sees ``status=cancelling`` at its next step boundary and finalizes the
    run as ``succeeded`` with whatever it has published so far. A job that never started is
    terminated directly here (no worker will run it — the start guard skips ``cancelling``).
    Terminal jobs are returned unchanged (idempotent).
    """

    job = session.get(AgentAnalysisJob, job_id)
    if job is None or job.project_id != project_id:
        return None
    if job.status in {"succeeded", "failed", "stale"}:
        return job
    now = utc_now()
    if job.status == "queued" and job.agent_run_id is None:
        # Never started; nothing was published. Finish cleanly instead of leaving a
        # ``cancelling`` job that no worker will ever pick up.
        job.status = "succeeded"
        job.error_code = None
        job.progress_json = {
            "message": ("追溯已中止（未发现可靠关系）" if job.kind == "trace" else "分析已中止"),
            "code": "analysis_cancelled",
        }
        job.completed_at = now
    else:
        job.status = "cancelling"
        job.progress_json = {
            "message": (
                "正在中止追溯（保留已发现的关系）" if job.kind == "trace" else "正在中止分析"
            ),
            "code": "analysis_cancelling",
        }
    job.updated_at = now
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _trace_precedents(session: Session, job: AgentAnalysisJob) -> str:
    """Few-shot block of this project's already-reviewed trace cases, or "" when none.

    Recalled by similarity to the paper's own title/abstract, so the examples are topically
    close to what this run will trace. Both verdicts are included: an accepted case shows the
    evidence standard that held up, a rejected one shows a lexical near-miss that did not.
    They are precedents for calibration, never evidence — the prompt says so explicitly,
    because a model handed prior verdicts will otherwise copy them.
    """

    if job.paper_document_id is None:
        return ""
    try:
        from app.services.rag import trace_examples

        paper = session.get(PaperDocument, job.paper_document_id)
        if paper is None:
            return ""
        query = " ".join(part for part in (paper.title, paper.abstract[:600]) if part).strip()
        if not query:
            return ""
        examples = trace_examples(session, job.project_id, query, limit=4)
    except Exception:  # noqa: BLE001 - prompt enrichment must never fail a job
        logger.exception("trace precedent recall failed for job %s", job.job_id)
        return ""
    if not examples:
        return ""
    lines: list[str] = []
    for index, example in enumerate(examples, start=1):
        accepted = example["status"] == "accepted"
        verdict = "ACCEPTED by reviewer" if accepted else "REJECTED by reviewer"
        lines.append(
            f"{index}. [{verdict}] relation={example['relation_type']}\n"
            f"   paper: {example['paper_quote'][:240]}\n"
            f"   code: {example['code_ref']} — {example['code_quote'][:240]}\n"
            f"   reviewer-visible rationale: {example['rationale'][:240]}"
        )
    return (
        "REVIEWED PRECEDENTS FROM THIS PROJECT. These paper-code relations were already judged "
        "by a human reviewer. Use them ONLY to calibrate what counts as a defensible relation "
        "and what evidence depth was expected. They are NOT evidence for this run: never cite "
        "them as a quote, never reuse a verdict without re-reading the current code, and do not "
        "assume a similar-looking pair deserves the same outcome.\n" + "\n".join(lines) + "\n\n"
    )


_SCORING_DIRECT = (
    "SCORING. For every candidate give THREE separate scores: salience (target importance), "
    "relevance (how much the code implements it), confidence (certainty).\n\n"
)

_SCORING_DEEP = (
    "SCORING. For every candidate give salience (target importance), relevance (how much the "
    "code implements it), and the six confidence dimensions below — the server computes "
    "confidence from them, so score each one deliberately.\n"
    "Six dimensions [0,1]: change_directness (direct mapping 20%), causal_reachability "
    "(traced call flow 25%), requirement_support (explicit in paper 20%), trace_support "
    "(precedent exists 15%), verification_support (tests exist 10%), context_coverage "
    "(files read 10%). Penalties (add to confidence_penalties list): "
    '"paper_association_inferred" (-0.10), "no_call_entry" (-0.20), '
    '"alternate_implementation" (-0.20), "config_or_caller_unread" (-0.15), '
    '"context_truncated" (-0.15), "runtime_condition_unverified" (-0.15). '
    "If omitted, defaults yield a 0.625 base score.\n\n"
)


def _system_prompt(
    job: AgentAnalysisJob,
    soft_target: int = 40,
    precedents: str = "",
    deep_thinking: bool = False,
) -> tuple[str, str]:
    # Deep thinking asks for the six-dimension breakdown; the default keeps the original
    # single-confidence wording so the run stays as fast as before the formula was added.
    scoring = _SCORING_DEEP if deep_thinking else _SCORING_DIRECT
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
    elif job.kind == "trace":
        request = (
            f"Trace paper document {job.paper_document_id} against repository revision "
            f"{job.code_revision}. Work in four stages inside this single run, publishing "
            f"candidates in batches as you confirm them. Aim to finish within about "
            f"{soft_target} tool steps.\n\n"
            f"{precedents}"
            "RETRIEVAL. semantic_search_paper and semantic_search_code rank paper blocks and code "
            "symbols by MEANING, so you can locate a target by describing the computation instead "
            "of paging the whole document or repository — use them first on a long paper or large "
            "repository. recall_trace_cases surfaces this project's already-reviewed relations for "
            "calibration. All three are navigation aids: a rank is never a verdict, and you must "
            "still read the real block/source and quote it verbatim before publishing.\n\n"
            "STAGE 1 — SCOUT (paper focus). Browse bounded paper metadata first with "
            "list_paper_blocks, use search_paper_blocks for focused concepts, then read only "
            "specific evidence with get_paper_block. Identify 3-8 core contributions / method "
            "components and the sections that implement them. Mark method-chapter formulas, "
            "algorithms/pseudocode, and figures as must-inspect. Deliberately EXCLUDE background, "
            "related work, and experiment/result tables from tracing.\n\n"
            "STAGE 2 — MAP (code responsibilities). Skim the repository (semantic_search_code for "
            "each core target, then list_repository_files, "
            "list_code_symbols, get_symbol_source) to locate where the model, losses, tensor "
            "transforms, main train/inference loops, constraints, and update rules live. Treat "
            "this as navigation only, not a conclusion.\n\n"
            "STAGE 3 — DISPATCH & REGION EVIDENCE. Group the core targets from STAGE 1 into "
            "2-6 coherent regions (one region = one method component, e.g. 'contrastive loss', "
            "'sampler update rule'). Call dispatch_trace_subagents ONCE with all regions, giving "
            "each a name, paper_target_hints (block ids or short quotes), code_hints (paths or "
            "symbol ids from STAGE 2), and notes on what computation must exist. Parallel "
            "sub-agents read the real evidence for every region and publish candidates directly; "
            "you receive a per-region summary. After it returns, verify coverage against the "
            "summaries: fill gaps yourself with the read tools (or one more dispatch — at most 2 "
            "total), and handle failed or unresolved regions. If dispatch is unavailable or "
            "errors, do the region evidence yourself: for each core paper target, turn its "
            "meaning into a code search intent (what computation must happen), then read the "
            "actual source. Do a counter-check: is a same-named symbol merely config, a wrapper, "
            "or a test? Only keep a relation when the real computation happens. A paper target "
            "implemented across several places yields several candidates (one-to-many).\n\n"
            "STAGE 4 — MERGE & SELF-CHECK. Keep only targets that matter: a core contribution, a "
            "must-inspect formula/algorithm, a defining variable/constraint, or something with a "
            "direct important implementation. Merge adjacent synonymous targets; do not stack "
            "overlapping highlights. Set paper_evidence.occurrence and code_evidence.occurrence "
            "correctly when a quote repeats.\n\n"
            f"{scoring}"
            "Tooling rules: to read code, either call get_symbol_source with an exact id from "
            "list_code_symbols, or call read_source_lines(path, line_start, line_end) for any "
            "file window — do NOT guess symbol ids. code_symbol_id may be a file path plus a line "
            "range. Copy paper quotes from an exact evidence_span returned by "
            "search_paper_blocks/get_paper_block, and copy code quotes VERBATIM from "
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
    else:
        request = (
            f"Analyze saved modifications in repository revision {job.code_revision} against "
            "the immutable imported baseline. Produce a read-only conflict report.\n\n"
            "Follow this order: inspect prefetched evidence; verify code impact; use trace-linked "
            "paper spans when present; otherwise perform one focused paper search; check for "
            "counter-evidence or missing context; publish the complete report.\n\n"
            "PREFETCHED EVIDENCE. Initial tool_results contain a prefetched "
            "get_conflict_context entry. Inspect it before calling any tool. If ok=false, use "
            "the granular change, impact, trace, and paper tools. If ok=true, its result contains "
            "exact changes, code impact, affected traces, trace-linked paper blocks with stable "
            "evidence_spans, and possibly inferred_paper_candidates. When "
            "coverage.complete=true, do not repeat list_changed_files, get_change_diff, "
            "get_change_impact, list_affected_traces, or get_paper_block for evidence already "
            "present. Read extra source only for a concrete ambiguity, then publish. When "
            "coverage.complete=false, use granular tools only for paths or sections named in "
            "coverage.truncated_sections, truncated_paths, or omitted references. A stale trace "
            "with previously_accepted=true was accepted before the edit and deserves extra "
            "scrutiny. Prefer the shortest sufficient span from an existing TraceLink. If no "
            "trace covers an important change, inspect inferred_paper_candidates first, then "
            "call search_paper_blocks with a focused behavioral query only when needed. If "
            "lexical candidates are insufficient for a conceptual match, use "
            "semantic_search_paper as navigation, then read the exact block and span. Read "
            "only the highest-value blocks and mark such evidence association=inferred. Do not "
            "page through the whole paper with list_paper_blocks. If no "
            "paper is available, perform code-only analysis and do not invent paper evidence.\n\n"
            "REPORT. Use only these categories: paper_consistency, "
            "behavior_regression, trace_invalidation, trace_coverage, configuration_risk. Every "
            "item must cite a verbatim non-empty before or after quote from get_change_diff with "
            "its real line range. For a pure insertion or deletion, include only the non-empty "
            'side in change_evidence; never submit quote="". Paper claims should use '
            "paper_evidence{block_id,span_id,association}; do not manually retype or reformat "
            "the quote. A pure code risk does not require paper evidence. Separate "
            "severity from confidence and give concrete recommendations and verification steps. "
            "Set language=zh-CN and write every user-visible title, "
            "description, recommendation, verification step, and unresolved item in Simplified "
            "Chinese. Keep file paths, identifiers, symbol names, and evidence quotes "
            "in their original language. Submit payload with repository_revision, items, and "
            "unresolved. Each item uses category, severity, confidence, title, description, "
            "change_evidence, affected_symbols, callers, graph_node_ids, trace_refs, "
            "paper_evidence, recommendations, and verification_steps. Code evidence uses side, "
            "path, line_start, line_end, quote; trace refs use trace_id; paper evidence uses "
            "block_id, span_id, association (legacy quote is accepted). Do NOT submit page, id, "
            "affected_files, summary, or "
            "risk counts because the server derives them. "
            "Uncertain observations go in unresolved, not as invented conflicts. Finally call "
            "publish_conflict_report exactly once, including repository_revision and all items; "
            "an empty items list is allowed when the evidence shows no conflict."
        )
    return common, request


def _trace_step(run: AgentRun, item: dict[str, Any], trace_entries: list[dict[str, Any]]) -> None:
    """Append a trace entry to the in-memory accumulator.

    The accumulated list is only written to the DB once, at job finalization, to avoid
    hundreds of large JSON blob commits that cause SQLite write-lock contention under
    concurrent workers.
    """
    trace_entries.append(item)


def _activity(tool_name: str, arguments: dict[str, Any]) -> str:
    """Human-readable description of the current agent action for the progress UI."""

    args = arguments or {}
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
    match tool_name:
        case "list_paper_blocks":
            return "浏览论文结构"
        case "search_paper_blocks":
            return f"定向检索论文证据 “{args.get('query', '')}”"
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
        case "dispatch_trace_subagents":
            count = len(args.get("regions", []) or [])
            return f"并行取证：派发 {count} 个区域子代理"
        case "publish_architecture_graph":
            return "发布架构图"
        case "get_conflict_context":
            return "准备冲突分析上下文"
        case "list_changed_files":
            return "收集已保存的代码修改"
        case "get_change_diff":
            return f"核对修改 {args.get('path', '')}".strip()
        case "get_change_impact":
            return f"分析影响范围 {args.get('path', '')}".strip()
        case "list_affected_traces":
            return "查找受影响的追溯关系"
        case "publish_conflict_report":
            count = len(payload.get("items", []) or [])
            return f"发布 {count} 条冲突分析结果"
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
    if isinstance(safe.get("diff"), str):
        safe["diff"] = safe["diff"][:30_000]
    if isinstance(safe.get("hunks"), list):
        safe["hunks"] = [
            {
                **hunk,
                "before_quote": str(hunk.get("before_quote", ""))[:4000],
                "after_quote": str(hunk.get("after_quote", ""))[:4000],
            }
            for hunk in safe["hunks"][:30]
            if isinstance(hunk, dict)
        ]
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
    target = session.exec(select(PaperTarget).where(PaperTarget.fingerprint == fingerprint)).first()
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
        base_version = 0
    else:
        for key, value in values.items():
            setattr(target, key, value)
        target.version += 1
        base_version = target.version - 1
    session.add(target)
    session.flush()
    _record_target_operation(session, job.project_id, "paper_target", target, base_version)
    return target


def _record_target_operation(
    session: Session,
    project_id: int,
    entity_type: str,
    target: PaperTarget | CodeTarget,
    base_version: int,
) -> None:
    """Mirror a paper/code anchor into the sync outbox.

    Anchors are what the workbench hovers and highlights. They used to stay device-local,
    so a downloaded project rebuilt its target views from ``trace_link.evidence`` alone and
    lost bbox geometry, salience reasons and anchor_status.

    ``record_local_operation`` is a no-op for projects that are not ``cloud_enabled``, so
    this is safe to call unconditionally from the analysis pipeline.
    """

    from app.services.local_sync import (
        code_target_payload,
        paper_target_payload,
        record_local_operation,
    )

    project = session.get(Project, project_id)
    if project is None:
        return
    if isinstance(target, PaperTarget):
        payload = paper_target_payload(project, target, session=session)
    else:
        payload = code_target_payload(project, target, session=session)
    record_local_operation(
        session,
        project,
        entity_type,
        target.public_id,
        payload,
        base_version=base_version,
    )


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
    target = session.exec(select(CodeTarget).where(CodeTarget.fingerprint == fingerprint)).first()
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
        base_version = 0
    else:
        for key, value in values.items():
            setattr(target, key, value)
        target.version += 1
        base_version = target.version - 1
    session.add(target)
    session.flush()
    _record_target_operation(session, job.project_id, "code_target", target, base_version)
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
    # The dimension breakdown is only meaningful when deep thinking produced it; recording
    # placeholder dimensions for a directly-scored run would misrepresent how the number arose.
    deep_thinking = is_deep_thinking_enabled(session, job.project_id)
    prompt_version = "trace-agent-v3" if deep_thinking else "trace-agent-v2"
    score_basis_extra: dict[str, Any] = {}
    for candidate in payload.get("candidates", []):
        if deep_thinking:
            score_basis_extra = {
                "confidence_dimensions": {
                    "change_directness": candidate.get("change_directness", 0.7),
                    "causal_reachability": candidate.get("causal_reachability", 0.6),
                    "requirement_support": candidate.get("requirement_support", 0.7),
                    "trace_support": candidate.get("trace_support", 0.5),
                    "verification_support": candidate.get("verification_support", 0.5),
                    "context_coverage": candidate.get("context_coverage", 0.7),
                },
                "confidence_penalties": candidate.get("confidence_penalties", []),
            }
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
                **score_basis_extra,
            },
            "provenance_json": {
                "job_id": job.job_id,
                "run_id": artifact.agent_run_id,
                "artifact_id": artifact.artifact_id,
                "prompt_version": prompt_version,
                "graph_node_ids": candidate.get("graph_node_ids", []),
            },
            "model_info_json": {
                **artifact.model_info_json,
                "prompt_version": prompt_version,
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
        if job.kind == "architecture" and item.payload_json.get("root_symbol") != payload.get(
            "root_symbol"
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
        if isinstance(b, dict) and b.get("kind") in {"equation", "equation_interline", "algorithm"}
    )
    soft = 18 + 2 * n_formula + len(blocks) // 30
    return max(28, min(soft, 64))


def _finalize_trace_run(
    session: Session,
    job: AgentAnalysisJob,
    run: AgentRun,
    emitter: RunEventEmitter | SharedRunEventBus,
    artifact: AgentAnalysisArtifact | None,
    published_count: int,
    trace_entries: list[dict[str, Any]] | None = None,
    cancelled: bool = False,
) -> None:
    """Mark a (possibly multi-publish) trace run complete and emit terminal events.

    When ``cancelled`` is set the run was interrupted early by the user; whatever was already
    published is preserved and the job still finishes as ``succeeded`` so those links render.
    """

    now = utc_now()
    job.status = "succeeded"
    job.error_code = None
    if artifact is not None:
        job.artifact_id = artifact.artifact_id
    if cancelled:
        noun = "追溯" if job.kind == "trace" else "分析"
        job.progress_json = {
            "message": (
                f"{noun}已中止，保留 {published_count} 条已发现结果"
                if published_count
                else f"{noun}已中止"
            ),
            "code": "analysis_cancelled",
        }
    else:
        job.progress_json = {
            "message": "Agent 分析完成" if published_count else "Agent 未发现可靠追溯关系"
        }
    job.updated_at = now
    job.completed_at = now
    run.status = "completed"
    run.updated_at = now
    run.completed_at = now
    # Flush accumulated in-memory trace entries to the run row exactly once.
    if trace_entries is not None:
        run.trace_json = trace_entries
        run.step_count = sum(e.get("type") == "model_step" for e in trace_entries)
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


def _fail(
    session: Session,
    job: AgentAnalysisJob,
    run: AgentRun | None,
    code: str,
    trace_entries: list[dict[str, Any]] | None = None,
) -> None:
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
        # Flush accumulated in-memory trace entries to the run row.
        if trace_entries is not None:
            run.trace_json = trace_entries
            run.step_count = sum(e.get("type") == "model_step" for e in trace_entries)
        session.add(run)
    session.commit()


def _execute_job(job_id: str) -> None:
    try:
        with Session(engine) as session:
            job = session.get(AgentAnalysisJob, job_id)
            if job is None or job.status in {"succeeded", "cancelling"}:
                # ``cancelling`` on a not-yet-started job: the cancel endpoint already wrote a
                # terminal state for the no-run case, so nothing to do here.
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
            # All writes of this run (event rows, publishes, progress updates) are serialized
            # behind one re-entrant lock so parallel sub-agent threads respect SQLite's single
            # writer and the (run_id, sequence) uniqueness the SSE cursor depends on.
            write_lock = RLock()
            emitter = SharedRunEventBus(engine, run.run_id, write_lock)
            sink = (
                TracePublishSink(
                    engine,
                    job.job_id,
                    run.run_id,
                    write_lock,
                    emitter,
                    persist_artifact=_persist_artifact,
                    append_links=_append_trace_links,
                )
                if job.kind == "trace"
                else None
            )

            def _current_artifact() -> AgentAnalysisArtifact | None:
                if sink is None or sink.artifact_id is None:
                    return None
                return session.get(AgentAnalysisArtifact, sink.artifact_id)

            def _published() -> int:
                return sink.published_count if sink is not None else 0

            emitter.emit("analysis.started", {"job_id": job.job_id, "kind": job.kind})
            soft_target = _trace_soft_target(session, job) if job.kind == "trace" else 40
            precedents = _trace_precedents(session, job) if job.kind == "trace" else ""
            deep_thinking = is_deep_thinking_enabled(session, job.project_id)
            system_prompt, request = _system_prompt(job, soft_target, precedents, deep_thinking)
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
                    "paper_available": job.paper_document_id is not None,
                },
                "memories": [],
                "skills": [{"name": f"{job.kind}-analysis", "instructions": system_prompt}],
                "tool_definitions": tool_definitions(job.kind),
            }
            tool_results: list[dict[str, Any]] = []
            # Accumulate trace entries in memory; write to DB exactly once at finalization to
            # avoid hundreds of large JSON blob commits that cause SQLite write-lock contention.
            trace_entries: list[dict[str, Any]] = []
            prefetched_conflict_context: dict[str, Any] | None = None
            if job.kind == "conflict":
                try:
                    prefetched_conflict_context = execute_tool(
                        session,
                        job.project_id,
                        job.code_repository_id,
                        job.paper_document_id,
                        job.requested_depth,
                        "get_conflict_context",
                        {},
                    )
                except (ValidationError, ValueError) as exc:
                    feedback = {
                        "tool": "get_conflict_context",
                        "ok": False,
                        "error": str(exc)[:240] or "conflict_context_prefetch_failed",
                        "instruction": (
                            "The aggregate prefetch failed. Use the granular change, impact, "
                            "trace, and paper tools before publishing."
                        ),
                    }
                    tool_results.append(feedback)
                    _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
                    emitter.emit(
                        "analysis.tool.failed",
                        {
                            "tool_name": "get_conflict_context",
                            "code": "conflict_context_prefetch_failed",
                            "step": 0,
                        },
                    )
                else:
                    feedback = {
                        "tool": "get_conflict_context",
                        "ok": True,
                        "prefetched": True,
                        "result": prefetched_conflict_context,
                        "instruction": (
                            "Use this evidence package first. Only fetch granular evidence named "
                            "as truncated or genuinely missing."
                        ),
                    }
                    tool_results.append(feedback)
                    summary = prefetched_conflict_context.get("summary", {})
                    coverage = prefetched_conflict_context.get("coverage", {})
                    context["environment"].update(
                        {
                            "changed_file_count": summary.get("changed_file_count", 0),
                            "changed_line_count": summary.get("changed_line_count", 0),
                        }
                    )
                    _trace_step(
                        run,
                        {
                            "type": "tool_result",
                            "tool": "get_conflict_context",
                            "ok": True,
                            "prefetched": True,
                            "summary": summary,
                            "coverage": coverage,
                        },
                        trace_entries,
                    )
                    emitter.emit(
                        "analysis.tool.completed",
                        {
                            "tool_name": "get_conflict_context",
                            "activity": (
                                f"已准备 {summary.get('changed_file_count', 0)} 个修改文件、"
                                f"{summary.get('affected_trace_count', 0)} 条追溯、"
                                f"{summary.get('paper_block_count', 0)} 个论文块"
                            ),
                            "step": 0,
                            "prefetched": True,
                            "coverage_complete": bool(coverage.get("complete")),
                        },
                    )
            # Transient provider hiccups (malformed/truncated JSON on a big publish payload,
            # empty responses, rate limits) should not kill an otherwise-successful run. Retry
            # them a bounded number of times before giving up.
            provider_failures = 0
            # Hard safety cap on tool steps only. Normal termination is the model calling
            # finish_analysis (trace) or publishing once (architecture); soft_target just nudges.
            conflict_context_complete = bool(
                prefetched_conflict_context
                and prefetched_conflict_context.get("coverage", {}).get("complete")
            )
            budget = 48 if job.kind == "architecture" else 100
            if job.kind == "conflict":
                soft_target = 24 if conflict_context_complete else 48
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
                "search_paper_blocks",
                "get_paper_block",
                "semantic_search_paper",
                "semantic_search_code",
                "recall_trace_cases",
                "get_analysis_artifact",
                "get_conflict_context",
                "list_changed_files",
                "get_change_diff",
                "get_change_impact",
                "list_affected_traces",
            }
            if prefetched_conflict_context is not None:
                seen_calls["get_conflict_context|{}"] = prefetched_conflict_context
            converge_nudged = False
            dispatch_calls = 0
            dispatched_regions = 0
            publish_name = (
                "publish_architecture_graph"
                if job.kind == "architecture"
                else (
                    "publish_conflict_report"
                    if job.kind == "conflict"
                    else "publish_trace_candidates"
                )
            )
            for step_number in range(1, budget + 1):
                # Check for an external stop signal at every step start. The cancel endpoint
                # sets status=cancelling to interrupt early while KEEPING whatever was already
                # published; a hard failure (manual abort) sets status=failed. Reloading the
                # job is one cheap SELECT per step under WAL.
                #
                # rollback() first: events and publishes now commit on their own sessions
                # (sink/bus), so this session no longer commits inside the loop. Without
                # ending the read transaction here, its WAL snapshot would pin and the
                # re-SELECT below would keep returning the stale pre-cancel status forever.
                session.rollback()
                session.expire(job)
                if job.status == "cancelling":
                    if sink is not None:
                        sink.close()
                    emitter.emit(
                        "analysis.progress",
                        {
                            "message": (
                                "正在中止追溯（保留已发现的关系）"
                                if job.kind == "trace"
                                else "正在中止分析"
                            ),
                            "step": step_number,
                        },
                    )
                    _finalize_trace_run(
                        session,
                        job,
                        run,
                        emitter,
                        _current_artifact(),
                        _published(),
                        trace_entries=trace_entries,
                        cancelled=True,
                    )
                    return
                if job.status == "failed":
                    if sink is not None:
                        sink.close()
                    run.status = "failed"
                    run.degraded_reason = job.error_code or "externally_aborted"
                    run.updated_at = utc_now()
                    run.completed_at = utc_now()
                    run.trace_json = trace_entries
                    run.step_count = sum(e.get("type") == "model_step" for e in trace_entries)
                    session.add(run)
                    session.commit()
                    return
                emitter.emit(
                    "analysis.progress",
                    {"message": "Agent 正在规划并核对证据", "step": step_number},
                )
                try:
                    step = provider.next_step(request, context, tool_results)
                except AgentProviderFailure as exc:
                    if exc.reason in RETRYABLE_PROVIDER_FAILURES and provider_failures < 6:
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
                        # Rate limits and timeouts back off exponentially (with jitter) so
                        # parallel runs don't hammer the provider; other retryable reasons
                        # are model mistakes and retry immediately.
                        time.sleep(backoff_seconds(provider_failures, exc.reason))
                        continue
                    if sink is not None:
                        sink.close()
                    emitter.emit("analysis.failed", {"code": exc.reason})
                    _fail(session, job, run, exc.reason, trace_entries=trace_entries)
                    return
                _trace_step(
                    run,
                    {
                        "type": "model_step",
                        "action": step.action,
                        "tool_name": step.tool_name,
                        "arguments": step.arguments,
                    },
                    trace_entries,
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
                if job.kind == "trace" and tool_name == "dispatch_trace_subagents":
                    assert sink is not None
                    try:
                        dispatch_args = DispatchSubagentsArguments.model_validate(step.arguments)
                    except ValidationError as exc:
                        details = "; ".join(
                            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                            for item in exc.errors()[:8]
                        )
                        feedback = {
                            "tool": tool_name,
                            "ok": False,
                            "error": "invalid_tool_arguments",
                            "details": details[:600],
                            "instruction": (
                                "Each region needs a short name; paper_target_hints and "
                                "code_hints are string lists; at most 8 regions per call."
                            ),
                        }
                        tool_results.append(feedback)
                        _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
                        emitter.emit(
                            "analysis.tool.failed",
                            {
                                "tool_name": tool_name,
                                "code": "invalid_tool_arguments",
                                "step": step_number,
                                "budget": budget,
                            },
                        )
                        continue
                    if (
                        dispatch_calls >= MAX_DISPATCH_CALLS
                        or dispatched_regions >= MAX_TOTAL_REGIONS
                    ):
                        feedback = {
                            "tool": tool_name,
                            "ok": False,
                            "error": "dispatch_limit_reached",
                            "instruction": (
                                "No more dispatches: do the remaining region evidence yourself "
                                "with the read tools, publish, then call finish_analysis."
                            ),
                        }
                        tool_results.append(feedback)
                        _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
                        emitter.emit(
                            "analysis.tool.failed",
                            {
                                "tool_name": tool_name,
                                "code": "dispatch_limit_reached",
                                "step": step_number,
                                "budget": budget,
                            },
                        )
                        continue
                    regions = dispatch_args.regions[: MAX_TOTAL_REGIONS - dispatched_regions]
                    dispatch_calls += 1
                    emitter.emit(
                        "analysis.subagents.started",
                        {
                            "regions": len(regions),
                            "names": [region.name for region in regions],
                            "step": step_number,
                            "budget": budget,
                            "activity": f"并行取证：启动 {len(regions)} 个区域子代理",
                        },
                    )
                    outcome = run_trace_subagents(
                        engine=engine,
                        provider=provider,
                        ctx=RegionJobContext(
                            job_id=job.job_id,
                            project_id=job.project_id,
                            repository_id=job.code_repository_id,
                            paper_document_id=job.paper_document_id,
                            requested_depth=job.requested_depth,
                            code_revision=job.code_revision,
                            system_prompt=system_prompt,
                            environment=context["environment"],
                            deep_thinking=deep_thinking,
                        ),
                        regions=regions,
                        sink=sink,
                        bus=emitter,
                        write_lock=write_lock,
                        parallelism=settings.tracelab_trace_subagent_parallelism,
                        step_budget=settings.tracelab_trace_subagent_steps,
                    )
                    dispatched_regions += outcome.regions_used
                    trace_entries.extend(outcome.trace_entries)
                    feedback = {"tool": tool_name, "ok": True, "result": outcome.tool_payload}
                    tool_results.append(feedback)
                    _trace_step(
                        run,
                        {
                            "type": "tool_result",
                            "tool": tool_name,
                            "ok": True,
                            "regions": outcome.regions_used,
                            "published": outcome.total_published,
                        },
                        trace_entries,
                    )
                    emitter.emit(
                        "analysis.tool.completed",
                        {
                            "tool_name": tool_name,
                            "activity": (
                                f"并行取证完成：{outcome.regions_used} 个区域、"
                                f"新增 {outcome.total_published} 条候选"
                            ),
                            "step": step_number,
                            "budget": budget,
                            "published": outcome.total_published > 0,
                        },
                    )
                    continue
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
                            f"{publish_name} ONCE with the complete structured payload."
                        ),
                    }
                    tool_results.append(feedback)
                    _trace_step(
                        run,
                        {"type": "tool_result", "tool": tool_name, "ok": True, "reused": True},
                        trace_entries,
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
                    publish_hint = (
                        "Publish the complete conflict report now; an empty items list is valid "
                        "when no conflict is supported"
                        if job.kind == "conflict"
                        else "Publish any remaining defensible candidates now (never empty)"
                    )
                    tool_results.append(
                        {
                            "tool": "runtime",
                            "ok": False,
                            "error": "soft_target_reached",
                            "instruction": (
                                f"You have reached the soft step target (~{soft_target}). "
                                f"{publish_hint}"
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
                    required_hint = (
                        "Conflict items require category, severity, confidence, title, "
                        "description, and change_evidence{side,path,line_start,line_end,quote}."
                        if job.kind == "conflict"
                        else (
                            "Required fields per candidate are paper_block_id, code_symbol_id, "
                            "rationale, paper_evidence{block_id,quote}, and "
                            "code_evidence{path,line_start,line_end,quote}."
                        )
                    )
                    feedback = {
                        "tool": tool_name,
                        "ok": False,
                        "error": error,
                        "details": details[:600],
                        "instruction": (
                            "Fix only the fields named in details and retry. Do not add fields "
                            f"outside the schema. {required_hint}"
                        ),
                    }
                    tool_results.append(feedback)
                    _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
                    emitter.emit(
                        "analysis.tool.failed",
                        {
                            "tool_name": tool_name,
                            "code": error,
                            "details": details[:600],
                            "step": step_number,
                            "budget": budget,
                        },
                    )
                    continue
                except ConflictEvidenceError as exc:
                    details = exc.details()
                    location = f"items.{exc.item_index}.paper_evidence.{exc.evidence_index}"
                    details_text = f"{location}: block={exc.block_id}, reason={exc.reason}"
                    feedback = {
                        "tool": tool_name,
                        "ok": False,
                        "error": exc.code,
                        "details": details_text,
                        "evidence_error": details,
                        "instruction": (
                            f"Repair only {location}. Reuse a span_id returned for block "
                            f"{exc.block_id}. Call {exc.retry_tool} only if that block or its "
                            "evidence_spans are not already present in cached tool results; do "
                            "not re-read code or rebuild other report items. If no exact span "
                            "supports the claim, remove that paper evidence or move the "
                            "observation to unresolved, then retry the same complete report."
                        ),
                    }
                    tool_results.append(feedback)
                    _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
                    emitter.emit(
                        "analysis.tool.failed",
                        {
                            "tool_name": tool_name,
                            "code": exc.code,
                            "details": details_text,
                            "evidence_error": details,
                            "step": step_number,
                            "budget": budget,
                        },
                    )
                    continue
                except ValueError as exc:
                    error = str(exc)[:240] or "analysis_evidence_invalid"
                    correction = (
                        "Rewrite every user-visible title, description, recommendation, "
                        "verification step, and unresolved item in Simplified Chinese, then "
                        "publish the complete report again. Keep paths, symbols, and verbatim "
                        "quotes unchanged."
                        if error == "conflict_output_must_be_chinese"
                        else "Correct the evidence or arguments and retry without guessing."
                    )
                    feedback = {
                        "tool": tool_name,
                        "ok": False,
                        "error": error,
                        "instruction": correction,
                    }
                    tool_results.append(feedback)
                    _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
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
                _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
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
                    if sink is not None:
                        sink.close()
                    _finalize_trace_run(
                        session,
                        job,
                        run,
                        emitter,
                        _current_artifact(),
                        _published(),
                        trace_entries=trace_entries,
                    )
                    return
                if tool_name == publish_name and result.get("published"):
                    if job.kind in {"architecture", "conflict"}:
                        # Architecture and conflict reports publish exactly once and terminate.
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
                            _fail(session, job, run, str(exc), trace_entries=trace_entries)
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
                        # Flush accumulated in-memory trace entries to the run row.
                        run.trace_json = trace_entries
                        run.step_count = sum(e.get("type") == "model_step" for e in trace_entries)
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
                    # Trace: incremental, NON-terminal publish — persist and render now,
                    # through the same single-writer sink the sub-agents use.
                    assert sink is not None
                    try:
                        sink.publish(result["payload"], step=step_number)
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
                        _trace_step(run, {"type": "tool_result", **feedback}, trace_entries)
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
                    # Past the soft target with results in hand: push to wrap up so runs don't
                    # drift toward the hard cap re-publishing overlapping candidates.
                    if step_number >= soft_target:
                        tool_results.append(
                            {
                                "tool": "runtime",
                                "ok": False,
                                "error": "wrap_up",
                                "instruction": (
                                    f"You have published {_published()} relations and passed "
                                    "the soft target. If the core contributions and must-inspect "
                                    "targets are covered, call finish_analysis NOW to end. Only "
                                    "publish again for a genuinely new, defensible target."
                                ),
                            }
                        )
                    continue
            # Budget exhausted. If the run already produced results, finalize as succeeded;
            # otherwise nothing defensible was ever published.
            if sink is not None:
                sink.close()
            final_artifact = _current_artifact()
            if final_artifact is not None or _published() > 0:
                _finalize_trace_run(
                    session,
                    job,
                    run,
                    emitter,
                    final_artifact,
                    _published(),
                    trace_entries=trace_entries,
                )
                return
            emitter.emit("analysis.failed", {"code": "agent_output_incomplete"})
            _fail(session, job, run, "agent_output_incomplete", trace_entries=trace_entries)
    except Exception as exc:
        # Preserve the full traceback and the underlying error detail. The bare class
        # name (e.g. "OperationalError") is useless for diagnosis; capture the message
        # (SQLite locks vs. disk errors vs. malformed statements all raise the same class).
        detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        logger.error(
            "analysis job %s crashed: %s: %s\n%s",
            job_id,
            exc.__class__.__name__,
            detail,
            traceback.format_exc(),
        )
        code = f"analysis_internal_error:{exc.__class__.__name__}"
        if detail:
            code = f"{code}:{detail}"
        with Session(engine) as session:
            job = session.get(AgentAnalysisJob, job_id)
            if job is not None:
                run = session.get(AgentRun, job.agent_run_id) if job.agent_run_id else None
                _fail(session, job, run, code)
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
        now = utc_now()
        linked_run_ids = {job.agent_run_id for job in jobs if job.agent_run_id}
        for job in jobs:
            # Drop zombie runs left by a previous process so they cannot occupy
            # both ThreadPoolExecutor slots forever after restart.
            stale = False
            if job.updated_at is not None:
                # Stored timestamps come back naive from SQLite; normalize before subtracting.
                age = (now - as_utc(job.updated_at)).total_seconds()
                stale = age > 900  # 15 minutes without progress
            if job.agent_run_id:
                run = session.get(AgentRun, job.agent_run_id)
                if run is not None and run.status in {"queued", "running"}:
                    run.status = "failed"
                    run.degraded_reason = "analysis_restarted"
                    run.updated_at = now
                    run.completed_at = now
                    session.add(run)
            if stale and job.status in {"running", "validating"}:
                job.status = "failed"
                job.error_code = "analysis_stale_timeout"
                job.progress_json = {
                    "message": "Agent 分析超时未更新，已自动结束",
                    "code": "analysis_stale_timeout",
                }
                job.updated_at = now
                job.completed_at = now
                session.add(job)
                continue
            job.status = "queued"
            job.agent_run_id = None
            job.progress_json = {"message": "排队等待 Agent 分析"}
            job.updated_at = now
            session.add(job)
        orphan_runs = list(
            session.exec(
                select(AgentRun).where(AgentRun.status.in_(["queued", "running", "cancelling"]))
            ).all()
        )
        for run in orphan_runs:
            if run.run_id in linked_run_ids:
                continue
            run.status = "failed"
            run.degraded_reason = "analysis_restarted"
            run.updated_at = now
            run.completed_at = now
            session.add(run)
        session.commit()
        # Capture ids before the session closes; committed instances expire and would
        # raise DetachedInstanceError if their attributes were read outside the session.
        job_ids = [job.job_id for job in jobs if job.status == "queued"]
    for job_id in job_ids:
        _submit(job_id)
