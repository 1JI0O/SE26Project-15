"""S6: admin console polling and maintenance jobs alongside sync traffic.

Run this concurrently with server_sync.py so the measured question is the one the
plan asks -- how much the admin surface and the maintenance workers degrade the sync
path -- rather than how fast the admin endpoints are on an idle server.

The identity used here must have is_platform_admin set; every /admin route depends on
require_platform_admin (`server/tracelab_server/auth/dependencies.py:63`).

Env:
    STRESS_ADMIN_INDEX   identity index to use as admin (default 59)
    STRESS_MAINTENANCE   "1" to also trigger gc and compact-events (default off)

WARNING: maintenance/gc deletes unreferenced blobs. Only ever point this at a
disposable stress environment.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import API, auth_headers, classify, env_int, load_pool  # noqa: E402

POOL = None
ADMIN_INDEX = 59
MAINTENANCE = False


@events.init.add_listener
def _on_init(environment, **_kwargs) -> None:
    global POOL, ADMIN_INDEX, MAINTENANCE
    POOL = load_pool()
    ADMIN_INDEX = env_int("STRESS_ADMIN_INDEX", 59)
    MAINTENANCE = os.environ.get("STRESS_MAINTENANCE", "").strip() == "1"
    print(f"[stress] admin_index={ADMIN_INDEX} maintenance={MAINTENANCE}")


class AdminUser(HttpUser):
    wait_time = between(1.0, 2.0)

    def on_start(self) -> None:
        self.identity = POOL.identities[ADMIN_INDEX % len(POOL.identities)]
        self.headers = auth_headers(self.identity)

    def _record(self, response, name: str) -> bool:
        if response.status_code >= 400:
            response.failure(f"{name}:{classify(response.status_code, response.text)}")
            return False
        response.success()
        return True

    @task(3)
    def metrics(self) -> None:
        with self.client.get(
            f"{API}/admin/metrics",
            headers=self.headers,
            name="GET /admin/metrics",
            catch_response=True,
        ) as response:
            self._record(response, "metrics")

    @task(2)
    def audit(self) -> None:
        with self.client.get(
            f"{API}/admin/audit",
            headers=self.headers,
            name="GET /admin/audit",
            catch_response=True,
        ) as response:
            self._record(response, "audit")

    @task(2)
    def jobs(self) -> None:
        with self.client.get(
            f"{API}/admin/jobs",
            headers=self.headers,
            name="GET /admin/jobs",
            catch_response=True,
        ) as response:
            self._record(response, "jobs")

    @task(2)
    def workspaces(self) -> None:
        with self.client.get(
            f"{API}/admin/workspaces",
            headers=self.headers,
            name="GET /admin/workspaces",
            catch_response=True,
        ) as response:
            self._record(response, "workspaces")

    @task(1)
    def maintenance_gc(self) -> None:
        if not MAINTENANCE:
            return
        with self.client.post(
            f"{API}/admin/maintenance/gc",
            headers=self.headers,
            name="POST /admin/maintenance/gc",
            catch_response=True,
        ) as response:
            self._record(response, "gc")

    @task(1)
    def maintenance_compact(self) -> None:
        if not MAINTENANCE:
            return
        with self.client.post(
            f"{API}/admin/maintenance/compact-events",
            headers=self.headers,
            name="POST /admin/maintenance/compact-events",
            catch_response=True,
        ) as response:
            self._record(response, "compact")
