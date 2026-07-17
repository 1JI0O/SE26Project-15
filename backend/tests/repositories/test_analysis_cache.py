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
        response = client.get(f"/api/v1/projects/{project_id}/workspace/tensor-flow")
        assert response.status_code == 200
        payload = response.json()
        if payload["analysis_status"] == "ready":
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
        cached = client.get(f"/api/v1/projects/{project_id}/workspace/tensor-flow").json()

    assert payload["nodes"]
    assert payload["analysis_revision"] == payload["repository_revision"] == 1
    assert cached["analysis_status"] == "ready"
    assert cached["nodes"] == payload["nodes"]
