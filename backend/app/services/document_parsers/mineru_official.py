import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.services.document_parsers.mineru import (
    HttpResponse,
    MinerUClientProtocol,
    MinerUError,
    MinerUTimeoutError,
    MinerUTransportProtocol,
    MinerUUnavailableError,
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class OfficialMinerUSettings:
    base_url: str = "https://mineru.net/api/v4"
    token: str = field(default="", repr=False)
    model: str = "vlm"
    language: str = "ch"
    ocr: bool = True
    formula_enable: bool = True
    table_enable: bool = True
    request_timeout_seconds: float = 60.0
    request_retries: int = 3
    task_timeout_seconds: float = 600.0
    poll_interval_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "OfficialMinerUSettings":
        defaults = cls()
        return cls(
            base_url=os.getenv("TRACELAB_MINERU_API_URL", defaults.base_url).rstrip("/"),
            token=os.getenv("TRACELAB_MINERU_API_TOKEN", ""),
            model=os.getenv("TRACELAB_MINERU_API_MODEL", defaults.model),
            language=os.getenv("TRACELAB_MINERU_LANGUAGE", defaults.language),
            ocr=_env_bool("TRACELAB_MINERU_API_OCR", defaults.ocr),
            formula_enable=_env_bool("TRACELAB_MINERU_FORMULA_ENABLE", defaults.formula_enable),
            table_enable=_env_bool("TRACELAB_MINERU_TABLE_ENABLE", defaults.table_enable),
            request_timeout_seconds=float(
                os.getenv("TRACELAB_MINERU_REQUEST_TIMEOUT", defaults.request_timeout_seconds)
            ),
            request_retries=int(
                os.getenv("TRACELAB_MINERU_REQUEST_RETRIES", defaults.request_retries)
            ),
            task_timeout_seconds=float(
                os.getenv("TRACELAB_MINERU_TASK_TIMEOUT", defaults.task_timeout_seconds)
            ),
            poll_interval_seconds=float(
                os.getenv("TRACELAB_MINERU_POLL_INTERVAL", defaults.poll_interval_seconds)
            ),
        )


class HttpxMinerUTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> HttpResponse:
        try:
            response = httpx.request(
                method,
                url,
                content=body,
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MinerUUnavailableError(f"MinerU request failed: {exc}") from exc
        return HttpResponse(
            body=response.content,
            content_type=response.headers.get("Content-Type", "application/octet-stream"),
        )


class OfficialMinerUClient(MinerUClientProtocol):
    def __init__(
        self,
        settings: OfficialMinerUSettings | None = None,
        transport: MinerUTransportProtocol | None = None,
    ) -> None:
        self.settings = settings or OfficialMinerUSettings.from_env()
        self.transport = transport or HttpxMinerUTransport()
        self.cache_namespace = ":".join(
            (
                "official",
                self.settings.model,
                self.settings.language,
                str(self.settings.ocr).lower(),
                str(self.settings.formula_enable).lower(),
                str(self.settings.table_enable).lower(),
            )
        )
        self._result_urls: dict[str, str] = {}

    def health(self) -> dict[str, Any]:
        return {"version": "official-v4", "provider": "official"}

    def submit(self, path: Path) -> str:
        if not self.settings.token:
            raise MinerUError("TRACELAB_MINERU_API_TOKEN is required for official MinerU API")
        payload = {
            "files": [{"name": path.name, "is_ocr": self.settings.ocr}],
            "model_version": self.settings.model,
            "enable_formula": self.settings.formula_enable,
            "enable_table": self.settings.table_enable,
            "language": self.settings.language,
        }
        data = self._api_data(
            "POST",
            "/file-urls/batch",
            body=json.dumps(payload).encode("utf-8"),
        )
        batch_id = data.get("batch_id")
        upload_urls = data.get("file_urls")
        if not batch_id or not isinstance(upload_urls, list) or not upload_urls:
            raise MinerUError("Official MinerU response has no batch ID or upload URL")
        self._request(
            "PUT",
            str(upload_urls[0]),
            body=path.read_bytes(),
        )
        return str(batch_id)

    def wait(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.task_timeout_seconds
        while time.monotonic() < deadline:
            try:
                payload = self._api_payload("GET", f"/extract-results/batch/{task_id}")
            except MinerUUnavailableError:
                time.sleep(self.settings.poll_interval_seconds)
                continue
            code = payload.get("code", 0)
            if str(code) == "-60012":
                time.sleep(self.settings.poll_interval_seconds)
                continue
            data = self._payload_data(payload)
            results = data.get("extract_result", [])
            if not isinstance(results, list) or not results:
                time.sleep(self.settings.poll_interval_seconds)
                continue
            result = results[0]
            if not isinstance(result, dict):
                raise MinerUError("Official MinerU task result is not an object")
            state = str(result.get("state", "")).lower()
            if state == "done":
                result_url = result.get("full_zip_url")
                if not result_url:
                    raise MinerUError("Official MinerU completed without a result URL")
                self._result_urls[task_id] = str(result_url)
                return result
            if state == "failed":
                detail = result.get("err_msg") or result.get("err_code") or state
                raise MinerUError(f"Official MinerU task failed: {detail}")
            time.sleep(self.settings.poll_interval_seconds)
        raise MinerUTimeoutError(
            f"Official MinerU task {task_id} exceeded "
            f"{self.settings.task_timeout_seconds:g} seconds"
        )

    def result(self, task_id: str) -> HttpResponse:
        result_url = self._result_urls.get(task_id)
        if result_url is None:
            self.wait(task_id)
            result_url = self._result_urls[task_id]
        return self._request(
            "GET",
            result_url,
        )

    def _api_data(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
    ) -> dict[str, Any]:
        return self._payload_data(self._api_payload(method, path, body=body))

    def _api_payload(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            method,
            f"{self.settings.base_url}{path}",
            body=body,
            headers={
                "Authorization": f"Bearer {self.settings.token}",
                "Content-Type": "application/json",
                "Source": "tracelab",
            },
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise MinerUError("Official MinerU response is not an object")
        return payload

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        attempts = max(1, self.settings.request_retries)
        for attempt in range(1, attempts + 1):
            try:
                return self.transport.request(
                    method,
                    url,
                    body=body,
                    headers=headers,
                    timeout=self.settings.request_timeout_seconds,
                )
            except MinerUUnavailableError:
                if attempt == attempts:
                    raise
                time.sleep(min(float(attempt), 3.0))
        raise AssertionError("unreachable")

    @staticmethod
    def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
        code = payload.get("code", 0)
        if code != 0:
            detail = payload.get("msg") or "unknown API error"
            raise MinerUError(f"Official MinerU API error {code}: {detail}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MinerUError("Official MinerU response has no data object")
        return data
