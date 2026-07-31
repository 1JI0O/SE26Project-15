from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import (
    AgentRun,
    AgentToolRequest,
    Project,
    TraceLink,
    as_utc,
    utc_now,
)
from app.schemas.agent import (
    AgentCitation,
    AgentConfirmationRead,
    AgentQueryRequest,
    AgentQueryResponse,
)
from app.services import workspace_service
from app.services.agent.capabilities import build_registry
from app.services.agent.mcp import validate_json_schema
from app.services.agent.provider import (
    AgentProvider,
    AgentProviderFailure,
    CompatibleAgentProvider,
)
from app.services.agent.tools import (
    WRITE_TOOLS,
    CreateTraceArguments,
    DeleteTraceLinkArguments,
    RerunAnalysisArguments,
    SaveCodeArguments,
    UpdateTraceArguments,
    UpdateTraceLinkArguments,
    build_context_snapshot,
    content_sha256,
    latest_code,
    latest_paper,
    prepare_write_request,
    validate_tool_arguments,
)
from app.services.integration_settings import get_effective_integration_config
from app.services.local_sync import record_local_operation, trace_payload
from app.services.tracing.manual_anchors import (
    UnresolvableAnchorError,
    build_reference_evidence,
)

AnalysisEnqueuer = Callable[[int, list[str], str], dict[str, Any]]
_analysis_enqueuer: AnalysisEnqueuer | None = None

# Chat-tool create_trace_link; distinct from analysis publish versions (trace-agent-v2/v3).
CHAT_CREATE_TRACE_PROMPT_VERSION = "chat-create-trace-v1"


def _model_info_for_chat_tool(session: Session, request: AgentToolRequest) -> dict[str, str]:
    """Shape required by ``TraceModelInfo`` so GET /trace-links does not 500.

    Earlier builds stuffed ``source``/``confirmation_id`` into ``model_info_json``; the read
    schema requires ``provider``/``name``/``prompt_version``. Those provenance fields belong in
    ``provenance_json`` instead (see ``_provenance_for_chat_tool``).
    """

    run: AgentRun | None = None
    if request.run_id:
        run = session.get(AgentRun, request.run_id)
    provider = (run.provider_name if run else "") or ""
    name = (run.model_name if run else "") or ""
    if not provider or not name:
        configured, _ = _provider_from_settings(session)
        if configured is not None:
            provider = provider or configured.provider_name or "openai-compatible"
            name = name or configured.model_name or "unknown"
    return {
        "provider": provider or "agent_tool",
        "name": name or "unknown",
        "prompt_version": CHAT_CREATE_TRACE_PROMPT_VERSION,
    }


def _provenance_for_chat_tool(request: AgentToolRequest) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "source": "agent_tool",
        "confirmation_id": request.confirmation_id,
    }
    if request.run_id:
        provenance["run_id"] = request.run_id
    return provenance


class ToolExecutionError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _record_trace_mutation(
    session: Session,
    project_id: int,
    link: TraceLink,
    *,
    base_version: int,
) -> None:
    """Keep Agent-authored trace writes consistent with the REST trace routes."""

    project = session.get(Project, project_id)
    if project is None:
        raise ToolExecutionError("project_not_found")
    record_local_operation(
        session,
        project,
        "trace_link",
        link.public_id,
        trace_payload(project, link, session=session),
        base_version=base_version,
    )
    # Reviewed traces are the precedent corpus. Rebuild lazily on the next search.
    from app.services.rag import invalidate

    invalidate(session, project_id, "trace")


def register_analysis_enqueuer(enqueuer: AnalysisEnqueuer) -> None:
    """Integration hook owned by the repository analysis module."""

    global _analysis_enqueuer
    _analysis_enqueuer = enqueuer


