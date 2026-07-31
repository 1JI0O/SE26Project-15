from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class MCPError(RuntimeError):
    pass


SUPPORTED_SCHEMA_KEYS = {
    "$schema",
    "type",
    "properties",
    "required",
    "additionalProperties",
    "description",
    "title",
    "default",
    "enum",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
}
MAX_MCP_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_MCP_RESULT_BYTES = 200_000
MAX_SCHEMA_DEPTH = 20


def validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
    _depth: int = 0,
) -> None:
    if _depth > MAX_SCHEMA_DEPTH:
        raise MCPError(f"schema_depth_exceeded:{path}")
    unsupported = set(schema) - SUPPORTED_SCHEMA_KEYS
    if unsupported:
        raise MCPError(f"unsupported_schema_keywords:{','.join(sorted(unsupported))}")
    if "enum" in schema and value not in schema["enum"]:
        raise MCPError(f"schema_enum_mismatch:{path}")
    expected = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected not in type_checks:
        raise MCPError(f"unsupported_schema_type:{expected}")
    if not type_checks[expected](value):
        raise MCPError(f"schema_type_mismatch:{path}:{expected}")

    if expected == "object":
        if len(value) > 256:
            raise MCPError(f"schema_object_too_large:{path}")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise MCPError("invalid_object_schema")
        missing = [name for name in required if name not in value]
        if missing:
            raise MCPError(f"schema_required:{path}:{','.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise MCPError(f"schema_extra_fields:{path}:{','.join(sorted(extras))}")
        for name, item in value.items():
            child = properties.get(name)
            if isinstance(child, dict):
                validate_json_schema(item, child, path=f"{path}.{name}", _depth=_depth + 1)
        return

    if expected == "array":
        minimum = int(schema.get("minItems", 0))
        maximum = min(int(schema.get("maxItems", 1000)), 1000)
        if not minimum <= len(value) <= maximum:
            raise MCPError(f"schema_array_length:{path}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_json_schema(
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                    _depth=_depth + 1,
                )
        return

    if expected == "string":
        if len(value) < int(schema.get("minLength", 0)):
            raise MCPError(f"schema_string_too_short:{path}")
        if len(value) > min(int(schema.get("maxLength", 100_000)), 100_000):
            raise MCPError(f"schema_string_too_long:{path}")
        return

    if expected in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise MCPError(f"schema_number_too_small:{path}")
        if "maximum" in schema and value > schema["maximum"]:
            raise MCPError(f"schema_number_too_large:{path}")


def _json_from_response(response: Any) -> dict[str, Any]:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_MCP_RESPONSE_BYTES:
                raise MCPError("mcp_response_too_large")
        except ValueError as exc:
            raise MCPError("invalid_mcp_content_length") from exc
    if len(response.content) > MAX_MCP_RESPONSE_BYTES:
        raise MCPError("mcp_response_too_large")
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        payload = response.json()
        if not isinstance(payload, dict):
            raise MCPError("invalid_mcp_response")
        return payload
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = json.loads(line.removeprefix("data:").strip())
        if isinstance(payload, dict):
            return payload
    raise MCPError("empty_mcp_event_stream")


def _bounded_result(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_MCP_RESULT_BYTES:
        raise MCPError("mcp_result_too_large")
    return payload


@dataclass(frozen=True)
class MCPServerConfig:
    server_id: str
    url: str
    headers: dict[str, str]
    timeout_seconds: float = 15.0


class MCPHttpClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.session_id: str | None = None
        self._request_id = 0

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise MCPError("mcp_http_dependency_missing") from exc
        self._request_id += 1
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            **self.config.headers,
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        try:
            response = httpx.post(
                self.config.url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": method,
                    "params": params or {},
                },
                timeout=self.config.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise MCPError("mcp_timeout") from exc
        except httpx.HTTPError as exc:
            raise MCPError("mcp_transport_error") from exc
        if response.status_code >= 400:
            raise MCPError(f"mcp_http_{response.status_code}")
        self.session_id = response.headers.get("mcp-session-id", self.session_id)
        payload = _json_from_response(response)
        if payload.get("error"):
            error = payload["error"]
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise MCPError(f"mcp_remote_error:{code}")
        result = payload.get("result", {})
        if not isinstance(result, dict):
            raise MCPError("invalid_mcp_result")
        return result

    def _notification(self, method: str) -> None:
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise MCPError("mcp_http_dependency_missing") from exc
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            **self.config.headers,
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        try:
            response = httpx.post(
                self.config.url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": method},
                timeout=self.config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise MCPError("mcp_transport_error") from exc
        if response.status_code >= 400:
            raise MCPError(f"mcp_http_{response.status_code}")

    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "TraceLab", "version": "0.2.0"},
            },
        )
        self._notification("notifications/initialized")

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self._request("tools/list")
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPError("invalid_mcp_tool_list")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_json_schema(arguments, input_schema)
        self.initialize()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise MCPError("mcp_tool_failed")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            if output_schema:
                validate_json_schema(structured, output_schema)
            return _bounded_result(structured)
        content = result.get("content", [])
        text = "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
        return _bounded_result({"content": text[:100_000]})
