"""Tests for local sync device adoption.

``LocalSyncState.device_id`` (embedded in every outbox op) must track the current
auth device. Device ids rotate across logins; if the workspace stays pinned to an
old device, the cloud rejects blob uploads (409) and pushes (403). Adoption
realigns the local state + pending outbox to the current device so previously
enabled projects keep syncing, and enabling a project on a rotated device must no
longer fail with 409 "Workspace is bound to another local device".
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

DEVICE_A = "22222222-2222-4222-8222-222222222222"
DEVICE_B = "33333333-3333-4333-8333-333333333333"
WORKSPACE = "11111111-1111-4111-8111-111111111111"


def _enable(client: TestClient, name: str, device_id: str) -> dict:
    project = client.post("/api/v1/projects", json={"name": name, "description": "x"}).json()
    resp = client.post(
        f"/api/v1/projects/{project['id']}/sync/enable",
        json={"workspace_id": WORKSPACE, "device_id": device_id, "agent_history_sync": False},
    )
    assert resp.status_code == 200, resp.text
    return project


def test_adopt_repoints_state_and_pending_outbox() -> None:
    with TestClient(app) as client:
        _enable(client, "proj-a", DEVICE_A)

        before = client.get("/api/v1/local-sync/outbox", params={"workspace_id": WORKSPACE}).json()
        assert before["operations"], "enable should have queued a project op"
        assert all(op["device_id"] == DEVICE_A for op in before["operations"])

        adopted = client.post(
            "/api/v1/local-sync/device/adopt",
            json={"workspace_id": WORKSPACE, "device_id": DEVICE_B},
        )
        assert adopted.status_code == 200
        assert adopted.json()["changed"] is True

        state = client.get("/api/v1/local-sync/state", params={"workspace_id": WORKSPACE}).json()
        assert state["device_id"] == DEVICE_B
        after = client.get("/api/v1/local-sync/outbox", params={"workspace_id": WORKSPACE}).json()
        assert after["operations"]
        assert all(op["device_id"] == DEVICE_B for op in after["operations"])

        # Idempotent: adopting the same device again reports no change.
        again = client.post(
            "/api/v1/local-sync/device/adopt",
            json={"workspace_id": WORKSPACE, "device_id": DEVICE_B},
        )
        assert again.json()["changed"] is False


def test_adopt_noop_when_no_state() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/local-sync/device/adopt",
            json={"workspace_id": WORKSPACE, "device_id": DEVICE_A},
        )
        assert resp.status_code == 200
        assert resp.json()["changed"] is False


def test_enable_on_rotated_device_adopts_instead_of_409() -> None:
    with TestClient(app) as client:
        _enable(client, "proj-a", DEVICE_A)
        # A second project enabled on the SAME workspace but a DIFFERENT (rotated)
        # device must succeed by adopting, not fail with 409.
        _enable(client, "proj-b", DEVICE_B)

        state = client.get("/api/v1/local-sync/state", params={"workspace_id": WORKSPACE}).json()
        assert state["device_id"] == DEVICE_B
        # Every pending op — including proj-a's, queued under DEVICE_A — is realigned.
        outbox = client.get("/api/v1/local-sync/outbox", params={"workspace_id": WORKSPACE}).json()
        assert outbox["operations"]
        assert all(op["device_id"] == DEVICE_B for op in outbox["operations"])
