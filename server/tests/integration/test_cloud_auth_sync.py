import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from tracelab_server.core.config import settings
from tracelab_server.db.session import get_session
from tracelab_server.main import app as cloud_app
from tracelab_server.models.cloud_entities import (
    BackgroundJob,
    BlobContent,
    BlobObject,
    CloudSQLModel,
    SyncReceipt,
    UserAccount,
)
from tracelab_server.services import cloud_jobs
from tracelab_server.storage.blob_store import blob_store


@pytest.fixture
def cloud_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "cloud_sync_feature_enabled", True)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CloudSQLModel.metadata.create_all(engine)
    blob_root = tmp_path / "blobs"
    tmp_root = tmp_path / "tmp"
    quarantine = tmp_root / "quarantine"
    blob_root.mkdir()
    quarantine.mkdir(parents=True)
    monkeypatch.setattr(blob_store, "root", blob_root)
    monkeypatch.setattr(blob_store, "tmp_root", tmp_root)
    monkeypatch.setattr(blob_store, "quarantine", quarantine)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    cloud_app.dependency_overrides[get_session] = session_override
    cloud_app.state.test_engine = engine
    with TestClient(cloud_app) as client:
        yield client
    cloud_app.dependency_overrides.pop(get_session, None)


def _register_verify_login(client: TestClient, email: str = "owner@example.com") -> dict:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "display_name": "Owner"},
    )
    assert registered.status_code == 201
    token = registered.headers["x-debug-email-token"]
    verified = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    logged_in = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "client_kind": "desktop",
            "device_name": "Test desktop",
            "platform": "test",
        },
    )
    assert logged_in.status_code == 200
    return logged_in.json()


def test_unverified_account_cannot_create_cloud_project(
    cloud_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "cloud_require_email_verification", True)
    registered = cloud_client.post(
        "/api/v1/auth/register",
        json={"email": "pending@example.com", "password": "correct horse battery staple"},
    )
    assert registered.status_code == 201
    logged_in = cloud_client.post(
        "/api/v1/auth/login",
        json={
            "email": "pending@example.com",
            "password": "correct horse battery staple",
            "client_kind": "desktop",
        },
    ).json()
    response = cloud_client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {logged_in['access_token']}"},
        json={
            "workspace_id": logged_in["default_workspace"]["workspace_id"],
            "name": "must not be created",
        },
    )
    assert response.status_code == 403


def test_unverified_account_can_create_cloud_project_when_verification_disabled(
    cloud_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "cloud_require_email_verification", False)
    registered = cloud_client.post(
        "/api/v1/auth/register",
        json={"email": "auto-verified@example.com", "password": "correct horse battery staple"},
    )
    assert registered.status_code == 201
    assert registered.json()["email_verified"] is True
    logged_in = cloud_client.post(
        "/api/v1/auth/login",
        json={
            "email": "auto-verified@example.com",
            "password": "correct horse battery staple",
            "client_kind": "desktop",
        },
    ).json()
    response = cloud_client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {logged_in['access_token']}"},
        json={
            "workspace_id": logged_in["default_workspace"]["workspace_id"],
            "name": "created without email verification",
        },
    )
    assert response.status_code == 201
    assert response.json()["name"] == "created without email verification"


def test_bootstrap_includes_device_bindings(cloud_client: TestClient) -> None:
    auth = _register_verify_login(cloud_client, "bootstrap@example.com")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    workspace_id = auth["default_workspace"]["workspace_id"]
    created = cloud_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"workspace_id": workspace_id, "name": "binding fixture"},
    ).json()
    cloud_client.patch(
        f"/api/v1/projects/{created['public_id']}/device-sync",
        headers=headers,
        json={"sync_mode": "cloud_paused"},
    )
    bootstrap = cloud_client.get(
        "/api/v1/sync/bootstrap",
        headers=headers,
        params={"workspace_id": workspace_id},
    )
    assert bootstrap.status_code == 200
    body = bootstrap.json()
    assert body["device_id"] == auth["device_id"]
    assert body["last_pulled_seq"] == 0
    assert {
        "project_public_id": created["public_id"],
        "sync_mode": "cloud_paused",
    } in body["device_bindings"]


