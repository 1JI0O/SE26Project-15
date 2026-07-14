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


def layout_tensor_graph(graph: dict[str, Any], project_id: str) -> dict[str, Any]:
    ranks = _node_ranks(graph)
    rows: dict[int, int] = defaultdict(int)
    width = 220
    height = 104
    horizontal_gap = 84
    vertical_gap = 56
    positioned: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for node in graph.get("nodes", []):
        node_id = str(node["id"])
        rank = ranks.get(node_id, 0)
        row = rows[rank]
        rows[rank] += 1
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
                "label": str(edge.get("label", edge.get("kind", "tensor"))),
                "points": [
                    [source["x"] + source["width"], source["y"] + source["height"] // 2],
                    [target["x"], target["y"] + target["height"] // 2],
                ],
            }
        )
    return {"project_id": project_id, "renderer": "semantic-dag-v1", "nodes": nodes, "edges": edges}
