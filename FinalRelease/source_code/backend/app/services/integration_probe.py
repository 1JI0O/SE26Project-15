"""Live reachability checks for the configured Agent LLM and MinerU endpoints.

The settings dialog previously let a user save an unreachable URL or a bad key and only found
out much later, when a trace run or a PDF parse failed with an opaque code. These probes issue
one cheap real request against the same base URL/credentials the runtime will use and report the
provider's own error text.

Probes accept the *pending* form values so a user can validate before saving. When a secret is
omitted the stored one is reused, which is what "已配置，留空则保留" implies in the dialog.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from sqlmodel import Session

from app.schemas.integration_settings import (
    IntegrationProbeRequest,
    IntegrationProbeResult,
)
from app.services.integration_settings import get_effective_integration_config

_MAX_DETAIL = 600


def _truncate(value: str) -> str:
    text = " ".join(value.split())
    return text[:_MAX_DETAIL]


def _provider_detail(response: httpx.Response) -> str:
    """Best-effort human-readable reason from an OpenAI-compatible error body."""

    try:
        body = response.json()
    except ValueError:
        return _truncate(response.text)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return _truncate(str(error["message"]))
        if isinstance(error, str) and error:
            return _truncate(error)
        if body.get("message"):
            return _truncate(str(body["message"]))
    return _truncate(json.dumps(body, ensure_ascii=False))


def probe_agent(
    base_url: str,
    api_key: str,
    model: str,
    timeout: float,
) -> IntegrationProbeResult:
    """Send a minimal chat completion so key, URL and model name are all exercised.

    A models-list call would pass even when the requested model does not exist, so this uses the
    real endpoint the agent runtime calls with a one-token response.
    """

    if not base_url:
        return IntegrationProbeResult(target="agent", ok=False, code="missing_base_url",
                                      detail="未填写 API 地址")
    if not model:
        return IntegrationProbeResult(target="agent", ok=False, code="missing_model",
                                      detail="未填写模型名称")
    if not api_key:
        return IntegrationProbeResult(target="agent", ok=False, code="missing_api_key",
                                      detail="未填写 API Key，且本机没有已保存的密钥")
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    started = time.monotonic()
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        return IntegrationProbeResult(
            target="agent",
            ok=False,
            code="timeout",
            detail=_truncate(f"请求超时（{timeout:g}s）：{exc}"),
        )
    except httpx.HTTPError as exc:
        return IntegrationProbeResult(
            target="agent",
            ok=False,
            code="transport_error",
            detail=_truncate(f"无法连接：{exc}"),
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code == 401 or response.status_code == 403:
        return IntegrationProbeResult(
            target="agent", ok=False, code="unauthorized", latency_ms=latency_ms,
            detail=_provider_detail(response) or "API Key 被拒绝",
        )
    if response.status_code == 404:
        return IntegrationProbeResult(
            target="agent", ok=False, code="not_found", latency_ms=latency_ms,
            detail=_provider_detail(response) or "地址或模型不存在，请检查 API 地址是否带 /v1",
        )
    if response.status_code == 429:
        return IntegrationProbeResult(
            target="agent", ok=False, code="rate_limited", latency_ms=latency_ms,
            detail=_provider_detail(response) or "请求被限流",
        )
    if response.status_code >= 400:
        return IntegrationProbeResult(
            target="agent", ok=False, code=f"http_{response.status_code}",
            latency_ms=latency_ms, detail=_provider_detail(response),
        )
    try:
        served = str(response.json()["choices"][0]["message"].get("content", ""))
    except (KeyError, IndexError, TypeError, ValueError):
        return IntegrationProbeResult(
            target="agent", ok=False, code="unexpected_response", latency_ms=latency_ms,
            detail=_truncate(f"响应结构不是 OpenAI 兼容格式：{response.text}"),
        )
    return IntegrationProbeResult(
        target="agent", ok=True, code="ok", latency_ms=latency_ms,
        detail=f"模型 {model} 可用（返回 {len(served)} 字符）",
    )


def probe_mineru_local(url: str, timeout: float) -> IntegrationProbeResult:
    if not url:
        return IntegrationProbeResult(target="mineru", ok=False, code="missing_base_url",
                                      detail="未填写本地服务地址")
    started = time.monotonic()
    try:
        response = httpx.get(f"{url.rstrip('/')}/health", timeout=timeout)
    except httpx.TimeoutException as exc:
        return IntegrationProbeResult(target="mineru", ok=False, code="timeout",
                                      detail=_truncate(f"请求超时（{timeout:g}s）：{exc}"))
    except httpx.HTTPError as exc:
        return IntegrationProbeResult(
            target="mineru", ok=False, code="transport_error",
            detail=_truncate(f"无法连接本地 MinerU：{exc}"),
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        return IntegrationProbeResult(
            target="mineru", ok=False, code=f"http_{response.status_code}",
            latency_ms=latency_ms, detail=_truncate(response.text),
        )
    return IntegrationProbeResult(
        target="mineru", ok=True, code="ok", latency_ms=latency_ms,
        detail=_truncate(f"本地 MinerU 可用：{response.text}"),
    )


def probe_mineru_official(url: str, token: str, timeout: float) -> IntegrationProbeResult:
    """Authenticate against the official API without creating a parse task.

    Requesting a batch result for an obviously non-existent id validates URL + token: a bad token
    answers 401, a good one answers a normal "not found" style body.
    """

    if not url:
        return IntegrationProbeResult(target="mineru", ok=False, code="missing_base_url",
                                      detail="未填写官方 API 地址")
    if not token:
        return IntegrationProbeResult(target="mineru", ok=False, code="missing_api_token",
                                      detail="未填写 API Token，且本机没有已保存的令牌")
    started = time.monotonic()
    try:
        response = httpx.get(
            f"{url.rstrip('/')}/extract-results/batch/tracelab-connectivity-probe",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        return IntegrationProbeResult(target="mineru", ok=False, code="timeout",
                                      detail=_truncate(f"请求超时（{timeout:g}s）：{exc}"))
    except httpx.HTTPError as exc:
        return IntegrationProbeResult(
            target="mineru", ok=False, code="transport_error",
            detail=_truncate(f"无法连接官方 MinerU API：{exc}"),
        )
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code in {401, 403}:
        return IntegrationProbeResult(
            target="mineru", ok=False, code="unauthorized", latency_ms=latency_ms,
            detail=_truncate(response.text) or "API Token 被拒绝",
        )
    if response.status_code >= 500:
        return IntegrationProbeResult(
            target="mineru", ok=False, code=f"http_{response.status_code}",
            latency_ms=latency_ms, detail=_truncate(response.text),
        )
    # The probe batch id never exists, so anything non-auth means the endpoint accepted our
    # credentials — that is exactly what we wanted to learn.
    return IntegrationProbeResult(
        target="mineru", ok=True, code="ok", latency_ms=latency_ms,
        detail="官方 MinerU API 可访问，Token 有效",
    )


def run_integration_probe(
    session: Session, payload: IntegrationProbeRequest
) -> IntegrationProbeResult:
    stored, _ = get_effective_integration_config(session)
    if payload.target == "agent":
        return probe_agent(
            base_url=payload.base_url or stored.agent_base_url,
            api_key=(
                payload.api_key.get_secret_value().strip()
                if payload.api_key is not None
                else stored.agent_api_key
            ),
            model=payload.model or stored.agent_analysis_model or stored.agent_model,
            timeout=payload.timeout_seconds or stored.agent_timeout_seconds,
        )
    provider = payload.mineru_provider or stored.mineru_provider
    timeout = payload.timeout_seconds or stored.mineru_request_timeout_seconds
    if provider == "local":
        return probe_mineru_local(payload.base_url or stored.mineru_local_url, timeout)
    return probe_mineru_official(
        payload.base_url or stored.mineru_official_api_url,
        (
            payload.api_key.get_secret_value().strip()
            if payload.api_key is not None
            else stored.mineru_official_api_token
        ),
        timeout,
    )
