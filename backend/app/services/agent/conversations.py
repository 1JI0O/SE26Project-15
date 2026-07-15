from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, func, select

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
    AgentToolEvent,
    AgentTurnRequest,
    AgentTurnResponse,
)
from app.services.agent.memory import capture_explicit_memory, retrieve_memories
from app.services.agent.provider import AgentProvider, AgentProviderFailure
from app.services.agent.service import (
    _create_confirmation,
    _provider_from_settings,
    _safe_citations,
    confirmation_to_read,
    decide_confirmation,
)
from app.services.agent.skills import select_skills, system_prompt
from app.services.agent.tools import (
    READ_TOOLS,
    WRITE_TOOLS,
    SaveCodeArguments,
    build_context_snapshot,
    content_sha256,
    execute_read_tool,
)

MAX_LOOP_STEPS = 10
MAX_PROVIDER_ATTEMPTS = 3
MAX_SAME_TOOL_FAILURES = 2
TRANSIENT_PROVIDER_FAILURES = {
    "llm_timeout",
    "llm_transport_error",
    "llm_rate_limited",
    "llm_upstream_error",
}


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
) -> Any:
    last_failure: AgentProviderFailure | None = None
    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            return provider.next_step(message, context, tool_results)
        except AgentProviderFailure as exc:
            last_failure = exc
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


def _save_preconditions(arguments: dict[str, Any], tool_results: list[dict[str, Any]]) -> list[str]:
    try:
        validated = SaveCodeArguments.model_validate(arguments)
    except ValidationError:
        return []
    target_hash = content_sha256(validated.content)
    completed = {
        item.get("tool")
        for item in tool_results
        if item.get("ok")
        and isinstance(item.get("result"), dict)
        and item["result"].get("path") == validated.path
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
) -> LoopResult:
    trace = list(run.trace_json)
    tool_results = list(initial_tool_results or [])
    tool_events: list[AgentToolEvent] = []
    citations: list[AgentCitation] = []
    failures: Counter[str] = Counter()

    for _step_index in range(MAX_LOOP_STEPS):
        try:
            step = _provider_step(provider, message, context, tool_results, trace)
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
        trace.append(
            {
                "type": "model_step",
                "action": step.action,
                "tool_name": step.tool_name,
                "arguments": step.arguments
                if step.tool_name not in WRITE_TOOLS
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
        if tool_name in READ_TOOLS:
            try:
                result = execute_read_tool(
                    session, conversation.project_id, tool_name, step.arguments
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
            continue

        if tool_name in WRITE_TOOLS:
            if tool_name == "save_code_file":
                missing = _save_preconditions(step.arguments, tool_results)
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
            "allowed_tools": sorted(READ_TOOLS | WRITE_TOOLS),
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

    return LoopResult(
        answer="Agent 达到本轮工具调用上限，已保存当前进度和证据。",
        status="failed",
        tool_events=tool_events,
        citations=citations,
        degraded=True,
        degraded_reason="tool_loop_limit",
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
    skills = select_skills(message, snapshot)
    return {
        "system_prompt": system_prompt(skills),
        "skills": skills,
        "history": _history(
            session,
            conversation.conversation_id,
            exclude_message_id=exclude_message_id,
        ),
        "active_context": snapshot,
        "environment": snapshot.get("environment", {}),
        "memories": memories,
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
                "active_context": payload.context.model_dump(exclude_none=True),
                "skills": [skill["name"] for skill in context["skills"]],
            }
        ],
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


def _latest_user_message(session: Session, conversation_id: str) -> AgentMessage | None:
    return session.exec(
        select(AgentMessage)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role == "user",
        )
        .order_by(AgentMessage.id.desc())
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
    decided = decide_confirmation(session, project_id, confirmation_id, decision)
    if decided is None:
        return None
    if decision == "reject" or decided.status in {"rejected", "expired"}:
        assistant = _add_message(
            session,
            conversation,
            "assistant",
            "已取消该工具操作，未修改项目环境。",
            metadata={"status": decided.status, "confirmation_id": confirmation_id},
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
    latest_user = _latest_user_message(session, conversation_id)
    actual_provider = provider
    degraded_reason: str | None = None
    if actual_provider is None:
        actual_provider, degraded_reason = _provider_from_settings(session)
    if run is None or latest_user is None or actual_provider is None:
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
        latest_user.content,
        active_context,
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
        latest_user.content,
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
