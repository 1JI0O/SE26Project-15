from fastapi.testclient import TestClient

from app.main import app


def test_project_routes_cover_confidence_patch_and_crud_contract() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "direct", "description": "before"},
        )
        assert created.status_code == 201
        project = created.json()
        project_id = project["id"]
        assert project["agent_deep_thinking"] is False

        listed = client.get("/api/v1/projects")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [project_id]
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 200

        updated = client.patch(
            f"/api/v1/projects/{project_id}",
            json={
                "name": "deep",
                "description": "after",
                "agent_deep_thinking": True,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["agent_deep_thinking"] is True
        assert updated.json()["version"] == project["version"] + 1

        unchanged = client.patch(
            f"/api/v1/projects/{project_id}",
            json={
                "name": "deep",
                "description": "after",
                "agent_deep_thinking": True,
            },
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["version"] == updated.json()["version"]

        invalid = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"agent_deep_thinking": "not-a-boolean"},
        )
        assert invalid.status_code == 422
        assert client.get("/api/v1/projects/999999").status_code == 404

        batch = client.post(
            "/api/v1/projects/batch-delete",
            json={"project_ids": [project_id, 999999]},
        )
        assert batch.status_code == 200
        assert batch.json() == {"deleted_ids": [project_id], "missing_ids": [999999]}

        second = client.post("/api/v1/projects", json={"name": "delete-me"}).json()
        deleted = client.delete(f"/api/v1/projects/{second['id']}")
        assert deleted.status_code == 204
