from __future__ import annotations

import os

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import IntegrationConfig, utc_now
from app.schemas.integration_settings import (
    AgentIntegrationRead,
    IntegrationSettingsRead,
    IntegrationSettingsUpdate,
    MinerUIntegrationRead,
    RagIntegrationRead,
)

CONFIG_ID = 1


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _environment_defaults() -> IntegrationConfig:
    provider = os.getenv("TRACELAB_MINERU_PROVIDER", "local").strip().lower()
    if provider not in {"local", "official"}:
        provider = "local"
    return IntegrationConfig(
        id=CONFIG_ID,
        agent_enabled=settings.tracelab_llm_enabled,
        agent_base_url=settings.tracelab_llm_base_url.rstrip("/"),
        agent_api_key=settings.tracelab_llm_api_key.get_secret_value(),
        agent_model=settings.tracelab_llm_model,
        agent_analysis_model=os.getenv("TRACELAB_LLM_ANALYSIS_MODEL", ""),
        agent_thinking_mode=settings.tracelab_llm_thinking_mode,
        agent_timeout_seconds=settings.tracelab_llm_timeout_seconds,
        mineru_provider=provider,
        mineru_local_url=os.getenv("TRACELAB_MINERU_URL", "http://127.0.0.1:8001").rstrip("/"),
        mineru_backend=os.getenv("TRACELAB_MINERU_BACKEND", "pipeline"),
        mineru_language=os.getenv("TRACELAB_MINERU_LANGUAGE", "ch"),
        mineru_parse_method=os.getenv("TRACELAB_MINERU_PARSE_METHOD", "auto"),
        mineru_official_api_url=os.getenv(
            "TRACELAB_MINERU_API_URL", "https://mineru.net/api/v4"
        ).rstrip("/"),
        mineru_official_api_token=os.getenv("TRACELAB_MINERU_API_TOKEN", ""),
        mineru_official_api_model=os.getenv("TRACELAB_MINERU_API_MODEL", "vlm"),
        mineru_ocr=_env_bool("TRACELAB_MINERU_API_OCR", True),
        mineru_formula_enable=_env_bool("TRACELAB_MINERU_FORMULA_ENABLE", True),
        mineru_table_enable=_env_bool("TRACELAB_MINERU_TABLE_ENABLE", True),
        mineru_request_timeout_seconds=float(os.getenv("TRACELAB_MINERU_REQUEST_TIMEOUT", "60")),
        mineru_request_retries=int(os.getenv("TRACELAB_MINERU_REQUEST_RETRIES", "3")),
        mineru_task_timeout_seconds=float(os.getenv("TRACELAB_MINERU_TASK_TIMEOUT", "600")),
        mineru_poll_interval_seconds=float(os.getenv("TRACELAB_MINERU_POLL_INTERVAL", "2")),
        rag_enabled=_env_bool("TRACELAB_RAG_ENABLED", True),
        rag_embedder=(
            os.getenv("TRACELAB_RAG_EMBEDDER", "local").strip().lower()
            if os.getenv("TRACELAB_RAG_EMBEDDER", "local").strip().lower() in {"local", "remote"}
            else "local"
        ),
        rag_base_url=os.getenv("TRACELAB_RAG_BASE_URL", "").rstrip("/"),
        rag_api_key=os.getenv("TRACELAB_RAG_API_KEY", ""),
        rag_model=os.getenv("TRACELAB_RAG_MODEL", ""),
        rag_dimensions=int(os.getenv("TRACELAB_RAG_DIMENSIONS", "512")),
        rag_timeout_seconds=float(os.getenv("TRACELAB_RAG_TIMEOUT", "30")),
    )


def get_effective_integration_config(session: Session) -> tuple[IntegrationConfig, str]:
    try:
        stored = session.get(IntegrationConfig, CONFIG_ID)
    except OperationalError:
        stored = None
    if stored is not None:
        return stored, "application"
    return _environment_defaults(), "environment"


