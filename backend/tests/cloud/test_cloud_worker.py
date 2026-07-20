import hashlib
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, create_engine, select

from app.models.cloud_entities import (
    AuthSession,
    BackgroundJob,
    BlobObject,
    CloudEntity,
    CloudSQLModel,
    Device,
    SyncDeviceCursor,
    SyncEvent,
    UserAccount,
    Workspace,
    WorkspaceMember,
)
from app.services import cloud_jobs
from app.storage.blob_store import blob_store


def test_worker_analyzes_blob_and_emits_only_derived_blob_reference(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'cloud.db'}")
    CloudSQLModel.metadata.create_all(engine)
    blob_root = tmp_path / "blobs"
    tmp_root = tmp_path / "tmp"
    blob_root.mkdir()
    (tmp_root / "quarantine").mkdir(parents=True)
    monkeypatch.setattr(cloud_jobs, "engine", engine)
    monkeypatch.setattr(blob_store, "root", blob_root)
    monkeypatch.setattr(blob_store, "tmp_root", tmp_root)
    monkeypatch.setattr(blob_store, "quarantine", tmp_root / "quarantine")

    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("demo/model.py", "def forward(x):\n    return x + 1\n")
    content = archive.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    stored = blob_store.content_path(digest)
    stored.parent.mkdir(parents=True)
    stored.write_bytes(content)

    with Session(engine) as session:
        user = UserAccount(
            email_normalized="worker@example.com",
            password_hash="not-used-in-worker-test",
            email_verified_at=cloud_jobs.utc_now(),
        )
        session.add(user)
        session.flush()
        workspace = Workspace(name="worker", created_by=user.user_id)
        session.add(workspace)
        session.flush()
        source = BlobObject(
            workspace_id=workspace.workspace_id,
            sha256=digest,
            byte_size=len(content),
            mime_type="application/zip",
            filename="source.zip",
            storage_key=str(stored.relative_to(blob_root)),
            status="ready",
            created_by=user.user_id,
            completed_at=cloud_jobs.utc_now(),
        )
        session.add(source)
        session.flush()
        job = BackgroundJob(
            workspace_id=workspace.workspace_id,
            job_type="analyze_code",
            idempotency_key=f"analyze:{source.blob_id}",
            payload_json={"blob_id": source.blob_id},
        )
        session.add(job)
        session.commit()
        job_id = job.job_id

    assert cloud_jobs.run_worker_once() == 1

    with Session(engine) as session:
        completed = session.get(BackgroundJob, job_id)
        derived = session.exec(
            select(CloudEntity).where(CloudEntity.entity_type == "repository_analysis")
        ).one()
        event = session.exec(
            select(SyncEvent).where(SyncEvent.entity_type == "repository_analysis")
        ).one()
        result_blob = session.get(BlobObject, derived.payload_json["result_blob_id"])

    assert completed is not None and completed.status == "completed"
    assert derived.payload_json["source_hash"] == digest
    assert derived.payload_json["processor_version"] == "architecture-v3"
    assert result_blob is not None and result_blob.status == "ready"
    assert event.payload_json == derived.payload_json
    assert "symbols" not in event.payload_json


def test_event_compaction_waits_for_every_valid_desktop_cursor(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'compaction.db'}")
    CloudSQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = UserAccount(email_normalized="cursor@example.com", password_hash="fixture")
        session.add(user)
        session.flush()
        workspace = Workspace(name="cursor", created_by=user.user_id, workspace_seq=1)
        session.add(workspace)
        session.flush()
        session.add(
            WorkspaceMember(
                workspace_id=workspace.workspace_id,
                user_id=user.user_id,
                role="owner",
            )
        )
        devices = [
            Device(user_id=user.user_id, name=f"desktop-{index}", platform="desktop")
            for index in range(2)
        ]
        session.add_all(devices)
        session.flush()
        for device in devices:
            session.add(
                AuthSession(
                    user_id=user.user_id,
                    device_id=device.device_id,
                    refresh_token_hash=f"hash-{device.device_id}",
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        session.add(
            SyncEvent(
                workspace_id=workspace.workspace_id,
                workspace_seq=1,
                entity_type="project",
                entity_public_id="11111111-1111-4111-8111-111111111111",
                operation="upsert",
                entity_version=1,
                payload_json={"name": "old"},
                created_at=datetime.now(UTC) - timedelta(days=8),
            )
        )
        session.add(
            SyncDeviceCursor(
                device_id=devices[0].device_id,
                workspace_id=workspace.workspace_id,
                last_pulled_seq=1,
            )
        )
        session.commit()

        assert cloud_jobs._compact_sync_events(session) == 0
        session.add(
            SyncDeviceCursor(
                device_id=devices[1].device_id,
                workspace_id=workspace.workspace_id,
                last_pulled_seq=1,
            )
        )
        session.flush()
        assert cloud_jobs._compact_sync_events(session) == 1
        session.commit()
        assert session.exec(select(SyncEvent)).all() == []
