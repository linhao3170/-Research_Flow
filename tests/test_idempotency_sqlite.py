from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from researchflow.contracts.encoding import hash_payload
from researchflow.contracts.models import TaskSpecCreate
from researchflow.orchestration.creation import TaskCreationService
from researchflow.orchestration.state_machine import (
    Actor,
    InitializationDenied,
    TransitionRequest,
)
from researchflow.orchestration.transitions import ActorRole
from researchflow.persistence.db import connect
from researchflow.persistence.idempotency import (
    InvalidIdempotencyKey,
    validate_idempotency_key,
)
from wp03_support import TASK_ID, TASK_PAYLOAD, build_state_machine, make_db


def _service(tmp_path: Path) -> TaskCreationService:
    db = make_db(tmp_path / "idempotency.db")
    sm = build_state_machine(db)
    return TaskCreationService(db, sm)


def _create_spec(**overrides):
    payload = {key: value for key, value in TASK_PAYLOAD.items() if key != "task_id"}
    payload.update(overrides)
    return TaskSpecCreate.model_validate(payload)


def _counts(db: Path) -> tuple[int, int]:
    connection = connect(db)
    try:
        tasks = connection.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        keys = connection.execute(
            "SELECT COUNT(*) AS n FROM idempotency_keys"
        ).fetchone()["n"]
        return int(tasks), int(keys)
    finally:
        connection.close()


def test_same_key_same_body_replays(tmp_path: Path) -> None:
    service = _service(tmp_path)
    spec = _create_spec()
    request_hash = hash_payload(spec.model_dump(mode="json"))
    first = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key="idem-1"
    )
    second = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key="idem-1"
    )
    assert first.kind == "CREATED"
    assert second.kind == "REPLAY"
    assert first.task_id == second.task_id
    assert _counts(tmp_path / "idempotency.db") == (1, 1)


def test_same_key_different_body_conflicts_without_new_task(tmp_path: Path) -> None:
    service = _service(tmp_path)
    spec = _create_spec()
    changed = _create_spec(goal="A different goal")
    first = service.create_task(
        create_spec=spec,
        request_hash=hash_payload(spec.model_dump(mode="json")),
        idempotency_key="idem-2",
    )
    conflict = service.create_task(
        create_spec=changed,
        request_hash=hash_payload(changed.model_dump(mode="json")),
        idempotency_key="idem-2",
    )
    assert first.kind == "CREATED"
    assert conflict.kind == "CONFLICT"
    assert _counts(tmp_path / "idempotency.db") == (1, 1)


def test_different_keys_create_two_tasks(tmp_path: Path) -> None:
    service = _service(tmp_path)
    spec = _create_spec()
    request_hash = hash_payload(spec.model_dump(mode="json"))
    first = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key="idem-3a"
    )
    second = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key="idem-3b"
    )
    assert first.task_id != second.task_id
    assert _counts(tmp_path / "idempotency.db") == (2, 2)


def test_missing_key_creates_two_tasks(tmp_path: Path) -> None:
    service = _service(tmp_path)
    spec = _create_spec()
    request_hash = hash_payload(spec.model_dump(mode="json"))
    first = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key=None
    )
    second = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key=None
    )
    assert first.task_id != second.task_id
    assert _counts(tmp_path / "idempotency.db") == (2, 0)


@pytest.mark.parametrize(
    "key",
    ["", "has space", "x" * 256, "line\nbreak"],
)
def test_invalid_idempotency_keys_are_rejected(key: str) -> None:
    with pytest.raises(InvalidIdempotencyKey) as excinfo:
        validate_idempotency_key(key)
    assert excinfo.value.field_path == "Idempotency-Key"


def test_absent_key_is_allowed() -> None:
    assert validate_idempotency_key(None) is None


def test_task_insert_failure_leaves_no_orphan_key(tmp_path: Path) -> None:
    service = _service(tmp_path)
    db = tmp_path / "idempotency.db"
    connection = connect(db)
    try:
        connection.execute(
            """
            CREATE TRIGGER trg_test_task_insert_fail
            BEFORE INSERT ON tasks
            WHEN NEW.goal = 'forced failure'
            BEGIN SELECT RAISE(ABORT, 'FORCED_TASK_FAILURE'); END;
            """
        )
    finally:
        connection.close()
    spec = _create_spec(goal="forced failure")
    with pytest.raises(InitializationDenied):
        service.create_task(
            create_spec=spec,
            request_hash=hash_payload(spec.model_dump(mode="json")),
            idempotency_key="idem-orphan",
        )
    tasks, keys = _counts(db)
    assert tasks == 0
    assert keys == 0


def test_replay_returns_created_receipt_after_state_change(tmp_path: Path) -> None:
    service = _service(tmp_path)
    db = tmp_path / "idempotency.db"
    spec = _create_spec()
    request_hash = hash_payload(spec.model_dump(mode="json"))
    first = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key="idem-4"
    )
    sm = build_state_machine(db)
    sm.transition(
        TransitionRequest(
            obj_type="task",
            task_id=first.task_id,
            previous_state="CREATED",
            next_state="PLANNING",
            actor=Actor(ActorRole.ORCHESTRATOR, "test"),
            reason_code="TASK_PLANNING_STARTED",
            rule_version="1.0",
            correlation_id="req-replay",
        )
    )
    replay = service.create_task(
        create_spec=spec, request_hash=request_hash, idempotency_key="idem-4"
    )
    assert replay.kind == "REPLAY"
    assert replay.task_id == first.task_id
    assert replay.state == "CREATED"
    assert replay.graph_version == 1