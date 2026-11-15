"""T0 WP-08 Gate tests: coverage, stale evidence, ruleset binding, E0 claims."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from researchflow.dag import build_graph, register_graph
from researchflow.evidence import Collector
from researchflow.gate import Gate
from researchflow.gate.gate import (
    GAP_ARTIFACT_HASH_MISMATCH,
    GAP_ARTIFACT_MISSING,
    GAP_CHAIN_INVALID,
    GAP_E2_MISSING,
    GAP_E3_MISSING,
    GAP_E3_NOT_BOUND,
    GAP_E3_NOT_PASS,
    GAP_EVIDENCE_STALE,
    GAP_GRAPH_MISSING,
    GAP_NODE_ROW_MISSING,
    GAP_RULESET_INVALID,
    GAP_RULESET_MISMATCH,
    GAP_STALE_ATTEMPT,
)
from researchflow.persistence.db import connect
from researchflow.persistence.repositories import (
    STATE_MACHINE_WRITE,
    EvidenceRepository,
    EvidenceRow,
)
from support import (
    create_task_with_graph,
    create_task_via_service,
    dataset_sha256,
    make_db,
    make_world,
)


def _codes(gate_result) -> list[str]:
    return [gap.code for gap in gate_result.gaps]


@pytest.fixture()
def executed(tmp_path: Path):
    world = make_world(tmp_path)
    result = world["pipeline"].execute(world["task_id"])
    assert result.ok is True, result.error
    world["gate"] = Gate(world["db_path"], world["root"])
    world["collector"] = Collector(world["db_path"], world["root"])
    return world


def _split_hash(world) -> str:
    path = (
        world["root"] / "tasks" / world["task_id"] / "attempts" / "split_dataset"
        / "attempt_01" / "output" / "split_manifest.json"
    )
    return str(json.loads(path.read_text(encoding="utf-8"))["split_hash"])


def _append_e3(
    world,
    *,
    l3_status: str = "PASS",
    node_id: str = "train_logistic_regression",
    bound: bool = True,
):
    connection = connect(world["db_path"])
    try:
        attempt_seq = connection.execute(
            "SELECT attempt_seq FROM nodes WHERE task_id = ? AND node_id = ?",
            (world["task_id"], node_id),
        ).fetchone()["attempt_seq"]
    finally:
        connection.close()
    payload = {
        "node_id": node_id,
        "l1_status": "PASS",
        "l2_status": "PASS",
        "l3_status": l3_status,
        "match_mode": "EXACT",
    }
    if bound:
        payload["executor_split_hash"] = _split_hash(world)
        payload["train_pid"] = 12345
        payload["l3_split_dir"] = "verification/l3-test/attempt_01"
    return world["collector"].append_verifier_recheck(
        task_id=world["task_id"],
        node_id=node_id,
        attempt_id=f"attempt_{attempt_seq:02d}",
        payload=payload,
    )


def test_gate_requires_live_e3_metric_source(executed) -> None:
    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is False
    assert result.required == 5  # split: 2 checks, train: 3 checks
    assert result.passed_checks == 4
    assert result.missing == 1
    assert GAP_E3_MISSING in _codes(result)
    assert result.l3_coverage == 0.0
    gap = next(gap for gap in result.gaps if gap.code == GAP_E3_MISSING)
    assert gap.node_id == "train_logistic_regression"
    assert gap.check == "metric_source"
    assert len(result.evidence_root) == 64


def test_gate_passes_with_live_e3(executed) -> None:
    _append_e3(executed)
    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is True, [gap.to_dict() for gap in result.gaps]
    assert result.missing == 0
    assert result.l3_coverage == 1.0
    assert result.metric_nodes_required == 1
    assert result.metric_nodes_verified == 1
    assert result.chain is not None and result.chain.ok is True


def test_e3_fail_status_does_not_satisfy_metric_source(executed) -> None:
    _append_e3(executed, l3_status="FAIL")
    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is False
    assert GAP_E3_NOT_BOUND in _codes(result)


def test_e3_without_split_binding_does_not_satisfy_metric_source(executed) -> None:
    _append_e3(executed, bound=False)
    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is False
    assert GAP_E3_NOT_BOUND in _codes(result)


def test_ruleset_level_floor_blocks_a_weakened_ruleset(executed) -> None:
    gate = executed["gate"]
    gate._ruleset["check_definitions"]["executor_observed"]["level"] = "E1"
    result = gate.evaluate(executed["task_id"])
    assert result.passed is False
    assert GAP_RULESET_INVALID in _codes(result)


def test_e0_claim_cannot_satisfy_an_execution_check(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world["pipeline"].plan(world["task_id"])
    collector = Collector(world["db_path"], world["root"])
    collector.record_claim(
        task_id=world["task_id"],
        node_id="split_dataset",
        attempt_id="attempt_00",
        claim="the split node ran successfully",
    )
    result = Gate(world["db_path"], world["root"]).evaluate(world["task_id"])
    assert result.passed is False
    assert GAP_E2_MISSING in _codes(result)
    assert result.passed_checks == 0


def test_stale_evidence_is_rejected_but_not_deleted(executed) -> None:
    collector = executed["collector"]
    rows = collector.rows(executed["task_id"])
    split_artifacts = [
        row for row in rows
        if row.node_id == "split_dataset" and row.kind == "artifact_observed"
    ]
    assert split_artifacts
    connection = connect(executed["db_path"])
    try:
        for index, split_attempt in enumerate(split_artifacts):
            EvidenceRepository().append_invalidation(
                connection,
                invalidation_id=uuid.uuid4().hex,
                task_id=executed["task_id"],
                node_id="split_dataset",
                evidence_id=split_attempt.evidence_id,
                reason_code="NODE_INVALIDATED",
                cause_type="INPUT_CHANGE",
                cause_ref=None,
                plan_id=None,
                plan_hash=None,
                created_at=f"2026-11-14T00:00:0{index}.000000Z",
                capability=STATE_MACHINE_WRITE,
            )
        connection.commit()
    finally:
        connection.close()

    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is False
    assert GAP_EVIDENCE_STALE in _codes(result)
    stale_gap = next(gap for gap in result.gaps if gap.code == GAP_EVIDENCE_STALE)
    assert stale_gap.node_id == "split_dataset"

    # Evidence is still present and its chain is still verifiable: the Gate
    # rejected it because it is invalidated, not because it was deleted.
    after = collector.rows(executed["task_id"])
    assert len(after) == len(rows)
    assert {row.evidence_id for row in split_artifacts} <= {
        row.evidence_id for row in after
    }
    assert collector.verify_chain(executed["task_id"]).ok is True


def test_missing_artifact_is_rejected(executed) -> None:
    split_dir = executed["root"] / "tasks" / executed["task_id"] / "attempts" / "split_dataset" / "attempt_01" / "output"
    (split_dir / "split_manifest.json").unlink()
    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is False
    assert GAP_ARTIFACT_MISSING in _codes(result)


def test_tampered_artifact_hash_is_rejected(executed) -> None:
    split_dir = executed["root"] / "tasks" / executed["task_id"] / "attempts" / "split_dataset" / "attempt_01" / "output"
    (split_dir / "split_manifest.json").write_text("{}", encoding="utf-8")
    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is False
    assert GAP_ARTIFACT_HASH_MISMATCH in _codes(result)


def test_tampered_payload_fails_the_chain_check(executed) -> None:
    rows = executed["collector"].rows(executed["task_id"])
    payload_path = (
        executed["root"] / "tasks" / executed["task_id"] / "evidence_payloads"
        / f"{rows[0].payload_hash}.json"
    )
    payload_path.write_bytes(b'{"tampered":1}')
    result = executed["gate"].evaluate(executed["task_id"])
    assert result.passed is False
    assert GAP_CHAIN_INVALID in _codes(result)


def test_ruleset_mismatch_blocks_the_gate(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    db_path = root / "researchflow.db"
    connection = make_db(db_path)
    connection.close()
    task_id = create_task_with_graph(db_path, ruleset_hash="0" * 64)
    result = Gate(db_path, root).evaluate(task_id.task_id)
    assert result.passed is False
    assert GAP_RULESET_MISMATCH in _codes(result)


def test_missing_graph_is_rejected(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    result = Gate(world["db_path"], world["root"]).evaluate(world["task_id"])
    assert result.passed is False
    assert GAP_GRAPH_MISSING in _codes(result)


def test_missing_node_rows_are_rejected(tmp_path: Path) -> None:
    from researchflow.contracts.models import TaskSpec
    from support import task_payload

    root = tmp_path / "runtime"
    db_path = root / "researchflow.db"
    connection = make_db(db_path)
    try:
        spec = TaskSpec.model_validate(task_payload())
        from researchflow.orchestration.state_machine import Actor, StateMachine
        from researchflow.orchestration.transitions import ActorRole

        state_machine = StateMachine(db_path)
        state_machine.create_initial(
            obj_type="task",
            task_id=spec.task_id,
            actor=Actor(ActorRole.API, "create"),
            correlation_id="req",
            task_spec=spec,
            connection=connection,
        )
        register_graph(connection, build_graph(spec))
        connection.commit()
        task_id = spec.task_id
    finally:
        connection.close()
    result = Gate(db_path, root).evaluate(task_id)
    assert result.passed is False
    assert GAP_NODE_ROW_MISSING in _codes(result)


def test_evidence_from_an_older_attempt_is_stale(tmp_path: Path) -> None:
    gate = Gate(tmp_path / "unused.db")
    rows = [
        EvidenceRow(
            evidence_id="ev_00000000-0000-4000-8000-00000000000" + str(index),
            task_id="task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
            node_id="split_dataset",
            attempt_id="attempt_01",
            event_seq=index,
            level="E2",
            kind="executor_process_exit",
            producer="collector",
            timestamp="2026-11-14T00:00:00.000000Z",
            payload_hash="a" * 64,
            artifact_refs=None,
            prev_hash="0" * 64,
            chain_hash="a" * 64,
        )
        for index in (1, 2)
    ]
    ok, gap = gate._check_required(
        task_id="task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
        node_id="split_dataset",
        attempt_id="attempt_02",
        attempt_seq=2,
        check="executor_observed",
        evidence=rows,
        invalidated_ids=set(),
    )
    assert ok is False
    assert gap is not None and gap.code == GAP_STALE_ATTEMPT