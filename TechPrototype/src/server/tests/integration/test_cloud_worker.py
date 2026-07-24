from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, create_engine, select

from tracelab_server.models.cloud_entities import (
    AuthSession,
    CloudSQLModel,
    Device,
    SyncDeviceCursor,
    SyncEvent,
    UserAccount,
    Workspace,
    WorkspaceMember,
)
from tracelab_server.services import cloud_jobs


def test_worker_does_not_run_local_analysis_jobs() -> None:
    assert cloud_jobs.SUPPORTED_JOB_TYPES == {
        "send_email",
        "gc_tombstones",
        "compact_sync_events",
    }
    assert "parse_paper" not in cloud_jobs.SUPPORTED_JOB_TYPES
    assert "analyze_code" not in cloud_jobs.SUPPORTED_JOB_TYPES


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
                created_at=datetime.now(UTC) - timedelta(days=31),
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
