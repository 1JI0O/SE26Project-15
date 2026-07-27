import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app


def _goto_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "repo/utils.py",
            (
                "def helper():\n"
                "    return 1\n\n"
                "def caller():\n"
                "    return helper()\n"
            ),
        )
        archive.writestr(
            "repo/main.py",
            (
                "from utils import helper\n\n"
                "def run():\n"
                "    return helper()\n"
            ),
        )
        archive.writestr(
            "repo/model.py",
            (
                "class Model:\n"
                "    def encode(self, x):\n"
                "        return self.proj(x)\n\n"
                "    def forward(self, x):\n"
                "        return self.encode(x)\n"
            ),
        )
    return buffer.getvalue()


def _upload_project(client: TestClient, name: str) -> int:
    project = client.post("/api/v1/projects", json={"name": name})
    assert project.status_code == 201
    return project.json()["id"]


def test_resolve_same_file_function_definition() -> None:
    with TestClient(app) as client:
        project_id = _upload_project(client, "goto same file")
        upload = client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("repo.zip", _goto_zip(), "application/zip")},
        )
        assert upload.status_code == 201
        response = client.post(
            f"/api/v1/projects/{project_id}/workspace/resolve-definition",
            json={"path": "utils.py", "line": 5, "column": 11, "identifier": "helper"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "resolved"
    assert payload["path"] == "utils.py"
    assert payload["line_start"] == 1


def test_resolve_imported_function_definition() -> None:
    with TestClient(app) as client:
        project_id = _upload_project(client, "goto import")
        client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("repo.zip", _goto_zip(), "application/zip")},
        )
        response = client.post(
            f"/api/v1/projects/{project_id}/workspace/resolve-definition",
            json={"path": "main.py", "line": 4, "column": 11, "identifier": "helper"},
        )
    payload = response.json()
    assert payload["status"] == "resolved"
    assert payload["path"] == "utils.py"
    assert payload["symbol_id"].endswith("helper")


def test_resolve_self_method_definition() -> None:
    with TestClient(app) as client:
        project_id = _upload_project(client, "goto self method")
        client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("repo.zip", _goto_zip(), "application/zip")},
        )
        response = client.post(
            f"/api/v1/projects/{project_id}/workspace/resolve-definition",
            json={"path": "model.py", "line": 6, "column": 20, "identifier": "encode"},
        )
    payload = response.json()
    assert payload["status"] == "resolved"
    assert payload["path"] == "model.py"
    assert "encode" in payload["symbol_id"]


def test_materialize_checkout_returns_absolute_path() -> None:
    with TestClient(app) as client:
        project_id = _upload_project(client, "checkout mirror")
        client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("repo.zip", _goto_zip(), "application/zip")},
        )
        first = client.post(f"/api/v1/projects/{project_id}/workspace/materialize-checkout")
        second = client.post(f"/api/v1/projects/{project_id}/workspace/materialize-checkout")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["path"] == second.json()["path"]
    assert first.json()["revision"] == second.json()["revision"]
