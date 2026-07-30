"""Parallel trace sub-agents: bounded fan-out for the STAGE 3 region evidence work.

The parent analysis loop (``analysis_jobs._execute_job``) intercepts the
``dispatch_trace_subagents`` tool and calls :func:`run_trace_subagents`. Each region runs a
small independent ReAct loop (own LLM context, own read cache, own DB session) and publishes
confirmed candidates directly through the shared :class:`TracePublishSink`.

Concurrency discipline (SQLite single-writer, SSE sequence uniqueness):

- All writes of one job — event rows, publish persistence, progress updates — go through one
  shared ``threading.RLock``. Sequence allocation, insert, and commit happen inside the lock
  so the SSE cursor can never skip an event committed out of order.
- Sub-agents run in a per-dispatch throwaway executor, never in the module-level analysis
  pool (two parent jobs waiting on sub-tasks in the same 2-worker pool would deadlock).
- ``engine`` is always passed in explicitly (tests monkeypatch it per module on
  ``analysis_jobs``; taking it as a parameter keeps this module out of that patch list).
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session, func, select

from app.models.entities import (
    AgentAnalysisArtifact,
    AgentAnalysisJob,
    AgentRun,
    AgentRunEvent,
    TraceLink,
    utc_now,
)
from app.services.agent.analysis_tools import DispatchRegion, execute_tool, tool_definitions
from app.services.agent.provider import AgentProvider, AgentProviderFailure, AgentProviderStep
from app.services.agent.run_events import append_event

logger = logging.getLogger("tracelab.agent.subagents")

# Provider failures worth retrying (shared with the parent loop).
RETRYABLE_PROVIDER_FAILURES = {
    "llm_invalid_json",
    "llm_empty_response",
    "llm_rate_limited",
    "llm_timeout",
    "llm_transport_error",
    "llm_upstream_error",
}

# Dispatch bookkeeping limits enforced by the parent loop.
MAX_DISPATCH_CALLS = 2
MAX_TOTAL_REGIONS = 12
DISPATCH_WALL_SECONDS = 900.0

_READ_TOOLS = {
    "list_repository_files",
    "search_repository_text",
    "list_code_symbols",
    "get_symbol_source",
    "get_symbol_calls",
    "read_source_lines",
    "list_paper_blocks",
    "get_paper_block",
}

_REGION_STATUS_LABEL = {
    "succeeded": "完成",
    "failed": "失败",
    "timeout": "超时",
    "cancelled": "已中止",
}


def backoff_seconds(failures: int, reason: str) -> float:
    """Exponential backoff with full jitter for rate-limit/timeout retries.

    Other retryable reasons (malformed JSON, empty responses) are model mistakes, not load
    signals — retrying them immediately is fine and keeps runs fast.
    """

    if reason not in {"llm_rate_limited", "llm_timeout"}:
        return 0.0
    base = min(30.0, 2.0 * (2 ** max(0, failures - 1)))
    return random.uniform(0.5 * base, base)


class SharedRunEventBus:
    """Thread-safe event emitter for one run, usable from parallel sub-agent threads.

    Drop-in replacement for ``RunEventEmitter`` in the analysis path: same ``emit``
    signature, but each emit opens its own short-lived session (worker threads must not
    share ORM sessions) and allocates the sequence inside the shared write lock.
    """

    def __init__(self, engine: Engine, run_id: str, write_lock: threading.RLock) -> None:
        self._engine = engine
        self._run_id = run_id
        self._lock = write_lock
        with Session(engine) as session:
            current = session.exec(
                select(func.max(AgentRunEvent.sequence)).where(AgentRunEvent.run_id == run_id)
            ).one()
        self.sequence = int(current or 0)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            self.sequence += 1
            with Session(self._engine) as session:
                run = session.get(AgentRun, self._run_id)
                if run is None:
                    return
                append_event(session, run, self.sequence, event_type, payload)


class TracePublishSink:
    """Single-writer funnel for every trace publish of one job (parent and sub-agents).

    Serializes ``_persist_artifact`` / ``_append_trace_links`` (select-then-upsert is not
    safe under concurrency) and keeps the artifact/link bookkeeping in one place. The
    persistence callables are injected by ``analysis_jobs`` to avoid a module cycle.
    """

    def __init__(
        self,
        engine: Engine,
        job_id: str,
        run_id: str,
        write_lock: threading.RLock,
        bus: SharedRunEventBus,
        *,
        persist_artifact: Callable[..., Any],
        append_links: Callable[..., None],
    ) -> None:
        self._engine = engine
        self._job_id = job_id
        self._run_id = run_id
        self._lock = write_lock
        self._bus = bus
        self._persist_artifact = persist_artifact
        self._append_links = append_links
        self.artifact_id: str | None = None
        self.published_count = 0
        self._closed = False

    def publish(
        self,
        payload: dict[str, Any],
        *,
        step: int | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                # A late publish after the run was finalized (cancellation race): drop it.
                logger.warning("trace publish after finalize dropped (job %s)", self._job_id)
                return {"published": False, "error": "publish_after_finalize"}
            with Session(self._engine) as session:
                job = session.get(AgentAnalysisJob, self._job_id)
                run = session.get(AgentRun, self._run_id)
                if job is None or run is None:
                    raise ValueError("analysis_job_missing")
                before_count = 0
                if self.artifact_id is not None:
                    before_count = session.exec(
                        select(func.count(TraceLink.id)).where(
                            TraceLink.artifact_id == self.artifact_id
                        )
                    ).one()
                if self.artifact_id is None:
                    self._bus.emit("analysis.validating", {"job_id": job.job_id})
                    artifact = self._persist_artifact(session, job, run, payload)
                else:
                    artifact = session.get(AgentAnalysisArtifact, self.artifact_id)
                    if artifact is None:
                        raise ValueError("analysis_artifact_missing")
                    self._append_links(session, job, artifact, payload)
                session.flush()
                after_count = session.exec(
                    select(func.count(TraceLink.id)).where(
                        TraceLink.artifact_id == artifact.artifact_id
                    )
                ).one()
                job.progress_json = {
                    "message": f"Agent 分析中，已发布 {after_count} 条关系",
                    "code": "trace_published",
                    "published_link_count": after_count,
                }
                session.add(job)
                session.add(artifact)
                session.commit()
                self.artifact_id = artifact.artifact_id
                new_links = max(0, after_count - before_count)
                self.published_count = after_count
                event: dict[str, Any] = {
                    "job_id": job.job_id,
                    "artifact_id": artifact.artifact_id,
                    "new_links": new_links,
                    "total_links": self.published_count,
                    "code_revision": job.code_revision,
                }
                if step is not None:
                    event["step"] = step
                if region is not None:
                    event["subagent"] = region
                self._bus.emit("analysis.published", event)
                return {"new_links": new_links, "total_links": self.published_count}

    def close(self) -> None:
        with self._lock:
            self._closed = True


@dataclass(frozen=True)
class RegionJobContext:
    """Immutable snapshot of the parent job passed into region threads.

    Plain values only — ORM instances must not cross thread/session boundaries.
    """

    job_id: str
    project_id: int
    repository_id: int
    paper_document_id: int | None
    requested_depth: int
    code_revision: int
    system_prompt: str
    environment: dict[str, Any]


@dataclass
class RegionResult:
    name: str
    status: str  # succeeded | failed | timeout | cancelled
    published_count: int = 0
    dropped_count: int = 0
    unresolved: list[str] = field(default_factory=list)
    summary: str = ""
    steps_used: int = 0
    trace_entries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DispatchOutcome:
    tool_payload: dict[str, Any]
    trace_entries: list[dict[str, Any]]
    regions_used: int
    total_published: int
    cancelled: bool


class _RegionCancelled(Exception):
    pass


class _CancelProbe:
    """Cheap per-thread cancellation check: shared event first, throttled DB poll second."""

    def __init__(
        self,
        engine: Engine,
        job_id: str,
        cancel_event: threading.Event,
        interval: float = 2.0,
    ) -> None:
        self._engine = engine
        self._job_id = job_id
        self._cancel_event = cancel_event
        self._interval = interval
        self._last_poll = 0.0

    def should_stop(self) -> bool:
        if self._cancel_event.is_set():
            return True
        now = time.monotonic()
        if now - self._last_poll < self._interval:
            return False
        self._last_poll = now
        with Session(self._engine) as session:
            status = session.exec(
                select(AgentAnalysisJob.status).where(AgentAnalysisJob.job_id == self._job_id)
            ).first()
        if status in {"cancelling", "failed"}:
            self._cancel_event.set()
            return True
        return False


def _region_request(region: DispatchRegion, ctx: RegionJobContext, step_budget: int) -> str:
    hints = {
        "paper_target_hints": region.paper_target_hints,
        "code_hints": region.code_hints,
        "notes": region.notes,
    }
    return (
        f"You are a TraceLab trace SUB-AGENT responsible ONLY for the region "
        f"\"{region.name}\" of paper document {ctx.paper_document_id} against repository "
        f"revision {ctx.code_revision}. Region hints (navigation aids, NOT conclusions): "
        f"{json.dumps(hints, ensure_ascii=False)}.\n"
        "Start with semantic_search_paper / semantic_search_code to locate your region's "
        "targets by describing the computation, and recall_trace_cases to see how similar "
        "relations were judged before — all three rank by similarity and settle nothing. "
        "Read the real evidence with the tools; copy every paper and code quote VERBATIM "
        "from get_paper_block / get_symbol_source / read_source_lines. Counter-check whether "
        "a same-named symbol is merely config, a wrapper, or a test. Publish confirmed "
        "candidates for this region with publish_trace_candidates in small batches — each "
        "candidate needs paper_evidence{block_id,quote,occurrence}, "
        "code_evidence{path,line_start,line_end,quote,occurrence}, salience, relevance, and "
        "confidence (or optionally the six dimension scores for finer control). Never publish "
        "an empty payload and never publish targets outside your region.\n"
        f"Work within about {step_budget} tool steps. When your region is fully covered (or "
        "nothing defensible exists), reply with a short plain-text summary of what you found "
        "INSTEAD of calling another tool — that ends your region."
    )


def _call_provider_with_retry(
    provider: AgentProvider,
    request: str,
    context: dict[str, Any],
    tool_results: list[dict[str, Any]],
    *,
    bus: SharedRunEventBus,
    probe: _CancelProbe,
    region_name: str,
    step_number: int,
    step_budget: int,
    max_retries: int = 4,
) -> AgentProviderStep:
    failures = 0
    while True:
        if probe.should_stop():
            raise _RegionCancelled()
        try:
            return provider.next_step(request, context, tool_results)
        except AgentProviderFailure as exc:
            if exc.reason not in RETRYABLE_PROVIDER_FAILURES or failures >= max_retries:
                raise
            failures += 1
            bus.emit(
                "analysis.tool.failed",
                {
                    "tool_name": "provider",
                    "code": exc.reason,
                    "subagent": region_name,
                    "step": step_number,
                    "budget": step_budget,
                },
            )
            tool_results.append(
                {
                    "tool": "runtime",
                    "ok": False,
                    "error": exc.reason,
                    "instruction": (
                        "Your previous response was not valid JSON or was empty. Re-issue "
                        "exactly one tool call with strict JSON. If publishing many candidates "
                        "at once fails, publish fewer at a time."
                    ),
                }
            )
            time.sleep(backoff_seconds(failures, exc.reason))


def _run_region(
    *,
    engine: Engine,
    provider: AgentProvider,
    ctx: RegionJobContext,
    region: DispatchRegion,
    sink: TracePublishSink,
    bus: SharedRunEventBus,
    cancel_event: threading.Event,
    step_budget: int,
) -> RegionResult:
    # Lazy import: analysis_jobs imports this module at load time; these are pure helpers.
    from app.services.agent.analysis_jobs import _activity, _safe_result

    result = RegionResult(name=region.name, status="failed")
    probe = _CancelProbe(engine, ctx.job_id, cancel_event)
    request = _region_request(region, ctx, step_budget)
    context = {
        "system_prompt": ctx.system_prompt,
        "history": [],
        "active_context": {
            "analysis_job_id": ctx.job_id,
            "kind": "trace",
            "repository_id": ctx.repository_id,
            "repository_revision": ctx.code_revision,
            "paper_document_id": ctx.paper_document_id,
            "region": region.name,
            "role": "trace_subagent",
        },
        "environment": ctx.environment,
        "memories": [],
        "skills": [],
        "tool_definitions": tool_definitions("trace", role="subagent"),
    }
    tool_results: list[dict[str, Any]] = []
    seen_calls: dict[str, dict[str, Any]] = {}
    try:
        # One region-long session: everything here is read-only (publishes go through the
        # sink, which opens its own session under the write lock).
        with Session(engine) as session:
            for step_number in range(1, step_budget + 1):
                if probe.should_stop():
                    result.status = "cancelled"
                    result.summary = result.summary or "cancelled before completion"
                    return result
                result.steps_used = step_number
                try:
                    step = _call_provider_with_retry(
                        provider,
                        request,
                        context,
                        tool_results,
                        bus=bus,
                        probe=probe,
                        region_name=region.name,
                        step_number=step_number,
                        step_budget=step_budget,
                    )
                except _RegionCancelled:
                    result.status = "cancelled"
                    result.summary = result.summary or "cancelled before completion"
                    return result
                except AgentProviderFailure as exc:
                    result.status = "failed"
                    result.summary = f"provider_error:{exc.reason}"
                    return result
                result.trace_entries.append(
                    {
                        "type": "subagent_step",
                        "region": region.name,
                        "action": step.action,
                        "tool": step.tool_name,
                    }
                )
                if step.action == "final":
                    result.status = "succeeded"
                    result.summary = (step.answer or "").strip()[:400] or "region finished"
                    return result
                tool_name = step.tool_name or ""
                activity = f"[{region.name}] {_activity(tool_name, step.arguments)}"
                call_key = (
                    tool_name
                    + "|"
                    + json.dumps(step.arguments, sort_keys=True, ensure_ascii=False)[:2000]
                )
                if tool_name in _READ_TOOLS and call_key in seen_calls:
                    tool_results.append(
                        {
                            "tool": tool_name,
                            "ok": True,
                            "reused": True,
                            "result": seen_calls[call_key],
                            "instruction": (
                                "You already retrieved this exact content — do not read it "
                                "again. Publish your confirmed candidates or end with a "
                                "plain-text summary."
                            ),
                        }
                    )
                    continue
                bus.emit(
                    "analysis.tool.started",
                    {
                        "tool_name": tool_name,
                        "activity": activity,
                        "message": activity,
                        "subagent": region.name,
                        "step": step_number,
                        "budget": step_budget,
                    },
                )
                try:
                    outcome = execute_tool(
                        session,
                        ctx.project_id,
                        ctx.repository_id,
                        ctx.paper_document_id,
                        ctx.requested_depth,
                        tool_name,
                        step.arguments,
                    )
                except ValidationError as exc:
                    details = "; ".join(
                        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                        for item in exc.errors()[:8]
                    )
                    tool_results.append(
                        {
                            "tool": tool_name,
                            "ok": False,
                            "error": "invalid_tool_arguments",
                            "details": details[:600],
                            "instruction": "Fix only the fields named in details and retry.",
                        }
                    )
                    bus.emit(
                        "analysis.tool.failed",
                        {
                            "tool_name": tool_name,
                            "code": "invalid_tool_arguments",
                            "subagent": region.name,
                            "step": step_number,
                            "budget": step_budget,
                        },
                    )
                    continue
                except ValueError as exc:
                    error = str(exc)[:240] or "analysis_evidence_invalid"
                    tool_results.append(
                        {
                            "tool": tool_name,
                            "ok": False,
                            "error": error,
                            "instruction": (
                                "Correct the evidence or arguments and retry without guessing."
                            ),
                        }
                    )
                    bus.emit(
                        "analysis.tool.failed",
                        {
                            "tool_name": tool_name,
                            "code": error[:120],
                            "subagent": region.name,
                            "step": step_number,
                            "budget": step_budget,
                        },
                    )
                    continue
                if tool_name == "publish_trace_candidates" and outcome.get("published"):
                    try:
                        publish_result = sink.publish(outcome["payload"], region=region.name)
                    except ValueError as exc:
                        tool_results.append(
                            {
                                "tool": tool_name,
                                "ok": False,
                                "error": str(exc)[:200],
                                "instruction": (
                                    "Fix the flagged evidence and re-publish only the "
                                    "corrected candidates."
                                ),
                            }
                        )
                        bus.emit(
                            "analysis.tool.failed",
                            {
                                "tool_name": tool_name,
                                "code": str(exc)[:120],
                                "subagent": region.name,
                                "step": step_number,
                                "budget": step_budget,
                            },
                        )
                        continue
                    batch = int(publish_result.get("new_links", 0) or 0)
                    result.published_count += batch
                    result.dropped_count += len(outcome.get("dropped", []) or [])
                    result.unresolved.extend(
                        str(item)[:200]
                        for item in outcome["payload"].get("unresolved", []) or []
                    )
                    tool_results.append(
                        {
                            "tool": tool_name,
                            "ok": True,
                            "result": {"published": True, "new_links": batch},
                            "instruction": (
                                "Publish any remaining region candidates, or reply with a "
                                "short plain-text summary to end this region."
                            ),
                        }
                    )
                    bus.emit(
                        "analysis.tool.completed",
                        {
                            "tool_name": tool_name,
                            "activity": activity,
                            "subagent": region.name,
                            "step": step_number,
                            "budget": step_budget,
                            "published": True,
                        },
                    )
                    continue
                safe = _safe_result(tool_name, outcome)
                if tool_name in _READ_TOOLS:
                    seen_calls[call_key] = safe
                tool_results.append({"tool": tool_name, "ok": True, "result": safe})
                bus.emit(
                    "analysis.tool.completed",
                    {
                        "tool_name": tool_name,
                        "activity": activity,
                        "subagent": region.name,
                        "step": step_number,
                        "budget": step_budget,
                        "published": False,
                    },
                )
        # Step budget exhausted: published evidence still counts as a covered region.
        result.status = "succeeded" if result.published_count else "failed"
        result.summary = result.summary or (
            f"published {result.published_count} candidates before the step budget ran out"
            if result.published_count
            else "step budget exhausted without defensible candidates"
        )
        return result
    except Exception as exc:
        logger.exception("trace subagent region %r crashed", region.name)
        result.status = "failed"
        result.summary = f"internal_error:{exc.__class__.__name__}"
        return result


def _update_job_progress(
    engine: Engine,
    write_lock: threading.RLock,
    job_id: str,
    message: str,
) -> None:
    with write_lock:
        with Session(engine) as session:
            job = session.get(AgentAnalysisJob, job_id)
            if job is None or job.status not in {"running", "validating"}:
                return
            job.progress_json = {"message": message, "code": "subagents_running"}
            job.updated_at = utc_now()
            session.add(job)
            session.commit()


def run_trace_subagents(
    *,
    engine: Engine,
    provider: AgentProvider,
    ctx: RegionJobContext,
    regions: list[DispatchRegion],
    sink: TracePublishSink,
    bus: SharedRunEventBus,
    write_lock: threading.RLock,
    parallelism: int,
    step_budget: int,
    wall_seconds: float = DISPATCH_WALL_SECONDS,
) -> DispatchOutcome:
    """Run one dispatch: fan the regions out over a bounded throwaway pool and wait.

    The calling parent thread blocks here (the dispatch is one long tool call). Cancellation
    flows through the job row: region probes see ``cancelling`` within ~2s and the shared
    event stops the rest; the parent loop finalizes at its next step boundary.
    """

    unique: list[DispatchRegion] = []
    seen_names: set[str] = set()
    for region in regions:
        key = region.name.strip().casefold()
        if not key or key in seen_names:
            continue
        seen_names.add(key)
        unique.append(region)
    cancel_event = threading.Event()
    workers = max(1, min(parallelism or 1, len(unique)))
    results: list[RegionResult] = []
    timeout_hit = False
    deadline = time.monotonic() + wall_seconds
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="tracelab-trace-subagent"
    ) as pool:
        futures = {
            pool.submit(
                _run_region,
                engine=engine,
                provider=provider,
                ctx=ctx,
                region=region,
                sink=sink,
                bus=bus,
                cancel_event=cancel_event,
                step_budget=step_budget,
            ): region
            for region in unique
        }
        pending = set(futures)
        while pending:
            done, pending = futures_wait(pending, timeout=0.7, return_when=FIRST_COMPLETED)
            for future in done:
                region = futures[future]
                try:
                    region_result = future.result()
                except Exception:
                    logger.exception("trace subagent region %r raised", region.name)
                    region_result = RegionResult(
                        name=region.name, status="failed", summary="internal_error"
                    )
                if timeout_hit and region_result.status == "cancelled":
                    region_result.status = "timeout"
                results.append(region_result)
                _update_job_progress(
                    engine,
                    write_lock,
                    ctx.job_id,
                    f"并行取证中（{len(results)}/{len(unique)} 区域完成，"
                    f"已发布 {sink.published_count} 条）",
                )
                status_label = _REGION_STATUS_LABEL.get(
                    region_result.status, region_result.status
                )
                bus.emit(
                    "analysis.subagents.progress",
                    {
                        "done": len(results),
                        "total": len(unique),
                        "region": region_result.name,
                        "status": region_result.status,
                        "published": region_result.published_count,
                        "activity": (
                            f"区域「{region_result.name}」{status_label}"
                            f"（{len(results)}/{len(unique)}）"
                        ),
                    },
                )
            if pending and not cancel_event.is_set() and time.monotonic() > deadline:
                timeout_hit = True
                cancel_event.set()
    order = {region.name: index for index, region in enumerate(unique)}
    results.sort(key=lambda item: order.get(item.name, len(order)))
    total_published = sum(item.published_count for item in results)
    tool_payload = {
        "dispatched": True,
        "total_published": total_published,
        "regions": [
            {
                "name": item.name,
                "status": item.status,
                "published_count": item.published_count,
                "dropped_count": item.dropped_count,
                "unresolved": item.unresolved[:20],
                "summary": item.summary[:400],
                "steps_used": item.steps_used,
            }
            for item in results
        ],
        "instruction": (
            "Review coverage using the region summaries; investigate failed/unresolved "
            "regions or publish anything still missing yourself, then call finish_analysis."
        ),
    }
    trace_entries = [entry for item in results for entry in item.trace_entries]
    return DispatchOutcome(
        tool_payload=tool_payload,
        trace_entries=trace_entries,
        regions_used=len(unique),
        total_published=total_published,
        cancelled=cancel_event.is_set() and not timeout_hit,
    )