def test_project_sync_enable_pause_detach(cloud_client: TestClient) -> None:
    auth = _register_verify_login(cloud_client, "sync-control@example.com")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    workspace_id = auth["default_workspace"]["workspace_id"]
    created = cloud_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"workspace_id": workspace_id, "name": "sync control"},
    ).json()
    public_id = created["public_id"]
    enabled = cloud_client.post(f"/api/v1/projects/{public_id}/sync/enable", headers=headers)
    paused = cloud_client.post(f"/api/v1/projects/{public_id}/sync/pause", headers=headers)
    detached = cloud_client.post(f"/api/v1/projects/{public_id}/sync/detach", headers=headers)
    assert enabled.json()["sync_mode"] == "cloud_enabled"
    assert paused.json()["sync_mode"] == "cloud_paused"
    assert detached.json()["sync_mode"] == "cloud_detached"


def test_project_sync_is_idempotent_and_conflicts_are_explicit(cloud_client: TestClient) -> None:
    auth = _register_verify_login(cloud_client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    workspace_id = auth["default_workspace"]["workspace_id"]
    operation = {
        "workspace_id": workspace_id,
        "device_id": auth["device_id"],
        "client_operation_id": "11111111-1111-4111-8111-111111111111",
        "entity_type": "project",
        "entity_public_id": "22222222-2222-4222-8222-222222222222",
        "operation": "upsert",
        "base_version": 0,
        "payload": {"name": "Cloud project", "description": "sync fixture"},
    }
    first = cloud_client.post(
        "/api/v1/sync/push", headers=headers, json={"operations": [operation]}
    )
    duplicate = cloud_client.post(
        "/api/v1/sync/push", headers=headers, json={"operations": [operation]}
    )
    stale = {
        **operation,
        "client_operation_id": "11111111-1111-4111-8111-111111111112",
    }
    conflict = cloud_client.post("/api/v1/sync/push", headers=headers, json={"operations": [stale]})
    pulled = cloud_client.get(
        "/api/v1/sync/pull",
        headers=headers,
        params={"workspace_id": workspace_id, "after": 0},
    )

    assert first.status_code == 200
    assert first.json()["results"][0]["status"] == "applied"
    assert duplicate.json()["results"][0]["status"] == "duplicate"
    assert conflict.json()["results"][0]["status"] == "conflict"
    assert pulled.json()["events"][0]["workspace_seq"] == 1
    with Session(cloud_client.app.state.test_engine) as session:
        receipts = session.exec(select(SyncReceipt)).all()
        assert len(receipts) == 2
        assert {receipt.result_json["status"] for receipt in receipts} == {
            "applied",
            "conflict",
        }
    resolved = cloud_client.post(
        "/api/v1/sync/push",
        headers=headers,
        json={
            "operations": [
                {
                    **stale,
                    "client_operation_id": "11111111-1111-4111-8111-111111111113",
                    "supersedes_operation_id": stale["client_operation_id"],
                    "base_version": 1,
                    "payload": {"name": "Resolved project"},
                }
            ]
        },
    )
    assert resolved.json()["results"][0]["status"] == "applied"


def test_ack_rejects_cursor_beyond_workspace_sequence(cloud_client: TestClient) -> None:
    auth = _register_verify_login(cloud_client, "cursor@example.com")
    response = cloud_client.post(
        "/api/v1/sync/ack",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
        json={
            "workspace_id": auth["default_workspace"]["workspace_id"],
            "device_id": auth["device_id"],
            "last_pulled_seq": 1,
        },
    )
    assert response.status_code == 409


def test_pausing_one_device_does_not_pause_web_or_another_device(
    cloud_client: TestClient,
) -> None:
    first = _register_verify_login(cloud_client, "device-scope@example.com")
    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    workspace_id = first["default_workspace"]["workspace_id"]
    created = cloud_client.post(
        "/api/v1/projects",
        headers=first_headers,
        json={"workspace_id": workspace_id, "name": "device scoped"},
    ).json()
    paused = cloud_client.patch(
        f"/api/v1/projects/{created['public_id']}/device-sync",
        headers=first_headers,
        json={"sync_mode": "cloud_paused"},
    )
    assert paused.json()["sync_mode"] == "cloud_paused"
    paused_push = cloud_client.post(
        "/api/v1/sync/push",
        headers=first_headers,
        json={
            "operations": [
                {
                    "workspace_id": workspace_id,
                    "device_id": first["device_id"],
                    "client_operation_id": "31313131-3131-4313-8313-313131313131",
                    "entity_type": "project",
                    "entity_public_id": created["public_id"],
                    "operation": "upsert",
                    "base_version": created["version"],
                    "payload": {"name": "must remain paused"},
                }
            ]
        },
    )
    assert paused_push.status_code == 409

    second = cloud_client.post(
        "/api/v1/auth/login",
        json={
            "email": "device-scope@example.com",
            "password": "correct horse battery staple",
            "client_kind": "desktop",
            "device_name": "Second device",
            "platform": "test",
        },
    ).json()
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}
    cloud_client.patch(
        f"/api/v1/projects/{created['public_id']}/device-sync",
        headers=second_headers,
        json={"sync_mode": "cloud_enabled"},
    )
    trace = cloud_client.post(
        f"/api/v1/projects/{created['public_id']}/entities/trace_link",
        headers=second_headers,
        json={
            "base_version": 0,
            "payload": {"paper_ref": "p1", "code_ref": "c1", "status": "pending"},
        },
    )
    assert trace.status_code == 201


