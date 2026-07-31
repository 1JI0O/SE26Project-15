"""Re-uploading a sha256 whose previous attempt failed must succeed, not 500 forever.

``upload_init`` clears a ``failed`` BlobObject so the client can retry. The blob's child
``upload_session`` row has a non-cascading FK to it, so deleting the parent alone raises
``upload_session_blob_id_fkey`` -- and because the failed row is found again on every
subsequent attempt, that sha256 stays permanently unusable with no client-side remedy.

This fixture enables ``PRAGMA foreign_keys=ON``. The rest of the suite leaves SQLite's
default off, under which the buggy delete silently succeeds and this test cannot fail.
PostgreSQL enforces the constraint in production, which is where the defect appeared.

Found by the stress-test round documented in ``docs/stress-test-report.md`` (D2).
"""

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from tracelab_server.core.config import settings
from tracelab_server.db.session import get_session
from tracelab_server.main import app as cloud_app
from tracelab_server.models.cloud_entities import BlobObject, CloudSQLModel, UploadSession
from tracelab_server.storage.blob_store import blob_store


@pytest.fixture
def fk_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "cloud_sync_feature_enabled", True)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enforce_fks(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    CloudSQLModel.metadata.create_all(engine)
    blob_root = tmp_path / "blobs"
    tmp_root = tmp_path / "tmp"
    quarantine = tmp_root / "quarantine"
    blob_root.mkdir()
    quarantine.mkdir(parents=True)
    monkeypatch.setattr(blob_store, "root", blob_root)
    monkeypatch.setattr(blob_store, "tmp_root", tmp_root)
    monkeypatch.setattr(blob_store, "quarantine", quarantine)
    # disk_percent() reads the real filesystem holding tmp_path, so on a host above
    # cloud_disk_stop_percent every upload-init returns 507 and this test never reaches
    # the retry path it exists to cover.
    monkeypatch.setattr(blob_store, "disk_percent", lambda: 0.0)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    cloud_app.dependency_overrides[get_session] = session_override
    cloud_app.state.test_engine = engine
    with TestClient(cloud_app) as client:
        yield client
    cloud_app.dependency_overrides.pop(get_session, None)


def _register_verify_login(client: TestClient, email: str) -> dict:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "display_name": "Owner"},
    )
    assert registered.status_code == 201
    token = registered.headers["x-debug-email-token"]
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    logged_in = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "device_name": "fk-test",
            "platform": "test",
        },
    )
    assert logged_in.status_code == 200
    return logged_in.json()


def _init(client: TestClient, headers: dict, workspace_id: str, project: str, content: bytes):
    return client.post(
        "/api/v1/blobs/upload-init",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "project_public_id": project,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
            "mime_type": "text/plain",
            "filename": "retry.txt",
        },
    )


def test_retry_after_failed_upload_succeeds(fk_client: TestClient) -> None:
    auth = _register_verify_login(fk_client, "retry@example.com")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    workspace_id = auth["default_workspace"]["workspace_id"]
    project = fk_client.post(
        "/api/v1/projects",
        headers=headers,
        json={"workspace_id": workspace_id, "name": "retry"},
    ).json()["public_id"]

    content = b"the real payload"
    first = _init(fk_client, headers, workspace_id, project, content)
    assert first.status_code == 200
    blob_id = first.json()["blob_id"]

    # Send bytes that do not match the declared sha256 so verification fails and the
    # BlobObject is parked as "failed" with its upload_session row still present.
    fk_client.put(f"/api/v1/blobs/{blob_id}/chunks/0", headers=headers, content=b"wrong bytes")
    failed = fk_client.post(f"/api/v1/blobs/{blob_id}/complete", headers=headers)
    assert failed.status_code >= 400

    engine = fk_client.app.state.test_engine
    with Session(engine) as session:
        assert session.get(BlobObject, blob_id).status == "failed"
        assert session.exec(select(UploadSession).where(UploadSession.blob_id == blob_id)).first()

    # The retry must clear the failed attempt. Before the fix the cascade-less FK made this
    # raise, and every later attempt at this sha256 failed identically.
    retried = _init(fk_client, headers, workspace_id, project, content)
    assert retried.status_code == 200
    retry_blob_id = retried.json()["blob_id"]

    fk_client.put(f"/api/v1/blobs/{retry_blob_id}/chunks/0", headers=headers, content=content)
    completed = fk_client.post(f"/api/v1/blobs/{retry_blob_id}/complete", headers=headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "ready"

    with Session(engine) as session:
        # The stale parent and its child are both gone, not merely orphaned.
        assert session.get(BlobObject, blob_id) is None
        assert (
            session.exec(select(UploadSession).where(UploadSession.blob_id == blob_id)).first()
            is None
        )


def test_foreign_keys_are_actually_enforced(fk_client: TestClient) -> None:
    """Guard the guard: without PRAGMA foreign_keys=ON the test above cannot fail."""

    engine = fk_client.app.state.test_engine
    with engine.connect() as connection:
        enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert enabled == 1

