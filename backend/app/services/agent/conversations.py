from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, func, select

from app.core.config import settings
from app.db.session import engine
from app.models.entities import (
    AgentConversation,
    AgentMessage,
    AgentRun,
    AgentToolRequest,
    utc_now,
)
from app.schemas.agent import (
    AgentCitation,
    AgentConfirmationRead,
    AgentContext,
    AgentConversationCreate,
    AgentConversationDecisionResponse,
    AgentConversationDetail,
    AgentConversationRead,
    AgentConversationUpdate,
    AgentMessageRead,
    AgentRunSubmission,
    AgentToolEvent,
    AgentTurnRequest,
    AgentTurnResponse,
)
from app.services import workspace_service
from app.services.agent.capabilities import (
    CapabilityRegistry,
    build_registry,
    select_skills,
    skill_prompt,
)
from app.services.agent.memory import capture_explicit_memory, retrieve_memories
from app.services.agent.provider import AgentProvider, AgentProviderFailure
from app.services.agent.run_events import RunEventEmitter
from app.services.agent.service import (
    _create_confirmation,
    _provider_from_settings,
    _safe_citations,
    confirmation_to_read,
    decide_confirmation,
)
from app.services.agent.tools import (
    SaveCodeArguments,
    build_context_snapshot,
    content_sha256,
    execute_read_tool,
)

MAX_LOOP_STEPS = settings.tracelab_agent_max_loop_steps
MAX_PROVIDER_ATTEMPTS = 3
MAX_SAME_TOOL_FAILURES = 2
TRANSIENT_PROVIDER_FAILURES = {
    "llm_timeout",
    "llm_transport_error",
    "llm_rate_limited",
    "llm_upstream_error",
}
_agent_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tracelab-agent")
EventCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class LoopResult:
    answer: str
    status: str
    citations: list[AgentCitation] = field(default_factory=list)
    tool_events: list[AgentToolEvent] = field(default_factory=list)
    confirmation: AgentToolRequest | None = None
    degraded: bool = False
    degraded_reason: str | None = None


def _conversation_or_none(
    session: Session, project_id: int, conversation_id: str
) -> AgentConversation | None:
    conversation = session.get(AgentConversation, conversation_id)
    if conversation is None or conversation.project_id != project_id:
        return None
    return conversation


def _confirmation_for_message(
    session: Session, message: AgentMessage
) -> AgentConfirmationRead | None:
    confirmation_id = message.metadata_json.get("confirmation_id")
    if not confirmation_id:
        return None
    request = session.exec(
        select(AgentToolRequest).where(AgentToolRequest.confirmation_id == str(confirmation_id))
    ).first()
    return confirmation_to_read(request) if request is not None else None


def message_to_read(session: Session, message: AgentMessage) -> AgentMessageRead:
    metadata = message.metadata_json
    events: list[AgentToolEvent] = []
    for item in metadata.get("tool_events", []):
        try:
            events.append(AgentToolEvent.model_validate(item))
        except ValidationError:
            continue
    citations: list[AgentCitation] = []
    for item in message.citations_json:
        try:
            citations.append(AgentCitation.model_validate(item))
        except ValidationError:
            continue
    return AgentMessageRead(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        project_id=message.project_id,
        role=message.role,
        content=message.content,
        citations=citations,
        tool_events=events,
        degraded=bool(metadata.get("degraded", False)),
        degraded_reason=metadata.get("degraded_reason"),
        run_id=metadata.get("run_id"),
        confirmation=_confirmation_for_message(session, message),
        created_at=message.created_at,
    )


