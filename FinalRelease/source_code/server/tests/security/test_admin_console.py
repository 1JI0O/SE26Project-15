from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from tracelab_server.auth.password import hash_password
from tracelab_server.db.session import get_session
from tracelab_server.main import app
from tracelab_server.models.cloud_entities import CloudSQLModel, UserAccount


@pytest.fixture
def admin_client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CloudSQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            UserAccount(
                email_normalized="admin@example.com",
                password_hash=hash_password("correct horse battery staple"),
                is_platform_admin=True,
                email_verified_at=datetime.now(UTC),
            )
        )
        session.add(
            UserAccount(
                email_normalized="user@example.com",
                password_hash=hash_password("correct horse battery staple"),
                is_platform_admin=False,
                email_verified_at=datetime.now(UTC),
            )
        )
        session.commit()

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


def test_admin_console_uses_opaque_strict_cookie_and_csrf(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/admin-console/login",
        data={
            "email": "admin@example.com",
            "password": "correct horse battery staple",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookies = response.headers.get_list("set-cookie")
    admin_cookie = next(value for value in cookies if "tracelab_admin_session=" in value)
    assert "HttpOnly" in admin_cookie
    assert "SameSite=strict" in admin_cookie
    assert "Path=/admin-console" in admin_cookie
    assert "correct horse" not in admin_cookie
    assert any("tracelab_admin_csrf=" in value for value in cookies)
    dashboard = admin_client.get("/admin-console")
    assert dashboard.status_code == 200
    assert "项目元数据" in dashboard.text
    assert "不提供 PDF、源码、TraceLink 正文或 Agent 内容" in dashboard.text
    rejected = admin_client.post(
        "/admin-console/maintenance/gc_tombstones",
        data={"csrf": "wrong-token"},
    )
    assert rejected.status_code == 403


def test_non_admin_cannot_use_admin_console(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/admin-console/login",
        data={
            "email": "user@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 401
    assert "账号或密码不正确" in response.text
