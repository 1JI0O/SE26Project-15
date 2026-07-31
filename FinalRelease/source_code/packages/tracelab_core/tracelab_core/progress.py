"""Emit NDJSON progress lines for the VS Code extension host."""

from __future__ import annotations

import json
import sys
from typing import Any


def emit_progress(
    phase: str,
    message: str,
    *,
    current: int | None = None,
    total: int | None = None,
    **extra: Any,
) -> None:
    payload: dict[str, Any] = {
        "event": "progress",
        "phase": phase,
        "message": message,
    }
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    payload.update(extra)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()