def test_refresh_rotation_rejects_reuse(cloud_client: TestClient) -> None:
    auth = _register_verify_login(cloud_client, "rotation@example.com")
    original = auth["refresh_token"]
    rotated = cloud_client.post(
        "/api/v1/auth/refresh",
        json={"client_kind": "desktop", "refresh_token": original},
    )
    reused = cloud_client.post(
        "/api/v1/auth/refresh",
        json={"client_kind": "desktop", "refresh_token": original},
    )
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != original
    assert reused.status_code == 401


def test_browser_refresh_requires_double_submit_csrf(cloud_client: TestClient) -> None:
    _register_verify_login(cloud_client, "browser@example.com")
    browser = cloud_client.post(
        "/api/v1/auth/login",
        json={
            "email": "browser@example.com",
            "password": "correct horse battery staple",
            "client_kind": "browser",
        },
    )
    csrf = browser.json()["csrf_token"]
    csrf_cookie = next(cookie for cookie in browser.cookies.jar if cookie.name == "tracelab_csrf")
    refresh_cookie = next(
        cookie for cookie in browser.cookies.jar if cookie.name == "tracelab_refresh"
    )

    rejected = cloud_client.post("/api/v1/auth/refresh", json={"client_kind": "browser"})
    accepted = cloud_client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-Token": csrf},
        json={"client_kind": "browser"},
    )

    assert csrf_cookie.path == "/"
    assert refresh_cookie.path == "/api/v1/auth"
    assert rejected.status_code == 403
    assert accepted.status_code == 200


def test_workspace_uuid_cannot_cross_tenant_boundary(cloud_client: TestClient) -> None:
    owner = _register_verify_login(cloud_client, "tenant-owner@example.com")
    outsider = _register_verify_login(cloud_client, "tenant-outsider@example.com")
    workspace_id = owner["default_workspace"]["workspace_id"]

    response = cloud_client.get(
        f"/api/v1/workspaces/{workspace_id}",
        headers={"Authorization": f"Bearer {outsider['access_token']}"},
    )

    assert response.status_code == 403


