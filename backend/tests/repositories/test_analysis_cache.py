import io
import time
import zipfile

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "repo/model.py",
            """import torch.nn as nn

class Model(nn.Module):
    def forward(self, x):
        return x + x
""",
        )
    return buffer.getvalue()


def _wait_for_ready(client: TestClient, project_id: int) -> dict:
    payload: dict = {}
    for _ in range(80):
        response = client.get(f"/api/v1/projects/{project_id}/code/analysis")
        if response.status_code == 200 and response.json().get("tensor_graph", {}).get("nodes"):
            payload = response.json()
            return payload
        time.sleep(0.025)
    raise AssertionError(f"analysis did not complete: {payload}")


def test_large_repository_analysis_runs_in_background_and_persists(monkeypatch) -> None:
    monkeypatch.setattr(settings, "tracelab_analysis_inline_max_bytes", 0)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Background graph"}).json()
        project_id = project["id"]
        upload = client.post(
            f"/api/v1/projects/{project_id}/code",
            files={"file": ("repo.zip", _archive(), "application/zip")},
        )
        assert upload.status_code == 201
        payload = _wait_for_ready(client, project_id)
        graph = client.get(f"/api/v1/projects/{project_id}/workspace/tensor-flow").json()

    assert payload["tensor_graph"]["nodes"]
    assert graph["analysis_status"] == "ready"
    assert graph["renderer"] == "architecture-dag-v2"
    assert graph["nodes"]
