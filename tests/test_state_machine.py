from __future__ import annotations

from pathlib import Path

import pytest

from researchflow.orchestration.ports import Ports
from researchflow.orchestration.state_machine import (
    Actor,
    StateMachine,
    StateTransitionDenied,
    TransitionContext,
    TransitionRequest,
    assert_single_write_entrypoint,
)
from researchflow.orchestration.transitions import ActorRole, ObjectType
from researchflow.persistence.db import connect
from wp03_support import (
    NODE_ID,
    TASK_ID,
    FakeCertificateFacts,
    FakeGateFacts,
    FakeGraphFacts,
    FakeNodeFacts,
    FakeReportFacts,
    FakeTaskFacts,
    build_state_machine,
    create_task_and_node,
    make_db,
)


def _task_request(
    sm: StateMachine,
    *,
    previous: str,
    next_state: str,
    actor: Actor | None = None,
    reason: str = "TASK_TEST",
    correlation: str | None = "req-test",
    context: TransitionContext | None = None,
):
    return sm.transition(
        TransitionRequest(
            obj_type=ObjectType.TASK,
            task_id=TASK_ID,
            previous_state=previous,
            next_state=next_state,
            actor=actor or Actor(ActorRole.ORCHESTRATOR, "test"),
            reason_code=reason,
            rule_version="1.0",
            correlation_id=correlation,
            context=context or TransitionContext(),
        )
    )


def _node_request(
    sm: StateMachine,
    *,
    previous: str,
    next_state: str,
    actor: Actor | None = None,
    reason: str = "NODE_TEST",
    context: TransitionContext | None = None,
):
    return sm.transition(
        TransitionRequest(
            obj_type=ObjectType.NODE,
            task_id=TASK_ID,
            node_id=NODE_ID,
            previous_state=previous,
            next_state=next_state,
            actor=actor or Actor(ActorRole.ORCHESTRATOR, "test"),
            reason_code=reason,
            rule_version="1.0",
            correlation_id="req-node-test",
            context=context or TransitionContext(),
        )
    )


def _advance_task_to_planning(sm: StateMachine) -> None:
    _task_request(sm, previous="CREATED", next_state="PLANNING")


def _advance_task_to_ready(sm: StateMachine) -> None:
    _advance_task_to_planning(sm)
    _task_request(
        sm,
        previous="PLANNING",
        next_state="READY",
        context=TransitionContext(graph_version=1),
    )


def _advance_node_to_ready(sm: StateMachine) -> None:
    _node_request(sm, previous="PLANNED", next_state="READY", actor=Actor(ActorRole.SCHEDULER, "test"))


def _advance_node_to_running(sm: StateMachine) -> None:
    _advance_node_to_ready(sm)
    _node_request(sm, previous="READY", next_state="RUNNING", actor=Actor(ActorRole.SCHEDULER, "test"))


def _advance_node_to_verifying(sm: StateMachine) -> None:
    _advance_node_to_running(sm)
    _node_request(
        sm,
        previous="RUNNING",
        next_state="VERIFYING",
        context=TransitionContext(attempt_id="attempt_01"),
    )


def test_create_initial_writes_initial_rows_and_audit(tmp_path: Path) -> None:
    db = make_db(tmp_path / "initial.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"] == "CREATED"
        assert connection.execute(
            "SELECT state FROM nodes WHERE task_id = ? AND node_id = ?",
            (TASK_ID, NODE_ID),
        ).fetchone()["state"] == "PLANNED"
        actions = [
            row["action"]
            for row in connection.execute(
                "SELECT action FROM audit_log WHERE result = 'OK' ORDER BY action"
            )
        ]
        assert actions == ["NODE_PLANNED", "TASK_CREATED"]
    finally:
        connection.close()


