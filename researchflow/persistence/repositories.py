"""Repositories for WP-03 persistence.

Public methods are read-only.  Every write needs an explicit capability object;
the capability is intentionally not a security boundary, but it prevents a
public repository API from becoming a second state-writing entry point.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AuditRepository",
    "AuditRow",
    "COLLECTOR_APPEND",
    "Capability",
    "DirectStateWriteDenied",
    "EvidenceRepository",
    "EvidenceRow",
    "IDEMPOTENCY_WRITE",
    "IdempotencyRepository",
    "IdempotencyRow",
    "InvalidationRow",
    "NodeRepository",
    "NodeRow",
    "EVIDENCE_WRITE",
    "STATE_MACHINE_WRITE",
    "TASK_CREATION",
    "TEST_FIXTURE",
    "TaskRepository",
    "TaskRow",
    "VERIFIER_EVIDENCE",
    "VERIFIER_AUDIT",
    "WP_R_FREEZE",
]


@dataclass(frozen=True, slots=True)
class Capability:
    name: str


STATE_MACHINE_WRITE = Capability("STATE_MACHINE_WRITE")
TASK_CREATION = Capability("TASK_CREATION")
COLLECTOR_APPEND = Capability("COLLECTOR_APPEND")
VERIFIER_EVIDENCE = Capability("VERIFIER_EVIDENCE")
EVIDENCE_WRITE = Capability("EVIDENCE_WRITE")
VERIFIER_AUDIT = Capability("VERIFIER_AUDIT")
WP_R_FREEZE = Capability("WP_R_FREEZE")
IDEMPOTENCY_WRITE = Capability("IDEMPOTENCY_WRITE")
TEST_FIXTURE = Capability("TEST_FIXTURE")


class DirectStateWriteDenied(RuntimeError):
    error_code = "STATE_TRANSITION_DENIED"

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(
            f"STATE_TRANSITION_DENIED: direct state write requires capability ({operation})"
        )


def _require(capability: Capability, expected: Capability, operation: str) -> None:
    if capability is not expected:
        raise DirectStateWriteDenied(operation)


@dataclass(frozen=True, slots=True)
class TaskRow:
    task_id: str
    schema_version: str
    domain_pack: str
    goal: str
    task_spec_hash: str
    task_spec_json: str
    state: str
    graph_version: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class NodeRow:
    task_id: str
    node_id: str
    schema_version: str
    node_type: str
    template_id: str
    state: str
    attempt_seq: int
    plan_id: str | None
    plan_hash: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class AuditRow:
    audit_id: str
    task_id: str | None
    node_id: str | None
    actor: str
    action: str
    previous_state: str | None
    next_state: str | None
    reason_code: str | None
    rule_version: str | None
    correlation_id: str | None
    plan_id: str | None
    plan_hash: str | None
    result: str
    error_code: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class IdempotencyRow:
    idem_key: str
    request_hash: str
    task_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    evidence_id: str
    task_id: str
    node_id: str
    attempt_id: str
    event_seq: int
    level: str
    kind: str
    producer: str
    timestamp: str
    payload_hash: str
    artifact_refs: str | None
    prev_hash: str
    chain_hash: str


@dataclass(frozen=True, slots=True)
class InvalidationRow:
    invalidation_id: str
    task_id: str
    node_id: str
    evidence_id: str
    reason_code: str
    cause_type: str
    cause_ref: str | None
    plan_id: str | None
    plan_hash: str | None
    created_at: str


def _task_from_row(row: sqlite3.Row) -> TaskRow:
    return TaskRow(
        task_id=row["task_id"],
        schema_version=row["schema_version"],
        domain_pack=row["domain_pack"],
        goal=row["goal"],
        task_spec_hash=row["task_spec_hash"],
        task_spec_json=row["task_spec_json"],
        state=row["state"],
        graph_version=row["graph_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _node_from_row(row: sqlite3.Row) -> NodeRow:
    return NodeRow(
        task_id=row["task_id"],
        node_id=row["node_id"],
        schema_version=row["schema_version"],
        node_type=row["node_type"],
        template_id=row["template_id"],
        state=row["state"],
        attempt_seq=row["attempt_seq"],
        plan_id=row["plan_id"],
        plan_hash=row["plan_hash"],
        updated_at=row["updated_at"],
    )


def _audit_from_row(row: sqlite3.Row) -> AuditRow:
    return AuditRow(
        audit_id=row["audit_id"],
        task_id=row["task_id"],
        node_id=row["node_id"],
        actor=row["actor"],
        action=row["action"],
        previous_state=row["previous_state"],
        next_state=row["next_state"],
        reason_code=row["reason_code"],
        rule_version=row["rule_version"],
        correlation_id=row["correlation_id"],
        plan_id=row["plan_id"],
        plan_hash=row["plan_hash"],
        result=row["result"],
        error_code=row["error_code"],
        created_at=row["created_at"],
    )


class TaskRepository:
    def get(self, connection: sqlite3.Connection, task_id: str) -> TaskRow | None:
        row = connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return None if row is None else _task_from_row(row)

    def _insert_initial(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        schema_version: str,
        domain_pack: str,
        goal: str,
        task_spec_hash: str,
        task_spec_json: str,
        created_at: str,
        updated_at: str,
        capability: Capability,
    ) -> None:
        _require(capability, TASK_CREATION, "_insert_initial")
        connection.execute(
            "INSERT INTO tasks(task_id, schema_version, domain_pack, goal, "
            "task_spec_hash, task_spec_json, state, graph_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'CREATED', 1, ?, ?)",
            (
                task_id,
                schema_version,
                domain_pack,
                goal,
                task_spec_hash,
                task_spec_json,
                created_at,
                updated_at,
            ),
        )

    def _apply_transition(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        expected_from: str,
        next_state: str,
        graph_version: int | None,
        updated_at: str,
        capability: Capability,
    ) -> int:
        _require(capability, STATE_MACHINE_WRITE, "_apply_transition")
        cursor = connection.execute(
            "UPDATE tasks SET state = ?, graph_version = ?, updated_at = ? "
            "WHERE task_id = ? AND state = ?",
            (next_state, graph_version, updated_at, task_id, expected_from),
        )
        return int(cursor.rowcount)


class NodeRepository:
    def get(
        self, connection: sqlite3.Connection, task_id: str, node_id: str
    ) -> NodeRow | None:
        row = connection.execute(
            "SELECT * FROM nodes WHERE task_id = ? AND node_id = ?",
            (task_id, node_id),
        ).fetchone()
        return None if row is None else _node_from_row(row)

    def list_for_task(
        self, connection: sqlite3.Connection, task_id: str
    ) -> list[NodeRow]:
        rows = connection.execute(
            "SELECT * FROM nodes WHERE task_id = ? ORDER BY node_id", (task_id,)
        ).fetchall()
        return [_node_from_row(row) for row in rows]

    def _insert_initial(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        node_id: str,
        schema_version: str,
        node_type: str,
        template_id: str,
        updated_at: str,
        capability: Capability,
    ) -> None:
        _require(capability, TASK_CREATION, "_insert_initial")
        connection.execute(
            "INSERT INTO nodes(task_id, node_id, schema_version, node_type, "
            "template_id, state, attempt_seq, plan_id, plan_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'PLANNED', 0, NULL, NULL, ?)",
            (task_id, node_id, schema_version, node_type, template_id, updated_at),
        )

    def _apply_transition(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        node_id: str,
        expected_from: str,
        next_state: str,
        attempt_seq: int,
        plan_id: str | None,
        plan_hash: str | None,
        updated_at: str,
        capability: Capability,
    ) -> int:
        _require(capability, STATE_MACHINE_WRITE, "_apply_transition")
        cursor = connection.execute(
            "UPDATE nodes SET state = ?, attempt_seq = ?, plan_id = ?, "
            "plan_hash = ?, updated_at = ? "
            "WHERE task_id = ? AND node_id = ? AND state = ?",
            (
                next_state,
                attempt_seq,
                plan_id,
                plan_hash,
                updated_at,
                task_id,
                node_id,
                expected_from,
            ),
        )
        return int(cursor.rowcount)


class AuditRepository:
    _ALLOWED_APPEND = {
        STATE_MACHINE_WRITE,
        WP_R_FREEZE,
        TEST_FIXTURE,
        EVIDENCE_WRITE,
        VERIFIER_AUDIT,
    }

    def get(self, connection: sqlite3.Connection, audit_id: str) -> AuditRow | None:
        row = connection.execute(
            "SELECT * FROM audit_log WHERE audit_id = ?", (audit_id,)
        ).fetchone()
        return None if row is None else _audit_from_row(row)

    def list_for_task(
        self, connection: sqlite3.Connection, task_id: str
    ) -> list[AuditRow]:
        rows = connection.execute(
            "SELECT * FROM audit_log WHERE task_id = ? ORDER BY created_at, audit_id",
            (task_id,),
        ).fetchall()
        return [_audit_from_row(row) for row in rows]

    def latest_freeze(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        node_id: str,
        plan_hash: str,
    ) -> AuditRow | None:
        row = connection.execute(
            "SELECT * FROM audit_log WHERE task_id = ? AND node_id = ? "
            "AND plan_hash = ? AND action = 'RECOVERY_PLAN_FROZEN' AND result = 'OK' "
            "ORDER BY created_at DESC, audit_id DESC LIMIT 1",
            (task_id, node_id, plan_hash),
        ).fetchone()
        return None if row is None else _audit_from_row(row)

    def append(
        self,
        connection: sqlite3.Connection,
        *,
        audit_id: str,
        task_id: str | None,
        node_id: str | None,
        actor: str,
        action: str,
        previous_state: str | None,
        next_state: str | None,
        reason_code: str | None,
        rule_version: str | None,
        correlation_id: str | None,
        plan_id: str | None,
        plan_hash: str | None,
        result: str,
        error_code: str | None,
        created_at: str,
        capability: Capability,
    ) -> None:
        if capability not in self._ALLOWED_APPEND:
            raise DirectStateWriteDenied("_append")
        connection.execute(
            "INSERT INTO audit_log(audit_id, task_id, node_id, actor, action, "
            "previous_state, next_state, reason_code, rule_version, correlation_id, "
            "plan_id, plan_hash, result, error_code, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                task_id,
                node_id,
                actor,
                action,
                previous_state,
                next_state,
                reason_code,
                rule_version,
                correlation_id,
                plan_id,
                plan_hash,
                result,
                error_code,
                created_at,
            ),
        )

    def count(self, connection: sqlite3.Connection, result: str | None = None) -> int:
        if result is None:
            row = connection.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM audit_log WHERE result = ?", (result,)
            ).fetchone()
        return int(row["n"])


class EvidenceRepository:
    def get(
        self, connection: sqlite3.Connection, evidence_id: str
    ) -> EvidenceRow | None:
        row = connection.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        if row is None:
            return None
        return EvidenceRow(
            evidence_id=row["evidence_id"],
            task_id=row["task_id"],
            node_id=row["node_id"],
            attempt_id=row["attempt_id"],
            event_seq=row["event_seq"],
            level=row["level"],
            kind=row["kind"],
            producer=row["producer"],
            timestamp=row["timestamp"],
            payload_hash=row["payload_hash"],
            artifact_refs=row["artifact_refs"],
            prev_hash=row["prev_hash"],
            chain_hash=row["chain_hash"],
        )

    def count(self, connection: sqlite3.Connection, task_id: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE task_id = ?", (task_id,)
        ).fetchone()
        return int(row["n"])

    def is_invalidated(self, connection: sqlite3.Connection, evidence_id: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM evidence_invalidations WHERE evidence_id = ? LIMIT 1",
            (evidence_id,),
        ).fetchone()
        return row is not None

    def append(
        self,
        connection: sqlite3.Connection,
        *,
        evidence_id: str,
        task_id: str,
        node_id: str,
        attempt_id: str,
        event_seq: int,
        level: str,
        kind: str,
        producer: str,
        timestamp: str,
        payload_hash: str,
        artifact_refs: str | None,
        prev_hash: str,
        chain_hash: str,
        capability: Capability,
    ) -> None:
        expected = VERIFIER_EVIDENCE if level == "E3" else COLLECTOR_APPEND
        _require(capability, expected, "_evidence_append")
        connection.execute(
            "INSERT INTO evidence(evidence_id, task_id, node_id, attempt_id, "
            "event_seq, level, kind, producer, timestamp, payload_hash, "
            "artifact_refs, prev_hash, chain_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence_id,
                task_id,
                node_id,
                attempt_id,
                event_seq,
                level,
                kind,
                producer,
                timestamp,
                payload_hash,
                artifact_refs,
                prev_hash,
                chain_hash,
            ),
        )

    def append_invalidation(
        self,
        connection: sqlite3.Connection,
        *,
        invalidation_id: str,
        task_id: str,
        node_id: str,
        evidence_id: str,
        reason_code: str,
        cause_type: str,
        cause_ref: str | None,
        plan_id: str | None,
        plan_hash: str | None,
        created_at: str,
        capability: Capability,
    ) -> None:
        _require(capability, STATE_MACHINE_WRITE, "_append_invalidation")
        connection.execute(
            "INSERT INTO evidence_invalidations(invalidation_id, task_id, node_id, "
            "evidence_id, reason_code, cause_type, cause_ref, plan_id, plan_hash, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                invalidation_id,
                task_id,
                node_id,
                evidence_id,
                reason_code,
                cause_type,
                cause_ref,
                plan_id,
                plan_hash,
                created_at,
            ),
        )

    def list_invalidations(
        self, connection: sqlite3.Connection, task_id: str, node_id: str
    ) -> list[InvalidationRow]:
        rows = connection.execute(
            "SELECT * FROM evidence_invalidations WHERE task_id = ? AND node_id = ? "
            "ORDER BY created_at, invalidation_id",
            (task_id, node_id),
        ).fetchall()
        return [
            InvalidationRow(
                invalidation_id=row["invalidation_id"],
                task_id=row["task_id"],
                node_id=row["node_id"],
                evidence_id=row["evidence_id"],
                reason_code=row["reason_code"],
                cause_type=row["cause_type"],
                cause_ref=row["cause_ref"],
                plan_id=row["plan_id"],
                plan_hash=row["plan_hash"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


class IdempotencyRepository:
    def lookup(
        self, connection: sqlite3.Connection, idem_key: str
    ) -> IdempotencyRow | None:
        row = connection.execute(
            "SELECT * FROM idempotency_keys WHERE idem_key = ?", (idem_key,)
        ).fetchone()
        if row is None:
            return None
        return IdempotencyRow(
            idem_key=row["idem_key"],
            request_hash=row["request_hash"],
            task_id=row["task_id"],
            created_at=row["created_at"],
        )

    def insert(
        self,
        connection: sqlite3.Connection,
        *,
        idem_key: str,
        request_hash: str,
        task_id: str,
        created_at: str,
        capability: Capability,
    ) -> None:
        _require(capability, IDEMPOTENCY_WRITE, "_idempotency_insert")
        connection.execute(
            "INSERT INTO idempotency_keys(idem_key, request_hash, task_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (idem_key, request_hash, task_id, created_at),
        )

    def count(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT COUNT(*) AS n FROM idempotency_keys").fetchone()
        return int(row["n"])