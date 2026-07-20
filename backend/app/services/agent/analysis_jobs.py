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
    PaperDocument,
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


def _system_prompt(job: AgentAnalysisJob) -> tuple[str, str]:
    common = (
        "You are TraceLab's autonomous evidence analysis agent. You are the only semantic "
        "decision-maker. Local indexes are navigation aids, not conclusions. Inspect actual "
        "paper/code evidence through tools. Never invent a path, symbol, line, quote, node, or "
        "relation. A task completes only by calling its publish tool with a schema-valid payload. "
        "If something cannot be resolved, record it as unresolved instead of guessing."
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
            f"Analyze paper document {job.paper_document_id} against repository revision "
            f"{job.code_revision}. Browse paper blocks and code autonomously; do not use keyword "
            "overlap as a semantic verdict. Every candidate needs exact paper and code quotes. "
            "Read the current architecture artifact when useful. Call publish_trace_candidates "
            "exactly once, including an empty candidates list if no defensible relation exists."
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


def _safe_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool_name.startswith("publish_"):
        return {"published": result.get("published", False)}
    safe = dict(result)
    if isinstance(safe.get("content"), str):
        safe["content"] = safe["content"][:40_000]
    if isinstance(safe.get("items"), list):
        safe["items"] = safe["items"][:100]
    return safe


def _persist_trace_links(
    session: Session,
    job: AgentAnalysisJob,
    artifact: AgentAnalysisArtifact,
    payload: dict[str, Any],
) -> None:
    if job.paper_document_id is None:
        raise ValueError("paper_document_not_found")
    for candidate in payload.get("candidates", []):
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
        values = {
            "project_id": job.project_id,
            "paper_document_id": job.paper_document_id,
            "paper_ref": candidate["paper_block_id"],
            "code_repository_id": job.code_repository_id,
            "code_revision": job.code_revision,
            "code_ref": candidate["code_symbol_id"],
            "relation_type": candidate["relation_type"],
            "confidence": candidate["confidence"],
            "static_confidence": 0.0,
            "llm_confidence": candidate["confidence"],
            "source": "agent",
            "evidence_json": [
                {
                    "side": "paper",
                    "ref": candidate["paper_block_id"],
                    "quote": paper_evidence["quote"],
                },
                {
                    "side": "code",
                    "ref": candidate["code_symbol_id"],
                    "quote": code_evidence["quote"],
                    "path": code_evidence["path"],
                    "line_start": code_evidence["line_start"],
                    "line_end": code_evidence["line_end"],
                },
            ],
            "rationale": candidate["rationale"],
            "uncertainty_json": {
                "level": candidate["uncertainty_level"],
                "reasons": candidate.get("uncertainty_reasons", []),
            },
            "model_info_json": {
                **artifact.model_info_json,
                "prompt_version": "trace-agent-v1",
                "run_id": artifact.agent_run_id,
                "artifact_id": artifact.artifact_id,
                "graph_node_ids": candidate.get("graph_node_ids", []),
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
            provider, reason = _provider_from_settings(session)
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
            system_prompt, request = _system_prompt(job)
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
            budget = 48 if job.kind == "architecture" else 64
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
                emitter.emit("analysis.tool.started", {"tool_name": tool_name})
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
                except ValidationError:
                    error = "invalid_tool_arguments"
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
                    emitter.emit("analysis.tool.failed", {"tool_name": tool_name, "code": error})
                    continue
                except ValueError as exc:
                    error = str(exc)[:128] or "analysis_evidence_invalid"
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
                    emitter.emit("analysis.tool.failed", {"tool_name": tool_name, "code": error})
                    continue
                safe = _safe_result(tool_name, result)
                feedback = {"tool": tool_name, "ok": True, "result": safe}
                tool_results.append(feedback)
                _trace_step(run, {"type": "tool_result", **feedback}, session)
                emitter.emit(
                    "analysis.tool.completed",
                    {"tool_name": tool_name, "published": bool(result.get("published"))},
                )
                if tool_name == publish_name and result.get("published"):
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
    for job in jobs:
        _submit(job.job_id)