def conversation_to_read(
    session: Session, conversation: AgentConversation
) -> AgentConversationRead:
    count = session.exec(
        select(func.count(AgentMessage.id)).where(
            AgentMessage.conversation_id == conversation.conversation_id
        )
    ).one()
    return AgentConversationRead(
        conversation_id=conversation.conversation_id,
        project_id=conversation.project_id,
        title=conversation.title,
        status=conversation.status,
        summary=conversation.summary,
        message_count=int(count or 0),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def create_conversation(
    session: Session, project_id: int, payload: AgentConversationCreate
) -> AgentConversation:
    conversation = AgentConversation(
        project_id=project_id,
        title=payload.title.strip() or "新对话",
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def list_conversations(
    session: Session, project_id: int, *, include_archived: bool = False
) -> list[AgentConversationRead]:
    statement = select(AgentConversation).where(AgentConversation.project_id == project_id)
    if not include_archived:
        statement = statement.where(AgentConversation.status == "active")
    conversations = session.exec(statement.order_by(AgentConversation.updated_at.desc())).all()
    return [conversation_to_read(session, conversation) for conversation in conversations]


def get_conversation_detail(
    session: Session, project_id: int, conversation_id: str
) -> AgentConversationDetail | None:
    conversation = _conversation_or_none(session, project_id, conversation_id)
    if conversation is None:
        return None
    messages = session.exec(
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation_id)
        .order_by(AgentMessage.id.asc())
    ).all()
    return AgentConversationDetail(
        **conversation_to_read(session, conversation).model_dump(),
        messages=[message_to_read(session, message) for message in messages],
    )


def update_conversation(
    session: Session,
    project_id: int,
    conversation_id: str,
    payload: AgentConversationUpdate,
) -> AgentConversation | None:
    conversation = _conversation_or_none(session, project_id, conversation_id)
    if conversation is None:
        return None
    if payload.title is not None:
        conversation.title = payload.title.strip()
    if payload.status is not None:
        conversation.status = payload.status
    conversation.updated_at = utc_now()
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def _add_message(
    session: Session,
    conversation: AgentConversation,
    role: str,
    content: str,
    *,
    citations: list[AgentCitation] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentMessage:
    message = AgentMessage(
        conversation_id=conversation.conversation_id,
        project_id=conversation.project_id,
        role=role,
        content=content,
        citations_json=[item.model_dump() for item in (citations or [])],
        metadata_json=metadata or {},
    )
    conversation.updated_at = utc_now()
    session.add(message)
    session.add(conversation)
    session.commit()
    session.refresh(message)
    return message


def _history(
    session: Session,
    conversation_id: str,
    *,
    exclude_message_id: str | None = None,
) -> list[dict[str, str]]:
    messages = list(
        session.exec(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.id.desc())
            .limit(30)
        ).all()
    )
    messages.reverse()
    return [
        {"role": message.role, "content": message.content[:8000]}
        for message in messages
        if message.message_id != exclude_message_id and message.role in {"user", "assistant"}
    ]


def _persist_run(session: Session, run: AgentRun, trace: list[dict[str, Any]]) -> None:
    run.trace_json = trace
    run.step_count = len([item for item in trace if item.get("type") == "model_step"])
    run.updated_at = utc_now()
    session.add(run)
    session.commit()


def _provider_step(
    provider: AgentProvider,
    message: str,
    context: dict[str, Any],
    tool_results: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    on_event: EventCallback | None = None,
) -> Any:
    last_failure: AgentProviderFailure | None = None
    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        emitted_text = False

        def emit_attempt_event(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal emitted_text
            if event_type == "message.delta":
                emitted_text = True
            if on_event is not None:
                on_event(event_type, payload)

        try:
            stream_method = getattr(provider, "next_step_stream", None)
            if on_event is not None and callable(stream_method):
                return stream_method(message, context, tool_results, emit_attempt_event)
            return provider.next_step(message, context, tool_results)
        except AgentProviderFailure as exc:
            last_failure = exc
            if emitted_text and on_event is not None:
                on_event(
                    "message.reset",
                    {
                        "reason": (
                            "provider_retry"
                            if exc.reason in TRANSIENT_PROVIDER_FAILURES
                            and attempt < MAX_PROVIDER_ATTEMPTS
                            else "provider_failed"
                        )
                    },
                )
            trace.append(
                {
                    "type": "provider_error",
                    "reason": exc.reason,
                    "attempt": attempt,
                    "recoverable": exc.reason in TRANSIENT_PROVIDER_FAILURES,
                }
            )
            if exc.reason not in TRANSIENT_PROVIDER_FAILURES:
                raise
        except Exception as exc:
            if emitted_text and on_event is not None:
                on_event("message.reset", {"reason": "provider_failed"})
            trace.append(
                {
                    "type": "provider_error",
                    "reason": "llm_provider_error",
                    "attempt": attempt,
                    "exception": exc.__class__.__name__,
                    "recoverable": False,
                }
            )
            raise AgentProviderFailure("llm_provider_error") from exc
    raise last_failure or AgentProviderFailure("llm_provider_error")


def _citation_side(tool_name: str) -> str:
    if "paper" in tool_name:
        return "paper"
    if "trace" in tool_name:
        return "trace"
    if "graph" in tool_name or "architecture" in tool_name:
        return "graph"
    if "memory" in tool_name:
        return "memory"
    if tool_name == "get_project_overview":
        return "project"
    return "code"


def _citations_from_result(tool_name: str, result: dict[str, Any]) -> list[AgentCitation]:
    refs: list[str] = []
    if result.get("ref"):
        refs.append(str(result["ref"]))
    for item in result.get("items", [])[:8] if isinstance(result.get("items"), list) else []:
        if isinstance(item, dict) and item.get("ref"):
            refs.append(str(item["ref"]))
    return [
        AgentCitation(side=_citation_side(tool_name), ref=ref, quote="")
        for ref in dict.fromkeys(refs)
        if ref and not ref.startswith("/") and ".." not in ref
    ][:8]


def _event_result(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "found",
        "ref",
        "path",
        "view",
        "root_symbol",
        "root_label",
        "risk_level",
        "risk_score",
        "changed_lines",
        "caller_count",
        "affected_symbols",
        "affected_traces",
        "recommendations",
        "ui_action",
        "base_sha256",
        "target_sha256",
    }
    return {key: value for key, value in result.items() if key in allowed}


def _safe_tool_summary(tool_name: str, result: dict[str, Any]) -> str:
    if result.get("error"):
        return f"{tool_name}: {result['error']}"
    if result.get("risk_level"):
        return f"风险 {result['risk_level']} · {result.get('changed_lines', 0)} 行变更"
    if result.get("root_label"):
        return f"已读取 {result['root_label']} {result.get('view', '')} 图"
    if result.get("path"):
        return f"已读取 {result['path']}"
    return f"{tool_name} 执行完成"


def _save_preconditions(
    session: Session,
    project_id: int,
    arguments: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> list[str]:
    try:
        validated = SaveCodeArguments.model_validate(arguments)
    except ValidationError:
        return []
    current = workspace_service.get_code_file(session, project_id, validated.path)
    if current is None:
        return ["propose_code_patch", "analyze_change_risk"]
    base_hash = content_sha256(str(current["content"]))
    target_hash = content_sha256(validated.content)
    completed = {
        item.get("tool")
        for item in tool_results
        if item.get("ok")
        and isinstance(item.get("result"), dict)
        and item["result"].get("found") is not False
        and not item["result"].get("error")
        and item["result"].get("path") == validated.path
        and item["result"].get("base_sha256") == base_hash
        and item["result"].get("target_sha256") == target_hash
    }
    return [tool for tool in ("propose_code_patch", "analyze_change_risk") if tool not in completed]


def _run_loop(
    session: Session,
    conversation: AgentConversation,
    run: AgentRun,
    provider: AgentProvider,
    message: str,
    context: dict[str, Any],
    *,
    initial_tool_results: list[dict[str, Any]] | None = None,
    on_event: EventCallback | None = None,
) -> LoopResult:
    trace = list(run.trace_json)
    recovered_results = [
        {key: value for key, value in item.items() if key != "type"}
        for item in trace
        if item.get("type") == "tool_result"
    ]
    tool_results = list(initial_tool_results or recovered_results)
    tool_events: list[AgentToolEvent] = []
    citations: list[AgentCitation] = []
    failures: Counter[str] = Counter()
    duplicate_calls: Counter[str] = Counter()
    successful_calls: dict[str, dict[str, Any]] = {}
    force_synthesis = False
    registry = context.get("_registry")
    if not isinstance(registry, CapabilityRegistry):
        registry = build_registry(session)

    for _step_index in range(MAX_LOOP_STEPS):
        if on_event is not None:
            on_event(
                "reasoning.summary",
                {
                    "summary": (
                        "正在整理已获得的证据并生成结论"
                        if force_synthesis
                        else "正在规划下一步并检查证据缺口"
                    )
                },
            )
        step_context = context
        if force_synthesis:
            step_context = {
                **context,
                "tool_definitions": [],
                "system_prompt": (
                    f"{context.get('system_prompt', '')}\n\n"
                    "Tool collection is complete. Produce the best evidence-grounded final "
                    "answer now. State uncertainty instead of requesting another tool."
                ),
            }
        try:
            step = _provider_step(
                provider,
                message,
                step_context,
                tool_results,
                trace,
                on_event,
            )
        except AgentProviderFailure as exc:
            _persist_run(session, run, trace)
            return LoopResult(
                answer="Agent 模型调用失败，已保留会话和工具执行记录，可稍后重试。",
                status="failed",
                tool_events=tool_events,
                citations=citations,
                degraded=True,
                degraded_reason=exc.reason,
            )
        tool_capability = registry.tool(step.tool_name or "") if step.action == "tool" else None
        trace.append(
            {
                "type": "model_step",
                "action": step.action,
                "tool_name": step.tool_name,
                "arguments": step.arguments
                if tool_capability is None or tool_capability.read_only
                else {"redacted": True},
            }
        )
        _persist_run(session, run, trace)
        if step.action == "final":
            citations.extend(_safe_citations(step.citations))
            return LoopResult(
                answer=step.answer or "任务已完成。",
                status="completed",
                citations=list({(item.side, item.ref): item for item in citations}.values())[:16],
                tool_events=tool_events,
            )

        tool_name = step.tool_name or ""
        call_fingerprint = hashlib.sha256(
            json.dumps(
                [tool_name, step.arguments],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if call_fingerprint in successful_calls:
            duplicate_calls[call_fingerprint] += 1
            cached = successful_calls[call_fingerprint]
            reused = {
                "tool": tool_name,
                "ok": True,
                "cached": True,
                "result": cached,
                "instruction": "Use this existing evidence; do not request it again.",
            }
            tool_results.append(reused)
            trace.append({"type": "tool_result", **reused})
            tool_events.append(
                AgentToolEvent(
                    tool_name=tool_name,
                    status="succeeded",
                    summary=f"已复用证据 · {_safe_tool_summary(tool_name, cached)}",
                    result=_event_result(cached),
                )
            )
            if on_event is not None:
                on_event(
                    "tool.reused",
                    {
                        "tool_name": tool_name,
                        "summary": _safe_tool_summary(tool_name, cached),
                    },
                )
            if duplicate_calls[call_fingerprint] >= 2:
                force_synthesis = True
            _persist_run(session, run, trace)
            continue
        if force_synthesis and step.action == "tool":
            return LoopResult(
                answer="已根据当前证据完成本轮分析；未继续重复读取相同环境。",
                status="completed",
                tool_events=tool_events,
                citations=citations,
                degraded=True,
                degraded_reason="forced_synthesis",
            )
        if tool_capability is not None and tool_capability.read_only:
            if on_event is not None:
                on_event(
                    "tool.started",
                    {"tool_name": tool_name, "summary": f"正在执行 {tool_name}"},
                )
            try:
                if tool_capability.source == "builtin":
                    result = execute_read_tool(
                        session,
                        conversation.project_id,
                        tool_name,
                        step.arguments,
                    )
                else:
                    result = registry.execute(
                        session,
                        conversation.project_id,
                        tool_name,
                        step.arguments,
                    )
            except (ValueError, ValidationError) as exc:
                key = f"{tool_name}:{exc}"
                failures[key] += 1
                failed = {
                    "tool": tool_name,
                    "ok": False,
                    "error": str(exc) or "invalid_tool_arguments",
                    "instruction": (
                        "Correct the arguments and do not repeat the same call unchanged."
                    ),
                }
                tool_results.append(failed)
                trace.append({"type": "tool_result", **failed})
                tool_events.append(
                    AgentToolEvent(
                        tool_name=tool_name,
                        status="failed",
                        summary=_safe_tool_summary(tool_name, failed),
                        result={"error": failed["error"]},
                    )
                )
                _persist_run(session, run, trace)
                if on_event is not None:
                    on_event(
                        "tool.failed",
                        {"tool_name": tool_name, "summary": failed["error"]},
                    )
                if failures[key] > MAX_SAME_TOOL_FAILURES:
                    return LoopResult(
                        answer="工具参数连续失败，Agent 已停止本轮以避免无效循环。",
                        status="failed",
                        tool_events=tool_events,
                        citations=citations,
                        degraded=True,
                        degraded_reason="repeated_tool_failure",
                    )
                continue
            except Exception as exc:
                key = f"{tool_name}:tool_execution_error"
                failures[key] += 1
                failed = {
                    "tool": tool_name,
                    "ok": False,
                    "error": "tool_execution_error",
                    "failure_type": exc.__class__.__name__,
                    "instruction": (
                        "The tool failed internally. Use another evidence source or retry with "
                        "a narrower valid request."
                    ),
                }
                tool_results.append(failed)
                trace.append({"type": "tool_result", **failed})
                tool_events.append(
                    AgentToolEvent(
                        tool_name=tool_name,
                        status="failed",
                        summary=_safe_tool_summary(tool_name, failed),
                        result={"error": failed["error"]},
                    )
                )
                _persist_run(session, run, trace)
                if on_event is not None:
                    on_event(
                        "tool.failed",
                        {"tool_name": tool_name, "summary": failed["error"]},
                    )
                if failures[key] > MAX_SAME_TOOL_FAILURES:
                    return LoopResult(
                        answer="工具连续执行失败，Agent 已保留运行记录并停止本轮。",
                        status="failed",
                        tool_events=tool_events,
                        citations=citations,
                        degraded=True,
                        degraded_reason="repeated_tool_execution_failure",
                    )
                continue
            successful = {"tool": tool_name, "ok": True, "result": result}
            successful_calls[call_fingerprint] = result
            tool_results.append(successful)
            trace.append({"type": "tool_result", **successful})
            citations.extend(_citations_from_result(tool_name, result))
            tool_events.append(
                AgentToolEvent(
                    tool_name=tool_name,
                    status="succeeded",
                    summary=_safe_tool_summary(tool_name, result),
                    result=_event_result(result),
                )
            )
            _persist_run(session, run, trace)
            if on_event is not None:
                on_event(
                    "tool.completed",
                    {
                        "tool_name": tool_name,
                        "summary": _safe_tool_summary(tool_name, result),
                        "result": _event_result(result),
                    },
                )
            continue

        if tool_capability is not None and not tool_capability.read_only:
            if tool_name == "save_code_file":
                missing = _save_preconditions(
                    session,
                    conversation.project_id,
                    step.arguments,
                    tool_results,
                )
                if missing:
                    feedback = {
                        "tool": tool_name,
                        "ok": False,
                        "error": "write_preconditions_missing",
                        "required_tools": missing,
                        "instruction": (
                            "Run every required read tool before proposing save_code_file again."
                        ),
                    }
                    tool_results.append(feedback)
                    trace.append({"type": "tool_result", **feedback})
                    _persist_run(session, run, trace)
                    continue
            try:
                confirmation = _create_confirmation(
                    session,
                    conversation.project_id,
                    tool_name,
                    step.arguments,
                    conversation_id=conversation.conversation_id,
                    run_id=run.run_id,
                )
            except (ValueError, ValidationError) as exc:
                key = f"{tool_name}:{exc}"
                failures[key] += 1
                feedback = {
                    "tool": tool_name,
                    "ok": False,
                    "error": str(exc) or "invalid_tool_arguments",
                    "instruction": "Re-read current state, correct arguments, and retry.",
                }
                tool_results.append(feedback)
                trace.append({"type": "tool_result", **feedback})
                _persist_run(session, run, trace)
                if failures[key] > MAX_SAME_TOOL_FAILURES:
                    return LoopResult(
                        answer="写工具提案连续无效，未创建确认请求。",
                        status="failed",
                        tool_events=tool_events,
                        citations=citations,
                        degraded=True,
                        degraded_reason="repeated_write_validation_failure",
                    )
                continue
            except Exception as exc:
                feedback = {
                    "tool": tool_name,
                    "ok": False,
                    "error": "write_preparation_failed",
                    "failure_type": exc.__class__.__name__,
                    "instruction": "Re-read the target state before preparing another write.",
                }
                tool_results.append(feedback)
                trace.append({"type": "tool_result", **feedback})
                _persist_run(session, run, trace)
                continue
            tool_events.append(
                AgentToolEvent(
                    tool_name=tool_name,
                    status="pending_confirmation",
                    summary="等待用户确认",
                    result=confirmation.parameter_summary_json,
                )
            )
            trace.append(
                {
                    "type": "tool_confirmation",
                    "tool": tool_name,
                    "confirmation_id": confirmation.confirmation_id,
                    "status": confirmation.status,
                }
            )
            _persist_run(session, run, trace)
            return LoopResult(
                answer=step.answer or "已准备好写操作，请确认后继续执行。",
                status="waiting_confirmation",
                citations=list({(item.side, item.ref): item for item in citations}.values())[:16],
                tool_events=tool_events,
                confirmation=confirmation,
            )

        key = f"unknown:{tool_name}"
        failures[key] += 1
        feedback = {
            "tool": tool_name,
            "ok": False,
            "error": "unknown_or_unauthorized_tool",
            "allowed_tools": sorted(tool.name for tool in registry.enabled_tools()),
        }
        tool_results.append(feedback)
        trace.append({"type": "tool_result", **feedback})
        _persist_run(session, run, trace)
        if failures[key] > MAX_SAME_TOOL_FAILURES:
            return LoopResult(
                answer="Agent 连续请求未授权工具，本轮已终止。",
                status="failed",
                tool_events=tool_events,
                citations=citations,
                degraded=True,
                degraded_reason="unknown_tool",
            )

    final_context = {
        **context,
        "tool_definitions": [],
        "system_prompt": (
            f"{context.get('system_prompt', '')}\n\n"
            "The tool budget is exhausted. Synthesize a final answer from collected evidence. "
            "Do not request tools. Explicitly identify uncertainty."
        ),
    }
    tool_results.append(
        {
            "tool": "runtime",
            "ok": True,
            "result": {"instruction": "tool_budget_exhausted; synthesize_now"},
        }
    )
    try:
        final_step = _provider_step(
            provider,
            message,
            final_context,
            tool_results,
            trace,
            on_event,
        )
        if final_step.action == "final" and final_step.answer:
            return LoopResult(
                answer=final_step.answer,
                status="completed",
                tool_events=tool_events,
                citations=citations,
                degraded=True,
                degraded_reason="tool_budget_synthesized",
            )
    except AgentProviderFailure:
        pass
    return LoopResult(
        answer="已达到本轮工具预算。以上结果基于已收集证据，未完成部分已保留在运行记录中。",
        status="completed",
        tool_events=tool_events,
        citations=citations,
        degraded=True,
        degraded_reason="tool_budget_exhausted",
    )


def _finish_run(session: Session, run: AgentRun, result: LoopResult) -> None:
    run.status = result.status
    run.degraded_reason = result.degraded_reason
    run.updated_at = utc_now()
    if result.status != "waiting_confirmation":
        run.completed_at = run.updated_at
    session.add(run)
    session.commit()


def _refresh_summary(session: Session, conversation: AgentConversation) -> None:
    messages = list(
        session.exec(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.conversation_id)
            .order_by(AgentMessage.id.desc())
            .limit(8)
        ).all()
    )
    messages.reverse()
    conversation.summary = "\n".join(
        f"{message.role}: {' '.join(message.content.split())[:280]}" for message in messages
    )[-2400:]
    conversation.updated_at = utc_now()
    session.add(conversation)
    session.commit()


def _context_for_turn(
    session: Session,
    conversation: AgentConversation,
    message: str,
    active_context: AgentContext,
    *,
    exclude_message_id: str | None = None,
) -> dict[str, Any]:
    snapshot = build_context_snapshot(session, conversation.project_id, active_context)
    memories = retrieve_memories(session, conversation.project_id, message)
    registry = build_registry(session)
    selected_skills = select_skills(registry, message, snapshot)
    preferred_tools = {
        tool_name
        for skill in selected_skills
        for tool_name in skill.preferred_tools
    }
    skills = [
        {
            "name": skill.name,
            "description": skill.description,
            "preferred_tools": list(skill.preferred_tools),
            "instructions": skill.instructions,
        }
        for skill in selected_skills
    ]
    return {
        "system_prompt": skill_prompt(selected_skills),
        "skills": skills,
        "tool_definitions": registry.tool_definitions(preferred_tools),
        "capability_snapshot": registry.snapshot(selected_skills),
        "history": _history(
            session,
            conversation.conversation_id,
            exclude_message_id=exclude_message_id,
        ),
        "active_context": snapshot,
        "environment": snapshot.get("environment", {}),
        "memories": memories,
        "_registry": registry,
    }


def run_conversation_turn(
    session: Session,
    project_id: int,
    conversation_id: str,
    payload: AgentTurnRequest,
    *,
    provider: AgentProvider | None = None,
) -> AgentTurnResponse | None:
    conversation = _conversation_or_none(session, project_id, conversation_id)
    if conversation is None or conversation.status != "active":
        return None
    user_message = _add_message(session, conversation, "user", payload.message.strip())
    if conversation.title == "新对话":
        conversation.title = " ".join(payload.message.strip().split())[:36]
        session.add(conversation)
        session.commit()
    context = _context_for_turn(
        session,
        conversation,
        payload.message,
        payload.context,
        exclude_message_id=user_message.message_id,
    )
    actual_provider = provider
    degraded_reason: str | None = None
    if actual_provider is None:
        actual_provider, degraded_reason = _provider_from_settings(session)
    run = AgentRun(
        conversation_id=conversation_id,
        project_id=project_id,
        provider_name=actual_provider.provider_name if actual_provider else "",
        model_name=actual_provider.model_name if actual_provider else "",
        trace_json=[
            {
                "type": "run_context",
                "user_message_id": user_message.message_id,
                "active_context": payload.context.model_dump(exclude_none=True),
                "skills": [skill["name"] for skill in context["skills"]],
            }
        ],
        capability_snapshot_json=context["capability_snapshot"],
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    if actual_provider is None:
        result = LoopResult(
            answer="LLM 当前不可用。会话和上下文已经保存，配置 Agent API 后可继续对话。",
            status="failed",
            degraded=True,
            degraded_reason=degraded_reason,
        )
    else:
        result = _run_loop(
            session,
            conversation,
            run,
            actual_provider,
            payload.message,
            context,
        )
    _finish_run(session, run, result)
    metadata = {
        "run_id": run.run_id,
        "status": result.status,
        "degraded": result.degraded,
        "degraded_reason": result.degraded_reason,
        "tool_events": [event.model_dump() for event in result.tool_events],
        "skills": [skill["name"] for skill in context["skills"]],
    }
    if result.confirmation is not None:
        metadata["confirmation_id"] = result.confirmation.confirmation_id
    assistant = _add_message(
        session,
        conversation,
        "assistant",
        result.answer,
        citations=result.citations,
        metadata=metadata,
    )
    capture_explicit_memory(session, project_id, conversation_id, payload.message.strip())
    _refresh_summary(session, conversation)
    return AgentTurnResponse(
        conversation=conversation_to_read(session, conversation),
        user_message=message_to_read(session, user_message),
        assistant_message=message_to_read(session, assistant),
        run_id=run.run_id,
        status=result.status,
        confirmation=confirmation_to_read(result.confirmation) if result.confirmation else None,
    )


def submit_conversation_turn(
    session: Session,
    project_id: int,
    conversation_id: str,
    payload: AgentTurnRequest,
) -> AgentRunSubmission | None:
    conversation = _conversation_or_none(session, project_id, conversation_id)
    if conversation is None or conversation.status != "active":
        return None
    user_message = _add_message(session, conversation, "user", payload.message.strip())
    if conversation.title == "新对话":
        conversation.title = " ".join(payload.message.strip().split())[:36]
        session.add(conversation)
        session.commit()
    run = AgentRun(
        conversation_id=conversation_id,
        project_id=project_id,
        status="queued",
        trace_json=[
            {
                "type": "run_context",
                "user_message_id": user_message.message_id,
                "active_context": payload.context.model_dump(exclude_none=True),
            }
        ],
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    RunEventEmitter(session, run).emit("run.queued", {"status": "queued"})
    _agent_executor.submit(_execute_submitted_run, run.run_id)
    return AgentRunSubmission(
        conversation=conversation_to_read(session, conversation),
        user_message=message_to_read(session, user_message),
        run_id=run.run_id,
        status="queued",
    )


def _execute_submitted_run(run_id: str) -> None:
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        existing_messages = session.exec(
            select(AgentMessage).where(
                AgentMessage.conversation_id == run.conversation_id,
                AgentMessage.role == "assistant",
            )
        ).all()
        existing = next(
            (
                item
                for item in existing_messages
                if item.metadata_json.get("run_id") == run.run_id
            ),
            None,
        )
        if existing is not None:
            run.status = str(existing.metadata_json.get("status") or "completed")
            run.degraded_reason = existing.metadata_json.get("degraded_reason")
            run.updated_at = utc_now()
            if run.status != "waiting_confirmation":
                run.completed_at = run.updated_at
            session.add(run)
            session.commit()
            return
        conversation = session.get(AgentConversation, run.conversation_id)
        context_entry = next(
            (item for item in run.trace_json if item.get("type") == "run_context"),
            {},
        )
        user_message_id = str(context_entry.get("user_message_id", ""))
        user_message = session.exec(
            select(AgentMessage).where(AgentMessage.message_id == user_message_id)
        ).first()
        if conversation is None or user_message is None:
            run.status = "failed"
            run.degraded_reason = "run_context_missing"
            run.completed_at = utc_now()
            session.add(run)
            session.commit()
            return
        emitter = RunEventEmitter(session, run)

        pending_confirmation = session.exec(
            select(AgentToolRequest)
            .where(
                AgentToolRequest.run_id == run.run_id,
                AgentToolRequest.status == "pending",
            )
            .order_by(AgentToolRequest.id.desc())
        ).first()
        if pending_confirmation is not None:
            run.status = "waiting_confirmation"
            run.updated_at = utc_now()
            session.add(run)
            session.commit()
            assistant = _add_message(
                session,
                conversation,
                "assistant",
                "写操作已准备完成，请确认后继续执行。",
                metadata={
                    "run_id": run.run_id,
                    "status": "waiting_confirmation",
                    "confirmation_id": pending_confirmation.confirmation_id,
                    "tool_events": [
                        AgentToolEvent(
                            tool_name=pending_confirmation.tool_name,
                            status="pending_confirmation",
                            summary="等待用户确认",
                            result=pending_confirmation.parameter_summary_json,
                        ).model_dump()
                    ],
                },
            )
            _refresh_summary(session, conversation)
            emitter.emit(
                "message.completed",
                {"message_id": assistant.message_id, "status": "waiting_confirmation"},
            )
            emitter.emit("run.completed", {"status": "waiting_confirmation"})
            return

        def emit(event_type: str, payload: dict[str, Any]) -> None:
            try:
                emitter.emit(event_type, payload)
            except Exception:
                session.rollback()

        try:
            run.status = "running"
            run.updated_at = utc_now()
            session.add(run)
            session.commit()
            emit("run.started", {"status": "running"})
            active_context = AgentContext.model_validate(context_entry.get("active_context", {}))
            context = _context_for_turn(
                session,
                conversation,
                user_message.content,
                active_context,
                exclude_message_id=user_message.message_id,
            )
            run.capability_snapshot_json = context["capability_snapshot"]
            provider, degraded_reason = _provider_from_settings(session)
            if provider is None:
                result = LoopResult(
                    answer=(
                        "LLM 当前不可用。会话和上下文已经保存，配置 Agent API 后可继续对话。"
                    ),
                    status="failed",
                    degraded=True,
                    degraded_reason=degraded_reason,
                )
            else:
                run.provider_name = provider.provider_name
                run.model_name = provider.model_name
                session.add(run)
                session.commit()
                result = _run_loop(
                    session,
                    conversation,
                    run,
                    provider,
                    user_message.content,
                    context,
                    on_event=emit,
                )
            _finish_run(session, run, result)
            metadata = {
                "run_id": run.run_id,
                "status": result.status,
                "degraded": result.degraded,
                "degraded_reason": result.degraded_reason,
                "tool_events": [event.model_dump() for event in result.tool_events],
                "skills": [skill["name"] for skill in context.get("skills", [])],
            }
            if result.confirmation is not None:
                metadata["confirmation_id"] = result.confirmation.confirmation_id
            assistant = _add_message(
                session,
                conversation,
                "assistant",
                result.answer,
                citations=result.citations,
                metadata=metadata,
            )
            capture_explicit_memory(
                session,
                run.project_id,
                conversation.conversation_id,
                user_message.content,
            )
            _refresh_summary(session, conversation)
            emit(
                "message.completed",
                {
                    "message_id": assistant.message_id,
                    "status": result.status,
                    "degraded": result.degraded,
                    "degraded_reason": result.degraded_reason,
                },
            )
            emit("run.completed", {"status": result.status})
        except Exception as exc:
            session.rollback()
            run = session.get(AgentRun, run_id)
            conversation = session.get(AgentConversation, run.conversation_id) if run else None
            if run is None or conversation is None:
                return
            run.status = "failed"
            run.degraded_reason = "agent_runtime_error"
            run.completed_at = utc_now()
            run.updated_at = run.completed_at
            session.add(run)
            session.commit()
            _add_message(
                session,
                conversation,
                "assistant",
                "Agent 运行发生内部错误，已保存当前进度，可重新发起本轮任务。",
                metadata={
                    "run_id": run.run_id,
                    "status": "failed",
                    "degraded": True,
                    "degraded_reason": "agent_runtime_error",
                },
            )
            emitter = RunEventEmitter(session, run)
            emitter.emit(
                "run.failed",
                {"status": "failed", "failure_type": exc.__class__.__name__},
            )


def recover_agent_runs() -> int:
    with Session(engine) as session:
        run_ids = list(
            session.exec(
                select(AgentRun.run_id).where(AgentRun.status.in_(["queued", "running"]))
            ).all()
        )
    for run_id in run_ids:
        _agent_executor.submit(_execute_submitted_run, run_id)
    return len(run_ids)


def _user_message_for_run(session: Session, run: AgentRun) -> AgentMessage | None:
    context_entry = next(
        (item for item in run.trace_json if item.get("type") == "run_context"),
        {},
    )
    message_id = str(context_entry.get("user_message_id", ""))
    if not message_id:
        return None
    return session.exec(
        select(AgentMessage).where(
            AgentMessage.message_id == message_id,
            AgentMessage.conversation_id == run.conversation_id,
            AgentMessage.project_id == run.project_id,
            AgentMessage.role == "user",
        )
    ).first()


def decide_conversation_confirmation(
    session: Session,
    project_id: int,
    conversation_id: str,
    confirmation_id: str,
    decision: str,
    *,
    provider: AgentProvider | None = None,
) -> AgentConversationDecisionResponse | None:
    conversation = _conversation_or_none(session, project_id, conversation_id)
    if conversation is None:
        return None
    request = session.exec(
        select(AgentToolRequest).where(
            AgentToolRequest.project_id == project_id,
            AgentToolRequest.conversation_id == conversation_id,
            AgentToolRequest.confirmation_id == confirmation_id,
        )
    ).first()
    if request is None:
        return None
    if request.status in {"rejected", "expired", "executed", "failed"}:
        messages = session.exec(
            select(AgentMessage)
            .where(
                AgentMessage.conversation_id == conversation_id,
                AgentMessage.role == "assistant",
            )
            .order_by(AgentMessage.id.desc())
        ).all()
        assistant = next(
            (
                message
                for message in messages
                if message.metadata_json.get("decision_confirmation_id") == confirmation_id
            ),
            None,
        )
        return AgentConversationDecisionResponse(
            confirmation=confirmation_to_read(request),
            assistant_message=message_to_read(session, assistant) if assistant else None,
            run_id=request.run_id,
            status=request.status,
        )
    decided = decide_confirmation(session, project_id, confirmation_id, decision)
    if decided is None:
        return None
    if decision == "reject" or decided.status in {"rejected", "expired"}:
        run = session.get(AgentRun, decided.run_id) if decided.run_id else None
        if run is not None:
            trace = list(run.trace_json)
            trace.append(
                {
                    "type": "confirmation_decision",
                    "confirmation_id": confirmation_id,
                    "status": decided.status,
                }
            )
            run.trace_json = trace
            run.status = "completed"
            run.degraded_reason = f"confirmation_{decided.status}"
            run.updated_at = utc_now()
            run.completed_at = run.updated_at
            session.add(run)
            session.commit()
        assistant = _add_message(
            session,
            conversation,
            "assistant",
            "已取消该工具操作，未修改项目环境。",
            metadata={
                "status": decided.status,
                "confirmation_id": confirmation_id,
                "decision_confirmation_id": confirmation_id,
            },
        )
        _refresh_summary(session, conversation)
        return AgentConversationDecisionResponse(
            confirmation=confirmation_to_read(decided),
            assistant_message=message_to_read(session, assistant),
            run_id=decided.run_id,
            status=decided.status,
        )

    result_payload = decided.result_json or {"error": decided.error_summary or "tool_failed"}
    _add_message(
        session,
        conversation,
        "tool",
        json.dumps(result_payload, ensure_ascii=False),
        metadata={
            "tool_name": decided.tool_name,
            "status": decided.status,
            "confirmation_id": confirmation_id,
        },
    )
    run = session.get(AgentRun, decided.run_id) if decided.run_id else None
    run_user = _user_message_for_run(session, run) if run is not None else None
    if run is not None:
        trace = list(run.trace_json)
        trace.extend(
            [
                {
                    "type": "confirmation_decision",
                    "confirmation_id": confirmation_id,
                    "status": decided.status,
                },
                {
                    "type": "tool_result",
                    "tool": decided.tool_name,
                    "ok": decided.status == "executed",
                    "result": result_payload,
                    "confirmed": True,
                },
            ]
        )
        _persist_run(session, run, trace)
    actual_provider = provider
    degraded_reason: str | None = None
    if actual_provider is None:
        actual_provider, degraded_reason = _provider_from_settings(session)
    if run is None or run_user is None or actual_provider is None:
        if run is not None:
            run.status = "failed" if actual_provider is None else "completed"
            run.degraded_reason = degraded_reason or "run_context_missing"
            run.updated_at = utc_now()
            run.completed_at = run.updated_at
            session.add(run)
            session.commit()
        assistant = _add_message(
            session,
            conversation,
            "assistant",
            "工具操作已执行。"
            if decided.status == "executed"
            else "工具执行失败，请检查错误后重试。",
            metadata={
                "status": decided.status,
                "degraded": actual_provider is None,
                "degraded_reason": degraded_reason,
                "confirmation_id": confirmation_id,
                "decision_confirmation_id": confirmation_id,
            },
        )
        _refresh_summary(session, conversation)
        return AgentConversationDecisionResponse(
            confirmation=confirmation_to_read(decided),
            assistant_message=message_to_read(session, assistant),
            run_id=decided.run_id,
            status=decided.status,
        )

    context_entry = next((item for item in run.trace_json if item.get("type") == "run_context"), {})
    active_context = AgentContext.model_validate(context_entry.get("active_context", {}))
    context = _context_for_turn(
        session,
        conversation,
        run_user.content,
        active_context,
        exclude_message_id=run_user.message_id,
    )
    run.status = "running"
    run.completed_at = None
    session.add(run)
    session.commit()
    loop_result = _run_loop(
        session,
        conversation,
        run,
        actual_provider,
        run_user.content,
        context,
        initial_tool_results=[
            {
                "tool": decided.tool_name,
                "ok": decided.status == "executed",
                "result": result_payload,
                "confirmed": True,
            }
        ],
    )
    _finish_run(session, run, loop_result)
    metadata = {
        "run_id": run.run_id,
        "status": loop_result.status,
        "degraded": loop_result.degraded,
        "degraded_reason": loop_result.degraded_reason,
        "tool_events": [event.model_dump() for event in loop_result.tool_events],
        "decision_confirmation_id": confirmation_id,
    }
    if loop_result.confirmation:
        metadata["confirmation_id"] = loop_result.confirmation.confirmation_id
    assistant = _add_message(
        session,
        conversation,
        "assistant",
        loop_result.answer,
        citations=loop_result.citations,
        metadata=metadata,
    )
    _refresh_summary(session, conversation)
    return AgentConversationDecisionResponse(
        confirmation=confirmation_to_read(decided),
        assistant_message=message_to_read(session, assistant),
        run_id=run.run_id,
        status=loop_result.status,
    )
