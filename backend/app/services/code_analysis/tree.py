from typing import Any


def _meta_for_language(language: str) -> str:
    return {"python": "python", "docs": "doc", "config": "config"}.get(language, "file")


def build_hierarchical_tree(
    file_tree: list[dict[str, Any]],
    *,
    root_name: str = "repository",
) -> list[dict[str, Any]]:
    if not file_tree:
        return []
    tree: dict[str, Any] = {"children": {}}
    for item in sorted(file_tree, key=lambda entry: str(entry["path"])):
        parts = [part for part in str(item["path"]).split("/") if part]
        node = tree
        for index, part in enumerate(parts):
            is_file = index == len(parts) - 1
            children = node.setdefault("children", {})
            children.setdefault(
                part,
                {
                    "name": part,
                    "path": "/".join(parts[: index + 1]),
                    "kind": "file" if is_file else "folder",
                    "meta": (
                        _meta_for_language(str(item.get("language", "file"))) if is_file else ""
                    ),
                    "size": int(item.get("size", 0)) if is_file else None,
                    "children": {},
                },
            )
            node = children[part]

    def serialize(node_map: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for name in sorted(node_map, key=lambda key: (node_map[key]["kind"] != "folder", key)):
            current = node_map[name]
            children = serialize(current["children"])
            descendant_count = sum(1 + int(child.get("descendant_count", 0)) for child in children)
            if current["kind"] == "folder":
                current["meta"] = f"{descendant_count} entries"
            result.append(
                {
                    "name": current["name"],
                    "path": current["path"],
                    "kind": current["kind"],
                    "meta": current["meta"],
                    "size": current["size"],
                    "child_count": len(children),
                    "descendant_count": descendant_count,
                    "has_children": bool(children),
                    "children": children,
                }
            )
        return result

    children = serialize(tree["children"])
    return [
        {
            "name": root_name,
            "path": "",
            "kind": "folder",
            "meta": "root",
            "size": None,
            "child_count": len(children),
            "descendant_count": sum(1 + child["descendant_count"] for child in children),
            "has_children": bool(children),
            "children": children,
        }
    ]
