"""Deterministic invalidation impact analysis (T0 WP-R)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["affected_nodes", "descendants", "topological_order"]


def topological_order(graph_json: Mapping[str, Any]) -> list[str]:
    order = graph_json.get("topology_order")
    if order:
        return [str(node_id) for node_id in order]
    nodes = {str(node["node_id"]): node for node in graph_json.get("nodes", [])}
    result: list[str] = []
    pending = dict(nodes)
    while pending:
        ready = sorted(
            node_id
            for node_id, node in pending.items()
            if all(str(dep) not in pending for dep in node.get("depends_on", []))
        )
        if not ready:  # pragma: no cover - graph was validated earlier
            raise ValueError("graph contains a cycle")
        for node_id in ready:
            result.append(node_id)
            pending.pop(node_id)
    return result


def descendants(graph_json: Mapping[str, Any], node_id: str) -> list[str]:
    nodes = {str(node["node_id"]): node for node in graph_json.get("nodes", [])}
    if node_id not in nodes:
        raise KeyError(node_id)
    children: dict[str, list[str]] = {key: [] for key in nodes}
    for key, node in nodes.items():
        for dependency in node.get("depends_on", []):
            children.setdefault(str(dependency), []).append(key)
    order = topological_order(graph_json)
    reachable = {node_id}
    frontier = [node_id]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, []):
            if child not in reachable:
                reachable.add(child)
                frontier.append(child)
    return [candidate for candidate in order if candidate in reachable]


def affected_nodes(graph_json: Mapping[str, Any], changed_node: str) -> list[str]:
    return descendants(graph_json, changed_node)