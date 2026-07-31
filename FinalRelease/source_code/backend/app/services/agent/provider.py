from __future__ import annotations

import json
from collections.abc import Callable
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

    def _request_components(
        self,
        message: str,
        context: dict[str, Any],
        tool_results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
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
                            "Use tools when evidence is missing. If tool_results contain an "
                            "error, correct the call instead of repeating it. Return a normal "
                            "final answer when the task is complete."
                        ),
                    },
                    ensure_ascii=False,
                ),
            }
        )
        definitions = context.get("tool_definitions")
        if not isinstance(definitions, list):
            from app.services.agent.tools import tool_definitions

            definitions = tool_definitions()
        return messages, definitions

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
        messages, definitions = self._request_components(message, context, tool_results)
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "messages": messages,
            # Publish payloads (many candidates with quotes/rationale) are large; the provider
            # default output cap truncates them into invalid JSON. Request the max so a full
            # publish call fits in one response.
            "max_tokens": 8192,
        }
        if definitions:
            payload.update(tools=definitions, tool_choice="auto")
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
                "max_tokens": 8192,
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

    def next_step_stream(
        self,
        message: str,
        context: dict[str, Any],
        tool_results: list[dict[str, Any]],
        on_event: Callable[[str, dict[str, Any]], None],
    ) -> AgentProviderStep:
        """Consume OpenAI-compatible SSE while retaining the non-stream fallback."""

        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise AgentProviderFailure("llm_dependency_missing") from exc
        messages, definitions = self._request_components(message, context, tool_results)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "temperature": 0,
            "messages": messages,
            "stream": True,
        }
        if definitions:
            payload.update(tools=definitions, tool_choice="auto")
        if self.thinking_mode:
            payload["thinking"] = {"type": self.thinking_mode}
        content_parts: list[str] = []
        buffered_json: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        reasoning_announced = False
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            ) as response:
                if response.status_code in {400, 422}:
                    return self.next_step(message, context, tool_results)
                if response.status_code == 429:
                    raise AgentProviderFailure("llm_rate_limited")
                if response.status_code >= 500:
                    raise AgentProviderFailure("llm_upstream_error")
                if response.status_code >= 400:
                    raise AgentProviderFailure("llm_request_rejected")
                pending_text = ""
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line.removeprefix("data:").strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        delta = json.loads(raw)["choices"][0].get("delta", {})
                    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                        continue
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning and not reasoning_announced:
                        reasoning_announced = True
                        on_event(
                            "reasoning.summary",
                            {"summary": "模型正在推理并核对当前证据"},
                        )
                    text = str(delta.get("content") or "")
                    if text:
                        content_parts.append(text)
                        pending_text += text
                        leading = "".join(content_parts).lstrip()[:1]
                        if leading == "{":
                            buffered_json.append(text)
                        elif len(pending_text) >= 24 or "\n" in pending_text:
                            on_event("message.delta", {"delta": pending_text})
                            pending_text = ""
                    for call in delta.get("tool_calls") or []:
                        index = int(call.get("index", 0))
                        current = tool_calls.setdefault(index, {"name": "", "arguments": ""})
                        function = call.get("function") or {}
                        current["name"] += str(function.get("name") or "")
                        current["arguments"] += str(function.get("arguments") or "")
                if pending_text and not buffered_json:
                    on_event("message.delta", {"delta": pending_text})
        except AgentProviderFailure:
            raise
        except httpx.TimeoutException as exc:
            raise AgentProviderFailure("llm_timeout") from exc
        except httpx.HTTPError as exc:
            raise AgentProviderFailure("llm_transport_error") from exc

        if tool_calls:
            function = tool_calls[min(tool_calls)]
            try:
                arguments = json.loads(function["arguments"] or "{}")
            except (TypeError, json.JSONDecodeError):
                arguments = {}
            return AgentProviderStep(
                action="tool",
                tool_name=function["name"],
                arguments=arguments,
            )
        content = "".join(content_parts).strip()
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
