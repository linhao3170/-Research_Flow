"""T0 WP-10 L3 tests: real replay from raw data and fake-L3 rejection."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from researchflow.verification import L3IsolationError, L3Verifier, load_context
from support import make_world, tamper_job_parameters


@pytest.fixture()
def executed(tmp_path: Path):
    world = make_world(tmp_path)
    result = world["pipeline"].execute(world["task_id"])
    assert result.ok is True, result.error
    world["ctx"] = load_context(world["db_path"], world["root"], world["task_id"])
    world["l3"] = L3Verifier(world["root"])
    return world


def _train_output(world) -> Path:
    return (
        world["root"] / "tasks" / world["task_id"] / "attempts"
        / "train_logistic_regression" / "attempt_01" / "output"
    )


def test_l3_replays_from_raw_data_in_separate_processes(executed) -> None:
    result = executed["l3"].run(executed["ctx"])
    assert result.status == "PASS", result.to_dict()
    assert result.coverage == 1.0
    assert len(result.nodes) == 1
    node = result.nodes[0]
    assert node.node_id == "train_logistic_regression"
    assert node.split_hash == node.executor_split_hash
    assert node.prediction_mismatches == 0
    assert node.match_mode in {"EXACT", "TOLERANCE"}
    assert node.split_pid is not None and node.train_pid is not None
    assert node.split_pid != os.getpid() and node.train_pid != os.getpid()
    assert node.split_pid != node.train_pid
    verification_root = Path(result.verification_root).resolve()
    assert verification_root.is_dir()
    for directory in (node.l3_split_dir, node.l3_train_dir):
        assert verification_root in Path(directory).resolve().parents
        assert "attempts" in Path(directory).parts
    assert Path(node.l3_train_dir).resolve() != (
        executed["root"] / "tasks" / executed["task_id"] / "attempts"
        / "train_logistic_regression" / "attempt_01"
    ).resolve()


def test_l3_rejects_executor_directory_reuse(executed) -> None:
    fake = SimpleNamespace(
        attempt_dir=(
            executed["root"] / "tasks" / executed["task_id"] / "attempts"
            / "train_logistic_regression" / "attempt_01"
        ),
        pid=99999,
        inputs=(),
    )
    with pytest.raises(L3IsolationError) as excinfo:
        executed["l3"].validate_isolation(
            fake,
            executor_attempt_dir=executed["ctx"].attempt_dir(
                "train_logistic_regression", 1
            ),
        )
    assert excinfo.value.code == "L3_DIR_NOT_ISOLATED"


def test_l3_rejects_in_process_state(executed) -> None:
    fake = SimpleNamespace(attempt_dir=executed["root"] / "verification" / "fake", pid=os.getpid(), inputs=())
    with pytest.raises(L3IsolationError) as excinfo:
        executed["l3"].validate_isolation(
            fake,
            executor_attempt_dir=executed["ctx"].attempt_dir("train_logistic_regression", 1),
        )
    assert excinfo.value.code == "L3_IN_PROCESS_STATE"


def test_l3_rejects_executor_output_as_input(executed) -> None:
    fake = SimpleNamespace(
        attempt_dir=executed["root"] / "verification" / "fake",
        pid=12345,
        inputs=({"name": "executor_predictions", "sha256": "a" * 64, "size": 1},),
    )
    with pytest.raises(L3IsolationError) as excinfo:
        executed["l3"].validate_isolation(
            fake,
            executor_attempt_dir=executed["ctx"].attempt_dir("train_logistic_regression", 1),
        )
    assert excinfo.value.code == "L3_REUSED_EXECUTOR_OUTPUT"


def test_l3_inputs_only_contain_the_replayed_split(executed) -> None:
    result = executed["l3"].run(executed["ctx"])
    assert result.status == "PASS"
    job_path = Path(result.nodes[0].l3_train_dir) / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert set(job["input_artifacts"]) == {"split_manifest"}
    verification_root = Path(result.verification_root).resolve()
    assert verification_root in Path(job["input_artifacts"]["split_manifest"]).resolve().parents


def test_l3_detects_tampered_executor_metrics(executed) -> None:
    path = _train_output(executed) / "metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))
    metrics["accuracy"] = 0.5
    path.write_text(json.dumps(metrics), encoding="utf-8")
    result = executed["l3"].run(executed["ctx"])
    assert result.status == "FAIL"
    assert "L3_METRIC_MISMATCH" in {issue.code for issue in result.issues}


def test_l3_detects_tampered_executor_predictions(executed) -> None:
    path = _train_output(executed) / "predictions.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["y_pred"] = "0" if rows[0]["y_pred"] == "1" else "1"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_index", "y_true", "y_pred"])
        writer.writeheader()
        writer.writerows(rows)
    result = executed["l3"].run(executed["ctx"])
    assert result.status == "FAIL"
    assert "L3_PREDICTION_MISMATCH" in {issue.code for issue in result.issues}


def test_l3_reports_missing_executor_output(executed) -> None:
    (_train_output(executed) / "metrics.json").unlink()
    result = executed["l3"].run(executed["ctx"])
    assert result.status == "FAIL"
    assert result.coverage == 0.0
    assert "L3_MISSING_EXECUTOR_OUTPUT" in {issue.code for issue in result.issues}


def _assert_no_l3_rerun(executed) -> None:
    verification_root = executed["root"] / "verification"
    if verification_root.is_dir():
        assert list(verification_root.glob("l3-*")) == []


def test_l3_rejects_train_parameter_mismatch_before_spawning(executed) -> None:
    job = tamper_job_parameters(
        executed["root"],
        executed["task_id"],
        "train_logistic_regression",
        1,
        lambda parameters: parameters.__setitem__("seed", 43),
    )
    result = executed["l3"].run(executed["ctx"])
    assert result.status == "FAIL"
    assert result.coverage == 0.0
    assert result.nodes == ()
    assert result.processes == ()
    assert result.verification_root == ""
    issues = [
        issue
        for issue in result.issues
        if issue.code == "L3_PARAMETERS_BINDING_MISMATCH"
    ]
    assert issues
    assert issues[0].node_id == "train_logistic_regression"
    assert job["parameters_hash"] in issues[0].detail
    assert "NodeSpec parameters_hash" in issues[0].detail
    _assert_no_l3_rerun(executed)


def test_l3_rejects_split_parameter_mismatch_before_spawning(executed) -> None:
    job = tamper_job_parameters(
        executed["root"],
        executed["task_id"],
        "split_dataset",
        1,
        lambda parameters: parameters.__setitem__("seed", 43),
    )
    result = executed["l3"].run(executed["ctx"])
    assert result.status == "FAIL"
    assert result.coverage == 0.0
    assert result.nodes == ()
    assert result.processes == ()
    assert result.verification_root == ""
    issues = [
        issue
        for issue in result.issues
        if issue.code == "L3_PARAMETERS_BINDING_MISMATCH"
    ]
    assert issues
    assert issues[0].node_id == "split_dataset"
    assert job["parameters_hash"] in issues[0].detail
    _assert_no_l3_rerun(executed)


def test_l3_rejects_missing_e2_parameters_binding(executed) -> None:
    filtered = [
        row
        for row in executed["ctx"].evidence
        if not (
            row.node_id == "train_logistic_regression"
            and row.attempt_id == "attempt_01"
            and row.level == "E2"
            and row.kind == "executor_launch"
        )
    ]
    ctx = replace(executed["ctx"], evidence=filtered)
    result = executed["l3"].run(ctx)
    assert result.status == "FAIL"
    assert result.coverage == 0.0
    assert result.nodes == ()
    assert result.processes == ()
    issues = [
        issue
        for issue in result.issues
        if issue.code == "L3_PARAMETERS_BINDING_INCOMPLETE"
        and issue.node_id == "train_logistic_regression"
    ]
    assert issues
    assert "E2 executor_launch is missing" in issues[0].detail
    _assert_no_l3_rerun(executed)