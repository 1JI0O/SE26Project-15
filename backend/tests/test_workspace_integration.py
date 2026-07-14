import io
import zipfile

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.main import app


def _build_sample_pdf() -> bytes:
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(buffer)
    return buffer.getvalue()


def _build_sample_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "demo-repo/models/net.py",
            "\n".join(
                [
                    "import torch.nn as nn",
                    "",
                    "class DemoBlock(nn.Module):",
                    "    def forward(self, x):",
                    "        return x",
                ]
            ),
        )
        archive.writestr("demo-repo/train.py", "def train_one_epoch():\n    return 0\n")
        archive.writestr("demo-repo/weights/model.pt", "fake-weights")
        archive.writestr("demo-repo/.DS_Store", "ignored")
    return buffer.getvalue()


def test_workspace_minimal_closed_loop() -> None:
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={"name": "闭环演示项目", "description": "workspace integration test"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]

        paper_pdf = _build_sample_pdf()
        upload_paper = client.post(
            f"/api/v1/projects/{project_id}/paper",
            files={"file": ("paper.pdf", paper_pdf, "application/pdf")},
        )
        assert upload_paper.status_code == 201

        upload_code = client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("repo.zip", _build_sample_zip(), "application/zip")},
        )
        assert upload_code.status_code == 201
        code_payload = upload_code.json()
        assert any(item["path"] == "models/net.py" for item in code_payload["file_tree"])

        paper_pages = client.get(f"/api/v1/projects/{project_id}/workspace/paper-pages")
        assert paper_pages.status_code == 200
        assert paper_pages.json()

        code_tree = client.get(f"/api/v1/projects/{project_id}/workspace/code-tree")
        assert code_tree.status_code == 200
        assert code_tree.json()[0]["kind"] == "folder"

        code_file = client.get(
            f"/api/v1/projects/{project_id}/workspace/code-files/models/net.py",
        )
        assert code_file.status_code == 200
        assert "DemoBlock" in code_file.json()["content"]

        save_file = client.put(
            f"/api/v1/projects/{project_id}/workspace/code-files/models/net.py",
            json={"content": "class DemoBlock:\n    pass\n"},
        )
        assert save_file.status_code == 200
        assert save_file.json()["status"] == "accepted"
        assert save_file.json()["repository_revision"] == 2
        assert save_file.json()["stale_trace_count"] == 0

        saved_file = client.get(
            f"/api/v1/projects/{project_id}/workspace/code-files/models/net.py",
        )
        assert saved_file.status_code == 200
        assert "pass" in saved_file.json()["content"]

        trace_matrix = client.get(f"/api/v1/projects/{project_id}/workspace/trace-matrix")
        assert trace_matrix.status_code == 200

        blocked_file = client.get(
            f"/api/v1/projects/{project_id}/workspace/code-files/weights/model.pt",
        )
        assert blocked_file.status_code == 415
