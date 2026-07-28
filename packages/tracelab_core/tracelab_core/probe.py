"""Connectivity probes for LLM and MinerU (no DB dependency)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

_MAX_DETAIL = 600


def _truncate(value: str) -> str:
    text = " ".join(value.split())
    return text[:_MAX_DETAIL]


def _provider_detail(response: httpx.Response) -> str:
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


def probe_llm(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config.get("base_url", "")).rstrip("/")
    api_key = str(config.get("api_key", "")).strip()
    model = str(config.get("model", "")).strip()
    timeout = float(config.get("timeout_seconds", 30))
    if not base_url:
        return {
            "ok": False,
            "target": "llm",
            "code": "missing_base_url",
            "detail": "未填写 API 地址",
        }
    if not model:
        return {"ok": False, "target": "llm", "code": "missing_model", "detail": "未填写模型名称"}
    if not api_key:
        return {"ok": False, "target": "llm", "code": "missing_api_key", "detail": "未填写 API Key"}

    url = f"{base_url}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    thinking = str(config.get("thinking_mode", "") or "")
    if thinking in {"enabled", "disabled"}:
        payload["thinking"] = {"type": thinking}

    started = time.monotonic()
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        return {
            "ok": False,
            "target": "llm",
            "code": "timeout",
            "detail": _truncate(f"请求超时（{timeout:g}s）：{exc}"),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "target": "llm",
            "code": "transport_error",
            "detail": _truncate(f"无法连接：{exc}"),
        }

    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code in {401, 403}:
        return {
            "ok": False,
            "target": "llm",
            "code": "unauthorized",
            "latency_ms": latency_ms,
            "detail": _provider_detail(response) or "API Key 被拒绝",
        }
    if response.status_code >= 400:
        return {
            "ok": False,
            "target": "llm",
            "code": f"http_{response.status_code}",
            "latency_ms": latency_ms,
            "detail": _provider_detail(response),
        }
    try:
        served = str(response.json()["choices"][0]["message"].get("content", ""))
    except (KeyError, IndexError, TypeError, ValueError):
        return {
            "ok": False,
            "target": "llm",
            "code": "unexpected_response",
            "latency_ms": latency_ms,
            "detail": _truncate(f"响应结构不是 OpenAI 兼容格式：{response.text}"),
        }
    return {
        "ok": True,
        "target": "llm",
        "code": "ok",
        "latency_ms": latency_ms,
        "detail": f"模型 {model} 可用（返回 {len(served)} 字符）",
    }


def probe_mineru(config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config.get("provider", "official"))
    timeout = float(config.get("request_timeout_seconds", 30))
    if provider == "local":
        url = str(config.get("base_url", "")).rstrip("/")
        if not url:
            return {
                "ok": False,
                "target": "mineru",
                "code": "missing_base_url",
                "detail": "未填写本地服务地址",
            }
        started = time.monotonic()
        try:
            response = httpx.get(f"{url}/health", timeout=timeout)
        except httpx.TimeoutException as exc:
            return {
                "ok": False,
                "target": "mineru",
                "code": "timeout",
                "detail": _truncate(f"请求超时（{timeout:g}s）：{exc}"),
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "target": "mineru",
                "code": "transport_error",
                "detail": _truncate(f"无法连接本地 MinerU：{exc}"),
            }
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return {
                "ok": False,
                "target": "mineru",
                "code": f"http_{response.status_code}",
                "latency_ms": latency_ms,
                "detail": _truncate(response.text),
            }
        return {
            "ok": True,
            "target": "mineru",
            "code": "ok",
            "latency_ms": latency_ms,
            "detail": _truncate(f"本地 MinerU 可用：{response.text}"),
        }

    url = str(config.get("base_url") or "https://mineru.net/api/v4").rstrip("/")
    token = str(config.get("api_token", "")).strip()
    if not token:
        return {
            "ok": False,
            "target": "mineru",
            "code": "missing_api_token",
            "detail": "未填写 API Token",
        }
    started = time.monotonic()
    try:
        response = httpx.get(
            f"{url}/extract-results/batch/tracelab-connectivity-probe",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        return {
            "ok": False,
            "target": "mineru",
            "code": "timeout",
            "detail": _truncate(f"请求超时（{timeout:g}s）：{exc}"),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "target": "mineru",
            "code": "transport_error",
            "detail": _truncate(f"无法连接官方 MinerU API：{exc}"),
        }
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code in {401, 403}:
        return {
            "ok": False,
            "target": "mineru",
            "code": "unauthorized",
            "latency_ms": latency_ms,
            "detail": _truncate(response.text) or "API Token 被拒绝",
        }
    if response.status_code >= 500:
        return {
            "ok": False,
            "target": "mineru",
            "code": f"http_{response.status_code}",
            "latency_ms": latency_ms,
            "detail": _truncate(response.text),
        }
    return {
        "ok": True,
        "target": "mineru",
        "code": "ok",
        "latency_ms": latency_ms,
        "detail": "官方 MinerU API 可访问，Token 有效",
    }
