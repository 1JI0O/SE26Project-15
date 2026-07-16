import os

from app.desktop import _configure_desktop_environment


def test_desktop_environment_allows_tauri_and_vite_origins(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRACELAB_APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)

    _configure_desktop_environment()

    origins = set(os.environ["BACKEND_CORS_ORIGINS"].split(","))
    assert origins == {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    }
