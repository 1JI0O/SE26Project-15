from pathlib import Path

from tracelab_server.main import app

SERVER_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = SERVER_ROOT.parent


def test_desktop_contract_routes_are_present() -> None:
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
        "/api/v1/auth/me",
        "/api/v1/auth/devices",
        "/api/v1/auth/verify-email",
        "/api/v1/auth/password/forgot",
        "/api/v1/auth/password/reset",
        "/api/v1/workspaces",
        "/api/v1/projects",
        "/api/v1/sync/bootstrap",
        "/api/v1/sync/push",
        "/api/v1/sync/pull",
        "/api/v1/sync/ack",
        "/api/v1/blobs/upload-init",
        "/api/v1/admin/users",
        "/api/v1/admin/workspaces",
        "/api/v1/admin/metrics",
        "/api/v1/admin/audit",
        "/api/v1/admin/jobs",
    }
    assert required <= set(paths)


def test_server_has_no_backend_or_frontend_runtime_imports() -> None:
    for path in (SERVER_ROOT / "tracelab_server").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from app." not in source
        assert "import app." not in source
        assert "from backend" not in source
        assert "frontend/" not in source


def test_server_build_context_does_not_copy_application_frontend() -> None:
    dockerfile = (SERVER_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (SERVER_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "COPY frontend" not in dockerfile
    assert "context: ./frontend" not in compose
    assert "context: ./backend" not in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "5432:5432" not in compose
    assert "8000:8000" not in compose


def test_cloud_baseline_is_explicit_and_local_schema_is_not_owned() -> None:
    migration = next(
        (SERVER_ROOT / "tracelab_server/db/migrations/versions").glob(
            "0001_server_baseline*.py"
        )
    ).read_text(encoding="utf-8")
    assert "op.create_table(" in migration
    assert "metadata.create_all" not in migration
    assert "local_sync_outbox" not in migration
    assert "paper_document" not in migration


def test_application_frontend_source_was_not_copied_to_server() -> None:
    assert not (SERVER_ROOT / "frontend").exists()
    assert (REPOSITORY_ROOT / "frontend/src").is_dir()
