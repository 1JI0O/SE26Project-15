from __future__ import annotations

import hashlib
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import CodeRepository, PaperDocument, TraceLink, utc_now
from app.schemas.traces import TraceLinkRead
from app.services.integration_settings import get_effective_integration_config
from app.services.tracing.context import build_contexts
from app.services.tracing.lifecycle import mark_noncurrent_traces_stale
from app.services.tracing.provider import (
    CompatibleRESTProvider,
    LLMExplanation,
    ProviderFailure,
    TraceExplanationProvider,
)
from app.services.tracing.static_candidates import StaticCandidate, generate_static_candidates

PROMPT_VERSION = "trace-v1"
UNCERTAINTY_PENALTY = {"low": 0.0, "medium": 0.05, "high": 0.15}


def trace_to_read(link: TraceLink) -> TraceLinkRead:
    return TraceLinkRead(
        id=link.trace_id,
        project_id=link.project_id,
        paper_document_id=link.paper_document_id,
        paper_block_id=link.paper_ref,
        code_repository_id=link.code_repository_id,
        code_revision=link.code_revision,
        code_symbol_id=link.code_ref,
        relation_type=link.relation_type,
        confidence=link.confidence,
        static_confidence=link.static_confidence,
        llm_confidence=link.llm_confidence,
        source=link.source,
        evidence=link.evidence_json,
        rationale=link.rationale,
        uncertainty=link.uncertainty_json,
        model=link.model_info_json,
        status=link.status,
        stale_reason=link.stale_reason,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


def trace_fingerprint(
    paper_document_id: int,
    code_repository_id: int,
    code_revision: int,
    paper_block_id: str,
    code_symbol_id: str,
    relation_type: str,
) -> str:
    raw = "\x00".join(
        (
            str(paper_document_id),
            str(code_repository_id),
            str(code_revision),
            paper_block_id,
            code_symbol_id,
            relation_type,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _valid_llm_evidence(explanation: LLMExplanation, candidate: StaticCandidate) -> bool:
    allowed = {
        "paper": (candidate.paper_block_id, _normalize(candidate.paper_text)),
        "code": (candidate.code_symbol_id, _normalize(candidate.code_text)),
    }
    sides: set[str] = set()
    for evidence in explanation.evidence:
        side = evidence.get("side", "")
        if side not in allowed:
            return False
        expected_ref, original = allowed[side]
        if evidence.get("ref") != expected_ref:
            return False
        quote = _normalize(evidence.get("quote", ""))
        if not quote or quote not in original:
            return False
        sides.add(side)
    return sides == {"paper", "code"}


def _provider_from_settings(session: Session) -> tuple[TraceExplanationProvider | None, str | None]:
    config, _ = get_effective_integration_config(session)
    if not config.agent_enabled:
        return None, "llm_disabled"
    if not config.agent_base_url or not config.agent_api_key or not config.agent_model:
        return None, "llm_not_configured"
    return (
        CompatibleRESTProvider(
            config.agent_base_url,
            config.agent_api_key,
            config.agent_model,
            config.agent_timeout_seconds,
            config.agent_thinking_mode,
        ),
        None,
    )


def _enhance_candidates(
    candidates: list[StaticCandidate],
    provider: TraceExplanationProvider,
) -> tuple[dict[str, LLMExplanation], str | None]:
    contexts = build_contexts(
        candidates,
        max_candidates=settings.tracelab_llm_max_candidates,
        max_chars=settings.tracelab_llm_max_context_chars,
    )
    try:
        explanations = provider.explain(contexts)
    except ProviderFailure as exc:
        return {}, exc.reason
    except Exception:
        return {}, "llm_provider_error"
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    valid: dict[str, LLMExplanation] = {}
    invalid_found = False
    for explanation in explanations:
        candidate = candidates_by_id.get(explanation.candidate_id)
        if candidate is None or not _valid_llm_evidence(explanation, candidate):
            invalid_found = True
            continue
        valid[explanation.candidate_id] = explanation
    return valid, "llm_evidence_invalid" if invalid_found else None


def _values_for_candidate(
    candidate: StaticCandidate,
    explanation: LLMExplanation | None,
    provider: TraceExplanationProvider | None,
) -> dict[str, Any]:
    if explanation is None or provider is None:
        return {
            "relation_type": candidate.relation_type,
            "confidence": candidate.confidence,
            "llm_confidence": None,
            "source": "static",
            "evidence_json": candidate.evidence,
            "rationale": candidate.rationale,
            "uncertainty_json": {"level": "high", "reasons": ["llm_not_used"]},
            "model_info_json": None,
        }
    penalty = UNCERTAINTY_PENALTY[explanation.uncertainty.level]
    confidence = max(
        0.0,
        min(1.0, 0.6 * candidate.confidence + 0.4 * explanation.confidence - penalty),
    )
    return {
        "relation_type": explanation.relation_type,
        "confidence": round(confidence, 4),
        "llm_confidence": explanation.confidence,
        "source": "static+llm",
        "evidence_json": explanation.evidence,
        "rationale": explanation.rationale,
        "uncertainty_json": explanation.uncertainty.model_dump(),
        "model_info_json": {
            "provider": provider.provider_name,
            "name": provider.model_name,
            "prompt_version": PROMPT_VERSION,
        },
    }


def suggest_and_persist(
    session: Session,
    project_id: int,
    paper: PaperDocument,
    code: CodeRepository,
    *,
    use_llm: bool,
    provider: TraceExplanationProvider | None = None,
) -> tuple[list[TraceLinkRead], str, bool, str | None]:
    mark_noncurrent_traces_stale(session, project_id, paper.id or 0, code.id or 0, code.revision)
    candidates = generate_static_candidates(
        paper.sections_json,
        paper.paragraphs_json,
        code.symbols_json,
        code.pytorch_candidates_json,
        code.tensor_graph_json,
    )
    degraded_reason: str | None = None
    actual_provider = provider
    if use_llm and actual_provider is None:
        actual_provider, degraded_reason = _provider_from_settings(session)
    explanations: dict[str, LLMExplanation] = {}
    if use_llm and actual_provider is not None and candidates:
        explanations, validation_reason = _enhance_candidates(candidates, actual_provider)
        degraded_reason = degraded_reason or validation_reason
    elif use_llm and not candidates:
        degraded_reason = degraded_reason or "no_static_candidates"

    persisted: list[TraceLink] = []
    for candidate in candidates:
        values = _values_for_candidate(
            candidate,
            explanations.get(candidate.candidate_id),
            actual_provider,
        )
        fingerprint = trace_fingerprint(
            paper.id or 0,
            code.id or 0,
            code.revision,
            candidate.paper_block_id,
            candidate.code_symbol_id,
            values["relation_type"],
        )
        link = session.exec(select(TraceLink).where(TraceLink.fingerprint == fingerprint)).first()
        if link is None:
            link = TraceLink(
                project_id=project_id,
                paper_document_id=paper.id,
                paper_ref=candidate.paper_block_id,
                code_repository_id=code.id,
                code_revision=code.revision,
                code_ref=candidate.code_symbol_id,
                relation_type=values["relation_type"],
                confidence=values["confidence"],
                static_confidence=candidate.confidence,
                llm_confidence=values["llm_confidence"],
                source=values["source"],
                evidence_json=values["evidence_json"],
                rationale=values["rationale"],
                uncertainty_json=values["uncertainty_json"],
                model_info_json=values["model_info_json"],
                fingerprint=fingerprint,
            )
            session.add(link)
        elif link.status == "proposed":
            link.confidence = values["confidence"]
            link.static_confidence = candidate.confidence
            link.llm_confidence = values["llm_confidence"]
            link.source = values["source"]
            link.evidence_json = values["evidence_json"]
            link.rationale = values["rationale"]
            link.uncertainty_json = values["uncertainty_json"]
            link.model_info_json = values["model_info_json"]
            link.updated_at = utc_now()
        persisted.append(link)
    session.commit()
    for link in persisted:
        session.refresh(link)
    enhanced = any(link.source == "static+llm" for link in persisted)
    mode = "static+llm" if enhanced else "static"
    degraded = bool(use_llm and (degraded_reason or not enhanced))
    if degraded and degraded_reason is None:
        degraded_reason = "llm_no_valid_explanations"
    return [trace_to_read(link) for link in persisted], mode, degraded, degraded_reason
