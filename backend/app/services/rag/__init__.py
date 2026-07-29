"""Semantic retrieval (RAG) over papers, code, and reviewed trace cases.

The layer is additive: every agent keeps its exhaustive read tools, and retrieval only
narrows *where to look first*. Nothing here is allowed to become a semantic verdict — the
agent still reads and verbatim-quotes real evidence before publishing a trace.
"""

from app.services.rag.service import (
    RagUnavailable,
    build_index,
    index_status,
    invalidate,
    refresh_project_indexes,
    search,
    trace_examples,
)

__all__ = [
    "RagUnavailable",
    "build_index",
    "index_status",
    "invalidate",
    "refresh_project_indexes",
    "search",
    "trace_examples",
]
