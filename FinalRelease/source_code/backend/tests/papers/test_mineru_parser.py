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
            assert b'name="return_images"\r\n\r\ntrue' in body
            # middle.json is the only source of page_size and line boxes, which the PDF
            # reader needs for sentence-level highlighting.
            assert b'name="return_middle_json"\r\n\r\ntrue' in body
            return HttpResponse(json.dumps({"task_id": "mineru-1"}).encode(), "application/json")
        if url.endswith("/tasks/mineru-1/result"):
            return self.result
        return HttpResponse(json.dumps({"status": "completed"}).encode(), "application/json")


def _result_archive(*, with_middle_json: bool = False) -> bytes:
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
        if with_middle_json:
            middle = {
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "page_size": [1000.0, 1000.0],
                        "para_blocks": [
                            {
                                "type": "text",
                                "lines": [
                                    {
                                        "bbox": [100, 220, 900, 300],
                                        "spans": [
                                            {"type": "text", "content": "Parsed paragraph."},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
            archive.writestr("sample/sample_middle.json", json.dumps(middle))
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


def test_mineru_parser_folds_middle_json_into_page_geometry(tmp_path: Path) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    transport = FakeTransport(
        HttpResponse(_result_archive(with_middle_json=True), "application/zip")
    )
    client = MinerUClient(
        MinerUSettings(poll_interval_seconds=0, task_timeout_seconds=1),
        transport=transport,  # type: ignore[arg-type]
    )

    outcome = MinerUParser(client).parse(pdf)

    blocks = outcome.document.to_dict()["pages"][0]["blocks"]
    paragraph = next(block for block in blocks if block["text"] == "Parsed paragraph.")
    assert paragraph["lines"] == [{"text": "Parsed paragraph.", "bbox": [0.1, 0.22, 0.9, 0.3]}]


def test_mineru_parser_without_middle_json_still_parses(tmp_path: Path) -> None:
    """An archive with no middle.json degrades to block-level geometry, never fails."""

    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-test")
    transport = FakeTransport(HttpResponse(_result_archive(), "application/zip"))
    client = MinerUClient(
        MinerUSettings(poll_interval_seconds=0, task_timeout_seconds=1),
        transport=transport,  # type: ignore[arg-type]
    )

    outcome = MinerUParser(client).parse(pdf)

    blocks = outcome.document.to_dict()["pages"][0]["blocks"]
    assert all(block["lines"] == [] for block in blocks)
    assert blocks[0]["bbox"] == [0.1, 0.1, 0.9, 0.18]


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


def test_local_mineru_defaults_to_supported_pipeline_backend() -> None:
    assert MinerUSettings().backend == "pipeline"
