from collections.abc import Callable

import httpx
import pytest

from tracelab_core.probe import _provider_detail, _truncate, probe_llm, probe_mineru


def _response(status: int, *, json_data: object | None = None, text: str = "") -> httpx.Response:
    request = httpx.Request("GET", "https://provider.test/probe")
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=request)
    return httpx.Response(status, text=text, request=request)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_response(400, text="  plain\n error "), "plain error"),
        (_response(400, json_data={"error": {"message": "nested"}}), "nested"),
        (_response(400, json_data={"error": "direct"}), "direct"),
        (_response(400, json_data={"message": "message"}), "message"),
        (_response(400, json_data=["detail"]), '["detail"]'),
    ],
)
def test_provider_detail_formats_common_error_bodies(
    response: httpx.Response, expected: str
) -> None:
    assert _provider_detail(response) == expected


def test_truncate_normalizes_whitespace_and_limits_length() -> None:
    assert _truncate("a\n  b") == "a b"
    assert len(_truncate("x" * 1000)) == 600


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ({"model": "m", "api_key": "key"}, "missing_base_url"),
        ({"base_url": "https://llm.test", "api_key": "key"}, "missing_model"),
        ({"base_url": "https://llm.test", "model": "m"}, "missing_api_key"),
    ],
)
def test_probe_llm_validates_required_settings(config: dict[str, str], code: str) -> None:
    assert probe_llm(config)["code"] == code


def test_probe_llm_success_sends_openai_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(url=url, **kwargs)
        return _response(200, json_data={"choices": [{"message": {"content": "pong"}}]})

    monkeypatch.setattr(httpx, "post", post)
    result = probe_llm(
        {
            "base_url": "https://llm.test/",
            "api_key": "secret",
            "model": "model-a",
            "timeout_seconds": 4,
            "thinking_mode": "enabled",
        }
    )

    assert result["ok"] is True
    assert "返回 4 字符" in result["detail"]
    assert captured["url"] == "https://llm.test/chat/completions"
    assert captured["timeout"] == 4.0
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["thinking"] == {"type": "enabled"}


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (_response(401, json_data={"error": {"message": "bad key"}}), "unauthorized"),
        (_response(429, json_data={"error": "rate limited"}), "http_429"),
        (_response(200, json_data={"unexpected": True}), "unexpected_response"),
    ],
)
def test_probe_llm_handles_provider_responses(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response, code: str
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    result = probe_llm({"base_url": "https://llm.test", "api_key": "key", "model": "model-a"})

    assert result["ok"] is False
    assert result["code"] == code


@pytest.mark.parametrize(
    ("error_factory", "code"),
    [
        (lambda request: httpx.ReadTimeout("late", request=request), "timeout"),
        (lambda request: httpx.ConnectError("offline", request=request), "transport_error"),
    ],
)
def test_probe_llm_handles_network_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_factory: Callable[[httpx.Request], httpx.HTTPError],
    code: str,
) -> None:
    def post(*args: object, **kwargs: object) -> httpx.Response:
        raise error_factory(httpx.Request("POST", "https://llm.test"))

    monkeypatch.setattr(httpx, "post", post)
    result = probe_llm(
        {
            "base_url": "https://llm.test",
            "api_key": "key",
            "model": "model-a",
            "timeout_seconds": 2,
        }
    )
    assert result["code"] == code


def test_probe_mineru_local_requires_base_url() -> None:
    assert probe_mineru({"provider": "local"})["code"] == "missing_base_url"


@pytest.mark.parametrize(
    ("response", "ok", "code"),
    [
        (_response(503, text=" unavailable "), False, "http_503"),
        (_response(200, text=" healthy "), True, "ok"),
    ],
)
def test_probe_mineru_local_handles_http_responses(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
    ok: bool,
    code: str,
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: response)
    result = probe_mineru({"provider": "local", "base_url": "http://mineru.test/"})

    assert result["ok"] is ok
    assert result["code"] == code


@pytest.mark.parametrize(
    ("error_factory", "code"),
    [
        (lambda request: httpx.ReadTimeout("late", request=request), "timeout"),
        (lambda request: httpx.ConnectError("offline", request=request), "transport_error"),
    ],
)
def test_probe_mineru_local_handles_network_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_factory: Callable[[httpx.Request], httpx.HTTPError],
    code: str,
) -> None:
    def get(*args: object, **kwargs: object) -> httpx.Response:
        raise error_factory(httpx.Request("GET", "http://mineru.test/health"))

    monkeypatch.setattr(httpx, "get", get)
    result = probe_mineru(
        {
            "provider": "local",
            "base_url": "http://mineru.test",
            "request_timeout_seconds": 2,
        }
    )
    assert result["code"] == code


def test_probe_mineru_official_requires_token() -> None:
    assert probe_mineru({"provider": "official"})["code"] == "missing_api_token"


@pytest.mark.parametrize(
    ("response", "ok", "code"),
    [
        (_response(403, text="invalid token"), False, "unauthorized"),
        (_response(500, text="failure"), False, "http_500"),
        (_response(404, text="probe batch absent"), True, "ok"),
    ],
)
def test_probe_mineru_official_handles_http_responses(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
    ok: bool,
    code: str,
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: response)
    result = probe_mineru({"provider": "official", "api_token": "token"})

    assert result["ok"] is ok
    assert result["code"] == code


@pytest.mark.parametrize(
    ("error_factory", "code"),
    [
        (lambda request: httpx.ReadTimeout("late", request=request), "timeout"),
        (lambda request: httpx.ConnectError("offline", request=request), "transport_error"),
    ],
)
def test_probe_mineru_official_handles_network_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_factory: Callable[[httpx.Request], httpx.HTTPError],
    code: str,
) -> None:
    def get(*args: object, **kwargs: object) -> httpx.Response:
        raise error_factory(httpx.Request("GET", "https://mineru.test"))

    monkeypatch.setattr(httpx, "get", get)
    result = probe_mineru(
        {
            "provider": "official",
            "base_url": "https://mineru.test/",
            "api_token": "token",
            "request_timeout_seconds": 2,
        }
    )
    assert result["code"] == code
