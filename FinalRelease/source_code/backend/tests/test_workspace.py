from fastapi.testclient import TestClient

from app.main import app


def test_read_workspace_placeholder() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/projects/prototype/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "prototype"
    assert data["paper_pages"]
    assert data["code_tree"]
    assert data["code_files"]
    assert data["trace_rows"]
    assert data["flow_nodes"]
    assert data["tensor_flow"]["renderer"] == "trace-svg"
    assert data["conflict_items"]
    assert data["report_cards"]


def test_read_workspace_code_tree_is_filtered_repository_tree() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/projects/prototype/workspace/code-tree")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["kind"] == "folder"
    assert data[0]["name"] == "resnet-reproduction"
    flattened = str(data)
    assert "models/resnet.py" in flattened
    assert ".DS_Store" not in flattened
    assert "__MACOSX" not in flattened


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


def test_save_workspace_code_file_placeholder() -> None:
    with TestClient(app) as client:
        response = client.put(
            "/api/v1/projects/prototype/workspace/code-files/models/resnet.py",
            json={"content": "print('edited in prototype')\n"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["path"] == "models/resnet.py"


def test_read_tensor_flow_placeholder_trace_svg() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/projects/prototype/workspace/tensor-flow")

    assert response.status_code == 200
    data = response.json()
    assert data["renderer"] == "trace-svg"
    assert any(node["id"] == "add" for node in data["nodes"])
    assert any(node["source_path"] == "models/resnet.py" for node in data["nodes"])
    assert all(edge["points"] for edge in data["edges"])


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
    assert data["job_id"].startswith("workspace-")
