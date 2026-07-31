"""S1 sync read/write mix and S2 workspace write-hotspot A/B.

Environment:
    STRESS_IDENTITIES  seed file path (default identities.json)
    STRESS_HOTSPOT     "isolated" (default, S1/S2-B) or "shared" (S2-A).
                       "shared" points every virtual user at one workspace to
                       measure the FOR UPDATE serialization described in plan H1.
    STRESS_OPS         operations per push (default 20, server cap is 100)
    STRESS_PULL_LIMIT  pull page size (default 500, server cap is 500)

Read/write ratio is 3:1 via task weights.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

# Locust imports a locustfile as a top-level script, not as a package member, so
# relative imports are unavailable here.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import API, auth_headers, classify, env_int, load_pool  # noqa: E402

POOL = None
HOTSPOT = "isolated"
OPS_PER_PUSH = 20
PULL_LIMIT = 500


@events.init.add_listener
def _on_init(environment, **_kwargs) -> None:
    global POOL, HOTSPOT, OPS_PER_PUSH, PULL_LIMIT
    POOL = load_pool()
    HOTSPOT = os.environ.get("STRESS_HOTSPOT", "isolated").strip().lower()
    OPS_PER_PUSH = max(1, min(env_int("STRESS_OPS", 20), 100))
    PULL_LIMIT = max(1, min(env_int("STRESS_PULL_LIMIT", 500), 500))
    print(
        f"[stress] hotspot={HOTSPOT} ops_per_push={OPS_PER_PUSH} "
        f"pull_limit={PULL_LIMIT} identities={len(POOL.identities)}"
    )


_SEQ = 0


def _next_index() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


class SyncDevice(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.identity = POOL.next_identity()
        self.headers = auth_headers(self.identity)
        index = _next_index()
        workspace = POOL.shared_workspace if HOTSPOT == "shared" else POOL.workspace(index)
        self.workspace_id = workspace["workspace_id"]
        self.projects = workspace["projects"]
        self.project_id = self.projects[index % len(self.projects)]
        self.cursor = 0
        # Track entity versions locally so base_version is usually correct and
        # conflicts stay a signal about concurrency, not about bad bookkeeping.
        self.versions: dict[str, int] = {}

    def _record(self, response, name: str) -> None:
        if response.status_code >= 400:
            response.failure(f"{name}:{classify(response.status_code, response.text)}")
        else:
            response.success()

    @task(3)
    def pull(self) -> None:
        with self.client.get(
            f"{API}/sync/pull",
            params={
                "workspace_id": self.workspace_id,
                "after": self.cursor,
                "limit": PULL_LIMIT,
            },
            headers=self.headers,
            name="GET /sync/pull",
            catch_response=True,
        ) as response:
            self._record(response, "pull")
            if response.status_code == 200:
                body = response.json()
                self.cursor = body.get("next_after", self.cursor)

    @task(1)
    def push(self) -> None:
        operations = [self._trace_link_op() for _ in range(OPS_PER_PUSH)]
        with self.client.post(
            f"{API}/sync/push",
            json={"operations": operations},
            headers=self.headers,
            name=f"POST /sync/push ({OPS_PER_PUSH} ops)",
            catch_response=True,
        ) as response:
            self._record(response, "push")
            if response.status_code == 200:
                self._absorb_results(response.json().get("results", []), operations)

    @task(1)
    def ack(self) -> None:
        with self.client.post(
            f"{API}/sync/ack",
            json={
                "workspace_id": self.workspace_id,
                "device_id": self.identity["device_id"],
                "last_pulled_seq": self.cursor,
            },
            headers=self.headers,
            name="POST /sync/ack",
            catch_response=True,
        ) as response:
            self._record(response, "ack")

    def _trace_link_op(self) -> dict:
        entity_id = str(uuid.uuid4())
        return {
            "workspace_id": self.workspace_id,
            "device_id": self.identity["device_id"],
            "client_operation_id": str(uuid.uuid4()),
            "entity_type": "trace_link",
            "entity_public_id": entity_id,
            "operation": "upsert",
            "base_version": self.versions.get(entity_id, 0),
            "payload": {
                "project_public_id": self.project_id,
                "paper_ref": f"p:{entity_id[:8]}",
                "code_ref": f"c:{entity_id[:8]}",
                "status": "proposed",
            },
        }

    def _absorb_results(self, results: list[dict], operations: list[dict]) -> None:
        """Keep local versions in sync and count conflicts as a first-class metric."""
        by_op = {op["client_operation_id"]: op for op in operations}
        for item in results:
            operation = by_op.get(item.get("client_operation_id"))
            if operation is None:
                continue
            version = item.get("entity_version")
            if version is not None:
                self.versions[operation["entity_public_id"]] = version
            if item.get("status") == "conflict":
                events.request.fire(
                    request_type="SYNC",
                    name="push:conflict",
                    response_time=0,
                    response_length=0,
                    exception=None,
                    context={},
                )