def integration_config_to_read(config: IntegrationConfig, source: str) -> IntegrationSettingsRead:
    return IntegrationSettingsRead(
        agent=AgentIntegrationRead(
            enabled=config.agent_enabled,
            base_url=config.agent_base_url,
            model=config.agent_model,
            analysis_model=config.agent_analysis_model,
            thinking_mode=config.agent_thinking_mode,
            timeout_seconds=config.agent_timeout_seconds,
            api_key_configured=bool(config.agent_api_key),
        ),
        mineru=MinerUIntegrationRead(
            provider=config.mineru_provider,
            local_url=config.mineru_local_url,
            backend=config.mineru_backend,
            language=config.mineru_language,
            parse_method=config.mineru_parse_method,
            official_api_url=config.mineru_official_api_url,
            official_api_model=config.mineru_official_api_model,
            api_token_configured=bool(config.mineru_official_api_token),
            ocr=config.mineru_ocr,
            formula_enable=config.mineru_formula_enable,
            table_enable=config.mineru_table_enable,
            request_timeout_seconds=config.mineru_request_timeout_seconds,
            request_retries=config.mineru_request_retries,
            task_timeout_seconds=config.mineru_task_timeout_seconds,
            poll_interval_seconds=config.mineru_poll_interval_seconds,
        ),
        rag=RagIntegrationRead(
            enabled=config.rag_enabled,
            embedder=config.rag_embedder if config.rag_embedder in {"local", "remote"} else "local",
            base_url=config.rag_base_url,
            model=config.rag_model,
            dimensions=config.rag_dimensions,
            timeout_seconds=config.rag_timeout_seconds,
            api_key_configured=bool(config.rag_api_key),
        ),
        source=source,
        updated_at=config.updated_at if source == "application" else None,
    )


def save_integration_config(
    session: Session, payload: IntegrationSettingsUpdate
) -> IntegrationConfig:
    config, _ = get_effective_integration_config(session)
    config.agent_enabled = payload.agent.enabled
    config.agent_base_url = payload.agent.base_url
    config.agent_model = payload.agent.model.strip()
    config.agent_analysis_model = payload.agent.analysis_model.strip()
    config.agent_thinking_mode = payload.agent.thinking_mode
    config.agent_timeout_seconds = payload.agent.timeout_seconds
    if payload.agent.clear_api_key:
        config.agent_api_key = ""
    elif payload.agent.api_key is not None:
        config.agent_api_key = payload.agent.api_key.get_secret_value().strip()

    config.mineru_provider = payload.mineru.provider
    config.mineru_local_url = payload.mineru.local_url
    config.mineru_backend = payload.mineru.backend.strip()
    config.mineru_language = payload.mineru.language.strip()
    config.mineru_parse_method = payload.mineru.parse_method.strip()
    config.mineru_official_api_url = payload.mineru.official_api_url
    config.mineru_official_api_model = payload.mineru.official_api_model.strip()
    config.mineru_ocr = payload.mineru.ocr
    config.mineru_formula_enable = payload.mineru.formula_enable
    config.mineru_table_enable = payload.mineru.table_enable
    config.mineru_request_timeout_seconds = payload.mineru.request_timeout_seconds
    config.mineru_request_retries = payload.mineru.request_retries
    config.mineru_task_timeout_seconds = payload.mineru.task_timeout_seconds
    config.mineru_poll_interval_seconds = payload.mineru.poll_interval_seconds
    if payload.mineru.clear_api_token:
        config.mineru_official_api_token = ""
    elif payload.mineru.official_api_token is not None:
        config.mineru_official_api_token = (
            payload.mineru.official_api_token.get_secret_value().strip()
        )
    if payload.rag is not None:
        previous_signature = (config.rag_embedder, config.rag_model, config.rag_dimensions)
        config.rag_enabled = payload.rag.enabled
        config.rag_embedder = payload.rag.embedder
        config.rag_base_url = payload.rag.base_url
        config.rag_model = payload.rag.model.strip()
        config.rag_dimensions = payload.rag.dimensions
        config.rag_timeout_seconds = payload.rag.timeout_seconds
        if payload.rag.clear_api_key:
            config.rag_api_key = ""
        elif payload.rag.api_key is not None:
            config.rag_api_key = payload.rag.api_key.get_secret_value().strip()
        if (config.rag_embedder, config.rag_model, config.rag_dimensions) != previous_signature:
            # Vectors from a different embedder or dimension are not comparable with new
            # queries, so every stored index must be rebuilt rather than silently mixed.
            _invalidate_all_rag_indexes(session)

    config.updated_at = utc_now()
    session.add(config)
    session.commit()
    session.refresh(config)
    return config


def _invalidate_all_rag_indexes(session: Session) -> None:
    from app.models.entities import RagIndexState

    try:
        for state in session.exec(select(RagIndexState)).all():
            state.status = "pending"
            state.updated_at = utc_now()
            session.add(state)
    except OperationalError:
        # Pre-0013 database being read through an old schema; nothing to invalidate.
        pass
