"""Seed the TraceLab sync server with stress-test fixtures.

Writes directly to PostgreSQL, bypassing the auth rate limits and the Argon2
password-hash cost that would otherwise dominate any load profile (plan H3), and
emits pre-signed access tokens so Locust never has to log in.

All rows created here are tagged with the ``stress-`` email prefix / name prefix so
``--cleanup`` can remove them without touching real data.

Usage:
    export TRACELAB_STRESS_DB="postgresql+psycopg://tracelab:tracelab@127.0.0.1:5432/tracelab"
    export CLOUD_JWT_SECRET="<same secret as the server under test>"
    python -m seed.seed_server --users 50 --workspaces 10 --out identities.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

# The server package owns the models, token format and password hashing. Reusing it
# keeps the seed data valid as the schema evolves instead of duplicating DDL here.
_SERVER_ROOT = Path(__file__).resolve().parents[2] / "server"
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

PREFIX = "stress-"
DEFAULT_PASSWORD = "StressTest-Passw0rd"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_env() -> str:
    url = os.environ.get("TRACELAB_STRESS_DB", "")
    if not url:
        raise SystemExit("TRACELAB_STRESS_DB is required (postgresql+psycopg://...)")
    if not os.environ.get("CLOUD_JWT_SECRET"):
        raise SystemExit(
            "CLOUD_JWT_SECRET is required and must match the server under test, "
            "otherwise every pre-signed token is rejected with 401."
        )
    return url


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--workspaces", type=int, default=10)
    parser.add_argument("--projects-per-workspace", type=int, default=20)
    parser.add_argument(
        "--events-per-project",
        type=int,
        default=100,
        help="Pre-existing sync_event rows per project, for pull pagination (S3).",
    )
    parser.add_argument(
        "--token-minutes",
        type=int,
        default=0,
        help="Access-token lifetime override in minutes. 0 uses the server default "
        "(15). Use a longer value for the 4h soak scenario (S10).",
    )
    parser.add_argument("--out", default="identities.json")
    parser.add_argument("--cleanup", action="store_true", help="Delete stress-* rows and exit.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    database_url = _require_env()

    # Imported after sys.path setup and env validation.
    from sqlalchemy import text
    from sqlmodel import Session, create_engine, select
    from tracelab_server.auth.password import hash_password
    from tracelab_server.models.cloud_entities import (
        AuthSession,
        Device,
        DeviceProjectBinding,
        UserAccount,
        Workspace,
        WorkspaceMember,
    )

    engine = create_engine(database_url, echo=False)

    if args.cleanup:
        _cleanup(engine, text)
        return

    # One Argon2 hash reused across every seeded account: hashing is deliberately
    # expensive (64 MiB, 3 passes) and the stress accounts all share a password.
    shared_hash = hash_password(DEFAULT_PASSWORD)
    now = _utc_now()
    identities: list[dict] = []

    with Session(engine) as session:
        existing = session.exec(
            select(UserAccount).where(UserAccount.email_normalized.like(f"{PREFIX}%"))
        ).first()
        if existing is not None:
            raise SystemExit("Stress fixtures already present; run --cleanup first.")

        users: list[UserAccount] = []
        for index in range(args.users):
            user = UserAccount(
                email_normalized=f"{PREFIX}user{index:04d}@stress.local",
                password_hash=shared_hash,
                display_name=f"Stress User {index:04d}",
                status="active",
                email_verified_at=now,  # require_verified() would 403 otherwise
            )
            session.add(user)
            users.append(user)
        session.commit()

        workspaces: list[Workspace] = []
        for index in range(args.workspaces):
            owner = users[index % len(users)]
            workspace = Workspace(
                name=f"{PREFIX}workspace{index:03d}",
                created_by=owner.user_id,
                plan="free",
                workspace_seq=0,
            )
            session.add(workspace)
            workspaces.append(workspace)
        session.commit()

        # Every user is an editor in every workspace so any virtual user can push
        # anywhere; the shared-vs-isolated split is decided by the locustfile.
        for workspace in workspaces:
            for user in users:
                role = "owner" if user.user_id == workspace.created_by else "editor"
                session.add(
                    WorkspaceMember(
                        workspace_id=workspace.workspace_id, user_id=user.user_id, role=role
                    )
                )
        session.commit()

        projects_by_workspace = _seed_projects(
            session, workspaces, users, args.projects_per_workspace
        )
        _seed_events(session, workspaces, projects_by_workspace, args.events_per_project)
        identities = _seed_devices_and_tokens(
            session, users, workspaces, projects_by_workspace, args, Device,
            AuthSession, DeviceProjectBinding,
        )
        # Snapshot plain values while the session is still open: the ORM instances
        # are detached once it closes.
        workspace_summary = [
            {
                "workspace_id": workspace.workspace_id,
                "projects": projects_by_workspace[workspace.workspace_id],
            }
            for workspace in workspaces
        ]

    payload = {
        "generated_at": now.isoformat(),
        "workspaces": workspace_summary,
        "identities": identities,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"Seeded {len(identities)} identities across {len(workspace_summary)} workspaces "
        f"-> {out_path}"
    )
    print("Token lifetime is limited; re-run before long soak scenarios if they expire.")


def _seed_projects(session, workspaces, users, per_workspace: int) -> dict[str, list[str]]:
    from tracelab_server.models.cloud_entities import CloudProject

    result: dict[str, list[str]] = {}
    for workspace in workspaces:
        owner = next(u for u in users if u.user_id == workspace.created_by)
        ids: list[str] = []
        for index in range(per_workspace):
            project = CloudProject(
                public_id=str(uuid4()),
                workspace_id=workspace.workspace_id,
                name=f"{PREFIX}project{index:03d}",
                description="stress fixture",
                created_by=owner.user_id,
                updated_by=owner.user_id,
                version=1,
                sync_mode="cloud_enabled",
            )
            session.add(project)
            ids.append(project.public_id)
        result[workspace.workspace_id] = ids
    session.commit()
    return result


def _seed_events(session, workspaces, projects_by_workspace, per_project: int) -> None:
    """Backfill sync_event rows so pull pagination (S3) has depth to page through."""
    from tracelab_server.models.cloud_entities import SyncEvent

    if per_project <= 0:
        return
    for workspace in workspaces:
        seq = workspace.workspace_seq
        for project_id in projects_by_workspace[workspace.workspace_id]:
            for _ in range(per_project):
                seq += 1
                session.add(
                    SyncEvent(
                        workspace_id=workspace.workspace_id,
                        workspace_seq=seq,
                        entity_type="trace_link",
                        entity_public_id=str(uuid4()),
                        operation="upsert",
                        entity_version=1,
                        payload_json={
                            "project_public_id": project_id,
                            "paper_ref": "seed",
                            "code_ref": "seed",
                            "status": "proposed",
                        },
                    )
                )
        workspace.workspace_seq = seq
        session.add(workspace)
        session.commit()


def _seed_devices_and_tokens(
    session, users, workspaces, projects_by_workspace, args,
    Device, AuthSession, DeviceProjectBinding,
) -> list[dict]:
    """Create one device + auth session per user and mint an access token for it.

    apply_operation() requires the JWT's device claim to match the operation's
    device_id, so tokens and devices must be minted together.
    """
    from tracelab_server.auth import tokens as token_module

    original_minutes = None
    if args.token_minutes > 0:
        # settings is a cached singleton; override for the signing window only.
        original_minutes = token_module.settings.cloud_access_token_minutes
        token_module.settings.cloud_access_token_minutes = args.token_minutes

    identities: list[dict] = []
    now = _utc_now()
    try:
        for index, user in enumerate(users):
            device = Device(
                user_id=user.user_id,
                name=f"{PREFIX}device{index:04d}",
                platform="stress",
                client_version="stress",
            )
            session.add(device)
            session.commit()

            auth_session = AuthSession(
                user_id=user.user_id,
                device_id=device.device_id,
                refresh_token_hash=f"stress-{uuid4().hex}",
                expires_at=now + timedelta(days=1),
            )
            session.add(auth_session)
            session.commit()

            # Bind the device to every project: _validate_project_allows_push()
            # rejects operations from devices without a cloud_enabled binding.
            for workspace in workspaces:
                for project_id in projects_by_workspace[workspace.workspace_id]:
                    session.add(
                        DeviceProjectBinding(
                            device_id=device.device_id,
                            workspace_id=workspace.workspace_id,
                            project_public_id=project_id,
                            sync_mode="cloud_enabled",
                        )
                    )
            session.commit()

            identities.append(
                {
                    "user_id": user.user_id,
                    "email": user.email_normalized,
                    "device_id": device.device_id,
                    "access_token": token_module.create_access_token(
                        user.user_id, auth_session.session_id, device.device_id
                    ),
                    "home_workspace_id": workspaces[index % len(workspaces)].workspace_id,
                }
            )
    finally:
        if original_minutes is not None:
            token_module.settings.cloud_access_token_minutes = original_minutes
    return identities


def _cleanup(engine, text) -> None:
    """Remove stress-* fixtures. Order follows FK dependencies."""
    # Devices are selected by owning user, not by name: auth scenarios log in with
    # their own device_name, so name-matching alone leaves rows behind and the
    # user_account delete then trips device_user_id_fkey.
    stress_devices = (
        "(SELECT device_id FROM device WHERE user_id IN "
        "(SELECT user_id FROM user_account WHERE email_normalized LIKE :p))"
    )
    statements = [
        f"DELETE FROM sync_receipt WHERE device_id IN {stress_devices}",
        f"DELETE FROM device_project_binding WHERE device_id IN {stress_devices}",
        # Created by ack during a run, not by seeding; must go before device.
        f"DELETE FROM sync_device_cursor WHERE device_id IN {stress_devices}",
        # Created by blob scenarios; upload_session and blob_reference both point at
        # blob_object, and neither FK cascades, so they have to go first.
        "DELETE FROM upload_session WHERE blob_id IN "
        "(SELECT blob_id FROM blob_object WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p))",
        "DELETE FROM blob_reference WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM artifact_version WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM blob_object WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM entity_tombstone WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM sync_event WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM cloud_entity WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM cloud_project WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM workspace_member WHERE workspace_id IN "
        "(SELECT workspace_id FROM workspace WHERE name LIKE :p)",
        "DELETE FROM auth_session WHERE user_id IN "
        "(SELECT user_id FROM user_account WHERE email_normalized LIKE :p)",
        "DELETE FROM admin_web_session WHERE user_id IN "
        "(SELECT user_id FROM user_account WHERE email_normalized LIKE :p)",
        "DELETE FROM device WHERE user_id IN "
        "(SELECT user_id FROM user_account WHERE email_normalized LIKE :p)",
        "DELETE FROM workspace WHERE name LIKE :p",
        "DELETE FROM email_token WHERE user_id IN "
        "(SELECT user_id FROM user_account WHERE email_normalized LIKE :p)",
        # bucket_key is a privacy hash, so it never matches the stress- prefix.
        # Clear every bucket instead: this is a disposable stress database, and
        # leftover counters would make the next run start pre-throttled.
        "DELETE FROM auth_rate_limit",
        "DELETE FROM user_account WHERE email_normalized LIKE :p",
    ]
    pattern = f"{PREFIX}%"
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), {"p": pattern})
    print("Stress fixtures removed.")


if __name__ == "__main__":
    main()
