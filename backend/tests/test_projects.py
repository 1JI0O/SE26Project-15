from fastapi.testclient import TestClient

from app.main import app


def test_create_and_list_project() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "接口契约验证项目", "description": "pytest smoke test"},
        )
        listed = client.get("/api/v1/projects")

    assert created.status_code == 201
    assert created.json()["name"] == "接口契约验证项目"
    assert listed.status_code == 200
    assert any(project["id"] == created.json()["id"] for project in listed.json())

