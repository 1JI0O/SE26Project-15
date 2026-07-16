import ctypes
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
        (
            "http://127.0.0.1:5173,http://localhost:5173,tauri://localhost,"
            "http://tauri.localhost,https://tauri.localhost"
        ),
    )


def _watch_desktop_parent() -> None:
    raw_parent_pid = os.getenv("TRACELAB_PARENT_PID")
    if not raw_parent_pid:
        return
    try:
        parent_pid = int(raw_parent_pid)
    except ValueError:
        return

    def parent_is_running() -> bool:
        if os.name != "nt":
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            return True

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            parent_pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            process_is_queryable = ctypes.windll.kernel32.GetExitCodeProcess(
                handle,
                ctypes.byref(exit_code),
            )
            return bool(process_is_queryable) and exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def monitor() -> None:
        while True:
            if not parent_is_running():
                os._exit(0)
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
