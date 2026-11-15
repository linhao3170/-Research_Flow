"""T0 WP-07 collector tests: real E2 records, idempotency, gaps and tampering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from researchflow.evidence import GENESIS_PREV_HASH, Collector, EvidenceConflict, chain_hash_for
from researchflow.execution import Executor
from researchflow.persistence.db import connect
from researchflow.persistence.repositories import (
    COLLECTOR_APPEND,
    DirectStateWriteDenied,
    EvidenceRepository,
    EvidenceRow,
)
from support import (
    DATASET_URI,
    TASK_ID,
    create_task_with_graph,
    dataset_sha256,
    make_db,
)

DATASET_REF = {"uri": DATASET_URI, "sha256": dataset_sha256(), "license": "CC0-1.0"}
LIMITS = {"wall_time_sec": 300, "max_workers": 2, "max_memory_mb": 4096}
NODE_ID = "split_dataset"


@pytest.fixture()
def world(tmp_path: Path):
    runtime = tmp_path / "runtime"
    db_path = runtime / "researchflow.db"
    connection = make_db(db_path)
    connection.close()
    graph = create_task_with_graph(db_path)
    executor = Executor(runtime)
    observation = executor.run(
        task_id=TASK_ID,
        node_id=NODE_ID,
        attempt_seq=1,
        template_id="split_dataset@1.0.0",
        parameters={"target": "diagnosis", "seed": 42, "test_size": 0.2},
        dataset_ref=DATASET_REF,
        limits=LIMITS,
    )
    collector = Collector(db_path, runtime)
    return db_path, runtime, collector, observation


def _evidence_rows(db_path: Path):
    connection = connect(db_path)
    try:
        return connection.execute(
            "SELECT * FROM evidence WHERE task_id = ? ORDER BY event_seq", (TASK_ID,)
        ).fetchall()
    finally:
        connection.close()


def _count(db_path: Path, table: str) -> int:
    connection = connect(db_path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
    finally:
        connection.close()


def _insert_raw(db_path: Path, **overrides) -> EvidenceRow:
    values = {
        "evidence_id": "ev_" + overrides.pop("suffix", "00000000-0000-4000-8000-000000009999"),
        "task_id": TASK_ID,
        "node_id": NODE_ID,
        "attempt_id": "attempt_99",
        "event_seq": 99,
        "level": "E2",
        "kind": "artifact_observed",
        "producer": "collector",
        "timestamp": "2026-11-14T00:00:00.000000Z",
        "payload_hash": "e" * 64,
        "artifact_refs": None,
        "prev_hash": GENESIS_PREV_HASH,
        "chain_hash": "",
    }
    values.update(overrides)
    draft = EvidenceRow(**values)
    row = EvidenceRow(
        evidence_id=draft.evidence_id,
        task_id=draft.task_id,
        node_id=draft.node_id,
        attempt_id=draft.attempt_id,
        event_seq=draft.event_seq,
        level=draft.level,
        kind=draft.kind,
        producer=draft.producer,
        timestamp=draft.timestamp,
        payload_hash=draft.payload_hash,
        artifact_refs=draft.artifact_refs,
        prev_hash=draft.prev_hash,
        chain_hash=draft.chain_hash or chain_hash_for(draft),
    )
    connection = connect(db_path)
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
    return row


def test_observation_produces_ordered_e2_chain(world) -> None:
    db_path, runtime, collector, observation = world
    results = collector.record_observation(observation)
    kinds = [result.kind for result in results]
    assert kinds[:2] == ["executor_launch", "executor_process_exit"]
    assert all(kind == "artifact_observed" for kind in kinds[2:])
    assert [result.event_seq for result in results] == list(range(1, len(results) + 1))
    assert all(result.created for result in results)
    assert _count(db_path, "evidence") == len(results)
    assert _count(db_path, "ingestion_log") == len(results)
    report = collector.verify_chain(TASK_ID)
    assert report.ok is True
    assert report.issues == ()
    assert report.count == len(results)
    assert collector.env_fingerprint(TASK_ID) == observation.env_fingerprint


def test_duplicate_delivery_does_not_create_a_second_row(world) -> None:
    db_path, _, collector, observation = world
    first = collector.record_observation(observation)
    before = _count(db_path, "evidence")
    second = collector.record_observation(observation)
    assert _count(db_path, "evidence") == before
    assert [item.evidence_id for item in first] == [item.evidence_id for item in second]
    assert all(item.created is False for item in second)
    assert all(item.delivery_seq == 2 for item in second)
    assert _count(db_path, "ingestion_log") == len(first) * 2


def test_same_event_key_with_different_content_is_rejected(world) -> None:
    db_path, _, collector, _ = world
    collector._append(
        task_id=TASK_ID,
        node_id=NODE_ID,
        attempt_id="attempt_01",
        level="E1",
        kind="tool_invocation",
        payload={"event": "tool_invocation", "value": 1},
        event_key="fixed-key",
        capability=COLLECTOR_APPEND,
        actor="collector:tool",
    )
    before = _count(db_path, "evidence")
    with pytest.raises(EvidenceConflict) as excinfo:
        collector._append(
            task_id=TASK_ID,
            node_id=NODE_ID,
            attempt_id="attempt_01",
            level="E1",
            kind="tool_invocation",
            payload={"event": "tool_invocation", "value": 2},
            event_key="fixed-key",
            capability=COLLECTOR_APPEND,
            actor="collector:tool",
        )
    assert excinfo.value.code == "CHAIN_CONTENT_CONFLICT"
    assert _count(db_path, "evidence") == before
    connection = connect(db_path)
    try:
        denied = connection.execute(
            "SELECT * FROM audit_log WHERE error_code = 'CHAIN_CONTENT_CONFLICT'"
        ).fetchall()
    finally:
        connection.close()
    assert len(denied) == 1
    assert denied[0]["result"] == "DENIED"


def test_e0_claim_does_not_advance_state(world) -> None:
    db_path, _, collector, _ = world
    connection = connect(db_path)
    try:
        before = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"]
        node_before = connection.execute(
            "SELECT state FROM nodes WHERE task_id = ? AND node_id = ?",
            (TASK_ID, NODE_ID),
        ).fetchone()["state"]
    finally:
        connection.close()
    result = collector.record_claim(
        task_id=TASK_ID,
        node_id=NODE_ID,
        attempt_id="attempt_01",
        claim="this node is complete",
    )
    assert result.level == "E0"
    connection = connect(db_path)
    try:
        after = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"]
        node_after = connection.execute(
            "SELECT state FROM nodes WHERE task_id = ? AND node_id = ?",
            (TASK_ID, NODE_ID),
        ).fetchone()["state"]
        transitions = connection.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action = 'STATE_TRANSITION'"
        ).fetchone()["n"]
    finally:
        connection.close()
    assert after == before == "CREATED"
    assert node_after == node_before == "PLANNED"
    assert transitions == 0
    assert collector.verify_chain(TASK_ID).ok is True


def test_sequence_gap_is_detected(world) -> None:
    db_path, _, collector, observation = world
    collector.record_observation(observation)
    _insert_raw(db_path, event_seq=999)
    report = collector.verify_chain(TASK_ID)
    assert report.ok is False
    assert "CHAIN_SEQ_GAP" in {issue.code for issue in report.issues}


def test_payload_tampering_is_detected(world) -> None:
    db_path, runtime, collector, observation = world
    results = collector.record_observation(observation)
    payload_path = runtime / "tasks" / TASK_ID / "evidence_payloads" / f"{results[0].payload_hash}.json"
    payload_path.write_bytes(b'{"tampered":true}')
    report = collector.verify_chain(TASK_ID)
    assert report.ok is False
    assert "CHAIN_PAYLOAD_HASH_MISMATCH" in {issue.code for issue in report.issues}
    # The evidence row itself is append-only and still present.
    assert _count(db_path, "evidence") == len(results)


def test_chain_hash_tamper_is_detected(world) -> None:
    db_path, _, collector, observation = world
    collector.record_observation(observation)
    _insert_raw(db_path, event_seq=999, chain_hash="f" * 64)
    report = collector.verify_chain(TASK_ID)
    assert "CHAIN_HASH_MISMATCH" in {issue.code for issue in report.issues}


def test_prev_hash_mismatch_is_detected(world) -> None:
    db_path, _, collector, observation = world
    collector.record_observation(observation)
    _insert_raw(db_path, event_seq=999, prev_hash="1" * 64)
    report = collector.verify_chain(TASK_ID)
    assert "CHAIN_PREV_MISMATCH" in {issue.code for issue in report.issues}


def test_e3_requires_the_verifier_capability(world) -> None:
    db_path, _, collector, _ = world
    connection = connect(db_path)
    try:
        with pytest.raises(DirectStateWriteDenied):
            EvidenceRepository().append(
                connection,
                evidence_id="ev_00000000-0000-4000-8000-000000001234",
                task_id=TASK_ID,
                node_id=NODE_ID,
                attempt_id="attempt_01",
                event_seq=1,
                level="E3",
                kind="verifier_recheck",
                producer="verifier",
                timestamp="2026-11-14T00:00:00.000000Z",
                payload_hash="e" * 64,
                artifact_refs=None,
                prev_hash=GENESIS_PREV_HASH,
                chain_hash="e" * 64,
                capability=COLLECTOR_APPEND,
            )
    finally:
        connection.close()
    result = collector.append_verifier_recheck(
        task_id=TASK_ID,
        node_id=NODE_ID,
        attempt_id="attempt_01",
        payload={"l1_status": "PASS"},
    )
    assert result.level == "E3"
    assert result.kind == "verifier_recheck"
    connection = connect(db_path)
    try:
        row = connection.execute(
            "SELECT producer FROM evidence WHERE evidence_id = ?", (result.evidence_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row["producer"] == "verifier"
    assert collector.verify_chain(TASK_ID).ok is True