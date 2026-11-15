"""T0 WP-04 static DAG tests.

Each negative case asserts the exact machine code (and, where relevant, the
detail) instead of merely expecting an exception.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from researchflow.contracts.models import TaskSpec
from researchflow.dag import DagError, build_graph, register_graph, validate_graph
from researchflow.dag.builder import graph_payload
from researchflow.orchestration.state_machine import Actor, StateMachine
from researchflow.orchestration.transitions import ActorRole
from researchflow.persistence.records import GraphRepository
from support import TASK_ID, make_db, task_payload


def _codes(issues) -> list[str]:
    return [issue["code"] for issue in issues]


def test_valid_graph_has_expected_nodes_edges_and_order() -> None:
    graph = build_graph(TaskSpec.model_validate(task_payload(models=("logistic_regression", "random_forest"))))
    assert graph.node_ids == ("split_dataset", "train_logistic_regression", "train_random_forest")
    assert graph.edges == (
        ("split_dataset", "train_logistic_regression"),
        ("split_dataset", "train_random_forest"),
    )
    assert graph.topology_order == (
        "split_dataset",
        "train_logistic_regression",
        "train_random_forest",
    )
    split = graph.node("split_dataset")
    assert split.required_checks == ("executor_observed", "artifact_hash")
    train = graph.node("train_random_forest")
    assert train.required_checks == (
        "executor_observed",
        "artifact_hash",
        "metric_source",
    )
    assert train.parameters == {"model": "random_forest", "seed": 42}


def test_graph_hash_is_stable_and_input_sensitive() -> None:
    spec = TaskSpec.model_validate(task_payload(models=("logistic_regression",)))
    first = build_graph(spec)
    second = build_graph(spec)
    assert first.graph_hash == second.graph_hash
    assert first.graph_hash == build_graph(
        TaskSpec.model_validate(task_payload(models=("logistic_regression",), seed=42))
    ).graph_hash

    other = build_graph(
        TaskSpec.model_validate(task_payload(models=("logistic_regression",), seed=7))
    )
    assert other.graph_hash != first.graph_hash
    assert graph_payload(first.nodes, first.edges)["nodes"][1]["parameters_hash"] != (
        graph_payload(other.nodes, other.edges)["nodes"][1]["parameters_hash"]
    )


def test_graph_payload_excludes_volatile_fields() -> None:
    graph = build_graph(TaskSpec.model_validate(task_payload()))
    payload = graph_payload(graph.nodes, graph.edges)
    assert "task_id" not in payload
    assert "created_at" not in payload
    assert "timestamp" not in str(payload)


def test_cycle_is_rejected_with_the_cycle_path() -> None:
    nodes = [
        SimpleNamespace(node_id="a", depends_on=["c"]),
        SimpleNamespace(node_id="b", depends_on=["a"]),
        SimpleNamespace(node_id="c", depends_on=["b"]),
    ]
    issues = validate_graph(nodes, [("c", "a"), ("a", "b"), ("b", "c")])
    assert "DAG_CYCLE" in _codes(issues)
    cycle = next(issue for issue in issues if issue["code"] == "DAG_CYCLE")
    assert all(node_id in cycle["detail"] for node_id in ("a", "b", "c"))


def test_self_dependency_is_rejected() -> None:
    nodes = [SimpleNamespace(node_id="a", depends_on=["a"])]
    issues = validate_graph(nodes, [("a", "a")])
    assert "DAG_SELF_DEPENDENCY" in _codes(issues)


def test_duplicate_edge_is_rejected() -> None:
    nodes = [
        SimpleNamespace(node_id="a", depends_on=[]),
        SimpleNamespace(node_id="b", depends_on=["a"]),
    ]
    issues = validate_graph(nodes, [("a", "b"), ("a", "b")])
    assert "DAG_DUPLICATE_EDGE" in _codes(issues)


def test_missing_dependency_is_rejected() -> None:
    nodes = [
        SimpleNamespace(node_id="a", depends_on=[]),
        SimpleNamespace(node_id="b", depends_on=["ghost"]),
    ]
    issues = validate_graph(nodes, [("ghost", "b")])
    assert "DAG_MISSING_DEPENDENCY" in _codes(issues)
    detail = next(i["detail"] for i in issues if i["code"] == "DAG_MISSING_DEPENDENCY")
    assert "ghost" in detail


def test_orphan_node_is_rejected() -> None:
    nodes = [
        SimpleNamespace(node_id="a", depends_on=[]),
        SimpleNamespace(node_id="b", depends_on=["a"]),
        SimpleNamespace(node_id="lonely", depends_on=[]),
    ]
    issues = validate_graph(nodes, [("a", "b")])
    assert "DAG_ORPHAN" in _codes(issues)
    detail = next(i["detail"] for i in issues if i["code"] == "DAG_ORPHAN")
    assert "lonely" in detail


def test_too_many_nodes_is_rejected() -> None:
    nodes = [SimpleNamespace(node_id=f"n{index:02d}", depends_on=[]) for index in range(40)]
    issues = validate_graph(nodes, [])
    assert "DAG_TOO_LARGE" in _codes(issues)


def test_register_graph_is_idempotent_and_version_conflict_fails(tmp_path: Path) -> None:
    db = make_db(tmp_path / "dag.db")
    try:
        spec = TaskSpec.model_validate(task_payload())
        state_machine = StateMachine(tmp_path / "dag.db")
        state_machine.create_initial(
            obj_type="task",
            task_id=TASK_ID,
            actor=Actor(ActorRole.API, "create"),
            correlation_id="req-task",
            task_spec=spec,
            connection=db,
        )
        graph = build_graph(spec)
        first = register_graph(db, graph)
        second = register_graph(db, graph)
        assert first == second
        assert GraphRepository().get(db, TASK_ID, 1).graph_hash == graph.graph_hash

        conflicting = type(graph)(
            task_id=graph.task_id,
            graph_version=graph.graph_version,
            nodes=graph.nodes,
            edges=graph.edges,
            topology_order=graph.topology_order,
            graph_hash="0" * 64,
            dataset_uri=graph.dataset_uri,
            dataset_sha256=graph.dataset_sha256,
        )
        with pytest.raises(DagError) as excinfo:
            register_graph(db, conflicting)
        assert excinfo.value.code == "GRAPH_VERSION_CONFLICT"
    finally:
        db.close()


def test_unknown_task_template_is_rejected() -> None:
    payload = task_payload()
    payload["template_id"] = "nope@1.0.0"
    with pytest.raises(DagError) as excinfo:
        build_graph(TaskSpec.model_validate(payload))
    assert excinfo.value.code == "TEMPLATE_NOT_REGISTERED"
    assert excinfo.value.field_path == "template_id"


def test_dataset_hash_mismatch_is_rejected() -> None:
    with pytest.raises(DagError) as excinfo:
        build_graph(TaskSpec.model_validate(task_payload(dataset_sha="0" * 64)))
    assert excinfo.value.code == "DATASET_HASH_MISMATCH"
    assert excinfo.value.field_path == "dataset_ref.sha256"


def test_unregistered_model_is_rejected_with_field_path() -> None:
    with pytest.raises(DagError) as excinfo:
        build_graph(TaskSpec.model_validate(task_payload(models=("svm",))))
    assert excinfo.value.code == "PARAM_INVALID"
    assert excinfo.value.field_path == "parameters.models[0]"


def test_unknown_parameter_is_rejected() -> None:
    payload = task_payload()
    payload["parameters"]["n_estimators"] = 10
    with pytest.raises(DagError) as excinfo:
        build_graph(TaskSpec.model_validate(payload))
    assert excinfo.value.code == "PARAM_INVALID"
    assert excinfo.value.field_path == "parameters.n_estimators"


def test_unknown_target_column_is_rejected() -> None:
    payload = task_payload()
    payload["parameters"]["target"] = "not_a_column"
    with pytest.raises(DagError) as excinfo:
        build_graph(TaskSpec.model_validate(payload))
    assert excinfo.value.code == "PARAM_INVALID"
    assert excinfo.value.field_path == "parameters.target"