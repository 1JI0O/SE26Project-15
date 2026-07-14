import io
import json
import zipfile
from pathlib import Path

from app.services.document_parsers.mineru import (
    HttpResponse,
    MinerUClient,
    MinerUParser,
    MinerUSettings,
    MinerUTimeoutError,
)


class FakeTransport:
    def __init__(self, result: HttpResponse) -> None:
        self.result = result
        self.requests: list[tuple[str, str, bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> HttpResponse:
        self.requests.append((method, url, body))
        if url.endswith("/health"):
            return HttpResponse(
                json.dumps({"protocol_version": "3-test"}).encode(),
                "application/json",
            )
        if method == "POST" and url.endswith("/tasks"):
            assert body is not None and b'filename="sample.pdf"' in body
            return HttpResponse(json.dumps({"task_id": "mineru-1"}).encode(), "application/json")
        if url.endswith("/tasks/mineru-1/result"):
            return self.result
        return HttpResponse(json.dumps({"status": "completed"}).encode(), "application/json")


def _result_archive() -> bytes:
    buffer = io.BytesIO()
    content = [
        {
            "type": "title",
            "text": "MinerU Parsed Paper",
            "text_level": 1,
            "bbox": [100, 100, 900, 180],
            "page_idx": 0,
        },
        {
            "type": "text",
            "text": "Parsed paragraph.",
            "bbox": [100, 220, 900, 300],
            "page_idx": 0,
        },
    ]
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("sample/sample_content_list.json", json.dumps(content))
    return buffer.getvalue()


def test_mineru_parser_uses_async_api_and_decodes_result_zip(tmp_path: Path) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    transport = FakeTransport(HttpResponse(_result_archive(), "application/zip"))
    client = MinerUClient(
        MinerUSettings(poll_interval_seconds=0, task_timeout_seconds=1),
        transport=transport,  # type: ignore[arg-type]
    )

    outcome = MinerUParser(client).parse(pdf)

    assert outcome.external_task_id == "mineru-1"
    assert outcome.raw_archive is not None
    assert outcome.document.title == "MinerU Parsed Paper"
    assert [method for method, _, _ in transport.requests] == ["GET", "POST", "GET", "GET"]


def test_mineru_client_times_out_pending_task() -> None:
    transport = FakeTransport(HttpResponse(b"{}", "application/json"))
    client = MinerUClient(
        MinerUSettings(poll_interval_seconds=0, task_timeout_seconds=0),
        transport=transport,  # type: ignore[arg-type]
    )

    try:
        client.wait("mineru-1")
    except MinerUTimeoutError as exc:
        assert "exceeded" in str(exc)
    else:
        raise AssertionError("Expected a pending MinerU task to time out")
