import argparse
import getpass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.auth.password import hash_password
from app.auth.service import normalize_email
from app.db.session import engine, init_db
from app.models.cloud_entities import UserAccount, Workspace, WorkspaceMember


def create_admin(email: str, password: str, display_name: str) -> None:
    init_db()
    normalized = normalize_email(email)
    with Session(engine) as session:
        existing = session.exec(
            select(UserAccount).where(UserAccount.email_normalized == normalized)
        ).first()
        if existing:
            existing.is_platform_admin = True
            existing.status = "active"
            existing.email_verified_at = existing.email_verified_at or datetime.now(UTC)
            if password:
                existing.password_hash = hash_password(password)
            session.add(existing)
            session.commit()
            return
        user = UserAccount(
            email_normalized=normalized,
            password_hash=hash_password(password),
            display_name=display_name or normalized.split("@", 1)[0],
            is_platform_admin=True,
            email_verified_at=datetime.now(UTC),
        )
        session.add(user)
        session.flush()
        workspace = Workspace(name=f"{user.display_name} 的工作区", created_by=user.user_id)
        session.add(workspace)
        session.flush()
        session.add(
            WorkspaceMember(workspace_id=workspace.workspace_id, user_id=user.user_id, role="owner")
        )
        session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(prog="tracelab-cloud")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    admin_parser = subparsers.add_parser("create-admin")
    admin_parser.add_argument("--email", required=True)
    admin_parser.add_argument("--display-name", default="TraceLab Admin")
    admin_parser.add_argument("--password")
    args = parser.parse_args()
    if args.command == "migrate":
        init_db()
    elif args.command == "create-admin":
        password = args.password or getpass.getpass("Admin password: ")
        if len(password) < 10:
            parser.error("password must contain at least 10 characters")
        create_admin(args.email, password, args.display_name)


if __name__ == "__main__":
    main()
