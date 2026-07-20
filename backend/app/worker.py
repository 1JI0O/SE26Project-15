import signal
import time

from app.core.config import settings
from app.services.cloud_jobs import run_worker_once


def main() -> None:
    settings.validate_cloud_runtime()
    stopped = False

    def stop(*_: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopped:
        if run_worker_once(limit=2) == 0:
            time.sleep(2)


if __name__ == "__main__":
    main()
