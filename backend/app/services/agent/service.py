from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import AgentToolRequest, TraceLink, utc_now
from app.schemas.agent import (
    AgentCitation,
    AgentConfirmationRead,
    AgentQueryRequest,
    AgentQueryResponse,
)
from app.services import workspace_service
from app.services.agent.provider import (
    AgentProvider,
    AgentProviderFailure,
    CompatibleAgentProvider,
)
from app.services.agent.tools import (
    READ_TOOLS,
    WRITE_TOOLS,
    RerunAnalysisArguments,
    SaveCodeArguments,
    UpdateTraceArguments,
    build_context_snapshot,
    content_sha256,
    execute_read_tool,
    latest_code,
    prepare_write_request,
    validate_tool_arguments,
)
from app.services.tracing.lifecycle import record_artifact_revision_change

AnalysisEnqueuer = Callable[[int, list[str], str], dict[str, Any]]
_analysis_enqueuer: AnalysisEnqueuer | None = None


class ToolExecutionError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def register_analysis_enqueuer(enqueuer: AnalysisEnqueuer) -> None:
    """Integration hook owned by the repository analysis module."""

    global _analysis_enqueuer
    _analysis_enqueuer = enqueuer


def confirmation_to_read(request: AgentToolRequest) -> AgentConfirmationRead:
    return AgentConfirmationRead(
        confirmation_id=request.confirmation_id,
        project_id=request.project_id,
        tool_name=request.tool_name,
        parameter_summary=request.parameter_summary_json,
        status=request.status,
        user_decision=request.user_decision,
        result=request.result_json,
        error_summary=request.error_summary,
        expires_at=request.expires_at,
        created_at=request.created_at,
        decided_at=request.decided_at,
        executed_at=request.executed_at,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _expire_if_needed(session: Session, request: AgentToolRequest) -> None:
    if request.status == "pending" and _aware(request.expires_at) <= utc_now():
        request.status = "expired"
        request.error_summary = "confirmation_expired"
        session.add(request)
        session.commit()
        session.refresh(request)


def read_confirmation(
    session: Session, project_id: int, confirmation_id: str
) -> AgentToolRequest | None:
    request = session.exec(
        select(AgentToolRequest).where(
            AgentToolRequest.project_id == project_id,
            AgentToolRequest.confirmation_id == confirmation_id,
        )
    ).first()
    if request is not None:
        _expire_if_needed(session, request)
    return request


def _create_confirmation(
    session: Session,
    project_id: int,
    tool_name: str,
    arguments: dict[str, Any],
) -> AgentToolRequest:
    private_arguments, summary = prepare_write_request(
        session, project_id, tool_name, arguments
    )
    request = AgentToolRequest(
        project_id=project_id,
        tool_name=tool_name,
        private_arguments_json=private_arguments,
        parameter_summary_json=summary,
        expires_at=utc_now()
        + timedelta(seconds=settings.tracelab_agent_confirmation_ttl_seconds),
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def _provider_from_settings() -> tuple[AgentProvider | None, str | None]:
    if not settings.tracelab_llm_enabled:
        return None, "llm_disabled"
    key = settings.tracelab_llm_api_key.get_secret_value()
    if not settings.tracelab_llm_base_url or not key or not settings.tracelab_llm_model:
        return None, "llm_not_configured"
    return (
        CompatibleAgentProvider(
            settings.tracelab_llm_base_url,
            key,
            settings.tracelab_llm_model,
            settings.tracelab_llm_timeout_seconds,
        ),
        None,
    )


def _safe_citations(raw: list[dict[str, str]]) -> list[AgentCitation]:
    citations: list[AgentCitation] = []
    for item in raw:
        ref = str(item.get("ref", ""))
        if not ref or ref.startswith("/") or ".." in ref:
            continue
        try:
            citations.append(AgentCitation.model_validate(item))
        except ValidationError:
            continue
    return citations


def query_agent(
    session: Session,
    project_id: int,
    payload: AgentQueryRequest,
    *,
    provider: AgentProvider | None = None,
) -> AgentQueryResponse:
    context = build_context_snapshot(session, project_id, payload.context)
    actual_provider = provider
    degraded_reason: str | None = None
    if actual_provider is None:
        actual_provider, degraded_reason = _provider_from_settings()
    if actual_provider is None:
        return AgentQueryResponse(
            answer="LLM 当前不可用；未执行或提出任何写操作。",
            degraded=True,
            degraded_reason=degraded_reason,
        )

    tool_results: list[dict[str, Any]] = []
    for _ in range(4):
        try:
            step = actual_provider.next_step(payload.message, context, tool_results)
        except AgentProviderFailure as exc:
            return AgentQueryResponse(
                answer="Agent 模型调用失败；未执行或提出任何写操作。",
                degraded=True,
                degraded_reason=exc.reason,
            )
        except Exception:
            return AgentQueryResponse(
                answer="Agent provider 发生安全降级；未执行任何写操作。",
                degraded=True,
                degraded_reason="llm_provider_error",
            )
        if step.action == "final":
            return AgentQueryResponse(
                answer=step.answer,
                citations=_safe_citations(step.citations),
            )
        if step.tool_name in READ_TOOLS:
            try:
                result = execute_read_tool(
                    session, project_id, step.tool_name, step.arguments
                )
            except (ValueError, ValidationError):
                return AgentQueryResponse(
                    answer="Agent 提出的只读工具参数无效。",
                    degraded=True,
                    degraded_reason="invalid_tool_arguments",
                )
            tool_results.append({"tool": step.tool_name, "result": result})
            continue
        if step.tool_name in WRITE_TOOLS:
            try:
                confirmation = _create_confirmation(
                    session, project_id, step.tool_name, step.arguments
                )
            except (ValueError, ValidationError):
                return AgentQueryResponse(
                    answer="Agent 提出的写工具参数无效，未创建确认请求。",
                    degraded=True,
                    degraded_reason="invalid_tool_arguments",
                )
            return AgentQueryResponse(
                answer=step.answer or "该写操作需要用户确认后才能执行。",
                citations=_safe_citations(step.citations),
                confirmation=confirmation_to_read(confirmation),
            )
        return AgentQueryResponse(
            answer="Agent 请求了未授权工具，已拒绝。",
            degraded=True,
            degraded_reason="unknown_tool",
        )
    return AgentQueryResponse(
        answer="Agent 达到本轮只读工具调用上限，未执行写操作。",
        degraded=True,
        degraded_reason="tool_loop_limit",
    )


def _execute_save_code(
    session: Session, request: AgentToolRequest, arguments: SaveCodeArguments
) -> dict[str, Any]:
    current = workspace_service.get_code_file(session, request.project_id, arguments.path)
    if current is None:
        raise ToolExecutionError("code_file_not_found_or_not_editable")
    current_content = str(current["content"])
    current_hash = content_sha256(current_content)
    target_hash = content_sha256(arguments.content)
    if current_hash != arguments.base_sha256 and current_hash != target_hash:
        raise ToolExecutionError("base_content_changed")
    repository = latest_code(session, request.project_id)
    if repository is None:
        raise ToolExecutionError("code_repository_not_found")
    if current_hash != target_hash:
        workspace_service.save_code_file(
            session, request.project_id, arguments.path, arguments.content
        )
    stale_count = record_artifact_revision_change(
        session,
        request.project_id,
        "code",
        repository.id or 0,
        "agent_code_save",
    )
    session.commit()
    return {
        "path": arguments.path,
        "status": "saved",
        "target_sha256": target_hash,
        "repository_revision": repository.revision,
        "stale_trace_count": stale_count,
    }


def _execute_update_trace(
    session: Session, request: AgentToolRequest, arguments: UpdateTraceArguments
) -> dict[str, Any]:
    link = session.exec(
        select(TraceLink).where(
            TraceLink.project_id == request.project_id,
            TraceLink.trace_id == arguments.trace_id,
        )
    ).first()
    if link is None:
        raise ToolExecutionError("trace_not_found")
    if link.status == arguments.status:
        return {"trace_id": arguments.trace_id, "status": arguments.status}
    if link.status != "proposed":
        raise ToolExecutionError("trace_not_proposed")
    link.status = arguments.status
    link.decided_at = utc_now()
    link.updated_at = link.decided_at
    session.add(link)
    session.commit()
    return {"trace_id": arguments.trace_id, "status": arguments.status}


def _execute_rerun_analysis(
    request: AgentToolRequest, arguments: RerunAnalysisArguments
) -> dict[str, Any]:
    if _analysis_enqueuer is None:
        raise ToolExecutionError("analysis_service_not_integrated")
    result = _analysis_enqueuer(
        request.project_id,
        arguments.targets,
        request.confirmation_id,
    )
    return {key: value for key, value in result.items() if "path" not in key.lower()}


def _execute_tool(session: Session, request: AgentToolRequest) -> dict[str, Any]:
    arguments = validate_tool_arguments(
        request.tool_name, request.private_arguments_json
    )
    if isinstance(arguments, SaveCodeArguments):
        return _execute_save_code(session, request, arguments)
    if isinstance(arguments, UpdateTraceArguments):
        return _execute_update_trace(session, request, arguments)
    if isinstance(arguments, RerunAnalysisArguments):
        return _execute_rerun_analysis(request, arguments)
    raise ToolExecutionError("tool_not_executable")


def decide_confirmation(
    session: Session,
    project_id: int,
    confirmation_id: str,
    decision: str,
) -> AgentToolRequest | None:
    request = read_confirmation(session, project_id, confirmation_id)
    if request is None or request.status != "pending":
        return request
    request.user_decision = decision
    request.decided_at = utc_now()
    if decision == "reject":
        request.status = "rejected"
        session.add(request)
        session.commit()
        session.refresh(request)
        return request

    request.status = "approved"
    session.add(request)
    session.commit()
    try:
        result = _execute_tool(session, request)
    except ToolExecutionError as exc:
        request.status = "failed"
        request.error_summary = exc.reason
    except Exception:
        request.status = "failed"
        request.error_summary = "tool_execution_error"
    else:
        request.status = "executed"
        request.result_json = result
    request.executed_at = utc_now()
    session.add(request)
    session.commit()
    session.refresh(request)
    return request