def test_viewer_can_pull_but_cannot_push(cloud_client: TestClient) -> None:
    owner = _register_verify_login(cloud_client, "role-owner@example.com")
    viewer = _register_verify_login(cloud_client, "role-viewer@example.com")
    workspace_id = owner["default_workspace"]["workspace_id"]
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    viewer_headers = {"Authorization": f"Bearer {viewer['access_token']}"}
    added = cloud_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": "role-viewer@example.com", "role": "viewer"},
    )
    pulled = cloud_client.get(
        "/api/v1/sync/pull",
        headers=viewer_headers,
        params={"workspace_id": workspace_id, "after": 0},
    )
    pushed = cloud_client.post(
        "/api/v1/sync/push",
        headers=viewer_headers,
        json={
            "operations": [
                {
                    "workspace_id": workspace_id,
                    "device_id": viewer["device_id"],
                    "client_operation_id": "66666666-6666-4666-8666-666666666666",
                    "entity_type": "project",
                    "entity_public_id": "55555555-5555-4555-8555-555555555555",
                    "operation": "upsert",
                    "base_version": 0,
                    "payload": {"name": "forbidden"},
                }
            ]
        },
    )

    assert added.status_code == 201
    assert pulled.status_code == 200
    assert pushed.status_code == 403


def test_editor_cannot_delete_cloud_project_through_sync_push(cloud_client: TestClient) -> None:
    owner = _register_verify_login(cloud_client, "delete-owner@example.com")
    editor = _register_verify_login(cloud_client, "delete-editor@example.com")
    workspace_id = owner["default_workspace"]["workspace_id"]
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    editor_headers = {"Authorization": f"Bearer {editor['access_token']}"}
    cloud_client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner_headers,
        json={"email": "delete-editor@example.com", "role": "editor"},
    )
    project = cloud_client.post(
        "/api/v1/projects",
        headers=owner_headers,
        json={"workspace_id": workspace_id, "name": "owner delete only"},
    ).json()
    denied = cloud_client.post(
        "/api/v1/sync/push",
        headers=editor_headers,
        json={
            "operations": [
                {
                    "workspace_id": workspace_id,
                    "device_id": editor["device_id"],
                    "client_operation_id": "67676767-6767-4676-8676-676767676767",
                    "entity_type": "project",
                    "entity_public_id": project["public_id"],
                    "operation": "delete",
                    "base_version": project["version"],
                    "payload": {},
                }
            ]
        },
    )

    assert denied.status_code == 403
    assert cloud_client.get(
        f"/api/v1/projects/{project['public_id']}", headers=owner_headers
    ).status_code == 200


def test_platform_admin_has_no_implicit_project_content_access(
    cloud_client: TestClient,
) -> None:
    owner = _register_verify_login(cloud_client, "content-owner@example.com")
    admin = _register_verify_login(cloud_client, "platform-admin@example.com")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    created = cloud_client.post(
        "/api/v1/projects",
        headers=owner_headers,
        json={
            "workspace_id": owner["default_workspace"]["workspace_id"],
            "name": "private source",
        },
    )
    with Session(cloud_client.app.state.test_engine) as session:
        user = session.get(UserAccount, admin["user"]["user_id"])
        assert user is not None
        user.is_platform_admin = True
        session.add(user)
        session.commit()
    denied = cloud_client.get(
        f"/api/v1/projects/{created.json()['public_id']}",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
    )

    assert denied.status_code == 403


def test_password_and_one_time_tokens_are_not_stored_in_plaintext(
    cloud_client: TestClient,
) -> None:
    password = "correct horse battery staple"
    registered = cloud_client.post(
        "/api/v1/auth/register",
        json={"email": "hashes@example.com", "password": password},
    )
    raw_email_token = registered.headers["x-debug-email-token"]
    with Session(cloud_client.app.state.test_engine) as session:
        user = session.exec(
            select(UserAccount).where(UserAccount.email_normalized == "hashes@example.com")
        ).one()
        persisted = " ".join(
            str(value) for row in session.exec(text("SELECT * FROM email_token")) for value in row
        )
        queued_mail = " ".join(
            str(value)
            for row in session.exec(text("SELECT payload_json FROM background_job"))
            for value in row
        )

    assert user.password_hash.startswith("$argon2id$")
    assert password not in user.password_hash
    assert raw_email_token not in persisted
    assert raw_email_token not in queued_mail


def test_login_limit_persists_failed_attempts(cloud_client: TestClient) -> None:
    responses = [
        cloud_client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "wrong"},
        )
        for _ in range(11)
    ]
    assert all(response.status_code == 401 for response in responses[:10])
    assert responses[-1].status_code == 429


