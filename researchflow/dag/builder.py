"""Static DAG builder and validator (T0 WP-04).

The graph is a pure function of ``TaskSpec`` (dataset contents, parameters,
template).  Building it validates the dataset fingerprint, template
registration, parameter ranges, node specs and graph structure.  ``graph_hash``
covers the canonical node/edge payload only, so two runs with the same inputs
produce the same hash.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from researchflow.contracts.encoding import hash_payload
from researchflow.contracts.models import NodeSpec, TaskSpec
from researchflow.dag.errors import DagError
from researchflow.persistence.db import format_utc, utc_now
from researchflow.persistence.records import (
    GRAPH_REGISTRATION,
    GraphRecord,
    GraphRepository,
)
from researchflow.rules import load_ruleset
from researchflow.templates.datasets import load_dataset_frame, resolve_dataset
from researchflow.templates.errors import TemplateError
from researchflow.templates.registry import (
    GROUP_COLUMN,
    SPLIT_TEMPLATE_ID,
    TASK_TEMPLATE_ID,
    TIME_COLUMN,
    TRAIN_TEMPLATE_ID,
    NODE_TYPE_SPLIT,
    NODE_TYPE_TRAIN,
    TemplateSpec,
    lookup_node_template,
    lookup_task_template,
    validate_split_parameters,
    validate_task_parameters,
    validate_train_parameters,
)

__all__ = [
    "GRAPH_SCHEMA_VERSION",
    "Graph",
    "GraphNode",
    "build_graph",
    "graph_payload",
    "register_graph",
    "validate_graph",
]

GRAPH_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    node_type: str
    template_id: str
    depends_on: tuple[str, ...]
    input_refs: tuple[str, ...]
    parameters_hash: str
    parameters: dict[str, Any]
    side_effect_class: str
    required_checks: tuple[str, ...]
    retry_policy: dict[str, Any]
    schema_version: str = "1.0"

    def to_spec_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "template_id": self.template_id,
            "depends_on": list(self.depends_on),
            "input_refs": list(self.input_refs),
            "parameters_hash": self.parameters_hash,
            "side_effect_class": self.side_effect_class,
            "retry_policy": dict(self.retry_policy),
            "required_checks": list(self.required_checks),
        }

    def to_node_spec(self) -> NodeSpec:
        return NodeSpec.model_validate(self.to_spec_dict())


@dataclass(frozen=True, slots=True)
class Graph:
    task_id: str
    graph_version: int
    nodes: tuple[GraphNode, ...]
    edges: tuple[tuple[str, str], ...]
    topology_order: tuple[str, ...]
    graph_hash: str
    dataset_uri: str
    dataset_sha256: str

    def node(self, node_id: str) -> GraphNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(node.node_id for node in self.nodes)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "task_id": self.task_id,
            "graph_version": self.graph_version,
            "graph_hash": self.graph_hash,
            "topology_order": list(self.topology_order),
            "dataset": {
                "uri": self.dataset_uri,
                "sha256": self.dataset_sha256,
            },
            "nodes": [node.to_spec_dict() for node in self.nodes],
            "edges": [[edge[0], edge[1]] for edge in self.edges],
            "parameters_by_node": {
                node.node_id: dict(node.parameters) for node in self.nodes
            },
        }


def graph_payload(nodes: Sequence[GraphNode], edges: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Canonical hash payload: node specs + edges, no timestamps or task id."""

    ordered_nodes = sorted(nodes, key=lambda node: node.node_id)
    ordered_edges = sorted({(edge[0], edge[1]) for edge in edges})
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "nodes": [node.to_spec_dict() for node in ordered_nodes],
        "edges": [[edge[0], edge[1]] for edge in ordered_edges],
    }


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def validate_graph(
    nodes: Sequence[NodeSpec], edges: Sequence[tuple[str, str]]
) -> list[dict[str, str]]:
    """Validate a static graph and return every structural problem found."""

    rules = load_ruleset().get("graph", {})
    max_nodes = int(rules.get("max_nodes", 32))
    max_edges = int(rules.get("max_edges", 64))
    issues: list[dict[str, str]] = []
    ids = [node.node_id for node in nodes]
    if len(ids) != len(set(ids)):
        duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
        issues.append(_issue("DAG_DUPLICATE_NODE", f"duplicate node ids: {duplicates}"))
    if len(nodes) > max_nodes:
        issues.append(
            _issue("DAG_TOO_LARGE", f"{len(nodes)} nodes exceed the limit {max_nodes}")
        )
    if len(edges) > max_edges:
        issues.append(
            _issue("DAG_TOO_LARGE", f"{len(edges)} edges exceed the limit {max_edges}")
        )
    edge_set = set(edges)
    if len(edge_set) != len(edges):
        issues.append(_issue("DAG_DUPLICATE_EDGE", "the edge list contains duplicates"))

    known = set(ids)
    for node in nodes:
        if len(set(node.depends_on)) != len(node.depends_on):
            issues.append(
                _issue(
                    "DAG_DUPLICATE_EDGE",
                    f"node {node.node_id!r} repeats a dependency",
                )
            )
        if node.node_id in node.depends_on:
            issues.append(
                _issue("DAG_SELF_DEPENDENCY", f"node {node.node_id!r} depends on itself")
            )
        for dependency in node.depends_on:
            if dependency not in known:
                issues.append(
                    _issue(
                        "DAG_MISSING_DEPENDENCY",
                        f"node {node.node_id!r} depends on unknown node {dependency!r}",
                    )
                )

    # Cycle detection over the declared edges (DFS with an explicit path).
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in ids}
    for source, target in sorted(edge_set):
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    state: dict[str, int] = {node_id: 0 for node_id in ids}
    stack_path: list[str] = []

    def _visit(node_id: str) -> list[str] | None:
        state[node_id] = 1
        stack_path.append(node_id)
        for successor in adjacency.get(node_id, []):
            if state.get(successor, 0) == 1:
                start = stack_path.index(successor)
                return stack_path[start:] + [successor]
            if state.get(successor, 0) == 0:
                found = _visit(successor)
                if found:
                    return found
        stack_path.pop()
        state[node_id] = 2
        return None

    for node_id in ids:
        if state[node_id] == 0:
            cycle = _visit(node_id)
            if cycle:
                issues.append(_issue("DAG_CYCLE", "cycle: " + " -> ".join(cycle)))
                break

    # Orphan/reachability: every node must be reachable from a dependency-free root.
    roots = [node.node_id for node in nodes if not node.depends_on]
    dependents: dict[str, int] = {node_id: 0 for node_id in ids}
    for source, target in edge_set:
        if target in dependents:
            dependents[target] += 1
    if len(ids) > 1:
        isolated = sorted(
            node_id
            for node_id in ids
            if not any(edge[0] == node_id for edge in edge_set)
            and dependents.get(node_id, 0) == 0
            and len(ids) > 1
        )
        if isolated:
            issues.append(
                _issue("DAG_ORPHAN", f"isolated nodes with no edges: {isolated}")
            )
    reachable: set[str] = set()

    def _reach(node_id: str) -> None:
        if node_id in reachable:
            return
        reachable.add(node_id)
        for successor in adjacency.get(node_id, []):
            _reach(successor)

    for root in roots:
        _reach(root)
    unreachable = sorted(known - reachable)
    if unreachable and not any(issue["code"] == "DAG_CYCLE" for issue in issues):
        issues.append(
            _issue("DAG_ORPHAN", f"nodes not reachable from any root: {unreachable}")
        )
    return issues


