from io import BytesIO
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient

from app.main import app


def _repository_archive(source: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("main.py", source)
    return buffer.getvalue()


def test_local_project_never_enters_outbox_before_explicit_enable() -> None:
    workspace_id = "11111111-1111-4111-8111-111111111111"
    device_id = "22222222-2222-4222-8222-222222222222"
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects", json={"name": "offline first", "description": "local"}
        ).json()
        project = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"agent_deep_thinking": True},
        ).json()
        before = client.get("/api/v1/local-sync/outbox", params={"workspace_id": workspace_id})
        enabled = client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={
                "workspace_id": workspace_id,
                "device_id": device_id,
                "agent_history_sync": False,
            },
        )
        after = client.get("/api/v1/local-sync/outbox", params={"workspace_id": workspace_id})

    assert project["sync_mode"] == "local_only"
    assert before.json()["operations"] == []
    assert enabled.status_code == 200
    assert len(after.json()["operations"]) == 1
    assert after.json()["operations"][0]["entity_type"] == "project"
    assert after.json()["operations"][0]["payload"]["agent_deep_thinking"] is True


def test_paused_project_is_device_local_and_suppresses_outbox() -> None:
    workspace_id = "33333333-3333-4333-8333-333333333333"
    device_id = "44444444-4444-4444-8444-444444444444"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "mode test"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        # Mark the initial project operation as delivered so only mode changes
        # are observed below.
        initial = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"][0]
        client.post(
            "/api/v1/local-sync/outbox/results",
            json={
                "results": [
                    {
                        "client_operation_id": initial["client_operation_id"],
                        "status": "applied",
                        "entity_version": 1,
                    }
                ]
            },
        )
        paused = client.patch(
            f"/api/v1/projects/{project['id']}/sync", json={"sync_mode": "cloud_paused"}
        )
        paused_pending = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        resumed = client.patch(
            f"/api/v1/projects/{project['id']}/sync", json={"sync_mode": "cloud_enabled"}
        )
        pending = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]

    assert paused.json()["sync_mode"] == "cloud_paused"
    assert resumed.json()["sync_mode"] == "cloud_enabled"
    assert paused_pending == []
    assert pending == []


def test_remote_project_metadata_does_not_resume_paused_desktop() -> None:
    workspace_id = "34343434-3434-4343-8343-343434343434"
    device_id = "45454545-4545-4454-8454-454545454545"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "before"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        client.patch(
            f"/api/v1/projects/{project['id']}/sync", json={"sync_mode": "cloud_paused"}
        )
        applied = client.post(
            "/api/v1/local-sync/events",
            json={
                "workspace_id": workspace_id,
                "device_id": device_id,
                "events": [
                    {
                        "event_id": "46464646-4646-4464-8464-464646464646",
                        "workspace_seq": 1,
                        "entity_type": "project",
                        "entity_public_id": project["public_id"],
                        "operation": "upsert",
                        "entity_version": 2,
                        "payload": {
                            "name": "changed on web",
                            "sync_mode": "cloud_enabled",
                            "agent_history_sync": True,
                            "agent_deep_thinking": True,
                        },
                    }
                ],
            },
        )
        persisted = client.get(f"/api/v1/projects/{project['id']}").json()

    assert applied.status_code == 204
    assert persisted["name"] == "changed on web"
    assert persisted["sync_mode"] == "cloud_paused"
    assert persisted["agent_deep_thinking"] is True


def test_rebind_device_updates_state_and_pending_outbox() -> None:
    workspace_id = "61616161-6161-4616-8616-616161616161"
    old_device = "62626262-6262-4626-8626-626262626262"
    new_device = "63636363-6363-4636-8636-636363636363"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "rebind me"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": old_device},
        )
        before = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        assert before and before[0]["device_id"] == old_device
        adopted = client.post(
            "/api/v1/local-sync/device/adopt",
            json={"workspace_id": workspace_id, "device_id": new_device},
        )
        state = client.get(
            "/api/v1/local-sync/state", params={"workspace_id": workspace_id}
        ).json()
        after = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        # Enable after adopt must not 409 on device mismatch.
        client.patch(
            f"/api/v1/projects/{project['id']}/sync", json={"sync_mode": "local_only"}
        )
        enabled = client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": new_device},
        )

    assert adopted.status_code == 200
    assert adopted.json()["changed"] is True
    assert state["device_id"] == new_device
    assert after and after[0]["device_id"] == new_device
    assert enabled.status_code == 200


def test_clear_cloud_bindings_detaches_all_without_deleting_local_projects() -> None:
    workspace_id = "51515151-5151-4515-8515-515151515151"
    device_id = "52525252-5252-4525-8525-525252525252"
    with TestClient(app) as client:
        enabled = client.post("/api/v1/projects", json={"name": "bound enabled"}).json()
        paused = client.post("/api/v1/projects", json={"name": "bound paused"}).json()
        local_only = client.post("/api/v1/projects", json={"name": "never cloud"}).json()
        client.post(
            f"/api/v1/projects/{enabled['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        client.post(
            f"/api/v1/projects/{paused['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        client.patch(
            f"/api/v1/projects/{paused['id']}/sync", json={"sync_mode": "cloud_paused"}
        )
        cleared = client.post("/api/v1/local-sync/clear-cloud-bindings")
        enabled_after = client.get(f"/api/v1/projects/{enabled['id']}").json()
        paused_after = client.get(f"/api/v1/projects/{paused['id']}").json()
        local_after = client.get(f"/api/v1/projects/{local_only['id']}").json()
        pending = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]

    assert cleared.status_code == 200
    assert cleared.json()["cleared"] == 2
    assert enabled_after["sync_mode"] == "local_only"
    assert enabled_after.get("cloud_workspace_id") in (None, "")
    assert enabled_after["name"] == "bound enabled"
    assert paused_after["sync_mode"] == "local_only"
    assert local_after["sync_mode"] == "local_only"
    assert pending == []


