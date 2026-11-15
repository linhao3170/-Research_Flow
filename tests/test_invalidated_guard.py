from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from researchflow.orchestration.state_machine import (
    ActorRole,
    StateTransitionDenied,
    TransitionContext,
)
from researchflow.persistence.db import connect
from wp03_support import (
    EVIDENCE_ID,
    NODE_ID,
    TASK_ID,
    FakeEvidenceFacts,
    build_state_machine,
    create_task_and_node,
    default_evidence,
    make_db,
    node_transition,
    seed_evidence,
    seed_freeze,
    walk_node_to_verified,
    write_plan,
)


def _setup_invalidated(
    tmp_path: Path,
    *,
    plan_root: Path | None = None,
    evidence: FakeEvidenceFacts | None = None,
):
    db = make_db(tmp_path / "invalidated.db")
    sm = build_state_machine(
        db,
        plan_root=plan_root,
        evidence=evidence or FakeEvidenceFacts(default_evidence()),
    )
    create_task_and_node(sm)
    seed_evidence(db)
    walk_node_to_verified(sm)
    node_transition(
        sm,
        previous_state="VERIFIED",
        next_state="INVALIDATED",
        role=ActorRole.WP_R,
        reason_code="NODE_INVALIDATED",
        context=TransitionContext(
            evidence_ids=(EVIDENCE_ID,),
            cause_type="INPUT_CHANGE",
            cause_ref="input-v2",
        ),
    )
    return db, sm


def _plan_context(plan_id: str, plan_hash: str, *, received_at: datetime | None = None):
    return TransitionContext(
        plan_id=plan_id,
        plan_hash=plan_hash,
        received_at=received_at or datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc),
    )


def _to_ready(sm, context):
    return node_transition(
        sm,
        previous_state="INVALIDATED",
        next_state="READY",
        role=ActorRole.WP_R,
        reason_code="NODE_READY",
        context=context,
    )


def test_verified_to_invalidated_appends_record_and_ready_succeeds(tmp_path: Path) -> None:
    plan_root = tmp_path / "plans"
    plan_root.mkdir()
    db, sm = _setup_invalidated(tmp_path, plan_root=plan_root)
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM nodes WHERE task_id = ? AND node_id = ?",
            (TASK_ID, NODE_ID),
        ).fetchone()["state"] == "INVALIDATED"
        assert connection.execute(
            "SELECT COUNT(*) AS n FROM evidence_invalidations"
        ).fetchone()["n"] == 1
        assert connection.execute(
            "SELECT COUNT(*) AS n FROM evidence"
        ).fetchone()["n"] == 1  # evidence is not deleted
    finally:
        connection.close()
    plan_id, plan_hash = write_plan(plan_root)
    seed_freeze(db, plan_id=plan_id, plan_hash=plan_hash)
    result = _to_ready(sm, _plan_context(plan_id, plan_hash))
    assert result.next_state == "READY"
    connection = connect(db)
    try:
        row = connection.execute(
            "SELECT state, plan_id, plan_hash FROM nodes WHERE task_id = ? AND node_id = ?",
            (TASK_ID, NODE_ID),
        ).fetchone()
        assert row["state"] == "READY"
        assert row["plan_id"] == plan_id
        assert row["plan_hash"] == plan_hash
    finally:
        connection.close()


def test_plan_file_missing_is_denied(tmp_path: Path) -> None:
    plan_root = tmp_path / "plans"
    plan_root.mkdir()
    db, sm = _setup_invalidated(tmp_path, plan_root=plan_root)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _to_ready(sm, _plan_context("plan-1", "a" * 64))
    exc = excinfo.value
    assert exc.api_error_code == "STATE_TRANSITION_DENIED"
    assert exc.error_code == "PLAN_HASH_MISMATCH"
    assert exc.reason == "PLAN_FILE_MISSING"
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM nodes WHERE task_id = ? AND node_id = ?",
            (TASK_ID, NODE_ID),
        ).fetchone()["state"] == "INVALIDATED"
        assert connection.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE result = 'DENIED'"
        ).fetchone()["n"] >= 1
    finally:
        connection.close()


