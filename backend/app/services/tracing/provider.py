from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError


class ProviderFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LLMUncertainty(BaseModel):
    level: str = Field(pattern="^(low|medium|high)$")
    reasons: list[str] = Field(default_factory=list, max_length=8)


class LLMExplanation(BaseModel):
    candidate_id: str
    relation_type: str = Field(pattern="^(implements|invokes|configures|tests|mentions)$")
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=5000)
    evidence: list[dict[str, str]] = Field(min_length=2, max_length=8)
    uncertainty: LLMUncertainty


class LLMExplanationBatch(BaseModel):
    items: list[LLMExplanation]


class TraceExplanationProvider(Protocol):
    provider_name: str
    model_name: str

    def explain(self, contexts: list[dict[str, Any]]) -> list[LLMExplanation]: ...


class CompatibleRESTProvider:
    provider_name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout

    def explain(self, contexts: list[dict[str, Any]]) -> list[LLMExplanation]:
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise ProviderFailure("llm_dependency_missing") from exc
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You validate preselected paper-code trace candidates. "
                        "Return one JSON object "
                        "with an items array. Use only supplied refs and verbatim evidence quotes."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"candidates": contexts}, ensure_ascii=False),
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
            raise ProviderFailure("llm_timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure("llm_transport_error") from exc
        if response.status_code == 429:
            raise ProviderFailure("llm_rate_limited")
        if response.status_code >= 500:
            raise ProviderFailure("llm_upstream_error")
        if response.status_code >= 400:
            raise ProviderFailure("llm_request_rejected")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return LLMExplanationBatch.model_validate(parsed).items
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise ProviderFailure("llm_invalid_json") from exc
