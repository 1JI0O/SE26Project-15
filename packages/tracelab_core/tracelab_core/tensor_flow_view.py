"""Build a single-layer tensor-flow payload (desktop parity)."""

from __future__ import annotations

from typing import Any

from tracelab_core.backend_path import ensure_backend_path
from tracelab_core.workspace import TraceLabPaths, read_json


def build_tensor_flow_view(
    paths: TraceLabPaths,
    *,
    view: str = "architecture",
    root_symbol: str | None = None,
) -> dict[str, Any]:
    ensure_backend_path()
    from app.services.tensor_flow.layout import layout_tensor_graph

    architecture = read_json(paths.architecture_json, {}) or {}
    tensor_graph = read_json(paths.tensor_graph_json, {}) or {}
    graphs = architecture.get("graphs") or {}
    selected_root = root_symbol if root_symbol in graphs else architecture.get("default_root")
    selected_graph = graphs.get(selected_root) or {"nodes": [], "edges": []}
    roots = list(architecture.get("roots") or [])
    if selected_root and not any(root.get("symbol_id") == selected_root for root in roots):
        graph_nodes = selected_graph.get("nodes") or []
        roots.append(
            {
                "symbol_id": selected_root,
                "label": selected_graph.get("root_label")
                or str(selected_root).rsplit("::", 1)[-1],
                "source_path": graph_nodes[0].get("source_path", "") if graph_nodes else "",
                "score": 0,
            }
        )

    if view == "debug":
        execution_symbol = selected_graph.get("execution_symbol")
        node_ids = {
            str(node["id"])
            for node in tensor_graph.get("nodes") or []
            if not execution_symbol or node.get("symbol_id") == execution_symbol
        }
        debug_graph = {
            "nodes": [
                node for node in tensor_graph.get("nodes") or [] if str(node["id"]) in node_ids
            ],
            "edges": [
                edge
                for edge in tensor_graph.get("edges") or []
                if str(edge["source"]) in node_ids and str(edge["target"]) in node_ids
            ],
            "root_symbol": selected_root,
            "root_label": selected_graph.get("root_label"),
        }
        payload = layout_tensor_graph(
            debug_graph,
            "vscode",
            renderer="semantic-dag-v1",
            view="debug",
            available_roots=roots,
        )
    else:
        payload = layout_tensor_graph(
            selected_graph,
            "vscode",
            renderer="architecture-dag-v2",
            view="architecture",
            available_roots=roots,
        )

    payload["default_root"] = architecture.get("default_root")
    payload["selected_root"] = selected_root
    return payload
