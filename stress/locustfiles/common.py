"""Shared helpers for the TraceLab stress locustfiles."""

from __future__ import annotations

import itertools
import json
import os
import threading
from pathlib import Path
from typing import Any

API = "/api/v1"

# Error taxonomy: aggregate error rate hides the bottleneck, so every scenario
# classifies failures into these buckets (plan section 6).
ERR_RATE_LIMIT = "rate_limited_429"
ERR_CONFLICT = "conflict_409"
ERR_QUOTA = "quota_413"
ERR_POOL = "db_pool_timeout"
ERR_LOCK = "db_lock_timeout"
ERR_SERVER = "server_5xx"
ERR_OTHER = "other"


def classify(status_code: int, body: str) -> str:
    """Map a failed response onto the error taxonomy used in the report."""
    lowered = body.lower()
    if status_code == 429:
        return ERR_RATE_LIMIT
    if status_code == 409:
        return ERR_CONFLICT
    if status_code == 413:
        return ERR_QUOTA
    if "queuepool" in lowered or "timed out getting connection" in lowered:
        return ERR_POOL
    if "database is locked" in lowered or "lock timeout" in lowered:
        return ERR_LOCK
    if status_code >= 500:
        return ERR_SERVER
    return ERR_OTHER


class IdentityPool:
    """Hands out pre-signed identities round-robin, one per virtual user.

    Tokens are minted by seed/seed_server.py so no scenario pays the Argon2 login
    cost or trips the login rate limit (plan H3).
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        source = Path(path)
        if not source.exists():
            raise RuntimeError(
                f"{source} not found. Run seed/seed_server.py before starting Locust."
            )
        data = json.loads(source.read_text(encoding="utf-8"))
        self.identities: list[dict[str, Any]] = data["identities"]
        self.workspaces: list[dict[str, Any]] = data["workspaces"]
        if not self.identities:
            raise RuntimeError("Seed file contains no identities.")
        self._cycle = itertools.cycle(self.identities)
        self._lock = threading.Lock()

    def next_identity(self) -> dict[str, Any]:
        with self._lock:
            return next(self._cycle)

    def workspace(self, index: int) -> dict[str, Any]:
        return self.workspaces[index % len(self.workspaces)]

    @property
    def shared_workspace(self) -> dict[str, Any]:
        """The single workspace used by the S2-A write-hotspot arm."""
        return self.workspaces[0]


def load_pool() -> IdentityPool:
    return IdentityPool(os.environ.get("STRESS_IDENTITIES", "identities.json"))


def auth_headers(identity: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {identity['access_token']}",
        "Content-Type": "application/json",
    }


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw.strip() else default
