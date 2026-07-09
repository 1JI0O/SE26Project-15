from fastapi.testclient import TestClient

from app.main import app


def test_read_workspace_placeholder() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/projects/prototype/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "prototype"
    assert data["paper_pages"]
    assert data["code_files"]
    assert data["trace_rows"]
    assert data["flow_nodes"]
    assert data["conflict_items"]
    assert data["report_cards"]


def test_read_workspace_code_file_by_path() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/projects/prototype/workspace/code-files/models/resnet.py")

    assert response.status_code == 200
    data = response.json()
    assert data["path"] == "models/resnet.py"
    assert "BasicBlock" in data["content"]
    assert data["linked_lines"]


def test_read_workspace_code_file_not_found() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/projects/prototype/workspace/code-files/missing.py")

    assert response.status_code == 404


def test_start_workspace_analysis_placeholder() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/projects/prototype/workspace/analyze",
            json={"mode": "trace-only", "targets": ["models/resnet.py"]},
        )

    assert response.status_code == 202
    data = response.json()
    assert data["project_id"] == "prototype"
    assert data["status"] == "queued"
    assert data["job_id"].startswith("placeholder-")
