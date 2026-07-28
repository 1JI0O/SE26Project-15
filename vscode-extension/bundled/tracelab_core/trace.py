"""Headless Agent-based trace generation (desktop-aligned)."""

from __future__ import annotations

from typing import Any

from tracelab_core.agent_trace import run_agent_trace
from tracelab_core.workspace import TraceLabPaths


def run_trace_batch(
    paths: TraceLabPaths,
    *,
    llm_config: dict[str, Any] | None = None,
    limit: int = 30,
    replace: bool = False,
) -> dict[str, Any]:
    """Run Agent trace. ``limit`` kept for CLI compat (soft hint via max_steps)."""
    _ = limit
    return run_agent_trace(
        paths,
        llm_config=llm_config or {},
        max_steps=48,
        replace=replace,
    )
