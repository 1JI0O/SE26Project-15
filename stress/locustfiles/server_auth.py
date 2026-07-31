"""S5 authentication cost and rate limiting (plan H3).

Argon2id at memory_cost=64 MiB / time_cost=3 / parallelism=2 makes every password
verification expensive on an api container capped at cpus: 1.5 / mem_limit: 3g.
This scenario measures that ceiling and checks the rate limiter stays well-behaved
under abuse.

Environment:
    STRESS_IDENTITIES  seed file path (default identities.json)
    STRESS_AUTH_MODE   within_limit | over_limit  (default within_limit)
                       within_limit: distinct accounts, staying under the per-bucket
                                     cap, to measure real login throughput.
                       over_limit:   hammer one account to verify 429 accuracy and
                                     the auth_rate_limit FOR UPDATE contention.
    STRESS_PASSWORD    seeded account password (default StressTest-Passw0rd)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    API,
    ERR_RATE_LIMIT,
    auth_headers,
    classify,
    load_pool,
)

POOL = None
MODE = "within_limit"
PASSWORD = "StressTest-Passw0rd"


@events.init.add_listener
def _on_init(environment, **_kwargs) -> None:
    global POOL, MODE, PASSWORD
    POOL = load_pool()
    MODE = os.environ.get("STRESS_AUTH_MODE", "within_limit").strip().lower()
    PASSWORD = os.environ.get("STRESS_PASSWORD", PASSWORD)
    print(f"[stress] auth mode={MODE} identities={len(POOL.identities)}")


_SEQ = 0


def _next_index() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


class AuthUser(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        index = _next_index()
        if MODE == "over_limit":
            # Every user targets the same account so all requests land in one
            # rate-limit bucket row.
            self.identity = POOL.identities[0]
        else:
            self.identity = POOL.identities[index % len(POOL.identities)]
        self.refresh_token: str | None = None

    def _record(self, response, name: str) -> str | None:
        if response.status_code >= 400:
            kind = classify(response.status_code, response.text)
            if MODE == "over_limit" and kind == ERR_RATE_LIMIT:
                # 429 is the expected, correct outcome here: count it separately
                # instead of polluting the failure rate.
                response.success()
                events.request.fire(
                    request_type="AUTH",
                    name=f"{name}:rate_limited",
                    response_time=0,
                    response_length=0,
                    exception=None,
                    context={},
                )
                return None
            response.failure(f"{name}:{kind}")
            return None
        response.success()
        return "ok"

    @task(3)
    def login(self) -> None:
        with self.client.post(
            f"{API}/auth/login",
            json={
                "email": self.identity["email"],
                "password": PASSWORD,
                "client_kind": "desktop",
                "device_name": "stress",
                "platform": "stress",
            },
            name="POST /auth/login",
            catch_response=True,
        ) as response:
            if self._record(response, "login") is None:
                return
            body = response.json()
            self.refresh_token = body.get("refresh_token")

    @task(1)
    def refresh(self) -> None:
        if not self.refresh_token:
            return
        with self.client.post(
            f"{API}/auth/refresh",
            json={"refresh_token": self.refresh_token, "client_kind": "desktop"},
            name="POST /auth/refresh",
            catch_response=True,
        ) as response:
            if self._record(response, "refresh") is None:
                return
            # Refresh rotates the token; keep the newest or the next call 401s.
            self.refresh_token = response.json().get("refresh_token") or self.refresh_token

    @task(1)
    def me(self) -> None:
        """Cheap authenticated read, as a control against the Argon2-bound paths."""
        with self.client.get(
            f"{API}/auth/me",
            headers=auth_headers(self.identity),
            name="GET /auth/me",
            catch_response=True,
        ) as response:
            self._record(response, "me")
