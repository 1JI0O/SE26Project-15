import logging
import signal
import time

from tracelab_server.core.config import settings
from tracelab_server.services.cloud_jobs import run_worker_once
from tracelab_server.storage.blob_store import blob_store

logger = logging.getLogger("tracelab_server.worker")


def main() -> None:
    settings.validate_runtime()
    stopped = False

    def stop(*_: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_disk_check = 0.0
    while not stopped:
        now = time.monotonic()
        if now - last_disk_check >= 60:
            disk_percent = blob_store.disk_percent()
            if disk_percent >= settings.cloud_disk_warn_percent:
                logger.error(
                    "Blob storage usage is above the configured warning threshold: %.2f%%",
                    disk_percent,
                )
            last_disk_check = now
        if run_worker_once(limit=2) == 0:
            time.sleep(2)


if __name__ == "__main__":
    main()
