from collections import defaultdict, deque
from typing import Any


def _node_ranks(graph: dict[str, Any]) -> dict[str, int]:
    node_ids = [str(node["id"]) for node in graph.get("nodes", [])]
    incoming: dict[str, int] = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges", []):
        source = str(edge["source"])
        target = str(edge["target"])
        if source not in incoming or target not in incoming:
            continue
        outgoing[source].append(target)
        incoming[target] += 1
    queue = deque(node_id for node_id in node_ids if incoming[node_id] == 0)
    ranks = {node_id: 0 for node_id in node_ids}
    while queue:
        source = queue.popleft()
        for target in outgoing[source]:
            ranks[target] = max(ranks[target], ranks[source] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    return ranks


def _edge_points(source: dict[str, Any], target: dict[str, Any]) -> list[list[int]]:
    source_x = int(source["x"] + source["width"])
    source_y = int(source["y"] + source["height"] // 2)
    target_x = int(target["x"])
    target_y = int(target["y"] + target["height"] // 2)
    if source_y == target_y:
        return [[source_x, source_y], [target_x, target_y]]
    middle_x = source_x + max((target_x - source_x) // 2, 24)
    return [
        [source_x, source_y],
        [middle_x, source_y],
        [middle_x, target_y],
        [target_x, target_y],
    ]


def layout_tensor_graph(
    graph: dict[str, Any],
    project_id: str,
    *,
    renderer: str = "semantic-dag-v1",
    view: str = "debug",
    available_roots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ranks = _node_ranks(graph)
    rows: dict[int, int] = defaultdict(int)
    architecture = view == "architecture"
    width = 204 if architecture else 220
    height = 88 if architecture else 104
    horizontal_gap = 96 if architecture else 84
    vertical_gap = 48 if architecture else 56
    positioned: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for node in graph.get("nodes", []):
        node_id = str(node["id"])
        rank = ranks.get(node_id, 0)
        row = rows[rank]
        rows[rank] += 1
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        laid_out = {
            "id": node_id,
            "label": str(node.get("label") or node.get("op") or node_id),
            "kind": str(node.get("kind", "operation")),
            "description": str(node.get("description", "")),
            "source_path": str(node.get("source_path", "")),
            "line_start": int(node.get("line_start", 1)),
            "line_end": int(node.get("line_end", node.get("line_start", 1))),
            "tensor_shape": node.get("shape"),
            "shape_reason": node.get("shape_reason"),
            "op": str(node.get("op", "unknown")),
            "symbol_id": str(node.get("symbol_id", "")),
            "component_symbol_id": metadata.get("component_symbol_id"),
            "expandable": bool(metadata.get("expandable", False)),
            "external": bool(metadata.get("external", False)),
            "x": 32 + rank * (width + horizontal_gap),
            "y": 32 + row * (height + vertical_gap),
            "width": width,
            "height": height,
        }
        positioned[node_id] = laid_out
        nodes.append(laid_out)
    edges: list[dict[str, Any]] = []
    for edge in graph.get("edges", []):
        source = positioned.get(str(edge["source"]))
        target = positioned.get(str(edge["target"]))
        if source is None or target is None:
            continue
        edges.append(
            {
                "id": str(edge.get("id", f"{source['id']}->{target['id']}")),
                "source": source["id"],
                "target": target["id"],
                "kind": str(edge.get("kind", "tensor")),
                "label": str(edge.get("label", "")),
                "points": _edge_points(source, target),
            }
        )
    return {
        "project_id": project_id,
        "renderer": renderer,
        "view": view,
        "root_symbol": graph.get("root_symbol"),
        "root_label": graph.get("root_label"),
        "available_roots": available_roots or [],
        "nodes": nodes,
        "edges": edges,
    }
