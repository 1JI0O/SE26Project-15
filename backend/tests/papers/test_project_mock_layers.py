"""进阶：对 TraceLab 论文解析层做 Mock 单元测试。

对应课程「在某一层创建 Mock 对象并验证行为」：
- 被测层：MinerUParser / PaperParsingService（业务编排层）
- Mock 层：MinerUClient / DocumentParser（下层依赖）
- 工具：unittest.mock（Python 生态对标 Java Mockito）
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.document_parsers.base import ParseOutcome
from app.services.document_parsers.jobs import PaperParsingService
from app.services.document_parsers.mineru import HttpResponse, MinerUParser
from app.services.document_parsers.normalizer import normalize_mineru_payload


def _minimal_content_list() -> list[dict]:
    return [
        {
            "type": "title",
            "content": {"title_content": "Mocked Paper", "level": 1},
            "bbox": [100, 100, 900, 180],
            "page_idx": 0,
        },
        {
            "type": "paragraph",
            "content": {"paragraph_content": "Hello from mocked MinerU client."},
            "bbox": [100, 220, 900, 300],
            "page_idx": 0,
        },
    ]


def _wait_job(service: PaperParsingService, job_id: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.get(job_id)
        assert job is not None
        if job.status in {"succeeded", "failed"}:
            return job.status
        time.sleep(0.01)
    raise AssertionError("paper parse job did not finish")


class TestMinerUParserWithMockedClient:
    """Parser 层单元测试：Mock 掉 MinerUClient，不发起真实 HTTP。"""

    def test_parse_orchestrates_health_submit_wait_result(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-mock")

        mock_client = MagicMock()
        mock_client.cache_namespace = "mock-client:v1"
        mock_client.health.return_value = {"version": "mock-3"}
        mock_client.submit.return_value = "task-mock-1"
        mock_client.wait.return_value = {"status": "completed"}
        mock_client.result.return_value = HttpResponse(
            body=json.dumps(_minimal_content_list()).encode("utf-8"),
            content_type="application/json",
        )

        parser = MinerUParser(client=mock_client)
        outcome = parser.parse(pdf)

        assert outcome.external_task_id == "task-mock-1"
        assert outcome.document.title == "Mocked Paper"
        assert "mocked MinerU" in outcome.document.abstract
        assert outcome.raw_archive is None

        mock_client.health.assert_called_once_with()
        mock_client.submit.assert_called_once_with(pdf)
        mock_client.wait.assert_called_once_with("task-mock-1")
        mock_client.result.assert_called_once_with("task-mock-1")
        assert mock_client.method_calls == [
            call.health(),
            call.submit(pdf),
            call.wait("task-mock-1"),
            call.result("task-mock-1"),
        ]

    def test_parse_rejects_missing_or_empty_pdf_without_calling_client(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "gone.pdf"
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")

        mock_client = MagicMock()
        mock_client.cache_namespace = "mock-client:v1"
        parser = MinerUParser(client=mock_client)

        with pytest.raises(ValueError, match="empty or missing"):
            parser.parse(missing)
        with pytest.raises(ValueError, match="empty or missing"):
            parser.parse(empty)

        mock_client.health.assert_not_called()
        mock_client.submit.assert_not_called()

    def test_parse_propagates_client_errors(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-mock")

        mock_client = MagicMock()
        mock_client.cache_namespace = "mock-client:v1"
        mock_client.health.return_value = {"version": "x"}
        mock_client.submit.side_effect = RuntimeError("MinerU offline")

        parser = MinerUParser(client=mock_client)
        with pytest.raises(RuntimeError, match="MinerU offline"):
            parser.parse(pdf)

        mock_client.wait.assert_not_called()
        mock_client.result.assert_not_called()


class TestPaperParsingServiceWithMockedParser:
    """Service 层单元测试：Mock 掉 DocumentParser，验证任务编排与失败记录。"""

    def test_submit_calls_mocked_parser_and_persists_success(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-service-mock")

        document = normalize_mineru_payload(
            _minimal_content_list(),
            filename="paper.pdf",
            parser_version="mock-parser",
        )
        document.parser = "mock-parser"

        mock_parser = MagicMock()
        mock_parser.name = "mock-parser"
        mock_parser.cache_namespace = "mock-parser:v1"
        mock_parser.parse.return_value = ParseOutcome(
            document=document,
            raw_payload=_minimal_content_list(),
            external_task_id="ext-1",
        )

        service = PaperParsingService(parser=mock_parser, root=tmp_path / "jobs")
        job = service.submit(project_id=42, filename="paper.pdf", source_path=pdf)

        assert _wait_job(service, job.id) == "succeeded"
        finished = service.get(job.id)
        assert finished is not None
        assert finished.status == "succeeded"
        assert finished.external_task_id == "ext-1"
        assert finished.cached is False
        mock_parser.parse.assert_called_once_with(pdf)

        result = service.result(job.id)
        assert result is not None
        assert result["title"] == "Mocked Paper"

    def test_submit_records_failure_when_mocked_parser_raises(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-fail")

        mock_parser = MagicMock()
        mock_parser.name = "mock-parser"
        mock_parser.cache_namespace = "mock-parser:v1"
        mock_parser.parse.side_effect = ConnectionError("downstream unavailable")

        service = PaperParsingService(parser=mock_parser, root=tmp_path / "jobs")
        job = service.submit(project_id=1, filename="paper.pdf", source_path=pdf)

        assert _wait_job(service, job.id) == "failed"
        failed = service.get(job.id)
        assert failed is not None
        assert "downstream unavailable" in str(failed.error)
        mock_parser.parse.assert_called_once_with(pdf)


def test_patch_create_mineru_parser_when_constructing_default_service(
    tmp_path: Path,
) -> None:
    """演示用 patch 替换工厂方法：默认构造 Service 时注入 Mock parser。"""
    mock_parser = MagicMock()
    mock_parser.name = "patched"
    mock_parser.cache_namespace = "patched:v1"

    with patch(
        "app.services.document_parsers.jobs.create_mineru_parser",
        return_value=mock_parser,
    ) as factory:
        service = PaperParsingService(root=tmp_path / "jobs")
        factory.assert_called_once_with()
        assert service.parser is mock_parser
