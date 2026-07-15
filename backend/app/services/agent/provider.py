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

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        thinking_mode: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        self.thinking_mode = thinking_mode

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
        history = context.get("history") if isinstance(context.get("history"), list) else []
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": str(context.get("system_prompt") or "You are TraceLab Agent."),
            }
        ]
        for item in history[-24:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = str(item.get("content", ""))[:8000]
            if content:
                messages.append({"role": str(item["role"]), "content": content})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": message,
                        "active_context": context.get("active_context", {}),
                        "environment": context.get("environment", {}),
                        "memories": context.get("memories", []),
                        "skills": context.get("skills", []),
                        "tool_results": tool_results,
                        "instruction": (
                            "Use tools when evidence is missing. If tool_results contain an error, "
                            "correct the call instead of repeating it. Return a normal final "
                            "answer when the task is complete."
                        ),
                    },
                    ensure_ascii=False,
                ),
            }
        )
        from app.services.agent.tools import tool_definitions

        definitions = tool_definitions()
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "messages": messages,
            "tools": definitions,
            "tool_choice": "auto",
        }
        if self.thinking_mode:
            payload["thinking"] = {"type": self.thinking_mode}

        def post(current_payload: dict[str, Any]) -> Any:
            try:
                return httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=current_payload,
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as exc:
                raise AgentProviderFailure("llm_timeout") from exc
            except httpx.HTTPError as exc:
                raise AgentProviderFailure("llm_transport_error") from exc

        response = post(payload)
        if response.status_code in {400, 422}:
            tool_catalog = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"]["description"],
                    "parameters": item["function"]["parameters"],
                }
                for item in definitions
            ]
            fallback_messages = list(messages)
            fallback_messages.insert(
                1,
                {
                    "role": "system",
                    "content": (
                        "Native function calling is unavailable. Return exactly one JSON object: "
                        '{"action":"tool","tool_name":"name","arguments":{},'
                        '"answer":""} to use a tool, or '
                        '{"action":"final","answer":"...","citations":[]} when done. '
                        f"Available tools: {json.dumps(tool_catalog, ensure_ascii=False)}"
                    ),
                },
            )
            fallback_payload = {
                "model": self.model_name,
                "temperature": 0,
                "messages": fallback_messages,
                "response_format": {"type": "json_object"},
            }
            response = post(fallback_payload)
            if response.status_code in {400, 422}:
                fallback_payload.pop("response_format")
                response = post(fallback_payload)
        if response.status_code == 429:
            raise AgentProviderFailure("llm_rate_limited")
        if response.status_code >= 500:
            raise AgentProviderFailure("llm_upstream_error")
        if response.status_code >= 400:
            raise AgentProviderFailure("llm_request_rejected")
        try:
            message_payload = response.json()["choices"][0]["message"]
            tool_calls = message_payload.get("tool_calls") or []
            if tool_calls:
                function = tool_calls[0].get("function") or {}
                raw_arguments = function.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_arguments)
                except (TypeError, json.JSONDecodeError):
                    arguments = {}
                return AgentProviderStep(
                    action="tool",
                    answer=str(message_payload.get("content") or ""),
                    tool_name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            content = str(message_payload.get("content") or "").strip()
            if not content:
                raise AgentProviderFailure("llm_empty_response")
            if content.startswith("{"):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and parsed.get("action") in {"final", "tool"}:
                        parsed.setdefault("arguments", {})
                        parsed.setdefault("citations", [])
                        return AgentProviderStep.model_validate(parsed)
                except (json.JSONDecodeError, ValidationError):
                    pass
            return AgentProviderStep(action="final", answer=content)
        except AgentProviderFailure:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise AgentProviderFailure("llm_invalid_json") from exc
