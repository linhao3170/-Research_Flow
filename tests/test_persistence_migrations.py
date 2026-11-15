from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from researchflow.persistence.db import connect
from researchflow.persistence.migrations import (
    DEFAULT_MIGRATIONS,
    Migration,
    MigrationError,
    MigrationRunner,
)
from researchflow.persistence.schema_sql import assert_schema_contract


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row["name"]) for row in rows}


def test_fresh_db_creates_all_migrated_tables(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    connection = connect(db)
    try:
        # WP-03 shipped 7 tables; WP-04/07/11/12 add the 4 tables frozen in
        # 06 §1.3 through migration 0002 (see docs/verification/t0/wp-04/00_decisions.md).
        assert MigrationRunner().upgrade(connection) == "0003_audit_actions"
        assert _table_names(connection) == {
            "tasks",
            "nodes",
            "evidence",
            "evidence_invalidations",
            "audit_log",
            "idempotency_keys",
            "schema_migrations",
            "graph_versions",
            "reports",
            "certificates",
            "ingestion_log",
        }
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        connection.close()


def test_schema_contract_and_key_objects(tmp_path: Path) -> None:
    assert assert_schema_contract() == []
    db = tmp_path / "objects.db"
    connection = connect(db)
    try:
        MigrationRunner().upgrade(connection)
        names = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('index','trigger')"
            )
        }
        for expected in {
            "idx_nodes_state",
            "idx_evidence_task_seq",
            "idx_audit_task_time",
            "trg_tasks_state_requires_audit",
            "trg_nodes_state_requires_audit",
            "trg_audit_log_no_update",
            "trg_idempotency_keys_no_update",
        }:
            assert expected in names
    finally:
        connection.close()


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "repeat.db"
    connection = connect(db)
    try:
        runner = MigrationRunner()
        assert runner.upgrade(connection) == "0003_audit_actions"
        assert runner.upgrade(connection) == "0003_audit_actions"
        count = connection.execute(
            "SELECT COUNT(*) AS n FROM schema_migrations"
        ).fetchone()["n"]
        assert count == 3
    finally:
        connection.close()


def test_failed_migration_rolls_back_all_statements(tmp_path: Path) -> None:
    db = tmp_path / "failure.db"
    connection = connect(db)
    try:
        runner = MigrationRunner(
            [
                Migration("0001_ok", ("CREATE TABLE ok_table (id TEXT);",)),
                Migration(
                    "0002_bad",
                    (
                        "CREATE TABLE bad_table (id TEXT);",
                        "CREATE TABLE broken (",
                    ),
                ),
            ]
        )
        with pytest.raises(sqlite3.OperationalError):
            runner.upgrade(connection)
        assert "ok_table" not in _table_names(connection)
        assert "bad_table" not in _table_names(connection)
    finally:
        connection.close()


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "checksum.db"
    connection = connect(db)
    try:
        MigrationRunner().upgrade(connection)
        altered = Migration(
            "0001_initial",
            tuple(statement + " " for statement in DEFAULT_MIGRATIONS[0].statements),
        )
        with pytest.raises(MigrationError):
            MigrationRunner([altered]).upgrade(connection)
    finally:
        connection.close()


def test_schema_migrations_is_append_only(tmp_path: Path) -> None:
    db = tmp_path / "append.db"
    connection = connect(db)
    try:
        MigrationRunner().upgrade(connection)
        with pytest.raises(sqlite3.IntegrityError, match="APPEND_ONLY_TABLE: schema_migrations"):
            connection.execute("UPDATE schema_migrations SET checksum = 'x'")
    finally:
        connection.close()


def test_audit_migration_preserves_rows_and_extends_actions(tmp_path: Path) -> None:
    db = tmp_path / "audit_upgrade.db"
    connection = connect(db)
    try:
        # Upgrade to the WP-03/WP-04 schema first (0001 + 0002), then add a row
        # using an action the original CHECK allowed.
        MigrationRunner(DEFAULT_MIGRATIONS[:2]).upgrade(connection)
        connection.execute(
            "INSERT INTO audit_log(audit_id, task_id, node_id, actor, action, "
            "previous_state, next_state, reason_code, rule_version, correlation_id, "
            "plan_id, plan_hash, result, error_code, created_at) "
            "VALUES ('a1', NULL, NULL, 'test:actor', 'TOOL_REQUEST', NULL, NULL, "
            "'R', '1.0', 'c1', NULL, NULL, 'OK', NULL, '2026-11-14T00:00:00.000000Z')"
        )
        assert MigrationRunner().upgrade(connection) == "0003_audit_actions"
        row = connection.execute("SELECT * FROM audit_log WHERE audit_id = 'a1'").fetchone()
        assert row is not None
        assert row["actor"] == "test:actor" and row["result"] == "OK"
        # New actions are accepted after the rebuild.
        connection.execute(
            "INSERT INTO audit_log(audit_id, task_id, node_id, actor, action, "
            "previous_state, next_state, reason_code, rule_version, correlation_id, "
            "plan_id, plan_hash, result, error_code, created_at) "
            "VALUES ('a2', NULL, NULL, 'collector:record', 'EVIDENCE_APPENDED', NULL, NULL, "
            "'E2:x', '1.0', 'c2', NULL, NULL, 'OK', NULL, '2026-11-14T00:00:01.000000Z')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="APPEND_ONLY_TABLE: audit_log"):
            connection.execute("UPDATE audit_log SET result = 'DENIED' WHERE audit_id = 'a1'")
        # The state-update guard trigger was recreated.
        names = {
            str(item["name"])
            for item in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
        assert "trg_tasks_state_requires_audit" in names
        assert "trg_nodes_state_requires_audit" in names
    finally:
        connection.close()