import io
import json
import zipfile
from pathlib import Path

import pytest

from app.models.entities import IntegrationConfig
from app.services.document_parsers.factory import create_mineru_parser
from app.services.document_parsers.mineru import HttpResponse, MinerUError, MinerUParser
from app.services.document_parsers.mineru_official import (
    OfficialMinerUClient,
    OfficialMinerUSettings,
)


def _archive() -> bytes:
    buffer = io.BytesIO()
    content_v2 = [
        [
            {
                "type": "title",
                "content": {
                    "title_content": [{"type": "text", "content": "Official API Paper"}],
                    "level": 1,
                },
                "bbox": [100, 50, 900, 120],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "Parsed by MinerU API."}
                    ]
                },
                "bbox": [100, 150, 900, 230],
            },
        ]
    ]
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("paper_content_list_v2.json", json.dumps(content_v2))
    return buffer.getvalue()


class FakeOfficialTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.polls = 0

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> HttpResponse:
        self.requests.append((method, url, body, headers or {}))
        if url.endswith("/file-urls/batch"):
            return HttpResponse(
                json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "batch_id": "batch-1",
                            "file_urls": ["https://upload.example/paper.pdf"],
                        },
                    }
                ).encode(),
                "application/json",
            )
        if url == "https://upload.example/paper.pdf":
            return HttpResponse(b"", "application/octet-stream")
        if url.endswith("/extract-results/batch/batch-1"):
            self.polls += 1
            if self.polls == 1:
                return HttpResponse(
                    json.dumps({"code": -60012, "msg": "task not found"}).encode(),
                    "application/json",
                )
            return HttpResponse(
                json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "extract_result": [
                                {
                                    "state": "done",
                                    "full_zip_url": "https://download.example/result.zip",
                                }
                            ]
                        },
                    }
                ).encode(),
                "application/json",
            )
        if url == "https://download.example/result.zip":
            return HttpResponse(_archive(), "application/zip")
        raise AssertionError(f"Unexpected request: {method} {url}")


def test_official_api_upload_poll_download_and_normalize(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    transport = FakeOfficialTransport()
    client = OfficialMinerUClient(
        OfficialMinerUSettings(
            token="test-token",
            poll_interval_seconds=0,
            task_timeout_seconds=1,
        ),
        transport,
    )

    outcome = MinerUParser(client).parse(pdf)

    assert outcome.external_task_id == "batch-1"
    assert outcome.document.title == "Official API Paper"
    assert outcome.document.parser_version == "official-v4"
    upload = next(request for request in transport.requests if request[1].startswith("https://upload"))
    assert upload[3] == {}
    assert "Authorization" not in upload[3]


def test_official_api_requires_token(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    client = OfficialMinerUClient(OfficialMinerUSettings(token=""), FakeOfficialTransport())

    with pytest.raises(MinerUError, match="API_TOKEN"):
        client.submit(pdf)


def test_parser_factory_selects_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    config = IntegrationConfig(
        mineru_provider="official",
        mineru_official_api_token="test-token",
    )
    monkeypatch.setattr(
        "app.services.document_parsers.factory.get_effective_integration_config",
        lambda session: (config, "application"),
    )

    parser = create_mineru_parser()

    assert parser.cache_namespace.startswith("mineru:official:")