def test_detach_restores_local_only_without_deleting_local_project() -> None:
    workspace_id = "55555555-5555-4555-8555-555555555555"
    device_id = "56565656-5656-4565-8565-565656565656"
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects", json={"name": "keep local", "description": "preserved"}
        ).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        detached = client.patch(
            f"/api/v1/projects/{project['id']}/sync", json={"sync_mode": "local_only"}
        )
        persisted = client.get(f"/api/v1/projects/{project['id']}")
        pending = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        rebound = client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )

    assert detached.status_code == 200
    assert detached.json()["sync_mode"] == "local_only"
    assert persisted.status_code == 200
    assert persisted.json()["description"] == "preserved"
    assert pending == []
    assert rebound.status_code == 200


def test_deleting_desktop_project_never_queues_cloud_project_delete() -> None:
    workspace_id = "57575757-5757-4575-8575-575757575757"
    device_id = "58585858-5858-4585-8585-585858585858"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "local delete only"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        initial = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        assert len(initial) == 1
        client.post(
            "/api/v1/local-sync/outbox/results",
            json={
                "results": [
                    {
                        "client_operation_id": initial[0]["client_operation_id"],
                        "status": "applied",
                        "entity_version": 1,
                    }
                ]
            },
        )
        deleted = client.delete(f"/api/v1/projects/{project['id']}")
        remaining = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]

    assert deleted.status_code == 204
    assert remaining == []


def test_conflict_keeps_local_operation_until_explicit_resolution() -> None:
    workspace_id = "66666666-6666-4666-8666-666666666666"
    device_id = "77777777-7777-4777-8777-777777777777"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "conflict local"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        operation = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"][0]
        client.post(
            "/api/v1/local-sync/outbox/results",
            json={
                "results": [
                    {
                        "client_operation_id": operation["client_operation_id"],
                        "status": "conflict",
                        "entity_version": 3,
                        "remote": {"name": "conflict remote", "version": 3},
                    }
                ]
            },
        )
        conflicts = client.get(
            "/api/v1/local-sync/conflicts", params={"workspace_id": workspace_id}
        ).json()
        pending_before = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        client.post(
            f"/api/v1/local-sync/conflicts/{conflicts[0]['conflict_id']}/resolve",
            json={"resolution": "keep_local"},
        )
        pending_after = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]

    assert pending_before == []
    assert len(conflicts) == 1
    assert len(pending_after) == 1
    assert pending_after[0]["base_version"] == 3
    assert pending_after[0]["client_operation_id"] != operation["client_operation_id"]
    assert pending_after[0]["supersedes_operation_id"] == operation["client_operation_id"]


def test_agent_history_uses_uuid_boundary_and_suppresses_pending_when_disabled() -> None:
    workspace_id = "88888888-8888-4888-8888-888888888888"
    device_id = "99999999-9999-4999-8999-999999999999"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "agent sync"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        client.post(
            f"/api/v1/projects/{project['id']}/agent/conversations",
            json={"title": "first"},
        )
        before = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        conversation = next(item for item in before if item["entity_type"] == "agent_conversation")
        assert str(UUID(conversation["entity_public_id"])) == conversation["entity_public_id"]

        client.patch(
            f"/api/v1/projects/{project['id']}/agent-history-sync",
            json={"enabled": False},
        )
        client.post(
            f"/api/v1/projects/{project['id']}/agent/conversations",
            json={"title": "local only"},
        )
        after = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
        assert all(not item["entity_type"].startswith("agent_") for item in after)


def test_desktop_preserves_downloaded_file_versions_and_selects_by_cloud_uuid() -> None:
    workspace_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    device_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    repository_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    first_artifact = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    second_artifact = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "file history"}).json()
        client.post(
            f"/api/v1/projects/{project['id']}/sync/enable",
            json={"workspace_id": workspace_id, "device_id": device_id},
        )
        for version, artifact_id, source in (
            (1, first_artifact, "print('v1')"),
            (2, second_artifact, "print('v2')"),
        ):
            response = client.put(
                f"/api/v1/local-sync/projects/{project['id']}/imports/"
                f"code_repository/{repository_id}",
                params={
                    "filename": "repo.zip",
                    "version": version,
                    "blob_id": str(UUID(int=version)),
                    "artifact_version_id": artifact_id,
                },
                content=_repository_archive(source),
            )
            assert response.status_code == 200
        versions = client.get(
            f"/api/v1/local-sync/projects/{project['id']}/artifacts/"
            f"code_repository/{repository_id}/versions"
        ).json()
        assert len(versions) == 2
        assert [item["is_current"] for item in versions] == [True, False]
        selected = client.post(
            f"/api/v1/local-sync/projects/{project['id']}/artifacts/"
            f"code_repository/{repository_id}/select",
            json={"local_version_id": versions[1]["local_version_id"]},
        )
        operations = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()["operations"]
    assert selected.status_code == 200
    select_operation = next(item for item in operations if item["operation"] == "select_version")
    assert select_operation["payload"]["version_id"] == first_artifact
