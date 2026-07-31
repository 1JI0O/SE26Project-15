from typing import Any

import httpx

from app.services.agent.provider import CompatibleAgentProvider


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


def test_provider_falls_back_when_native_tools_are_rejected(monkeypatch) -> None:
    payloads: list[dict[str, Any]] = []
    responses = [
        FakeResponse(400, {}),
        FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"action":"tool","tool_name":"search_code",'
                                '"arguments":{"query":"Net"}}'
                            )
                        }
                    }
                ]
            },
        ),
    ]

    def fake_post(*_args, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = CompatibleAgentProvider(
        "https://llm.example/v1",
        "secret",
        "model",
        10,
    )
    step = provider.next_step("Find Net", {"history": []}, [])

    assert step.action == "tool"
    assert step.tool_name == "search_code"
    assert step.arguments == {"query": "Net"}
    assert "tools" in payloads[0]
    assert "tools" not in payloads[1]
    assert payloads[1]["response_format"] == {"type": "json_object"}
