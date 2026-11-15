"""Generate the required WP-03 evidence logs from real SQLite operations.

This is not a pytest test; it is a reproducible verification script.  It uses
real SQLite files for transactions/audit/direct-write checks.  Fake external
fact ports are used only for the INVALIDATED path, matching the test strategy.

Run with the project interpreter:

    & .venv/Scripts/python.exe docs/verification/t0/wp-03/make_evidence.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import wp03_support as support  # noqa: E402
from researchflow.orchestration.state_machine import (  # noqa: E402
    Actor,
    AuditWriteFailed,
    StateTransitionDenied,
    TransitionContext,
    TransitionRequest,
)
from researchflow.orchestration.transitions import ActorRole  # noqa: E402
from researchflow.persistence.db import connect  # noqa: E402

OUT = Path(__file__).resolve().parent


def _write_jsonl(name: str, records: list[dict]) -> None:
    with (OUT / name).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _task_request(
    sm,
    *,
    previous: str,
    next_state: str,
    role: ActorRole = ActorRole.ORCHESTRATOR,
    reason: str = "EVIDENCE",
    correlation: str | None = "evidence-c",
    context: TransitionContext | None = None,
):
    return sm.transition(
        TransitionRequest(
            obj_type="task",
            task_id=support.TASK_ID,
            previous_state=previous,
            next_state=next_state,
            actor=Actor(role, "evidence"),
            reason_code=reason,
            rule_version="1.0",
            correlation_id=correlation,
            context=context or TransitionContext(),
        )
    )


def _node_request(
    sm,
    *,
    previous: str,
    next_state: str,
    role: ActorRole,
    reason: str,
    context: TransitionContext | None = None,
):
    return support.node_transition(
        sm,
        previous_state=previous,
        next_state=next_state,
        role=role,
        reason_code=reason,
        context=context or TransitionContext(),
    )


def _record_denial(
    *, case: str, expected_reason: str, exc: StateTransitionDenied, db: Path
) -> dict:
    connection = connect(db)
    try:
        state = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (support.TASK_ID,)
        ).fetchone()
        denied = connection.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE result = 'DENIED'"
        ).fetchone()["n"]
    finally:
        connection.close()
    assert exc.reason == expected_reason, (case, exc.reason, expected_reason)
    return {
        "case": case,
        "expected_reason": expected_reason,
        "actual_reason": exc.reason,
        "api_error_code": exc.api_error_code,
        "error_code": exc.error_code,
        "field_path": exc.field_path,
        "state": None if state is None else state["state"],
        "denied_audit_rows": int(denied),
    }


def evidence_transitions(tmp: Path) -> None:
    db = support.make_db(tmp / "transitions.db")
    plans = tmp / "transitions-plans"
    plans.mkdir()
    sm = support.build_state_machine(db, plan_root=plans)
    support.create_task_and_node(sm)
    support.seed_evidence(db)
    records: list[dict] = []

    def record(result, label: str) -> None:
        records.append(
            {
                "label": label,
                "obj_type": result.obj_type,
                "obj_id": result.obj_id,
                "previous_state": result.previous_state,
                "next_state": result.next_state,
                "audit_id": result.audit_id,
                "applied_at": result.applied_at,
                "ok": result.ok,
            }
        )

    record(_task_request(sm, previous="CREATED", next_state="PLANNING"), "task-start")
    record(
        _node_request(
            sm,
            previous="PLANNED",
            next_state="READY",
            role=ActorRole.SCHEDULER,
            reason="NODE_READY",
        ),
        "node-ready",
    )
    record(
        _node_request(
            sm,
            previous="READY",
            next_state="RUNNING",
            role=ActorRole.SCHEDULER,
            reason="NODE_RUNNING",
        ),
        "node-running",
    )
    record(
        _node_request(
            sm,
            previous="RUNNING",
            next_state="VERIFYING",
            role=ActorRole.ORCHESTRATOR,
            reason="NODE_VERIFYING",
            context=TransitionContext(attempt_id="attempt_01"),
        ),
        "node-verifying",
    )
    record(
        _node_request(
            sm,
            previous="VERIFYING",
            next_state="VERIFIED",
            role=ActorRole.ORCHESTRATOR,
            reason="NODE_VERIFIED",
        ),
        "node-verified",
    )
    record(
        _node_request(
            sm,
            previous="VERIFIED",
            next_state="INVALIDATED",
            role=ActorRole.WP_R,
            reason="NODE_INVALIDATED",
            context=TransitionContext(
                evidence_ids=(support.EVIDENCE_ID,),
                cause_type="INPUT_CHANGE",
                cause_ref="input-v2",
            ),
        ),
        "node-invalidated",
    )
    plan_id, plan_hash = support.write_plan(plans, b'{"plan":"transitions"}')
    support.seed_freeze(db, plan_id=plan_id, plan_hash=plan_hash)
    record(
        _node_request(
            sm,
            previous="INVALIDATED",
            next_state="READY",
            role=ActorRole.WP_R,
            reason="NODE_READY",
            context=TransitionContext(
                plan_id=plan_id,
                plan_hash=plan_hash,
                received_at=datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc),
            ),
        ),
        "node-recovered-ready",
    )
    _write_jsonl("transitions.jsonl", records)

    connection = connect(db)
    try:
        rows = connection.execute(
            "SELECT * FROM audit_log ORDER BY created_at, audit_id"
        ).fetchall()
        audits = [dict(row) for row in rows]
    finally:
        connection.close()
    _write_jsonl("audit_log.jsonl", audits)
    assert len(records) == 7
    assert any(row["action"] == "STATE_TRANSITION" for row in audits)


def evidence_illegal(tmp: Path) -> None:
    db = support.make_db(tmp / "illegal.db")
    sm = support.build_state_machine(db)
    support.create_task_and_node(sm)
    records: list[dict] = []
    try:
        _task_request(sm, previous="CREATED", next_state="COMPLETED")
    except StateTransitionDenied as exc:
        records.append(
            _record_denial(
                case="illegal-edge",
                expected_reason="ILLEGAL_EDGE",
                exc=exc,
                db=db,
            )
        )
    try:
        _task_request(
            sm,
            previous="CREATED",
            next_state="PLANNING",
            role=ActorRole.API,
        )
    except StateTransitionDenied as exc:
        records.append(
            _record_denial(
                case="non-writer-role",
                expected_reason="ROLE_NOT_ALLOWED",
                exc=exc,
                db=db,
            )
        )
    try:
        _task_request(
            sm,
            previous="CREATED",
            next_state="PLANNING",
            correlation=None,
        )
    except StateTransitionDenied as exc:
        records.append(
            _record_denial(
                case="missing-correlation",
                expected_reason="MISSING_PARAMETER",
                exc=exc,
                db=db,
            )
        )
    try:
        _task_request(
            sm,
            previous="CREATED",
            next_state="PLANNING",
            context=TransitionContext(plan_id="p", plan_hash="a" * 64),
        )
    except StateTransitionDenied as exc:
        records.append(
            _record_denial(
                case="plan-fields-on-wrong-edge",
                expected_reason="PLAN_FIELDS_NOT_ALLOWED",
                exc=exc,
                db=db,
            )
        )
    _task_request(sm, previous="CREATED", next_state="PLANNING")
    try:
        _task_request(sm, previous="CREATED", next_state="READY")
    except StateTransitionDenied as exc:
        records.append(
            _record_denial(
                case="stale-previous-state",
                expected_reason="STALE_PREVIOUS_STATE",
                exc=exc,
                db=db,
            )
        )
    _write_jsonl("illegal.log", records)
    assert len(records) == 5
    assert all(record["actual_reason"] == record["expected_reason"] for record in records)


def evidence_direct_write(tmp: Path) -> None:
    db = support.make_db(tmp / "direct.db")
    sm = support.build_state_machine(db)
    support.create_task_and_node(sm)
    records: list[dict] = []

    def attempt(case: str, sql: str, expected: str, params: tuple = ()) -> None:
        connection = connect(db)
        try:
            try:
                connection.execute(sql, params)
            except sqlite3.IntegrityError as exc:
                message = str(exc)
                assert expected in message, (case, expected, message)
                records.append(
                    {
                        "case": case,
                        "sql": sql,
                        "expected_trigger": expected,
                        "actual_error": message,
                        "denied": True,
                    }
                )
            else:
                raise AssertionError(f"{case}: direct write was not denied")
        finally:
            connection.close()

    attempt(
        "direct-task-state-update",
        "UPDATE tasks SET state = 'COMPLETED' WHERE task_id = ?",
        "STATE_WRITE_WITHOUT_AUDIT: tasks",
        (support.TASK_ID,),
    )
    attempt(
        "direct-node-state-update",
        "UPDATE nodes SET state = 'VERIFIED' WHERE task_id = ? AND node_id = ?",
        "STATE_WRITE_WITHOUT_AUDIT: nodes",
        (support.TASK_ID, support.NODE_ID),
    )
    attempt(
        "direct-task-insert-non-initial",
        "INSERT INTO tasks(task_id, schema_version, domain_pack, goal, "
        "task_spec_hash, task_spec_json, state, graph_version, created_at, updated_at) "
        "VALUES ('task_00000000-0000-0000-0000-000000000099', '1.0', "
        "'tabular_ml@1.0.0', 'g', 'h', '{}', 'COMPLETED', 1, 't', 't')",
        "TASK_MUST_BE_INSERTED_CREATED",
    )
    attempt(
        "direct-audit-delete",
        "DELETE FROM audit_log",
        "APPEND_ONLY_TABLE: audit_log",
    )
    connection = connect(db)
    try:
        state = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (support.TASK_ID,)
        ).fetchone()["state"]
    finally:
        connection.close()
    _write_jsonl("direct_write.log", records)
    assert state == "CREATED"
    assert len(records) == 4


def evidence_denied_rollback(tmp: Path) -> None:
    db = support.make_db(tmp / "rollback.db")
    sm = support.build_state_machine(db)
    support.create_task_and_node(sm)
    connection = connect(db)
    try:
        connection.execute(
            """
            CREATE TRIGGER trg_evidence_force_state_failure
            BEFORE UPDATE OF state ON tasks
            WHEN NEW.state = 'PLANNING'
            BEGIN SELECT RAISE(ABORT, 'FORCED_STATE_FAILURE'); END;
            """
        )
    finally:
        connection.close()
    try:
        _task_request(sm, previous="CREATED", next_state="PLANNING")
    except StateTransitionDenied as exc:
        failure = exc
    else:
        raise AssertionError("forced state failure was not denied")
    connection = connect(db)
    try:
        state = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (support.TASK_ID,)
        ).fetchone()["state"]
        ok = connection.execute(
            "SELECT COUNT(*) AS n FROM audit_log "
            "WHERE action = 'STATE_TRANSITION' AND result = 'OK'"
        ).fetchone()["n"]
        denied = connection.execute(
            "SELECT * FROM audit_log WHERE result = 'DENIED'"
        ).fetchone()
    finally:
        connection.close()
    assert state == "CREATED"
    assert ok == 0
    assert denied is not None
    record = {
        "case": "denied-survives-rolled-back-state",
        "state_after_rollback": state,
        "ok_transition_audits": int(ok),
        "denied_exists": denied is not None,
        "denied_error_code": denied["error_code"],
        "denied_previous_state": denied["previous_state"],
        "denied_next_state": denied["next_state"],
        "denial_reason": failure.reason,
    }
    _write_jsonl("denied_survives_rollback.log", [record])


def evidence_audit_degraded(tmp: Path) -> None:
    db = support.make_db(tmp / "degraded.db")
    sm = support.build_state_machine(db)
    support.create_task_and_node(sm)
    connection = connect(db)
    try:
        connection.execute(
            """
            CREATE TRIGGER trg_evidence_force_denied_audit_failure
            BEFORE INSERT ON audit_log
            WHEN NEW.result = 'DENIED'
            BEGIN SELECT RAISE(ABORT, 'FORCED_DENIED_AUDIT_FAILURE'); END;
            """
        )
    finally:
        connection.close()
    captured = io.StringIO()
    with contextlib.redirect_stderr(captured):
        try:
            _task_request(sm, previous="CREATED", next_state="COMPLETED")
        except AuditWriteFailed as exc:
            failure = exc
        else:
            raise AssertionError("secondary audit failure was swallowed")
    line = captured.getvalue().strip()
    assert line, "no structured stderr was written"
    payload = json.loads(line)
    assert payload["audit_write_failed"] is True
    assert payload["error_code"] == "AUDIT_WRITE_FAILED"
    assert payload["original_error_code"] == "STATE_TRANSITION_DENIED"
    (OUT / "audit_degraded_stderr.log").write_text(line + "\n", encoding="utf-8")
    assert failure.audit_write_failed is True


def evidence_invalidated(tmp: Path) -> None:
    db = support.make_db(tmp / "invalidated.db")
    plans = tmp / "invalidated-plans"
    plans.mkdir()
    sm = support.build_state_machine(db, plan_root=plans)
    support.create_task_and_node(sm)
    support.seed_evidence(db)
    support.walk_node_to_verified(sm)
    _node_request(
        sm,
        previous="VERIFIED",
        next_state="INVALIDATED",
        role=ActorRole.WP_R,
        reason="NODE_INVALIDATED",
        context=TransitionContext(
            evidence_ids=(support.EVIDENCE_ID,),
            cause_type="INPUT_CHANGE",
            cause_ref="input-v2",
        ),
    )
    records: list[dict] = []
    received = datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)

    def denied(case: str, context: TransitionContext, expected: str) -> None:
        try:
            support.node_transition(
                sm,
                previous_state="INVALIDATED",
                next_state="READY",
                role=ActorRole.WP_R,
                reason_code="NODE_READY",
                context=context,
            )
        except StateTransitionDenied as exc:
            assert exc.reason == expected, (case, exc.reason, expected)
            records.append(
                {
                    "case": case,
                    "expected_reason": expected,
                    "actual_reason": exc.reason,
                    "api_error_code": exc.api_error_code,
                    "error_code": exc.error_code,
                    "state": "INVALIDATED",
                }
            )
        else:
            raise AssertionError(f"{case}: guard did not deny")

    denied(
        "plan-file-missing",
        TransitionContext(plan_id="plan-1", plan_hash="a" * 64, received_at=received),
        "PLAN_FILE_MISSING",
    )
    mismatch_hash = "b" * 64
    (plans / f"{mismatch_hash}.json").write_bytes(b"wrong bytes")
    denied(
        "plan-hash-mismatch",
        TransitionContext(
            plan_id="plan-1", plan_hash=mismatch_hash, received_at=received
        ),
        "PLAN_HASH_MISMATCH",
    )
    plan_id, plan_hash = support.write_plan(plans, b'{"plan":"missing-freeze"}')
    denied(
        "freeze-record-missing",
        TransitionContext(plan_id=plan_id, plan_hash=plan_hash, received_at=received),
        "PLAN_FREEZE_RECORD_MISSING",
    )
    late_id, late_hash = support.write_plan(plans, b'{"plan":"late-freeze"}')
    support.seed_freeze(
        db,
        plan_id=late_id,
        plan_hash=late_hash,
        created_at="2026-11-12T02:00:00.000000Z",
    )
    denied(
        "freeze-after-rerun",
        TransitionContext(
            plan_id=late_id, plan_hash=late_hash, received_at=received
        ),
        "PLAN_FROZEN_AFTER_RERUN",
    )
    ok_id, ok_hash = support.write_plan(plans, b'{"plan":"ok-freeze"}')
    support.seed_freeze(
        db,
        plan_id=ok_id,
        plan_hash=ok_hash,
        created_at="2026-11-12T00:00:00.000000Z",
    )
    result = support.node_transition(
        sm,
        previous_state="INVALIDATED",
        next_state="READY",
        role=ActorRole.WP_R,
        reason_code="NODE_READY",
        context=TransitionContext(
            plan_id=ok_id, plan_hash=ok_hash, received_at=received
        ),
    )
    assert result.next_state == "READY"
    connection = connect(db)
    try:
        node = connection.execute(
            "SELECT state, plan_id, plan_hash FROM nodes "
            "WHERE task_id = ? AND node_id = ?",
            (support.TASK_ID, support.NODE_ID),
        ).fetchone()
    finally:
        connection.close()
    records.append(
        {
            "case": "all-three-guards-pass",
            "expected_reason": None,
            "actual_reason": None,
            "state": node["state"],
            "plan_id": node["plan_id"],
            "plan_hash": node["plan_hash"],
        }
    )
    _write_jsonl("invalidated_guard.log", records)
    assert node["state"] == "READY"
    assert len(records) == 5


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rf_wp03_evidence_") as raw_tmp:
        tmp = Path(raw_tmp)
        evidence_transitions(tmp)
        evidence_illegal(tmp)
        evidence_direct_write(tmp)
        evidence_denied_rollback(tmp)
        evidence_audit_degraded(tmp)
        evidence_invalidated(tmp)
    print("EVIDENCE_OK")
    print("transitions.jsonl=7 audit_log.jsonl=all illegal.log=5 direct_write.log=4")
    print("denied_survives_rollback.log=1 audit_degraded_stderr.log=1 invalidated_guard.log=5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())