def _topology_order(nodes: Sequence[NodeSpec]) -> tuple[str, ...]:
    """Deterministic Kahn order: ties are broken by node id."""

    dependencies = {node.node_id: set(node.depends_on) for node in nodes}
    order: list[str] = []
    ready = sorted(node_id for node_id, deps in dependencies.items() if not deps)
    remaining = {node_id: set(deps) for node_id, deps in dependencies.items()}
    while ready:
        current = ready[0]
        ready = ready[1:]
        order.append(current)
        remaining.pop(current, None)
        for node_id in sorted(remaining):
            remaining[node_id].discard(current)
        newly_ready = {
            node_id
            for node_id, deps in remaining.items()
            if not deps and node_id not in order
        }
        ready = sorted(set(ready) | newly_ready)
    return tuple(order)


def _node_spec(
    *,
    node_id: str,
    node_type: str,
    template: TemplateSpec,
    depends_on: Sequence[str],
    input_refs: Sequence[str],
    parameters: Mapping[str, Any],
) -> GraphNode:
    payload = dict(parameters)
    node = GraphNode(
        node_id=node_id,
        node_type=node_type,
        template_id=template.template_id,
        depends_on=tuple(depends_on),
        input_refs=tuple(input_refs),
        parameters_hash=hash_payload(payload),
        parameters=payload,
        side_effect_class=template.side_effect_class,
        required_checks=template.required_checks,
        retry_policy={
            "max_attempts": template.retry_policy[0],
            "backoff_sec": template.retry_policy[1],
        },
    )
    try:
        node.to_node_spec()
    except Exception as exc:  # pydantic ValidationError
        raise DagError(
            "DAG_INVALID_NODE_SPEC",
            f"node {node_id!r} failed NodeSpec validation: {exc}",
            field_path=f"nodes.{node_id}",
        ) from exc
    return node