def test_legal_task_transition_writes_ok_audit_in_same_transaction(tmp_path: Path) -> None:
    db = make_db(tmp_path / "legal.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    result = _task_request(sm, previous="CREATED", next_state="PLANNING")
    assert result.previous_state == "CREATED"
    assert result.next_state == "PLANNING"
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"] == "PLANNING"
        row = connection.execute(
            "SELECT * FROM audit_log WHERE action = 'STATE_TRANSITION' AND result = 'OK'"
        ).fetchone()
        assert row["previous_state"] == "CREATED"
        assert row["next_state"] == "PLANNING"
        assert row["audit_id"] == result.audit_id
    finally:
        connection.close()


def test_illegal_task_edge_is_denied_with_reason(tmp_path: Path) -> None:
    db = make_db(tmp_path / "illegal.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(sm, previous="CREATED", next_state="COMPLETED")
    exc = excinfo.value
    assert exc.api_error_code == "STATE_TRANSITION_DENIED"
    assert exc.error_code == "STATE_TRANSITION_DENIED"
    assert exc.reason == "ILLEGAL_EDGE"
    assert exc.previous_state == "CREATED"
    assert exc.next_state == "COMPLETED"
    connection = connect(db)
    try:
        assert connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()["state"] == "CREATED"
        denied = connection.execute(
            "SELECT * FROM audit_log WHERE result = 'DENIED'"
        ).fetchone()
        assert denied["reason_code"] == "TASK_TEST"
        assert denied["error_code"] == "STATE_TRANSITION_DENIED"
    finally:
        connection.close()


def test_stale_previous_state_is_denied_and_audit_records_actual_state(tmp_path: Path) -> None:
    db = make_db(tmp_path / "stale.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_task_to_planning(sm)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(sm, previous="CREATED", next_state="READY")
    assert excinfo.value.reason == "STALE_PREVIOUS_STATE"
    assert excinfo.value.previous_state == "PLANNING"
    connection = connect(db)
    try:
        denied = connection.execute(
            "SELECT * FROM audit_log WHERE result = 'DENIED' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert denied["previous_state"] == "PLANNING"
        assert denied["next_state"] == "READY"
    finally:
        connection.close()


def test_non_writer_role_is_denied(tmp_path: Path) -> None:
    db = make_db(tmp_path / "role.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(
            sm,
            previous="CREATED",
            next_state="PLANNING",
            actor=Actor(ActorRole.API, "test"),
        )
    assert excinfo.value.reason == "ROLE_NOT_ALLOWED"


def test_missing_correlation_id_is_denied_with_sentinel_audit(tmp_path: Path) -> None:
    db = make_db(tmp_path / "missing.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(
            sm,
            previous="CREATED",
            next_state="PLANNING",
            correlation=None,
        )
    assert excinfo.value.reason == "MISSING_PARAMETER"
    assert excinfo.value.field_path == "correlation_id"
    connection = connect(db)
    try:
        denied = connection.execute(
            "SELECT * FROM audit_log WHERE result = 'DENIED'"
        ).fetchone()
        assert denied["correlation_id"] == "<missing>"
    finally:
        connection.close()


def test_plan_fields_on_non_plan_edge_are_denied(tmp_path: Path) -> None:
    db = make_db(tmp_path / "plan-fields.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(
            sm,
            previous="CREATED",
            next_state="PLANNING",
            context=TransitionContext(plan_id="p", plan_hash="a" * 64),
        )
    assert excinfo.value.reason == "PLAN_FIELDS_NOT_ALLOWED"


def test_evidence_object_type_is_not_managed(tmp_path: Path) -> None:
    db = make_db(tmp_path / "evidence-type.db")
    sm = build_state_machine(db)
    with pytest.raises(StateTransitionDenied) as excinfo:
        sm.transition(
            TransitionRequest(
                obj_type=ObjectType.EVIDENCE,
                task_id="ev_x",
                previous_state="RECEIVED",
                next_state="VALIDATED",
                actor=Actor(ActorRole.COLLECTOR, "test"),
                reason_code="X",
                rule_version="1.0",
                correlation_id="c",
            )
        )
    assert excinfo.value.reason == "OBJECT_TYPE_NOT_MANAGED"


def test_unknown_object_is_denied(tmp_path: Path) -> None:
    db = make_db(tmp_path / "missing-object.db")
    sm = build_state_machine(db)
    with pytest.raises(StateTransitionDenied) as excinfo:
        sm.transition(
            TransitionRequest(
                obj_type=ObjectType.TASK,
                task_id="task_00000000-0000-0000-0000-000000000099",
                previous_state="CREATED",
                next_state="PLANNING",
                actor=Actor(ActorRole.ORCHESTRATOR, "test"),
                reason_code="X",
                rule_version="1.0",
                correlation_id="c",
            )
        )
    assert excinfo.value.reason == "OBJECT_NOT_FOUND"


def test_missing_port_fails_closed(tmp_path: Path) -> None:
    db = make_db(tmp_path / "port.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_task_to_planning(sm)
    bare = StateMachine(db, ports=Ports())
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(
            bare,
            previous="PLANNING",
            next_state="READY",
            context=TransitionContext(graph_version=1),
        )
    assert excinfo.value.reason == "PORT_UNAVAILABLE"


def test_task_ready_requires_valid_dag(tmp_path: Path) -> None:
    db = make_db(tmp_path / "dag.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_task_to_planning(sm)
    invalid = StateMachine(db, ports=Ports(graph=FakeGraphFacts(valid=False)))
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(
            invalid,
            previous="PLANNING",
            next_state="READY",
            context=TransitionContext(graph_version=1),
        )
    assert excinfo.value.reason == "DAG_INVALID"


def test_task_ready_succeeds_when_dag_valid(tmp_path: Path) -> None:
    db = make_db(tmp_path / "dag-ok.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_task_to_ready(sm)
    connection = connect(db)
    try:
        row = connection.execute(
            "SELECT state, graph_version FROM tasks WHERE task_id = ?", (TASK_ID,)
        ).fetchone()
        assert row["state"] == "READY"
        assert row["graph_version"] == 1
    finally:
        connection.close()


def test_task_running_requires_a_ready_node(tmp_path: Path) -> None:
    db = make_db(tmp_path / "ready-node.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_task_to_ready(sm)
    no_ready = StateMachine(
        db, ports=Ports(task=FakeTaskFacts(has_ready=False))
    )
    with pytest.raises(StateTransitionDenied) as excinfo:
        _task_request(no_ready, previous="READY", next_state="RUNNING")
    assert excinfo.value.reason == "NO_READY_NODE"


def test_node_ready_requires_dependencies(tmp_path: Path) -> None:
    db = make_db(tmp_path / "deps.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    blocked = StateMachine(
        db, ports=Ports(node=FakeNodeFacts(dependencies=False))
    )
    with pytest.raises(StateTransitionDenied) as excinfo:
        _node_request(
            blocked,
            previous="PLANNED",
            next_state="READY",
            actor=Actor(ActorRole.SCHEDULER, "test"),
        )
    assert excinfo.value.reason == "DEPENDENCIES_NOT_SATISFIED"


def test_node_running_requires_resources(tmp_path: Path) -> None:
    db = make_db(tmp_path / "resources.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_node_to_ready(sm)
    blocked = StateMachine(
        db, ports=Ports(node=FakeNodeFacts(resources=False))
    )
    with pytest.raises(StateTransitionDenied) as excinfo:
        _node_request(
            blocked,
            previous="READY",
            next_state="RUNNING",
            actor=Actor(ActorRole.SCHEDULER, "test"),
        )
    assert excinfo.value.reason == "RESOURCES_UNAVAILABLE"


def test_node_verifying_requires_attempt_end_and_zero_exit(tmp_path: Path) -> None:
    db = make_db(tmp_path / "attempt.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_node_to_running(sm)
    not_ended = StateMachine(db, ports=Ports(node=FakeNodeFacts(ended=False)))
    with pytest.raises(StateTransitionDenied) as first:
        _node_request(
            not_ended,
            previous="RUNNING",
            next_state="VERIFYING",
            context=TransitionContext(attempt_id="attempt_01"),
        )
    assert first.value.reason == "ATTEMPT_NOT_ENDED"
    nonzero = StateMachine(db, ports=Ports(node=FakeNodeFacts(exit_code=1)))
    with pytest.raises(StateTransitionDenied) as second:
        _node_request(
            nonzero,
            previous="RUNNING",
            next_state="VERIFYING",
            context=TransitionContext(attempt_id="attempt_01"),
        )
    assert second.value.reason == "EXIT_CODE_NONZERO"


def test_node_verified_requires_gate_report_and_certificate(tmp_path: Path) -> None:
    db = make_db(tmp_path / "verified.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    _advance_node_to_verifying(sm)
    gate_failed = StateMachine(db, ports=Ports(gate=FakeGateFacts(passed=False)))
    with pytest.raises(StateTransitionDenied) as first:
        _node_request(gate_failed, previous="VERIFYING", next_state="VERIFIED")
    assert first.value.reason == "GATE_NOT_PASS"
    partial = StateMachine(
        db, ports=Ports(gate=FakeGateFacts(), report=FakeReportFacts(final_state="PARTIAL"))
    )
    with pytest.raises(StateTransitionDenied) as second:
        _node_request(partial, previous="VERIFYING", next_state="VERIFIED")
    assert second.value.reason == "REPORT_NOT_VERIFIED"
    revoked = StateMachine(
        db,
        ports=Ports(
            gate=FakeGateFacts(),
            report=FakeReportFacts(),
            certificate=FakeCertificateFacts(revoked=True),
        ),
    )
    with pytest.raises(StateTransitionDenied) as third:
        _node_request(revoked, previous="VERIFYING", next_state="VERIFIED")
    assert third.value.reason == "CERTIFICATE_INVALID"


def test_single_write_entrypoint_contract() -> None:
    assert assert_single_write_entrypoint() == []