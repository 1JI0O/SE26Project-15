import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.document_parsers.jobs import PaperParsingService, get_paper_parsing_service
from app.services.document_parsers.stub import StubParser


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
