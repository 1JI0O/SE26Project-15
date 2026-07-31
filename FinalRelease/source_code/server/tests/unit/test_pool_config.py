"""Pool sizing is configurable, and exhaustion answers 503 rather than 500.

The stress run hit "QueuePool limit of size 5 overflow 10 reached" because the engine was
created without pool arguments and silently took SQLAlchemy's defaults. Both halves matter:
the width has to be settable per service, and hitting it has to degrade gracefully.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import TimeoutError as PoolTimeout

from tracelab_server.db.session import _engine_kwargs
from tracelab_server.main import _pool_timeout_handler


def test_pool_kwargs_are_passed_for_postgres() -> None:
    kwargs = _engine_kwargs("postgresql+psycopg://u:p@host:5432/db")

    # Defaults, not SQLAlchemy's implicit 5+10 with a 30s wait.
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 5
    assert kwargs["pool_timeout"] == 10
    assert kwargs["pool_pre_ping"] is True


def test_pool_kwargs_are_omitted_for_sqlite() -> None:
    kwargs = _engine_kwargs("sqlite:///./test.db")

    # SQLite's pool implementations reject these, so passing them would break the tests.
    for key in ("pool_size", "max_overflow", "pool_timeout"):
        assert key not in kwargs


def test_pool_kwargs_follow_settings(monkeypatch) -> None:
    from tracelab_server.db import session as session_module

    monkeypatch.setattr(session_module.settings, "database_pool_size", 20)
    monkeypatch.setattr(session_module.settings, "database_max_overflow", 20)

    kwargs = _engine_kwargs("postgresql+psycopg://u:p@host:5432/db")
    assert kwargs["pool_size"] == 20
    assert kwargs["max_overflow"] == 20


def test_exhausted_pool_returns_503_with_retry_after() -> None:
    app = FastAPI()
    app.add_exception_handler(PoolTimeout, _pool_timeout_handler)

    @app.get("/boom")
    def _boom() -> None:
        raise PoolTimeout("QueuePool limit of size 5 overflow 5 reached")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert "capacity" in response.json()["detail"]
