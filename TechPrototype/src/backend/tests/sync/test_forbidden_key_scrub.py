"""Regression tests for client-side scrubbing of the cloud server's forbidden
sync keys.

Root cause these guard against: agent operation payloads embed arbitrary runtime
data (tool results, run-event payloads, message metadata) that can contain keys
like ``storage_path`` / ``api_key``. The cloud server recursively rejects any
sync push carrying such a key with HTTP 422, and because the client batches all
child operations into one request, a single poison op blocks the whole
workspace's sync. We strip these keys client-side before they ever reach the
outbox / push.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.session import get_session
from app.main import app
from app.models.entities import Project
from app.models.sync import LocalSyncOutbox
from app.services.local_sync import (
    FORBIDDEN_SYNC_KEYS,
    record_local_operation,
    scrub_forbidden_keys,
)

# Hard-coded copy of the cloud server's FORBIDDEN_SYNC_KEYS
# (server/tracelab_server/services/cloud_sync.py). If the server ever adds a key
# and the local mirror is not updated, this test fails loudly instead of the bug
# silently regressing to whole-batch sync failures.
_SERVER_FORBIDDEN_KEYS = {
    "storage_path",
    "absolute_path",
    "local_path",
    "api_key",
    "llm_api_key",
    "mineru_api_key",
    "refresh_token",
    "access_token",
    "secret",
    "_upload_content",
}


def test_scrub_drops_forbidden_keys_recursively() -> None:
    payload = {
        "role": "assistant",
        "content": "keep me",
        "storage_path": "/home/user/x",
        "metadata": {
            "model": "keep",
            "access_token": "drop",
            "nested": {"llm_api_key": "drop", "keep": 1},
        },
        "events": [
            {"event_type": "tool", "absolute_path": "/tmp/y", "ok": True},
            {"payload": {"openai_api_key": "drop", "delta": "keep"}},
        ],
    }
    cleaned = scrub_forbidden_keys(payload)

    # Kept content survives.
    assert cleaned["content"] == "keep me"
    assert cleaned["metadata"]["model"] == "keep"
    assert cleaned["metadata"]["nested"]["keep"] == 1
    assert cleaned["events"][0]["ok"] is True
    assert cleaned["events"][1]["payload"]["delta"] == "keep"

    # Every forbidden key removed at every depth, including endswith("_api_key").
    assert "storage_path" not in cleaned
    assert "access_token" not in cleaned["metadata"]
    assert "llm_api_key" not in cleaned["metadata"]["nested"]
    assert "absolute_path" not in cleaned["events"][0]
    assert "openai_api_key" not in cleaned["events"][1]["payload"]


def test_scrub_is_non_mutating() -> None:
    original = {"api_key": "secret", "keep": {"local_path": "x", "v": 1}}
    scrub_forbidden_keys(original)
    # The caller's live ORM-derived dict must be untouched.
    assert original == {"api_key": "secret", "keep": {"local_path": "x", "v": 1}}


def test_local_forbidden_keys_superset_of_server() -> None:
    assert _SERVER_FORBIDDEN_KEYS <= FORBIDDEN_SYNC_KEYS


def _enable_synced_project(client: TestClient, workspace_id: str, device_id: str) -> str:
    project = client.post(
        "/api/v1/projects", json={"name": "synced", "description": "x"}
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/sync/enable",
        json={
            "workspace_id": workspace_id,
            "device_id": device_id,
            "agent_history_sync": True,
        },
    )
    return project["public_id"]


def test_record_local_operation_scrubs_on_write() -> None:
    workspace_id = "11111111-1111-4111-8111-111111111111"
    device_id = "22222222-2222-4222-8222-222222222222"
    with TestClient(app) as client:
        project_public_id = _enable_synced_project(client, workspace_id, device_id)

        session_gen = app.dependency_overrides[get_session]()
        session = next(session_gen)
        try:
            project_row = session.exec(
                select(Project).where(Project.public_id == project_public_id)
            ).first()
            record_local_operation(
                session,
                project_row,
                "agent_message",
                "33333333-3333-4333-8333-333333333333",
                {
                    "project_public_id": project_public_id,
                    "role": "assistant",
                    "metadata": {"api_key": "leak", "keep": 1},
                },
            )
            session.commit()
            stored = session.exec(
                select(LocalSyncOutbox).where(LocalSyncOutbox.entity_type == "agent_message")
            ).first()
            assert "api_key" not in stored.payload_json["metadata"]
            assert stored.payload_json["metadata"]["keep"] == 1
        finally:
            session.close()


def test_read_outbox_heals_pre_existing_poison_rows() -> None:
    """Rows enqueued before the fix (unscrubbed) must be cleaned on read so a
    stuck client self-heals on the next sync without a DB migration."""
    workspace_id = "11111111-1111-4111-8111-111111111111"
    device_id = "22222222-2222-4222-8222-222222222222"
    with TestClient(app) as client:
        project_public_id = _enable_synced_project(client, workspace_id, device_id)

        # Insert a raw poison row directly (bypassing record_local_operation) to
        # simulate an outbox row persisted before this fix shipped.
        session_gen = app.dependency_overrides[get_session]()
        session = next(session_gen)
        try:
            session.add(
                LocalSyncOutbox(
                    workspace_id=workspace_id,
                    device_id=device_id,
                    entity_type="agent_run_event",
                    entity_public_id="44444444-4444-4444-8444-444444444444",
                    operation="upsert",
                    base_version=0,
                    payload_json={
                        "project_public_id": project_public_id,
                        "run_public_id": "55555555-5555-4555-8555-555555555555",
                        "event_type": "tool",
                        "payload": {
                            "storage_path": "/home/user/repo",
                            "nested": {"llm_api_key": "leak", "delta": "keep"},
                        },
                    },
                )
            )
            session.commit()
        finally:
            session.close()

        outbox = client.get(
            "/api/v1/local-sync/outbox", params={"workspace_id": workspace_id}
        ).json()

    event_ops = [op for op in outbox["operations"] if op["entity_type"] == "agent_run_event"]
    assert len(event_ops) == 1
    payload = event_ops[0]["payload"]
    assert "storage_path" not in payload["payload"]
    assert "llm_api_key" not in payload["payload"]["nested"]
    assert payload["payload"]["nested"]["delta"] == "keep"
