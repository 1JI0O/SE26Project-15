from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AgentProviderFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AgentProviderStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern="^(final|tool)$")
    answer: str = Field(default="", max_length=8000)
    citations: list[dict[str, str]] = Field(default_factory=list, max_length=12)
    tool_name: str | None = Field(default=None, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentProvider(Protocol):
    provider_name: str
    model_name: str

    def next_step(
        self,
        message: str,
        context: dict[str, Any],
        tool_results: list[dict[str, Any]],
    ) -> AgentProviderStep: ...


class CompatibleAgentProvider:
    provider_name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout

    def next_step(
        self,
        message: str,
        context: dict[str, Any],
        tool_results: list[dict[str, Any]],
    ) -> AgentProviderStep:
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise AgentProviderFailure("llm_dependency_missing") from exc
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a restricted TraceLab agent. "
                        "Return JSON with action final or tool. Only use the listed tools. "
                        "Write tools are proposals and require confirmation."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "context": context,
                            "tool_results": tool_results,
                            "read_tools": [
                                "get_paper_block",
                                "get_code_symbol",
                                "get_graph_node",
                                "list_trace_links",
                                "propose_code_patch",
                            ],
                            "write_tools": [
                                "save_code_file",
                                "rerun_analysis",
                                "update_trace_status",
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise AgentProviderFailure("llm_timeout") from exc
        except httpx.HTTPError as exc:
            raise AgentProviderFailure("llm_transport_error") from exc
        if response.status_code == 429:
            raise AgentProviderFailure("llm_rate_limited")
        if response.status_code >= 500:
            raise AgentProviderFailure("llm_upstream_error")
        if response.status_code >= 400:
            raise AgentProviderFailure("llm_request_rejected")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            return AgentProviderStep.model_validate(json.loads(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise AgentProviderFailure("llm_invalid_json") from exc
