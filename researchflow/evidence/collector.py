"""Controlled evidence collector (T0 WP-07).

The Collector is the only writer of E0/E1/E2 records.  E2 records are derived
from a real controlled observation (:class:`AttemptObservation` produced by the
executor from an actual process and its artifacts), never from a claim.

Properties enforced here:

* ``event_seq`` is assigned inside ``BEGIN IMMEDIATE`` and is contiguous per
  task (``UNIQUE(task_id, event_seq)`` backs it up);
* a repeated delivery of the same event returns the existing record and only
  bumps ``ingestion_log.delivery_seq`` 鈥?it never creates a second row;
* a repeated event key with *different* content is a conflict: it is recorded
  as ``DENIED`` in the audit log and rejected;
* ``prev_hash``/``chain_hash`` form the hash chain; payload bytes are stored
  content-addressed so their hashes can be re-verified offline;
* every successful append writes one ``audit_log`` row in the same transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from researchflow.contracts.encoding import canonical_bytes, hash_payload
from researchflow.contracts.models import EvidenceRecord
from researchflow.evidence.chain import (
    GENESIS_PREV_HASH,
    ChainReport,
    chain_hash_for,
    verify_chain,
)
from researchflow.execution.executor import AttemptObservation
from researchflow.persistence.db import connect, format_utc, transaction, utc_now
from researchflow.persistence.repositories import (
    COLLECTOR_APPEND,
    EVIDENCE_WRITE,
    VERIFIER_AUDIT,
    VERIFIER_EVIDENCE,
    AuditRepository,
    EvidenceRepository,
    EvidenceRow,
)
from researchflow.persistence.records import IngestionRepository

__all__ = [
    "Collector",
    "EvidenceAppendResult",
    "EvidenceConflict",
    "payload_reader",
]

_NAMESPACE = uuid.UUID("6f1d9c1e-2a3b-4c5d-8e9f-0a1b2c3d4e5f")


class EvidenceConflict(RuntimeError):
    code = "CHAIN_CONTENT_CONFLICT"

    def __init__(self, evidence_id: str, detail: str) -> None:
        self.evidence_id = evidence_id
        self.code = "CHAIN_CONTENT_CONFLICT"
        super().__init__(f"{self.code}: {detail}")


@dataclass(frozen=True, slots=True)
class EvidenceAppendResult:
    evidence_id: str
    created: bool
    delivery_seq: int
    event_seq: int
    level: str
    kind: str
    chain_hash: str
    payload_hash: str


def _row_from_sql(row: sqlite3.Row) -> EvidenceRow:
    return EvidenceRow(
        evidence_id=str(row["evidence_id"]),
        task_id=str(row["task_id"]),
        node_id=str(row["node_id"]),
        attempt_id=str(row["attempt_id"]),
        event_seq=int(row["event_seq"]),
        level=str(row["level"]),
        kind=str(row["kind"]),
        producer=str(row["producer"]),
        timestamp=str(row["timestamp"]),
        payload_hash=str(row["payload_hash"]),
        artifact_refs=None if row["artifact_refs"] is None else str(row["artifact_refs"]),
        prev_hash=str(row["prev_hash"]),
        chain_hash=str(row["chain_hash"]),
    )


def payload_reader(task_root: str | Path, task_id: str) -> Callable[[str], bytes | None]:
    def _read(payload_hash: str) -> bytes | None:
        path = Path(task_root) / "tasks" / task_id / "evidence_payloads" / f"{payload_hash}.json"
        if not path.is_file():
            return None
        return path.read_bytes()

    return _read


class Collector:
    def __init__(
        self,
        db_path: str | Path,
        task_root: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root) if task_root else self._db_path.parent
        self._clock = clock or utc_now
        self._evidence = EvidenceRepository()
        self._audit = AuditRepository()
        self._ingestion = IngestionRepository()

    # ------------------------------------------------------------- payload store
    def payload_dir(self, task_id: str) -> Path:
        directory = self._task_root / "tasks" / task_id / "evidence_payloads"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def payload_path(self, task_id: str, payload_hash: str) -> Path:
        return self.payload_dir(task_id) / f"{payload_hash}.json"

    def _store_payload(self, task_id: str, payload: Mapping[str, Any]) -> tuple[str, bytes]:
        data = canonical_bytes(dict(payload))
        digest = hashlib.sha256(data).hexdigest()
        path = self.payload_path(task_id, digest)
        if path.is_file():
            if path.read_bytes() != data:
                raise EvidenceConflict(
                    digest, "payload store already holds different bytes for this hash"
                )
            return digest, data
        with path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return digest, data

    def payload_reader(self, task_id: str) -> Callable[[str], bytes | None]:
        return payload_reader(self._task_root, task_id)

    # -------------------------------------------------------------------- append
    def _append(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        level: str,
        kind: str,
        payload: Mapping[str, Any],
        artifact_refs: tuple[str, ...] = (),
        event_key: str,
        capability,
        actor: str,
    ) -> EvidenceAppendResult:
        payload_hash, _ = self._store_payload(task_id, payload)
        evidence_id = "ev_" + str(
            uuid.uuid5(_NAMESPACE, f"researchflow:{task_id}:{node_id}:{event_key}")
        )
        connection = connect(self._db_path)
        try:
            conflict: EvidenceRow | None = None
            result: EvidenceAppendResult | None = None
            with transaction(connection):
                existing = self._evidence.get(connection, evidence_id)
                if existing is not None:
                    if existing.payload_hash == payload_hash:
                        delivery = self._ingestion.next_delivery_seq(
                            connection, evidence_id
                        )
                        self._ingestion.append(
                            connection,
                            ingestion_id=uuid.uuid4().hex,
                            evidence_id=evidence_id,
                            delivery_seq=delivery,
                            received_at=format_utc(self._clock()),
                            capability=COLLECTOR_APPEND,
                        )
                        result = EvidenceAppendResult(
                            evidence_id=evidence_id,
                            created=False,
                            delivery_seq=delivery,
                            event_seq=existing.event_seq,
                            level=existing.level,
                            kind=existing.kind,
                            chain_hash=existing.chain_hash,
                            payload_hash=existing.payload_hash,
                        )
                    else:
                        conflict = existing
                else:
                    result = self._insert_new(
                        connection,
                        task_id=task_id,
                        node_id=node_id,
                        attempt_id=attempt_id,
                        level=level,
                        kind=kind,
                        payload_hash=payload_hash,
                        artifact_refs=artifact_refs,
                        evidence_id=evidence_id,
                        capability=capability,
                        actor=actor,
                    )
            if conflict is not None:
                with transaction(connection):
                    delivery = self._ingestion.next_delivery_seq(connection, evidence_id)
                    self._ingestion.append(
                        connection,
                        ingestion_id=uuid.uuid4().hex,
                        evidence_id=evidence_id,
                        delivery_seq=delivery,
                        received_at=format_utc(self._clock()),
                        capability=COLLECTOR_APPEND,
                    )
                    self._audit.append(
                        connection,
                        audit_id=uuid.uuid4().hex,
                        task_id=task_id,
                        node_id=node_id,
                        actor=actor,
                        action="EVIDENCE_APPENDED",
                        previous_state=None,
                        next_state=None,
                        reason_code=f"{level}:{kind}:CONFLICT",
                        rule_version="1.0",
                        correlation_id=attempt_id,
                        plan_id=None,
                        plan_hash=None,
                        result="DENIED",
                        error_code="CHAIN_CONTENT_CONFLICT",
                        created_at=format_utc(self._clock()),
                        capability=EVIDENCE_WRITE,
                    )
                raise EvidenceConflict(
                    evidence_id,
                    "same event key was delivered with different payload content",
                )
            assert result is not None
            return result
        finally:
            connection.close()

    def _insert_new(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        level: str,
        kind: str,
        payload_hash: str,
        artifact_refs: tuple[str, ...],
        evidence_id: str,
        capability,
        actor: str,
    ) -> EvidenceAppendResult:
        previous = connection.execute(
            "SELECT event_seq, chain_hash FROM evidence WHERE task_id = ? "
            "ORDER BY event_seq DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        event_seq = 1 if previous is None else int(previous["event_seq"]) + 1
        prev_hash = GENESIS_PREV_HASH if previous is None else str(previous["chain_hash"])
        timestamp = format_utc(self._clock())
        artifact_json = (
            json.dumps(list(artifact_refs), separators=(",", ":")) if artifact_refs else None
        )
        draft = EvidenceRow(
            evidence_id=evidence_id,
            task_id=task_id,
            node_id=node_id,
            attempt_id=attempt_id,
            event_seq=event_seq,
            level=level,
            kind=kind,
            producer="verifier" if level == "E3" else "collector",
            timestamp=timestamp,
            payload_hash=payload_hash,
            artifact_refs=artifact_json,
            prev_hash=prev_hash,
            chain_hash="",
        )
        chain_hash = chain_hash_for(draft)
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
            chain_hash=chain_hash,
        )
        EvidenceRecord.model_validate(
            {
                "schema_version": "1.0",
                "evidence_id": row.evidence_id,
                "task_id": row.task_id,
                "node_id": row.node_id,
                "attempt_id": row.attempt_id,
                "event_seq": row.event_seq,
                "level": row.level,
                "kind": row.kind,
                "producer": row.producer,
                "timestamp": row.timestamp,
                "payload_hash": row.payload_hash,
                "artifact_refs": list(artifact_refs) if artifact_refs else None,
                "prev_hash": row.prev_hash,
                "chain_hash": row.chain_hash,
            }
        )
        self._evidence.append(
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
            capability=capability,
        )
        self._ingestion.append(
            connection,
            ingestion_id=uuid.uuid4().hex,
            evidence_id=evidence_id,
            delivery_seq=1,
            received_at=timestamp,
            capability=COLLECTOR_APPEND,
        )
        self._audit.append(
            connection,
            audit_id=uuid.uuid4().hex,
            task_id=task_id,
            node_id=node_id,
            actor=actor,
            action="EVIDENCE_APPENDED",
            previous_state=None,
            next_state=None,
            reason_code=f"{level}:{kind}",
            rule_version="1.0",
            correlation_id=attempt_id,
            plan_id=None,
            plan_hash=None,
            result="OK",
            error_code=None,
            created_at=timestamp,
            capability=VERIFIER_AUDIT if level == "E3" else EVIDENCE_WRITE,
        )
        return EvidenceAppendResult(
            evidence_id=evidence_id,
            created=True,
            delivery_seq=1,
            event_seq=event_seq,
            level=level,
            kind=kind,
            chain_hash=chain_hash,
            payload_hash=payload_hash,
        )

    # ------------------------------------------------------------ E2 observation
    def record_observation(
        self, observation: AttemptObservation
    ) -> list[EvidenceAppendResult]:
        """Record E2 facts for one controlled attempt (launch 鈫?exit 鈫?artifacts)."""

        results: list[EvidenceAppendResult] = [
            self._append(
                task_id=observation.task_id,
                node_id=observation.node_id,
                attempt_id=observation.attempt_id,
                level="E2",
                kind="executor_launch",
                payload={
                    "event": "executor_launch",
                    "attempt_seq": observation.attempt_seq,
                    "template_id": observation.template_id,
                    "parameters_hash": observation.parameters_hash,
                    "command": list(observation.command),
                    "started_at": observation.started_at,
                    "inputs": list(observation.inputs),
                    "dataset_sha256": observation.dataset_sha256,
                    "env_fingerprint": observation.env_fingerprint,
                    "code_hash": observation.code_hash,
                },
                event_key=f"executor_launch:{observation.attempt_id}",
                capability=COLLECTOR_APPEND,
                actor="collector:record",
            ),
            self._append(
                task_id=observation.task_id,
                node_id=observation.node_id,
                attempt_id=observation.attempt_id,
                level="E2",
                kind="executor_process_exit",
                payload={
                    "event": "executor_process_exit",
                    "attempt_seq": observation.attempt_seq,
                    "status": observation.status,
                    "exit_code": observation.exit_code,
                    "timed_out": observation.timed_out,
                    "killed": observation.killed,
                    "memory_exceeded": observation.memory_exceeded,
                    "duration_sec": observation.duration_sec,
                    "peak_memory_mb": observation.peak_memory_mb,
                    "worker_pids": list(observation.worker_pids),
                    "kill_verified": observation.kill_verified,
                    "ended_at": observation.ended_at,
                    "dataset_sha256": observation.dataset_sha256,
                    "env_fingerprint": observation.env_fingerprint,
                    "code_hash": observation.code_hash,
                    "worker_error": observation.worker_error,
                    "template_id": observation.template_id,
                },
                event_key=f"executor_process_exit:{observation.attempt_id}",
                capability=COLLECTOR_APPEND,
                actor="collector:record",
            ),
        ]
        for artifact in observation.artifacts:
            reference = (
                f"artifact://{observation.task_id}/{observation.node_id}/"
                f"{observation.attempt_id}/{artifact.path}"
            )
            results.append(
                self._append(
                    task_id=observation.task_id,
                    node_id=observation.node_id,
                    attempt_id=observation.attempt_id,
                    level="E2",
                    kind="artifact_observed",
                    payload={
                        "event": "artifact_observed",
                        "attempt_seq": observation.attempt_seq,
                        "template_id": observation.template_id,
                        "artifact_path": artifact.path,
                        "sha256": artifact.sha256,
                        "size": artifact.size,
                    },
                    artifact_refs=(reference,),
                    event_key=f"artifact_observed:{observation.attempt_id}:{artifact.path}",
                    capability=COLLECTOR_APPEND,
                    actor="collector:record",
                )
            )
        return results

    # --------------------------------------------------------------- E0 / E1 / E3
    def record_claim(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        claim: str,
        basis: str = "",
    ) -> EvidenceAppendResult:
        return self._append(
            task_id=task_id,
            node_id=node_id,
            attempt_id=attempt_id,
            level="E0",
            kind="agent_claim",
            payload={"event": "agent_claim", "claim": claim, "basis": basis},
            event_key=(
                f"agent_claim:{attempt_id}:"
                f"{hash_payload({'claim': claim, 'basis': basis})}"
            ),
            capability=COLLECTOR_APPEND,
            actor="collector:claim",
        )

    def record_tool_invocation(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        tool: str,
        detail: Mapping[str, Any] | None = None,
    ) -> EvidenceAppendResult:
        payload = {"event": "tool_invocation", "tool": tool, "detail": dict(detail or {})}
        return self._append(
            task_id=task_id,
            node_id=node_id,
            attempt_id=attempt_id,
            level="E1",
            kind="tool_invocation",
            payload=payload,
            event_key=f"tool_invocation:{attempt_id}:{tool}:{hash_payload(payload)}",
            capability=COLLECTOR_APPEND,
            actor="collector:tool",
        )

    def append_verifier_recheck(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        payload: Mapping[str, Any],
    ) -> EvidenceAppendResult:
        body = {"event": "verifier_recheck", **dict(payload)}
        return self._append(
            task_id=task_id,
            node_id=node_id,
            attempt_id=attempt_id,
            level="E3",
            kind="verifier_recheck",
            payload=body,
            event_key=f"verifier_recheck:{attempt_id}:{hash_payload(body)}",
            capability=VERIFIER_EVIDENCE,
            actor="verifier:recheck",
        )

    # ------------------------------------------------------------------ read side
    def rows(self, task_id: str) -> list[EvidenceRow]:
        connection = connect(self._db_path)
        try:
            return [
                _row_from_sql(row)
                for row in connection.execute(
                    "SELECT * FROM evidence WHERE task_id = ? ORDER BY event_seq",
                    (task_id,),
                ).fetchall()
            ]
        finally:
            connection.close()

    def verify_chain(self, task_id: str) -> ChainReport:
        return verify_chain(self.rows(task_id), self.payload_reader(task_id))

    def env_fingerprint(self, task_id: str) -> str | None:
        connection = connect(self._db_path)
        try:
            row = connection.execute(
                "SELECT payload_hash FROM evidence WHERE task_id = ? "
                "AND level = 'E2' AND kind = 'executor_process_exit' "
                "ORDER BY event_seq DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        path = self.payload_path(task_id, str(row["payload_hash"]))
        if not path.is_file():
            return None
        payload = json.loads(path.read_bytes())
        value = payload.get("env_fingerprint")
        return None if value is None else str(value)
