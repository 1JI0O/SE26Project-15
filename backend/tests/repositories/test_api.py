import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app


def _sample_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "repo/block.py",
            (
                "import torch.nn as nn\n\n"
                "class Block(nn.Module):\n"
                "    def forward(self, x):\n"
                "        out = self.conv(x)\n"
                "        return out + x\n"
            ),
        )
    return buffer.getvalue()


def _single_file_zip(content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("repo/model.py", content)
    return buffer.getvalue()


def test_repository_analysis_and_layout_endpoints_return_real_graph() -> None:
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "张量图 API 测试"})
        project_id = project.json()["id"]
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("repo.zip", _sample_zip(), "application/zip")},
        )
        analysis = client.get(f"/api/v1/projects/{project_id}/code/analysis")
        layout = client.get(f"/api/v1/projects/{project_id}/workspace/tensor-flow")

    assert uploaded.status_code == 201
    assert uploaded.json()["summary"]["symbol_count"] == 2
    assert uploaded.json()["tensor_graph"]["nodes"]
    assert analysis.status_code == 200
    assert any(node["op"] == "add" for node in analysis.json()["tensor_graph"]["nodes"])
    assert layout.status_code == 200
    assert layout.json()["renderer"] == "architecture-dag-v2"
    assert layout.json()["view"] == "architecture"
    assert layout.json()["analysis_status"] == "ready"
    assert layout.json()["nodes"]

    with TestClient(app) as client:
        debug_layout = client.get(
            f"/api/v1/projects/{project_id}/workspace/tensor-flow",
            params={"view": "debug"},
        )
    assert debug_layout.status_code == 200
    assert debug_layout.json()["renderer"] == "semantic-dag-v1"
    assert debug_layout.json()["nodes"]


def test_invalid_zip_has_clear_client_error() -> None:
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "非法 ZIP 测试"})
        response = client.post(
            f"/api/v1/projects/{project.json()['id']}/code",
            files={"file": ("bad.zip", b"not a zip", "application/zip")},
        )
    assert response.status_code == 400
    assert "Invalid ZIP archive" in response.json()["detail"]


def test_replacing_repository_does_not_reuse_previous_edit_overlay() -> None:
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "仓库编辑隔离测试"})
        project_id = project.json()["id"]
        client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("first.zip", _single_file_zip("VALUE = 1\n"), "application/zip")},
        )
        saved = client.put(
            f"/api/v1/projects/{project_id}/workspace/code-files/model.py",
            json={"content": "VALUE = 'edited'\n"},
        )
        replaced = client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("second.zip", _single_file_zip("VALUE = 2\n"), "application/zip")},
        )
        current = client.get(f"/api/v1/projects/{project_id}/workspace/code-files/model.py")

    assert saved.status_code == 200
    assert replaced.status_code == 201
    assert current.status_code == 200
    assert current.json()["content"] == "VALUE = 2\n"


def test_openapi_operation_ids_are_unique() -> None:
    operation_ids = [
        operation["operationId"]
        for path in app.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))


def test_main_router_exposes_agent_contract() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/projects/{project_id}/agent/query" in paths
    assert "/api/v1/projects/{project_id}/agent/confirmations/{confirmation_id}/decision" in paths
