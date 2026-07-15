import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.document_parsers.base import ParseOutcome
from app.services.document_parsers.jobs import PaperParsingService, get_paper_parsing_service
from app.services.document_parsers.stub import StubParser


class MarkdownArchiveStub(StubParser):
    cache_namespace = "stub:markdown-v1"

    def parse(self, path: Path) -> ParseOutcome:
        outcome = super().parse(path)
        image_name = f"{'a' * 64}.jpg"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "sample/auto/sample.md",
                f"# Structured Paper\n\n![](images/{image_name})\n\n## 1. Intro\n\nBody.",
            )
            archive.writestr(f"sample/auto/images/{image_name}", b"jpeg-test")
        outcome.raw_archive = buffer.getvalue()
        return outcome


def test_paper_job_api_returns_status_and_persists_result(tmp_path: Path) -> None:
    service = PaperParsingService(StubParser(), root=tmp_path / "paper-jobs")
    app.dependency_overrides[get_paper_parsing_service] = lambda: service
    try:
        with TestClient(app) as client:
            project = client.post(
                "/api/v1/projects",
                json={"name": "MinerU job demo", "description": "test"},
            )
            project_id = project.json()["id"]
            submitted = client.post(
                f"/api/v1/projects/{project_id}/paper-jobs",
                files={"file": ("paper.pdf", b"%PDF-stub", "application/pdf")},
            )
            assert submitted.status_code == 202
            job_id = submitted.json()["id"]

            deadline = time.monotonic() + 2
            status_response = None
            while time.monotonic() < deadline:
                status_response = client.get(f"/api/v1/projects/{project_id}/paper-jobs/{job_id}")
                if status_response.json()["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.01)

            assert status_response is not None
            assert status_response.json()["status"] == "succeeded"
            assert status_response.json()["document_id"] is not None

            pages = client.get(f"/api/v1/projects/{project_id}/workspace/paper-pages")
            assert pages.status_code == 200
            assert pages.json()[0]["anchors"][0]["id"] == "p1-b1"

            paper_document = client.get(
                f"/api/v1/projects/{project_id}/workspace/paper-document"
            )
            assert paper_document.status_code == 200
            assert paper_document.json()["source"] == "normalized-fallback"
            assert paper_document.json()["markdown"].startswith("# TraceLab Stub Paper")
            assert paper_document.json()["sections"][0]["id"] == "section-1"

            result = client.get(f"/api/v1/projects/{project_id}/paper-jobs/{job_id}/result")
            assert result.status_code == 200
            assert result.json()["parser"] == "stub"
            assert result.json()["pages"][0]["blocks"][0]["bbox"]
            assert result.json()["document"]["parser"] == "stub"
            assert result.json()["document"]["content_hash"]
    finally:
        app.dependency_overrides.pop(get_paper_parsing_service, None)


def test_paper_job_api_rejects_empty_pdf(tmp_path: Path) -> None:
    service = PaperParsingService(StubParser(), root=tmp_path / "paper-jobs")
    app.dependency_overrides[get_paper_parsing_service] = lambda: service
    try:
        with TestClient(app) as client:
            project_id = client.post(
                "/api/v1/projects",
                json={"name": "Empty PDF", "description": "test"},
            ).json()["id"]
            response = client.post(
                f"/api/v1/projects/{project_id}/paper-jobs",
                files={"file": ("paper.pdf", b"", "application/pdf")},
            )
        assert response.status_code == 400
        assert response.json()["detail"] == "PDF file is empty"
    finally:
        app.dependency_overrides.pop(get_paper_parsing_service, None)


def test_paper_document_serves_mineru_markdown_and_assets(tmp_path: Path) -> None:
    service = PaperParsingService(MarkdownArchiveStub(), root=tmp_path / "paper-jobs")
    app.dependency_overrides[get_paper_parsing_service] = lambda: service
    try:
        with TestClient(app) as client:
            project_id = client.post(
                "/api/v1/projects",
                json={"name": "Structured paper", "description": "test"},
            ).json()["id"]
            submitted = client.post(
                f"/api/v1/projects/{project_id}/paper-jobs",
                files={"file": ("paper.pdf", b"%PDF-stub", "application/pdf")},
            )
            job_id = submitted.json()["id"]
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/projects/{project_id}/paper-jobs/{job_id}")
                if job.json()["status"] == "succeeded":
                    break
                time.sleep(0.01)

            document = client.get(
                f"/api/v1/projects/{project_id}/workspace/paper-document"
            )
            assert document.status_code == 200
            assert document.json()["source"] == "mineru-markdown"
            assert document.json()["sections"][1]["level"] == 2

            image_name = f"{'a' * 64}.jpg"
            asset = client.get(
                f"/api/v1/projects/{project_id}/paper/assets/images/{image_name}"
            )
            assert asset.status_code == 200
            assert asset.content == b"jpeg-test"
            assert asset.headers["content-type"] == "image/jpeg"
    finally:
        app.dependency_overrides.pop(get_paper_parsing_service, None)