def test_password_recovery_response_does_not_enumerate_accounts(
    cloud_client: TestClient,
) -> None:
    _register_verify_login(cloud_client, "recovery@example.com")
    existing = cloud_client.post(
        "/api/v1/auth/password/forgot", json={"email": "recovery@example.com"}
    )
    missing = cloud_client.post(
        "/api/v1/auth/password/forgot", json={"email": "absent@example.com"}
    )
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json()


def test_blob_upload_hash_range_and_workspace_dedup(cloud_client: TestClient) -> None:
    auth = _register_verify_login(cloud_client, "blob-owner@example.com")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    workspace_id = auth["default_workspace"]["workspace_id"]
    content = b"immutable cloud blob"
    digest = hashlib.sha256(content).hexdigest()
    payload = {
        "workspace_id": workspace_id,
        "sha256": digest,
        "byte_size": len(content),
        "mime_type": "application/octet-stream",
        "filename": "fixture.txt",
    }
    initialized = cloud_client.post("/api/v1/blobs/upload-init", headers=headers, json=payload)
    blob_id = initialized.json()["blob_id"]
    chunked = cloud_client.put(
        f"/api/v1/blobs/{blob_id}/chunks/0", headers=headers, content=content
    )
    completed = cloud_client.post(f"/api/v1/blobs/{blob_id}/complete", headers=headers)
    reused = cloud_client.post("/api/v1/blobs/upload-init", headers=headers, json=payload)
    ranged = cloud_client.get(
        f"/api/v1/blobs/{blob_id}/download",
        headers={**headers, "Range": "bytes=2-8"},
    )

    assert initialized.status_code == 200
    assert chunked.status_code == 200
    assert completed.status_code == 200
    assert reused.json()["status"] == "reuse"
    assert reused.json()["blob_id"] == blob_id
    assert ranged.status_code == 206
    assert ranged.content == content[2:9]
    with Session(cloud_client.app.state.test_engine) as session:
        job_types = set(session.exec(select(BackgroundJob.job_type)).all())
        assert not {"parse_paper", "analyze_code"} & job_types


