from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from researchflow.orchestration.state_machine import (
    Actor,
    AuditWriteFailed,
    StateTransitionDenied,
    TransitionRequest,
)
from researchflow.orchestration.transitions import ActorRole
from researchflow.persistence.db import connect
from wp03_support import (
    TASK_ID,
    build_state_machine,
    count_audit,
    create_task_and_node,
    make_db,
)


def _legal_request():
    return TransitionRequest(
        obj_type="task",
        task_id=TASK_ID,
        previous_state="CREATED",
        next_state="PLANNING",
        actor=Actor(ActorRole.ORCHESTRATOR, "test"),
        reason_code="TASK_PLANNING_STARTED",
        rule_version="1.0",
        correlation_id="req-audit",
    )


def _illegal_request():
    return TransitionRequest(
        obj_type="task",
        task_id=TASK_ID,
        previous_state="CREATED",
        next_state="COMPLETED",
        actor=Actor(ActorRole.ORCHESTRATOR, "test"),
        reason_code="ILLEGAL",
        rule_version="1.0",
        correlation_id="req-illegal",
    )


def test_success_audit_failure_rolls_back_state(tmp_path: Path) -> None:
    db = make_db(tmp_path / "ok-failure.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        connection.execute(
            """
            CREATE TRIGGER trg_test_ok_audit_failure
            BEFORE INSERT ON audit_log
            WHEN NEW.action = 'STATE_TRANSITION' AND NEW.result = 'OK'
            BEGIN SELECT RAISE(ABORT, 'FORCED_OK_AUDIT_FAILURE'); END;
            """
        )
    finally:
        connection.close()
    with pytest.raises(StateTransitionDenied) as excinfo:
        sm.transition(_legal_request())
    assert excinfo.value.reason == "STATE_WRITE_FAILED"
    assert excinfo.value.audit_id is not None
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"] == "CREATED"
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM audit_log "
                "WHERE action = 'STATE_TRANSITION' AND result = 'OK'"
            ).fetchone()["n"]
            == 0
        )
    finally:
        connection.close()
    assert count_audit(db, "DENIED") == 1


def test_denied_survives_state_transaction_rollback(tmp_path: Path) -> None:
    db = make_db(tmp_path / "denied-rollback.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        connection.execute(
            """
            CREATE TRIGGER trg_test_force_state_failure
            BEFORE UPDATE OF state ON tasks
            WHEN NEW.state = 'PLANNING'
            BEGIN SELECT RAISE(ABORT, 'FORCED_STATE_FAILURE'); END;
            """
        )
    finally:
        connection.close()
    with pytest.raises(StateTransitionDenied) as excinfo:
        sm.transition(_legal_request())
    assert excinfo.value.reason == "STATE_WRITE_FAILED"
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"] == "CREATED"
        denied = connection.execute(
            "SELECT * FROM audit_log WHERE result = 'DENIED'"
        ).fetchone()
        assert denied is not None
        assert denied["error_code"] == "STATE_TRANSITION_DENIED"
        assert denied["previous_state"] == "CREATED"
        assert denied["next_state"] == "PLANNING"
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM audit_log "
                "WHERE action = 'STATE_TRANSITION' AND result = 'OK'"
            ).fetchone()["n"]
            == 0
        )
    finally:
        connection.close()


def test_secondary_denied_audit_failure_writes_structured_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = make_db(tmp_path / "denied-failure.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        connection.execute(
            """
            CREATE TRIGGER trg_test_denied_audit_failure
            BEFORE INSERT ON audit_log
            WHEN NEW.result = 'DENIED'
            BEGIN SELECT RAISE(ABORT, 'FORCED_DENIED_AUDIT_FAILURE'); END;
            """
        )
    finally:
        connection.close()
    with pytest.raises(AuditWriteFailed) as excinfo:
        sm.transition(_illegal_request())
    failure = excinfo.value
    assert failure.audit_write_failed is True
    assert failure.original_error_code == "STATE_TRANSITION_DENIED"
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["audit_write_failed"] is True
    assert payload["error_code"] == "AUDIT_WRITE_FAILED"
    assert payload["original_error_code"] == "STATE_TRANSITION_DENIED"
    assert payload["task_id"] == TASK_ID
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"] == "CREATED"
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM audit_log WHERE result = 'DENIED'"
            ).fetchone()["n"]
            == 0
        )
    finally:
        connection.close()