def test_plan_hash_mismatch_is_denied(tmp_path: Path) -> None:
    plan_root = tmp_path / "plans"
    plan_root.mkdir()
    db, sm = _setup_invalidated(tmp_path, plan_root=plan_root)
    plan_hash = "a" * 64
    (plan_root / f"{plan_hash}.json").write_bytes(b"different bytes")
    with pytest.raises(StateTransitionDenied) as excinfo:
        _to_ready(sm, _plan_context("plan-1", plan_hash))
    assert excinfo.value.error_code == "PLAN_HASH_MISMATCH"
    assert excinfo.value.reason == "PLAN_HASH_MISMATCH"


def test_freeze_record_missing_is_denied(tmp_path: Path) -> None:
    plan_root = tmp_path / "plans"
    plan_root.mkdir()
    db, sm = _setup_invalidated(tmp_path, plan_root=plan_root)
    plan_id, plan_hash = write_plan(plan_root)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _to_ready(sm, _plan_context(plan_id, plan_hash))
    assert excinfo.value.error_code == "PLAN_HASH_MISMATCH"
    assert excinfo.value.reason == "PLAN_FREEZE_RECORD_MISSING"


def test_plan_id_mismatch_is_denied(tmp_path: Path) -> None:
    plan_root = tmp_path / "plans"
    plan_root.mkdir()
    db, sm = _setup_invalidated(tmp_path, plan_root=plan_root)
    plan_id, plan_hash = write_plan(plan_root)
    seed_freeze(db, plan_id="other-plan", plan_hash=plan_hash)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _to_ready(sm, _plan_context(plan_id, plan_hash))
    assert excinfo.value.error_code == "PLAN_HASH_MISMATCH"
    assert excinfo.value.reason == "PLAN_ID_MISMATCH"


@pytest.mark.parametrize(
    "freeze_time",
    ["2026-11-12T01:00:00.000000Z", "2026-11-12T02:00:00.000000Z"],
)
def test_freeze_not_strictly_before_rerun_is_denied(
    tmp_path: Path, freeze_time: str
) -> None:
    plan_root = tmp_path / "plans"
    plan_root.mkdir()
    db, sm = _setup_invalidated(tmp_path, plan_root=plan_root)
    plan_id, plan_hash = write_plan(plan_root)
    seed_freeze(db, plan_id=plan_id, plan_hash=plan_hash, created_at=freeze_time)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _to_ready(sm, _plan_context(plan_id, plan_hash))
    assert excinfo.value.error_code == "PLAN_HASH_MISMATCH"
    assert excinfo.value.reason == "PLAN_FROZEN_AFTER_RERUN"


def test_verified_to_invalidated_requires_cause_and_evidence(tmp_path: Path) -> None:
    db = make_db(tmp_path / "cause.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    seed_evidence(db)
    walk_node_to_verified(sm)
    with pytest.raises(StateTransitionDenied) as first:
        node_transition(
            sm,
            previous_state="VERIFIED",
            next_state="INVALIDATED",
            role=ActorRole.WP_R,
            reason_code="NODE_INVALIDATED",
            context=TransitionContext(
                evidence_ids=(EVIDENCE_ID,), cause_type="NOT_A_CAUSE"
            ),
        )
    assert first.value.reason == "CAUSE_INVALID"
    with pytest.raises(StateTransitionDenied) as second:
        node_transition(
            sm,
            previous_state="VERIFIED",
            next_state="INVALIDATED",
            role=ActorRole.WP_R,
            reason_code="NODE_INVALIDATED",
            context=TransitionContext(evidence_ids=(), cause_type="INPUT_CHANGE"),
        )
    assert second.value.reason == "NO_STALE_EVIDENCE"