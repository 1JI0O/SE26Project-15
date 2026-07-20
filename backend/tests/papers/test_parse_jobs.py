import time
from pathlib import Path

from app.services.document_parsers.jobs import PaperParsingService
from app.services.document_parsers.stub import StubParser


def _wait(service: PaperParsingService, job_id: str) -> str:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.get(job_id)
        assert job is not None
        if job.status in {"succeeded", "failed"}:
            return job.status
        time.sleep(0.01)
    raise AssertionError("Paper parse job did not finish")


def test_parse_job_saves_raw_normalized_output_and_reuses_cache(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-stub")
    service = PaperParsingService(StubParser(), root=tmp_path / "jobs")

    first = service.submit(1, "paper.pdf", pdf)
    assert _wait(service, first.id) == "succeeded"
    first_result = service.result(first.id)
    assert first_result is not None
    assert first_result["parser"] == "stub"
    assert list((tmp_path / "jobs" / "cache").glob("*.normalized.json"))
    assert list((tmp_path / "jobs" / "cache").glob("*.raw.json"))

    second = service.submit(1, "paper.pdf", pdf)
    assert _wait(service, second.id) == "succeeded"
    cached_job = service.get(second.id)
    assert cached_job is not None and cached_job.cached is True


class FailingParser:
    name = "failing"
    cache_namespace = "failing:v1"

    def parse(self, path: Path):  # type: ignore[no-untyped-def]
        raise ConnectionError("MinerU is offline")


def test_parse_job_records_parser_failure(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-stub")
    service = PaperParsingService(FailingParser(), root=tmp_path / "jobs")  # type: ignore[arg-type]
    job = service.submit(1, "paper.pdf", pdf)

    assert _wait(service, job.id) == "failed"
    failed = service.get(job.id)
    assert failed is not None
    assert "MinerU is offline" in str(failed.error)
