import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.document_parsers.base import ParseOutcome
from app.services.document_parsers.normalizer import normalize_mineru_payload


class MinerUError(RuntimeError):
    pass


class MinerUUnavailableError(MinerUError):
    pass


class MinerUTimeoutError(MinerUError):
    pass


@dataclass(frozen=True, slots=True)
class MinerUSettings:
    base_url: str = "http://127.0.0.1:8001"
    backend: str = "pipeline"
    language: str = "ch"
    parse_method: str = "auto"
    request_timeout_seconds: float = 20.0
    task_timeout_seconds: float = 600.0
    poll_interval_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "MinerUSettings":
        defaults = cls()
        return cls(
            base_url=os.getenv("TRACELAB_MINERU_URL", defaults.base_url).rstrip("/"),
            backend=os.getenv("TRACELAB_MINERU_BACKEND", defaults.backend),
            language=os.getenv("TRACELAB_MINERU_LANGUAGE", defaults.language),
            parse_method=os.getenv("TRACELAB_MINERU_PARSE_METHOD", defaults.parse_method),
            request_timeout_seconds=float(
                os.getenv("TRACELAB_MINERU_REQUEST_TIMEOUT", defaults.request_timeout_seconds)
            ),
            task_timeout_seconds=float(
                os.getenv("TRACELAB_MINERU_TASK_TIMEOUT", defaults.task_timeout_seconds)
            ),
            poll_interval_seconds=float(
                os.getenv("TRACELAB_MINERU_POLL_INTERVAL", defaults.poll_interval_seconds)
            ),
        )


@dataclass(slots=True)
class HttpResponse:
    body: bytes
    content_type: str

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class UrllibMinerUTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    body=response.read(),
                    content_type=response.headers.get("Content-Type", "application/octet-stream"),
                )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MinerUUnavailableError(f"MinerU request failed: {exc}") from exc


class MinerUClientProtocol(Protocol):
    cache_namespace: str

    def health(self) -> dict[str, Any]: ...

    def submit(self, path: Path) -> str: ...

    def wait(self, task_id: str) -> dict[str, Any]: ...

    def result(self, task_id: str) -> HttpResponse: ...


class MinerUTransportProtocol(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> HttpResponse: ...


class MinerUClient:
    def __init__(
        self,
        settings: MinerUSettings | None = None,
        transport: MinerUTransportProtocol | None = None,
    ) -> None:
        self.settings = settings or MinerUSettings.from_env()
        self.transport = transport or UrllibMinerUTransport()
        self.cache_namespace = ":".join(
            (
                "local",
                self.settings.backend,
                self.settings.parse_method,
                self.settings.language,
                "assets-v1",
            )
        )

    def health(self) -> dict[str, Any]:
        response = self.transport.request(
            "GET",
            f"{self.settings.base_url}/health",
            timeout=self.settings.request_timeout_seconds,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise MinerUError("MinerU health response is not an object")
        return payload

    def submit(self, path: Path) -> str:
        boundary = f"----TraceLab{uuid.uuid4().hex}"
        body = self._multipart_body(path, boundary)
        response = self.transport.request(
            "POST",
            f"{self.settings.base_url}/tasks",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=self.settings.request_timeout_seconds,
        )
        payload = response.json()
        task_id = payload.get("task_id") if isinstance(payload, dict) else None
        if not task_id:
            raise MinerUError("MinerU submission response does not contain task_id")
        return str(task_id)

    def wait(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.task_timeout_seconds
        while time.monotonic() < deadline:
            response = self.transport.request(
                "GET",
                f"{self.settings.base_url}/tasks/{task_id}",
                timeout=self.settings.request_timeout_seconds,
            )
            payload = response.json()
            if not isinstance(payload, dict):
                raise MinerUError("MinerU task response is not an object")
            state = str(payload.get("status", "")).lower()
            if state in {"completed", "complete", "succeeded", "success", "done"}:
                return payload
            if state in {"failed", "error", "cancelled", "canceled"}:
                detail = payload.get("error") or payload.get("message") or state
                raise MinerUError(f"MinerU task failed: {detail}")
            time.sleep(self.settings.poll_interval_seconds)
        raise MinerUTimeoutError(
            f"MinerU task {task_id} exceeded {self.settings.task_timeout_seconds:g} seconds"
        )

    def result(self, task_id: str) -> HttpResponse:
        return self.transport.request(
            "GET",
            f"{self.settings.base_url}/tasks/{task_id}/result",
            timeout=self.settings.request_timeout_seconds,
        )

    def _multipart_body(self, path: Path, boundary: str) -> bytes:
        line = b"\r\n"
        chunks: list[bytes] = []

        def field(name: str, value: str) -> None:
            chunks.extend(
                [
                    f"--{boundary}".encode(),
                    f'Content-Disposition: form-data; name="{name}"'.encode(),
                    b"",
                    value.encode(),
                ]
            )

        fields = {
            "backend": self.settings.backend,
            "parse_method": self.settings.parse_method,
            "lang_list": self.settings.language,
            "formula_enable": "true",
            "table_enable": "true",
            "return_md": "true",
            "return_content_list": "true",
            "return_middle_json": "false",
            "return_images": "true",
            "response_format_zip": "true",
        }
        for name, value in fields.items():
            field(name, value)
        chunks.extend(
            [
                f"--{boundary}".encode(),
                (f'Content-Disposition: form-data; name="files"; filename="{path.name}"').encode(),
                b"Content-Type: application/pdf",
                b"",
                path.read_bytes(),
                f"--{boundary}--".encode(),
                b"",
            ]
        )
        return line.join(chunks)


class MinerUParser:
    name = "mineru"

    def __init__(self, client: MinerUClientProtocol | None = None) -> None:
        self.client = client or MinerUClient()
        self.cache_namespace = f"{self.name}:{self.client.cache_namespace}"

    def parse(self, path: Path) -> ParseOutcome:
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError("PDF file is empty or missing")
        health = self.client.health()
        task_id = self.client.submit(path)
        self.client.wait(task_id)
        response = self.client.result(task_id)
        payload, archive = _decode_result(response)
        version = str(health.get("version") or health.get("protocol_version") or "unknown")
        document = normalize_mineru_payload(
            payload,
            filename=path.name,
            parser_version=version,
        )
        return ParseOutcome(
            document=document,
            raw_payload=payload,
            raw_archive=archive,
            external_task_id=task_id,
        )


def _decode_result(response: HttpResponse) -> tuple[Any, bytes | None]:
    if "json" in response.content_type:
        return response.json(), None
    try:
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            names = archive.namelist()
            preferred = next(
                (name for name in names if name.endswith("content_list_v2.json")),
                None,
            ) or next((name for name in names if name.endswith("content_list.json")), None)
            if preferred is None:
                raise MinerUError("MinerU result archive has no content list JSON")
            return json.loads(archive.read(preferred).decode("utf-8")), response.body
    except zipfile.BadZipFile as exc:
        raise MinerUError("MinerU result is neither JSON nor a ZIP archive") from exc
