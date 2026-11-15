"""T0 WP-R tests: deterministic plans, guarded invalidation and conservative rerun."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from researchflow.evidence import Collector
from researchflow.gate import Gate
from researchflow.orchestration.sqlite_ports import build_ports
from researchflow.orchestration.state_machine import (
    Actor,
    StateMachine,
    StateTransitionDenied,
    TransitionContext,
    TransitionRequest,
)
from researchflow.orchestration.transitions import ActorRole, ObjectType
from researchflow.persistence.db import connect, format_utc, transaction, utc_now
from researchflow.persistence.records import list_evidence
from researchflow.persistence.repositories import WP_R_FREEZE, AuditRepository
from researchflow.recovery import (
    PlanError,
    RecoveryService,
    build_plan,
    plan_path,
    read_plan,
    write_plan,
)
from support import make_world, resign_bundle_manifest, task_payload

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "verify_bundle.py"


@pytest.fixture()
def verified_two_models(tmp_path: Path):
    world = make_world(tmp_path, models=("logistic_regression", "random_forest"))
    execution = world["pipeline"].execute(world["task_id"])
    assert execution.ok is True, execution.error
    outcome = world["pipeline"].verify(world["task_id"])
    assert outcome.final_state == "VERIFIED", [gap for gap in outcome.gaps][:3]
    world["pipeline"].mark_nodes_verified(world["task_id"])
    world["recovery"] = RecoveryService(world["db_path"], world["root"])
    return world


def _graph_json(world) -> dict:
    connection = connect(world["db_path"])
    try:
        from researchflow.persistence.records import GraphRepository

        return GraphRepository().get(connection, world["task_id"]).graph_json
    finally:
        connection.close()


def _node_rows(world) -> dict[str, tuple[str, int]]:
    connection = connect(world["db_path"])
    try:
        return {
            str(row["node_id"]): (str(row["state"]), int(row["attempt_seq"]))
            for row in connection.execute(
                "SELECT node_id, state, attempt_seq FROM nodes WHERE task_id = ?",
                (world["task_id"],),
            )
        }
    finally:
        connection.close()


def test_plan_is_deterministic_and_has_no_timestamps() -> None:
    graph_json = {
        "graph_version": 1,
        "graph_hash": "a" * 64,
        "nodes": [
            {
                "node_id": "split_dataset",
                "node_type": "ml.split",
                "template_id": "split_dataset@1.0.0",
                "parameters_hash": "b" * 64,
                "depends_on": [],
            },
            {
                "node_id": "train_logistic_regression",
                "node_type": "ml.train.classifier",
                "template_id": "train_classifier@1.0.0",
                "parameters_hash": "c" * 64,
                "depends_on": ["split_dataset"],
            },
        ],
        "parameters_by_node": {
            "split_dataset": {"target": "diagnosis", "seed": 1, "test_size": 0.2},
            "train_logistic_regression": {"model": "logistic_regression", "seed": 1},
        },
    }
    arguments = dict(
        task_id="task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
        graph_json=graph_json,
        ruleset_hash="d" * 64,
        cause_type="INPUT_CHANGE",
        cause_ref="e" * 64,
        affected=["split_dataset", "train_logistic_regression"],
        invalidated_evidence=["ev_b", "ev_a"],
        dataset_uri="local://datasets/synthetic_breast_cancer.csv",
        dataset_sha256="f" * 64,
    )
    first = build_plan(**arguments)
    second = build_plan(**arguments)
    assert first.plan_hash == second.plan_hash
    assert first.plan_id == second.plan_id
    serialized = json.dumps(first.document, sort_keys=True)
    assert "created_at" not in serialized and "frozen_at" not in serialized
    assert "timestamp" not in serialized
    assert first.document["invalidated_evidence"] == ["ev_a", "ev_b"]


def test_plan_file_is_content_addressed(tmp_path: Path) -> None:
    graph_json = {"graph_version": 1, "graph_hash": "a" * 64, "nodes": []}
    plan = build_plan(
        task_id="task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
        graph_json=graph_json,
        ruleset_hash="b" * 64,
        cause_type="INPUT_CHANGE",
        cause_ref="c" * 64,
        affected=[],
        invalidated_evidence=[],
        dataset_uri="local://datasets/x.csv",
        dataset_sha256="d" * 64,
    )
    root = tmp_path / "plans"
    path, created = write_plan(root, plan)
    assert created is True
    assert path.name == f"{plan.plan_hash}.json"
    again, created_again = write_plan(root, plan)
    assert created_again is False and again == path
    assert read_plan(root, plan.plan_hash) == plan.document

    path.write_bytes(b"tampered")
    with pytest.raises(PlanError) as excinfo:
        read_plan(root, plan.plan_hash)
    assert excinfo.value.code == "PLAN_HASH_MISMATCH"
    with pytest.raises(PlanError) as excinfo:
        plan_path(root, "../../escape")
    assert excinfo.value.code == "PLAN_HASH_MISMATCH"


def test_unrelated_node_is_not_invalidated(verified_two_models) -> None:
    world = verified_two_models
    outcome = world["recovery"].invalidate(
        world["task_id"],
        changed_node="train_logistic_regression",
        cause_type="PREDECESSOR_CHANGE",
        cause_ref="manual",
    )
    assert outcome["affected_nodes"] == ["train_logistic_regression"]
    states = _node_rows(world)
    assert states["train_logistic_regression"][0] == "INVALIDATED"
    assert states["train_random_forest"][0] == "VERIFIED"
    assert states["split_dataset"][0] == "VERIFIED"


def test_repeated_invalidate_keeps_the_same_plan_hash(verified_two_models) -> None:
    world = verified_two_models
    first = world["recovery"].invalidate(
        world["task_id"],
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref="input-2",
        new_dataset_sha256="a" * 64,
    )
    second = world["recovery"].invalidate(
        world["task_id"],
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref="input-2",
        new_dataset_sha256="a" * 64,
    )
    assert first["plan_hash"] == second["plan_hash"]
    assert second["plan_created"] is False
    assert _node_rows(world)["split_dataset"][0] == "INVALIDATED"


def test_invalidation_guard_rejects_all_three_conditions(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    execution = world["pipeline"].execute(world["task_id"])
    assert execution.ok is True
    outcome = world["pipeline"].verify(world["task_id"])
    assert outcome.final_state == "VERIFIED"
    world["pipeline"].mark_nodes_verified(world["task_id"])
    recovery = RecoveryService(world["db_path"], world["root"])
    invalidation = recovery.invalidate(
        world["task_id"],
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref="input-3",
        new_dataset_sha256="b" * 64,
    )
    plan_hash = invalidation["plan_hash"]
    plan_id = invalidation["plan_id"]
    root = world["root"] / "recovery_plans"
    state_machine = StateMachine(
        world["db_path"], ports=build_ports(world["db_path"], world["root"])
    )

    def attempt(plan_id_value: str, plan_hash_value: str):
        return state_machine.transition(
            TransitionRequest(
                obj_type=ObjectType.NODE,
                task_id=world["task_id"],
                node_id="split_dataset",
                previous_state="INVALIDATED",
                next_state="READY",
                actor=Actor(ActorRole.WP_R, "test"),
                reason_code="NODE_READY",
                rule_version="1.0",
                correlation_id="guard-test",
                context=TransitionContext(
                    plan_id=plan_id_value,
                    plan_hash=plan_hash_value,
                ),
            )
        )

    # (a) plan file missing
    target = plan_path(root, plan_hash)
    target.unlink()
    with pytest.raises(StateTransitionDenied) as excinfo:
        attempt(plan_id, plan_hash)
    assert excinfo.value.reason == "PLAN_FILE_MISSING"
    assert _node_rows(world)["split_dataset"][0] == "INVALIDATED"
    recovery.invalidate(
        world["task_id"],
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref="input-3",
        new_dataset_sha256="b" * 64,
    )  # recreates the missing plan file idempotently
    assert plan_path(root, plan_hash).is_file()

    # (c) plan exists but has no freeze record
    graph_json = _graph_json(world)
    unfrozen = build_plan(
        task_id=world["task_id"],
        graph_json=graph_json,
        ruleset_hash=json.loads(
            connect(world["db_path"])
            .execute("SELECT task_spec_json FROM tasks WHERE task_id = ?", (world["task_id"],))
            .fetchone()[0]
        )["ruleset_hash"],
        cause_type="INPUT_CHANGE",
        cause_ref="not-frozen",
        affected=["split_dataset"],
        invalidated_evidence=[],
        dataset_uri="local://datasets/synthetic_breast_cancer.csv",
        dataset_sha256="c" * 64,
    )
    write_plan(root, unfrozen)
    with pytest.raises(StateTransitionDenied) as excinfo:
        attempt(unfrozen.plan_id, unfrozen.plan_hash)
    assert excinfo.value.reason == "PLAN_FREEZE_RECORD_MISSING"

    # (d) plan frozen after the rerun attempt
    future = build_plan(
        task_id=world["task_id"],
        graph_json=graph_json,
        ruleset_hash=json.loads(
            connect(world["db_path"])
            .execute("SELECT task_spec_json FROM tasks WHERE task_id = ?", (world["task_id"],))
            .fetchone()[0]
        )["ruleset_hash"],
        cause_type="INPUT_CHANGE",
        cause_ref="frozen-in-the-future",
        affected=["split_dataset"],
        invalidated_evidence=[],
        dataset_uri="local://datasets/synthetic_breast_cancer.csv",
        dataset_sha256="d" * 64,
    )
    write_plan(root, future)
    future_time = format_utc(utc_now() + timedelta(hours=1))
    connection = connect(world["db_path"])
    try:
        with transaction(connection):
            AuditRepository().append(
                connection,
                audit_id="future-freeze",
                task_id=world["task_id"],
                node_id="split_dataset",
                actor="wp_r:test",
                action="RECOVERY_PLAN_FROZEN",
                previous_state=None,
                next_state=None,
                reason_code="RECOVERY_PLAN_FROZEN",
                rule_version="1.0",
                correlation_id=future.plan_id,
                plan_id=future.plan_id,
                plan_hash=future.plan_hash,
                result="OK",
                error_code=None,
                created_at=future_time,
                capability=WP_R_FREEZE,
            )
    finally:
        connection.close()
    with pytest.raises(StateTransitionDenied) as excinfo:
        state_machine.transition(
            TransitionRequest(
                obj_type=ObjectType.NODE,
                task_id=world["task_id"],
                node_id="split_dataset",
                previous_state="INVALIDATED",
                next_state="READY",
                actor=Actor(ActorRole.WP_R, "test"),
                reason_code="NODE_READY",
                rule_version="1.0",
                correlation_id="guard-test",
                context=TransitionContext(
                    plan_id=future.plan_id,
                    plan_hash=future.plan_hash,
                    received_at=utc_now(),
                ),
            )
        )
    assert excinfo.value.reason == "PLAN_FROZEN_AFTER_RERUN"

    # (b) plan bytes do not match the hash
    target = plan_path(root, plan_hash)
    target.write_bytes(b"{}")
    with pytest.raises(StateTransitionDenied) as excinfo:
        attempt(plan_id, plan_hash)
    assert excinfo.value.reason == "PLAN_HASH_MISMATCH"
    assert _node_rows(world)["split_dataset"][0] == "INVALIDATED"


def test_full_recovery_rerun_and_offline_bundle(tmp_path: Path, monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_template_dataset as btd

    data_dir = tmp_path / "data"
    btd.write_dataset(data_dir, 20261114)
    monkeypatch.setenv("RESEARCHFLOW_DATA_ROOT", str(data_dir))

    world = make_world(tmp_path / "flow")
    task_id = world["task_id"]
    execution = world["pipeline"].execute(task_id)
    assert execution.ok is True, execution.error
    first = world["pipeline"].verify(task_id)
    assert first.final_state == "VERIFIED"
    world["pipeline"].mark_nodes_verified(task_id)

    registry2 = btd.write_dataset(data_dir, 7)
    dataset_sha2 = registry2["datasets"]["local://datasets/synthetic_breast_cancer.csv"]["sha256"]
    recovery = RecoveryService(world["db_path"], world["root"])
    invalidation = recovery.invalidate(
        task_id,
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref=dataset_sha2,
        new_dataset_sha256=dataset_sha2,
    )
    assert invalidation["affected_nodes"] == ["split_dataset", "train_logistic_regression"]

    connection = connect(world["db_path"])
    try:
        before = list_evidence(connection, task_id)
    finally:
        connection.close()
    collector = Collector(world["db_path"], world["root"])
    after = collector.rows(task_id)
    assert len(after) == len(before)
    assert set(invalidation["invalidated_evidence"]) <= {row.evidence_id for row in after}
    assert collector.verify_chain(task_id).ok is True

    gate = Gate(world["db_path"], world["root"]).evaluate(task_id)
    assert gate.passed is False
    assert "GAP_EVIDENCE_STALE" in {gap.code for gap in gate.gaps}

    rerun = recovery.rerun(task_id, invalidation["plan_hash"])
    assert [item["attempt_id"] for item in rerun["attempts"]] == ["attempt_02", "attempt_02"]
    second = world["pipeline"].verify(task_id)
    assert second.final_state == "VERIFIED", second.gaps[:3]
    world["pipeline"].mark_nodes_verified(task_id)
    world["pipeline"].complete_task(task_id)

    states = _node_rows(world)
    assert all(state == "VERIFIED" and seq == 2 for state, seq in states.values())
    connection = connect(world["db_path"])
    try:
        task_state = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert task_state == "COMPLETED"

    from researchflow.bundle import BundleExporter
    from researchflow.signing import KeyStore

    store = KeyStore(world["root"] / "keys")
    store.load_or_create()
    anchor = tmp_path / "trust_store.json"
    store.write_trust_anchor(anchor)
    bundle = tmp_path / "bundle"
    BundleExporter(world["db_path"], world["root"]).export(task_id, bundle, trust_anchor_path=anchor)
    completed = subprocess.run(
        [sys.executable, "-E", str(VERIFY), "--bundle", str(bundle), "--trust-store", str(anchor)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout.strip().splitlines()[-1])
    assert summary["status"] == "VERIFIED"
    assert summary["invalidated_evidence"] == len(invalidation["invalidated_evidence"])

    # A bundle whose *new* evidence is marked stale must be rejected even though
    # every file hash and every signature is still valid.
    tampered = tmp_path / "bundle_stale"
    shutil.copytree(bundle, tampered)
    invalidations_path = tampered / "evidence" / "invalidations.json"
    invalidations = json.loads(invalidations_path.read_text(encoding="utf-8"))
    import json as _json

    records = [
        _json.loads(line)
        for line in (tampered / "evidence" / "records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    new_attempt = [record for record in records if record["attempt_id"] == "attempt_02"][:2]
    for record in new_attempt:
        invalidations.append(
            {
                "invalidation_id": "stale-" + record["evidence_id"],
                "task_id": record["task_id"],
                "node_id": record["node_id"],
                "evidence_id": record["evidence_id"],
                "reason_code": "TEST_STALE",
                "cause_type": "INPUT_CHANGE",
                "cause_ref": None,
                "plan_id": None,
                "plan_hash": None,
                "created_at": "2026-11-14T00:00:00.000000Z",
            }
        )
    invalidations_path.write_text(json.dumps(invalidations, indent=2), encoding="utf-8")
    resign_bundle_manifest(tampered, store.load())
    rejected = subprocess.run(
        [sys.executable, "-E", str(VERIFY), "--bundle", str(tampered), "--trust-store", str(anchor)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert rejected.returncode != 0
    payload = json.loads(rejected.stdout.strip().splitlines()[-1])
    assert payload["status"] == "REJECTED"
    assert payload["code"] == "REQUIRED_EVIDENCE_MISSING"
    assert "GAP_EVIDENCE_STALE" in payload["detail"]