def confirmation_to_read(request: AgentToolRequest) -> AgentConfirmationRead:
    return AgentConfirmationRead(
        confirmation_id=request.confirmation_id,
        project_id=request.project_id,
        conversation_id=request.conversation_id,
        run_id=request.run_id,
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


def _expire_if_needed(session: Session, request: AgentToolRequest) -> None:
    if request.status == "pending" and as_utc(request.expires_at) <= utc_now():
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
    *,
    conversation_id: str | None = None,
    run_id: str | None = None,
) -> AgentToolRequest:
    registry = build_registry(session)
    capability = registry.tool(tool_name)
    if capability is None or capability.read_only:
        raise ValueError("write_tool_not_available")
    if tool_name in WRITE_TOOLS:
        private_arguments, summary = prepare_write_request(
            session, project_id, tool_name, arguments
        )
    else:
        validate_json_schema(arguments, capability.input_schema)
        private_arguments = arguments
        summary = {
            "tool": capability.title,
            "source": capability.source,
            "argument_keys": sorted(arguments),
            "external": True,
        }
    request = AgentToolRequest(
        project_id=project_id,
        conversation_id=conversation_id,
        run_id=run_id,
        tool_name=tool_name,
        private_arguments_json=private_arguments,
        parameter_summary_json=summary,
        expires_at=utc_now() + timedelta(seconds=settings.tracelab_agent_confirmation_ttl_seconds),
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def _provider_from_settings(
    session: Session, *, for_analysis: bool = False
) -> tuple[AgentProvider | None, str | None]:
    config, _ = get_effective_integration_config(session)
    if not config.agent_enabled:
        return None, "llm_disabled"
    if not config.agent_base_url or not config.agent_api_key or not config.agent_model:
        return None, "llm_not_configured"
    # Analysis jobs (trace/architecture) may opt into a stronger, costlier model configured
    # separately from the chat model. Falls back to the chat model when unset.
    analysis_model = (getattr(config, "agent_analysis_model", "") or "").strip()
    model = analysis_model if (for_analysis and analysis_model) else config.agent_model
    return (
        CompatibleAgentProvider(
            config.agent_base_url,
            config.agent_api_key,
            model,
            config.agent_timeout_seconds,
            config.agent_thinking_mode,
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
    registry = build_registry(session)
    context["tool_definitions"] = registry.tool_definitions()
    actual_provider = provider
    degraded_reason: str | None = None
    if actual_provider is None:
        actual_provider, degraded_reason = _provider_from_settings(session)
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
        capability = registry.tool(step.tool_name or "")
        if capability is not None and capability.read_only:
            try:
                result = registry.execute(session, project_id, step.tool_name or "", step.arguments)
            except (ValueError, ValidationError):
                return AgentQueryResponse(
                    answer="Agent 提出的只读工具参数无效。",
                    degraded=True,
                    degraded_reason="invalid_tool_arguments",
                )
            tool_results.append({"tool": step.tool_name, "result": result})
            continue
        if capability is not None and not capability.read_only:
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
        save_result = workspace_service.save_code_file(
            session, request.project_id, arguments.path, arguments.content
        )
    else:
        save_result = {
            "repository_revision": repository.revision,
            "stale_trace_count": 0,
        }
    return {
        "path": arguments.path,
        "status": "saved",
        "target_sha256": target_hash,
        "repository_revision": save_result["repository_revision"],
        "stale_trace_count": save_result["stale_trace_count"],
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
    link.version += 1
    session.add(link)
    _record_trace_mutation(
        session,
        request.project_id,
        link,
        base_version=link.version - 1,
    )
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


def _execute_create_trace(
    session: Session,
    request: AgentToolRequest,
    arguments: CreateTraceArguments,
) -> dict[str, Any]:
    paper = latest_paper(session, request.project_id)
    code = latest_code(session, request.project_id)
    if paper is None:
        raise ToolExecutionError("paper_not_found")
    if code is None:
        raise ToolExecutionError("code_repository_not_found")
    fingerprint_payload = (
        f"{request.project_id}:{arguments.paper_ref}:{arguments.code_ref}:"
        f"{arguments.relation_type}:{code.revision}"
    )
    fingerprint = f"agent-{content_sha256(fingerprint_payload)[:58]}"
    existing = session.exec(select(TraceLink).where(TraceLink.fingerprint == fingerprint)).first()
    if existing is not None:
        return {
            "trace_id": existing.trace_id,
            "status": existing.status,
            "created": False,
        }
    try:
        evidence = build_reference_evidence(
            session,
            request.project_id,
            paper,
            code,
            arguments.paper_ref,
            arguments.code_ref,
        )
    except UnresolvableAnchorError as exc:
        # A relation whose reference cannot be anchored can never be highlighted or quoted, so
        # it must fail loudly here rather than land in the matrix as a dead row.
        raise ToolExecutionError(f"{exc.side}_reference_not_anchorable") from exc
    link = TraceLink(
        project_id=request.project_id,
        paper_document_id=paper.id,
        paper_ref=arguments.paper_ref,
        code_repository_id=code.id,
        code_revision=code.revision,
        code_ref=arguments.code_ref,
        relation_type=arguments.relation_type,
        confidence=arguments.confidence,
        static_confidence=0,
        source="agent",
        rationale=arguments.rationale,
        uncertainty_json={
            "level": "low" if arguments.confidence >= 0.85 else "medium",
            "reasons": ["Agent-generated relation; user confirmation recorded"],
        },
        model_info_json=_model_info_for_chat_tool(session, request),
        provenance_json=_provenance_for_chat_tool(request),
        # Without evidence the link would carry no anchor ids, and the reader's decoration
        # index drops any link whose target id is null — the relation would appear in the
        # matrix and jump correctly while leaving both panes unhighlighted.
        evidence_json=evidence,
        fingerprint=fingerprint,
        status="accepted",
        decided_at=utc_now(),
    )
    session.add(link)
    session.flush()
    _record_trace_mutation(session, request.project_id, link, base_version=0)
    session.commit()
    session.refresh(link)
    return {"trace_id": link.trace_id, "status": link.status, "created": True}


def _execute_update_trace_link(
    session: Session,
    request: AgentToolRequest,
    arguments: UpdateTraceLinkArguments,
) -> dict[str, Any]:
    link = session.exec(
        select(TraceLink).where(
            TraceLink.project_id == request.project_id,
            TraceLink.trace_id == arguments.trace_id,
        )
    ).first()
    if link is None:
        raise ToolExecutionError("trace_link_not_found")

    updated_fields = []
    if arguments.relation_type is not None:
        link.relation_type = arguments.relation_type
        updated_fields.append("relation_type")
    if arguments.confidence is not None:
        link.confidence = arguments.confidence
        link.static_confidence = arguments.confidence
        updated_fields.append("confidence")
    if arguments.rationale is not None:
        link.rationale = arguments.rationale
        updated_fields.append("rationale")

    link.updated_at = utc_now()
    link.version += 1
    session.add(link)
    _record_trace_mutation(
        session,
        request.project_id,
        link,
        base_version=link.version - 1,
    )
    session.commit()
    session.refresh(link)
    return {
        "trace_id": link.trace_id,
        "updated_fields": updated_fields,
        "status": link.status,
    }


def _execute_delete_trace_link(
    session: Session,
    request: AgentToolRequest,
    arguments: DeleteTraceLinkArguments,
) -> dict[str, Any]:
    link = session.exec(
        select(TraceLink).where(
            TraceLink.project_id == request.project_id,
            TraceLink.trace_id == arguments.trace_id,
        )
    ).first()
    if link is None:
        raise ToolExecutionError("trace_link_not_found")

    # Soft delete: set status to rejected
    link.status = "rejected"
    link.decided_at = utc_now()
    link.updated_at = utc_now()
    link.version += 1
    session.add(link)
    _record_trace_mutation(
        session,
        request.project_id,
        link,
        base_version=link.version - 1,
    )
    session.commit()
    return {
        "trace_id": link.trace_id,
        "deleted": True,
        "reason": arguments.reason,
    }


def _execute_tool(session: Session, request: AgentToolRequest) -> dict[str, Any]:
    if request.tool_name not in WRITE_TOOLS:
        registry = build_registry(session)
        capability = registry.tool(request.tool_name)
        if capability is None or capability.read_only:
            raise ToolExecutionError("tool_not_executable")
        try:
            return registry.execute(
                session,
                request.project_id,
                request.tool_name,
                request.private_arguments_json,
            )
        except Exception as exc:
            raise ToolExecutionError("external_tool_execution_error") from exc
    arguments = validate_tool_arguments(request.tool_name, request.private_arguments_json)
    if isinstance(arguments, SaveCodeArguments):
        return _execute_save_code(session, request, arguments)
    if isinstance(arguments, UpdateTraceArguments):
        return _execute_update_trace(session, request, arguments)
    if isinstance(arguments, RerunAnalysisArguments):
        return _execute_rerun_analysis(request, arguments)
    if isinstance(arguments, CreateTraceArguments):
        return _execute_create_trace(session, request, arguments)
    if isinstance(arguments, UpdateTraceLinkArguments):
        return _execute_update_trace_link(session, request, arguments)
    if isinstance(arguments, DeleteTraceLinkArguments):
        return _execute_delete_trace_link(session, request, arguments)
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
