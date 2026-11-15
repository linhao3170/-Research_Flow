from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from researchflow.orchestration.state_machine import assert_single_write_entrypoint
from researchflow.persistence.db import connect
from wp03_support import (
    EVIDENCE_ID,
    NODE_ID,
    TASK_ID,
    build_state_machine,
    create_task_and_node,
    make_db,
    seed_evidence,
)


def _state(db: Path, table: str, key: str) -> str:
    connection = connect(db)
    try:
        if table == "tasks":
            row = connection.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (key,)
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT state FROM nodes WHERE task_id = ? AND node_id = ?",
                (TASK_ID, key),
            ).fetchone()
        return str(row["state"])
    finally:
        connection.close()


def test_direct_task_state_update_is_denied(tmp_path: Path) -> None:
    db = make_db(tmp_path / "direct-task.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="STATE_WRITE_WITHOUT_AUDIT: tasks"
        ):
            connection.execute(
                "UPDATE tasks SET state = 'COMPLETED' WHERE task_id = ?", (TASK_ID,)
            )
    finally:
        connection.close()
    assert _state(db, "tasks", TASK_ID) == "CREATED"


def test_direct_node_state_update_is_denied(tmp_path: Path) -> None:
    db = make_db(tmp_path / "direct-node.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="STATE_WRITE_WITHOUT_AUDIT: nodes"
        ):
            connection.execute(
                "UPDATE nodes SET state = 'VERIFIED' WHERE task_id = ? AND node_id = ?",
                (TASK_ID, NODE_ID),
            )
    finally:
        connection.close()
    assert _state(db, "nodes", NODE_ID) == "PLANNED"


def test_direct_task_insert_must_be_created(tmp_path: Path) -> None:
    db = make_db(tmp_path / "insert-task.db")
    connection = connect(db)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="TASK_MUST_BE_INSERTED_CREATED"
        ):
            connection.execute(
                "INSERT INTO tasks(task_id, schema_version, domain_pack, goal, "
                "task_spec_hash, task_spec_json, state, graph_version, created_at, updated_at) "
                "VALUES ('task_00000000-0000-0000-0000-000000000099', '1.0', "
                "'tabular_ml@1.0.0', 'g', 'h', '{}', 'COMPLETED', 1, 't', 't')"
            )
    finally:
        connection.close()


def test_direct_node_insert_must_be_planned(tmp_path: Path) -> None:
    db = make_db(tmp_path / "insert-node.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="NODE_MUST_BE_INSERTED_PLANNED"
        ):
            connection.execute(
                "INSERT INTO nodes(task_id, node_id, schema_version, node_type, "
                "template_id, state, attempt_seq, updated_at) VALUES (?, ?, '1.0', "
                "'ml.train.classifier', 'random_forest@1.0.0', 'VERIFIED', 0, 't')",
                (TASK_ID, "extra_node"),
            )
    finally:
        connection.close()


def test_direct_attempt_seq_change_is_denied(tmp_path: Path) -> None:
    db = make_db(tmp_path / "attempt.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        # M02 NEG-M02-08: a same-state attempt_seq change is rejected by the
        # non-state-change trigger, not by the state-write-without-audit one.
        with pytest.raises(
            sqlite3.IntegrityError,
            match="NODE_FIELD_CHANGE_WITHOUT_STATE_TRANSITION",
        ):
            connection.execute(
                "UPDATE nodes SET attempt_seq = 2 WHERE task_id = ? AND node_id = ?",
                (TASK_ID, NODE_ID),
            )
    finally:
        connection.close()


def test_direct_audit_delete_is_denied(tmp_path: Path) -> None:
    db = make_db(tmp_path / "audit.db")
    sm = build_state_machine(db)
    create_task_and_node(sm)
    connection = connect(db)
    try:
        with pytest.raises(
            sqlite3.IntegrityError, match="APPEND_ONLY_TABLE: audit_log"
        ):
            connection.execute("DELETE FROM audit_log")
    finally:
        connection.close()


def test_repository_surface_has_no_public_writes() -> None:
    assert assert_single_write_entrypoint() == []