"""T0 WP-09 verifier L1/L2 tests: integrity, metric recomputation, leakage rules."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from researchflow.evidence import GENESIS_PREV_HASH, chain_hash_for
from researchflow.persistence.db import connect
from researchflow.persistence.repositories import COLLECTOR_APPEND, EvidenceRepository, EvidenceRow
from researchflow.templates.split import manifest_hash
from researchflow.verification import L1Verifier, L2Verifier, load_context
from support import make_world, tamper_job_parameters


@pytest.fixture()
def executed(tmp_path: Path):
    world = make_world(tmp_path)
    result = world["pipeline"].execute(world["task_id"])
    assert result.ok is True, result.error
    world["ctx"] = load_context(world["db_path"], world["root"], world["task_id"])
    return world


def _split_output(world) -> Path:
    return (
        world["root"] / "tasks" / world["task_id"] / "attempts" / "split_dataset"
        / "attempt_01" / "output"
    )


def _train_output(world) -> Path:
    return (
        world["root"] / "tasks" / world["task_id"] / "attempts"
        / "train_logistic_regression" / "attempt_01" / "output"
    )


def test_l1_passes_on_a_real_execution(executed) -> None:
    result = L1Verifier().run(executed["ctx"])
    assert result.status == "PASS", result.to_dict()
    assert result.chain_ok is True
    assert result.checks > 0


def test_l1_detects_artifact_tampering(executed) -> None:
    ( _split_output(executed) / "split_manifest.json").write_text("{}", encoding="utf-8")
    result = L1Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    assert "L1_ARTIFACT_HASH_MISMATCH" in {issue.code for issue in result.issues}


def test_l1_detects_a_missing_artifact(executed) -> None:
    (_split_output(executed) / "split_manifest.json").unlink()
    result = L1Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    assert "L1_ARTIFACT_MISSING" in {issue.code for issue in result.issues}


def test_l1_detects_a_chain_gap(executed) -> None:
    row = EvidenceRow(
        evidence_id="ev_" + str(uuid.uuid4()),
        task_id=executed["task_id"],
        node_id="split_dataset",
        attempt_id="attempt_01",
        event_seq=999,
        level="E2",
        kind="artifact_observed",
        producer="collector",
        timestamp="2026-11-14T23:59:59.000000Z",
        payload_hash="e" * 64,
        artifact_refs=None,
        prev_hash=GENESIS_PREV_HASH,
        chain_hash="",
    )
    row = EvidenceRow(
        **{**_row_dict(row), "chain_hash": chain_hash_for(row)}
    )
    connection = connect(executed["db_path"])
    try:
        EvidenceRepository().append(
            connection,
            evidence_id=row.evidence_id,
            task_id=row.task_id,
            node_id=row.node_id,
            attempt_id=row.attempt_id,
            event_seq=row.event_seq,
            level=row.level,
            kind=row.kind,
            producer=row.producer,
            timestamp=row.timestamp,
            payload_hash=row.payload_hash,
            artifact_refs=row.artifact_refs,
            prev_hash=row.prev_hash,
            chain_hash=row.chain_hash,
            capability=COLLECTOR_APPEND,
        )
        connection.commit()
    finally:
        connection.close()
    fresh = load_context(executed["db_path"], executed["root"], executed["task_id"])
    result = L1Verifier().run(fresh)
    assert result.status == "FAIL"
    assert any(issue.code.startswith("L1_CHAIN_") for issue in result.issues)


def test_l1_detects_missing_attempt_result(executed) -> None:
    (
        executed["root"] / "tasks" / executed["task_id"] / "attempts"
        / "split_dataset" / "attempt_01" / "result.json"
    ).unlink()
    result = L1Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    assert "L1_ATTEMPT_RESULT_MISSING" in {issue.code for issue in result.issues}


def test_l1_rejects_train_job_parameters_not_matching_nodespec(executed) -> None:
    job = tamper_job_parameters(
        executed["root"],
        executed["task_id"],
        "train_logistic_regression",
        1,
        lambda parameters: parameters.__setitem__("seed", 43),
    )
    # The attacker also rewrote the declared hash; only NodeSpec/E2 can catch it.
    assert job["parameters_hash"] != executed["ctx"].parameter_binding(
        "train_logistic_regression", 1
    ).nodespec_parameters_hash

    result = L1Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    issues = [
        issue
        for issue in result.issues
        if issue.code == "L1_PARAMETERS_BINDING_MISMATCH"
    ]
    assert issues
    assert issues[0].node_id == "train_logistic_regression"
    assert "NodeSpec parameters_hash" in issues[0].detail
    assert job["parameters_hash"] in issues[0].detail


def test_l1_rejects_split_job_parameters_not_matching_nodespec(executed) -> None:
    job = tamper_job_parameters(
        executed["root"],
        executed["task_id"],
        "split_dataset",
        1,
        lambda parameters: parameters.__setitem__("seed", 43),
    )
    result = L1Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    issues = [
        issue
        for issue in result.issues
        if issue.code == "L1_PARAMETERS_BINDING_MISMATCH"
    ]
    assert issues
    assert issues[0].node_id == "split_dataset"
    assert job["parameters_hash"] in issues[0].detail
    assert "NodeSpec parameters_hash" in issues[0].detail


def test_l1_rejects_stale_declared_parameters_hash(executed) -> None:
    tamper_job_parameters(
        executed["root"],
        executed["task_id"],
        "train_logistic_regression",
        1,
        lambda parameters: parameters.__setitem__("seed", 43),
        update_declared_hash=False,
    )
    result = L1Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    issues = [
        issue
        for issue in result.issues
        if issue.code == "L1_PARAMETERS_BINDING_MISMATCH"
    ]
    assert issues
    assert any("hash_payload(job.parameters)" in issue.detail for issue in issues)


def test_l1_rejects_missing_e2_parameters_binding(executed) -> None:
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
    result = L1Verifier().run(ctx)
    assert result.status == "FAIL"
    issues = [
        issue
        for issue in result.issues
        if issue.code == "L1_PARAMETERS_BINDING_INCOMPLETE"
        and issue.node_id == "train_logistic_regression"
    ]
    assert issues
    assert "E2 executor_launch is missing" in issues[0].detail


def _row_dict(row: EvidenceRow) -> dict:
    return {
        "evidence_id": row.evidence_id,
        "task_id": row.task_id,
        "node_id": row.node_id,
        "attempt_id": row.attempt_id,
        "event_seq": row.event_seq,
        "level": row.level,
        "kind": row.kind,
        "producer": row.producer,
        "timestamp": row.timestamp,
        "payload_hash": row.payload_hash,
        "artifact_refs": row.artifact_refs,
        "prev_hash": row.prev_hash,
        "chain_hash": row.chain_hash,
    }


def test_l2_passes_and_recomputes_metrics(executed) -> None:
    result = L2Verifier().run(executed["ctx"])
    assert result.status == "PASS", result.to_dict()
    assert "train_logistic_regression" in result.metrics
    reported = result.metrics["train_logistic_regression"]
    recomputed = result.recomputed["train_logistic_regression"]
    assert reported["accuracy"] == pytest.approx(recomputed["accuracy"], abs=1e-12)


def test_l2_rejects_tampered_metrics(executed) -> None:
    path = _train_output(executed) / "metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))
    metrics["accuracy"] = metrics["accuracy"] + 0.1
    path.write_text(json.dumps(metrics), encoding="utf-8")
    result = L2Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    issues = [issue for issue in result.issues if issue.code == "L2_METRIC_MISMATCH"]
    assert issues and issues[0].node_id == "train_logistic_regression"
    assert "accuracy" in issues[0].detail


def test_l2_rejects_tampered_predictions(executed) -> None:
    path = _train_output(executed) / "predictions.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["y_true"] = "1" if rows[0]["y_true"] == "0" else "0"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_index", "y_true", "y_pred"])
        writer.writeheader()
        writer.writerows(rows)
    result = L2Verifier().run(executed["ctx"])
    assert result.status == "FAIL"
    assert "L2_YTRUE_MISMATCH" in {issue.code for issue in result.issues}


def test_l2_leakage_rule_r1_target_in_features(executed) -> None:
    path = _split_output(executed) / "split_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["feature_columns"] = list(manifest["feature_columns"]) + ["diagnosis"]
    manifest["split_hash"] = manifest_hash(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    fresh = load_context(executed["db_path"], executed["root"], executed["task_id"])
    result = L2Verifier().run(fresh)
    assert result.status == "FAIL"
    leakage = [issue for issue in result.issues if issue.code == "L2_LEAKAGE"]
    assert leakage and "R1_TARGET_IN_FEATURES" in leakage[0].detail


def test_l2_leakage_rule_r4_temporal_order(executed) -> None:
    path = _split_output(executed) / "split_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["test_time_min"] = manifest["train_time_max"]
    manifest["split_hash"] = manifest_hash(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    fresh = load_context(executed["db_path"], executed["root"], executed["task_id"])
    result = L2Verifier().run(fresh)
    assert result.status == "FAIL"
    leakage = [issue for issue in result.issues if issue.code == "L2_LEAKAGE"]
    assert leakage and "R4_TEMPORAL_ORDER" in leakage[0].detail


def test_l2_leakage_rule_r3_group_overlap(executed) -> None:
    path = _split_output(executed) / "split_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["test_groups"] = list(manifest["test_groups"]) + [manifest["train_groups"][0]]
    manifest["split_hash"] = manifest_hash(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    fresh = load_context(executed["db_path"], executed["root"], executed["task_id"])
    result = L2Verifier().run(fresh)
    assert result.status == "FAIL"
    leakage = [issue for issue in result.issues if issue.code == "L2_LEAKAGE"]
    assert leakage and "R3_GROUP_OVERLAP" in leakage[0].detail