import multiprocessing
import os
import threading
import time
from pathlib import Path


def _configure_desktop_environment() -> None:
    data_dir = Path(
        os.getenv("TRACELAB_APP_DATA_DIR", Path.home() / ".tracelab")
    ).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{data_dir / 'workbench.db'}")
    os.environ.setdefault("UPLOAD_ROOT", str(data_dir / "uploads"))
    os.environ.setdefault("TRACELAB_PAPER_JOB_ROOT", str(data_dir / "paper-jobs"))
    os.environ.setdefault(
        "BACKEND_CORS_ORIGINS",
        "tauri://localhost,http://tauri.localhost,https://tauri.localhost",
    )


def _watch_desktop_parent() -> None:
    raw_parent_pid = os.getenv("TRACELAB_PARENT_PID")
    if not raw_parent_pid:
        return
    try:
        parent_pid = int(raw_parent_pid)
    except ValueError:
        return

    def monitor() -> None:
        while True:
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                os._exit(0)
            except PermissionError:
                pass
            time.sleep(0.5)

    threading.Thread(target=monitor, name="desktop-parent-watch", daemon=True).start()


def main() -> None:
    multiprocessing.freeze_support()
    _configure_desktop_environment()
    _watch_desktop_parent()

    import uvicorn

    from app.main import app

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("TRACELAB_BACKEND_PORT", "8765")),
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