def build_graph(spec: TaskSpec | Mapping[str, Any]) -> Graph:
    task_spec = spec if isinstance(spec, TaskSpec) else TaskSpec.model_validate(spec)
    try:
        lookup_task_template(task_spec.template_id)
        dataset = resolve_dataset(
            task_spec.dataset_ref.uri, task_spec.dataset_ref.sha256
        )
        frame = load_dataset_frame(dataset)
        parameters = validate_task_parameters(
            task_spec.model_dump()["parameters"], list(dataset.columns)
        )
    except TemplateError as exc:
        raise DagError(exc.code, str(exc), field_path=exc.field_path) from exc

    split_template = lookup_node_template(SPLIT_TEMPLATE_ID)
    train_template = lookup_node_template(TRAIN_TEMPLATE_ID)

    split_parameters = validate_split_parameters(
        {
            "target": parameters["target"],
            "seed": parameters["seed"],
            "test_size": parameters["test_size"],
        },
        list(dataset.columns),
    )
    nodes: list[GraphNode] = [
        _node_spec(
            node_id="split_dataset",
            node_type=NODE_TYPE_SPLIT,
            template=split_template,
            depends_on=(),
            input_refs=("artifact://dataset",),
            parameters=split_parameters,
        )
    ]
    for model in parameters["models"]:
        train_parameters = validate_train_parameters(
            {"model": model, "seed": parameters["seed"]}
        )
        nodes.append(
            _node_spec(
                node_id=f"train_{model}",
                node_type=NODE_TYPE_TRAIN,
                template=train_template,
                depends_on=("split_dataset",),
                input_refs=("artifact://split_manifest",),
                parameters=train_parameters,
            )
        )

    specs = [node.to_node_spec() for node in nodes]
    edges = tuple(
        (dependency, node.node_id)
        for node in nodes
        for dependency in node.depends_on
    )
    issues = validate_graph(specs, edges)
    if issues:
        first = issues[0]
        raise DagError(first["code"], first["detail"])
    order = _topology_order(specs)
    payload = graph_payload(nodes, edges)
    return Graph(
        task_id=task_spec.task_id,
        graph_version=1,
        nodes=tuple(nodes),
        edges=tuple(sorted(set(edges))),
        topology_order=order,
        graph_hash=hash_payload(payload),
        dataset_uri=task_spec.dataset_ref.uri,
        dataset_sha256=task_spec.dataset_ref.sha256,
    )


def register_graph(
    connection: sqlite3.Connection,
    graph: Graph,
    *,
    repository: GraphRepository | None = None,
    created_at: str | None = None,
) -> GraphRecord:
    repo = repository or GraphRepository()
    existing = repo.get(connection, graph.task_id, graph.graph_version)
    if existing is not None:
        if existing.graph_hash == graph.graph_hash:
            return existing
        raise DagError(
            "GRAPH_VERSION_CONFLICT",
            "graph version already registered with a different graph_hash",
        )
    repo.register(
        connection,
        task_id=graph.task_id,
        graph_version=graph.graph_version,
        graph_hash=graph.graph_hash,
        topology_order=graph.topology_order,
        graph_json=graph.to_json(),
        created_at=created_at or format_utc(utc_now()),
        capability=GRAPH_REGISTRATION,
    )
    record = repo.get(connection, graph.task_id, graph.graph_version)
    assert record is not None
    return record