def test_cross_workspace_dedup_keeps_other_workspace_content_during_gc(
    cloud_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"same physical content across tenants"
    digest = hashlib.sha256(content).hexdigest()
    blob_ids: list[str] = []
    for index in range(2):
        auth = _register_verify_login(cloud_client, f"dedup-{index}@example.com")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        initialized = cloud_client.post(
            "/api/v1/blobs/upload-init",
            headers=headers,
            json={
                "workspace_id": auth["default_workspace"]["workspace_id"],
                "sha256": digest,
                "byte_size": len(content),
                "mime_type": "application/octet-stream",
                "filename": "shared.txt",
            },
        ).json()
        blob_ids.append(initialized["blob_id"])
        cloud_client.put(
            f"/api/v1/blobs/{initialized['blob_id']}/chunks/0",
            headers=headers,
            content=content,
        )
        completed = cloud_client.post(
            f"/api/v1/blobs/{initialized['blob_id']}/complete", headers=headers
        )
        assert completed.status_code == 200

    with Session(cloud_client.app.state.test_engine) as session:
        first = session.get(BlobObject, blob_ids[0])
        second = session.get(BlobObject, blob_ids[1])
        assert first is not None and second is not None
        assert first.content_id == second.content_id
        assert session.exec(select(BlobContent)).one().physical_ref_count == 2
        first.completed_at = first.completed_at.replace(year=2000)
        second.reference_count = 1
        session.add(first)
        session.add(second)
        job = BackgroundJob(
            job_type="gc_tombstones",
            idempotency_key="cross-workspace-gc",
            status="running",
            attempt_count=1,
        )
        session.add(job)
        session.commit()
        job_id = job.job_id

    monkeypatch.setattr(cloud_jobs, "engine", cloud_client.app.state.test_engine)
    cloud_jobs.execute_job(job_id)
    with Session(cloud_client.app.state.test_engine) as session:
        assert session.get(BlobObject, blob_ids[0]) is None
        remaining = session.get(BlobObject, blob_ids[1])
        assert remaining is not None
        physical = session.get(BlobContent, remaining.content_id)
        assert physical is not None and physical.physical_ref_count == 1
        assert (blob_store.root / physical.storage_key).is_file()


def test_reused_blob_is_charged_once_per_project_on_entity_write(
    cloud_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = _register_verify_login(cloud_client, "project-quota@example.com")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    workspace_id = auth["default_workspace"]["workspace_id"]
    projects = [
        cloud_client.post(
            "/api/v1/projects",
            headers=headers,
            json={"workspace_id": workspace_id, "name": f"quota-{index}"},
        ).json()
        for index in range(2)
    ]
    content = b"shared"
    initialized = cloud_client.post(
        "/api/v1/blobs/upload-init",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "project_public_id": projects[0]["public_id"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
            "mime_type": "text/plain",
            "filename": "shared.txt",
        },
    ).json()
    cloud_client.put(
        f"/api/v1/blobs/{initialized['blob_id']}/chunks/0",
        headers=headers,
        content=content,
    )
    cloud_client.post(f"/api/v1/blobs/{initialized['blob_id']}/complete", headers=headers)
    monkeypatch.setattr(settings, "cloud_project_quota_bytes", len(content) - 1)
    rejected = cloud_client.post(
        f"/api/v1/projects/{projects[1]['public_id']}/entities/code_edit",
        headers=headers,
        json={
            "base_version": 0,
            "payload": {
                "path": "shared.txt",
                "repository_public_id": "23232323-2323-4323-8323-232323232323",
                "blob_id": initialized["blob_id"],
            },
        },
    )
    assert rejected.status_code == 413


def test_artifact_replacement_preserves_both_versions_and_can_select_old_version(
    cloud_client: TestClient,
) -> None:
    auth = _register_verify_login(cloud_client, "versions@example.com")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    workspace_id = auth["default_workspace"]["workspace_id"]
    project = cloud_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"workspace_id": workspace_id, "name": "versions"},
    ).json()

    blob_ids = []
    for index, content in enumerate((b"version one", b"version two"), start=1):
        initialized = cloud_client.post(
            "/api/v1/blobs/upload-init",
            headers=headers,
            json={
                "workspace_id": workspace_id,
                "project_public_id": project["public_id"],
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content),
                "mime_type": "text/plain",
                "filename": f"version-{index}.txt",
            },
        ).json()
        blob_ids.append(initialized["blob_id"])
        cloud_client.put(
            f"/api/v1/blobs/{initialized['blob_id']}/chunks/0",
            headers=headers,
            content=content,
        )
        cloud_client.post(f"/api/v1/blobs/{initialized['blob_id']}/complete", headers=headers)

    entity_id = "12121212-1212-4212-8212-121212121212"
    repository_id = "13131313-1313-4313-8313-131313131313"
    created = cloud_client.post(
        f"/api/v1/projects/{project['public_id']}/entities/code_edit",
        headers=headers,
        json={
            "public_id": entity_id,
            "base_version": 0,
            "payload": {
                "path": "main.py",
                "repository_public_id": repository_id,
                "blob_id": blob_ids[0],
            },
        },
    )
    updated = cloud_client.patch(
        f"/api/v1/projects/{project['public_id']}/entities/code_edit/{entity_id}",
        headers=headers,
        json={
            "base_version": 1,
            "payload": {
                "path": "main.py",
                "repository_public_id": repository_id,
                "blob_id": blob_ids[1],
            },
        },
    )
    versions = cloud_client.get(
        f"/api/v1/projects/{project['public_id']}/artifacts/code_edit/{entity_id}/versions",
        headers=headers,
    ).json()
    older = next(item for item in versions if item["version_number"] == 1)
    selected = cloud_client.post(
        f"/api/v1/projects/{project['public_id']}/artifacts/code_edit/{entity_id}/"
        f"versions/{older['version_id']}/select",
        headers=headers,
        params={"base_version": 2},
    )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert len(versions) == 2
    assert selected.status_code == 200
    assert selected.json()["blob_id"] == blob_ids[0]
    with Session(cloud_client.app.state.test_engine) as session:
        assert session.get(BlobObject, blob_ids[0]).reference_count == 1
        assert session.get(BlobObject, blob_ids[1]).reference_count == 1
