"""Read-only fact ports used by the WP-03 state machine.

Ports that depend on later work packages (Gate, Report, Certificate, graph,
executor attempts, recovery) deliberately fail closed instead of inventing
facts.  Tests may inject small fake implementations for state-machine tests;
the production API does not expose transitions in WP-03.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from researchflow.persistence.db import connect

__all__ = [
    "CertificateFacts",
    "CertificateFactsPort",
    "ClockLike",
    "EvidenceFacts",
    "EvidenceFactsPort",
    "FilePlanStore",
    "GateFacts",
    "GateFactsPort",
    "GraphFacts",
    "GraphFactsPort",
    "NodeFacts",
    "NodeFactsPort",
    "PlanFileMissing",
    "PlanStorePort",
    "Ports",
    "ReportFacts",
    "ReportFactsPort",
    "SqliteEvidenceFacts",
    "SqliteTaskFacts",
    "TaskFacts",
    "TaskFactsPort",
    "UnsafePlanPath",
]


class ClockLike(Protocol):
    def now(self) -> datetime: ...


class GraphFactsPort(Protocol):
    def dag_valid(self, task_id: str, graph_version: int) -> bool: ...
    def blocking_gap(self, task_id: str, failure_ref: str) -> bool: ...


class TaskFactsPort(Protocol):
    def has_ready_node(self, task_id: str) -> bool: ...
    def execution_finished(self, task_id: str) -> bool: ...
    def all_required_nodes_verified(self, task_id: str) -> bool: ...


class NodeFactsPort(Protocol):
    def dependencies_satisfied(self, task_id: str, node_id: str) -> bool: ...
    def resources_available(self, task_id: str, node_id: str) -> bool: ...
    def attempt_end(
        self, task_id: str, node_id: str, attempt_id: str
    ) -> AttemptEnd: ...
    def recovery_budget_available(
        self, task_id: str, node_id: str, recovery_ref: str
    ) -> bool: ...
    def diagnosis_valid(
        self, task_id: str, node_id: str, diagnosis_ref: str
    ) -> bool: ...
    def recovery_rechecked(
        self, task_id: str, node_id: str, recheck_ref: str
    ) -> bool: ...


class GateFactsPort(Protocol):
    def get(self, task_id: str, node_id: str) -> GateFacts: ...


class ReportFactsPort(Protocol):
    def get(self, task_id: str) -> ReportFacts: ...


class CertificateFactsPort(Protocol):
    def get(self, task_id: str) -> CertificateFacts: ...


class EvidenceFactsPort(Protocol):
    def get(self, evidence_id: str) -> EvidenceFacts | None: ...
    def count(self, task_id: str) -> int: ...
    def is_invalidated(self, evidence_id: str) -> bool: ...
    def verify_chain(self, task_id: str) -> bool: ...
    def env_fingerprint(self, task_id: str) -> str | None: ...


class PlanStorePort(Protocol):
    def resolve(self, plan_hash: str) -> Path: ...
    def read_bytes(self, path: Path) -> bytes: ...


@dataclass(frozen=True, slots=True)
class GraphFacts:
    dag_valid: bool
    graph_version: int | None = None
    blocking_gap: bool = False


@dataclass(frozen=True, slots=True)
class TaskFacts:
    has_ready_node: bool
    execution_finished: bool
    all_required_nodes_verified: bool


@dataclass(frozen=True, slots=True)
class AttemptEnd:
    ended: bool
    exit_code: int | None = None
    payload_readable: bool = True


@dataclass(frozen=True, slots=True)
class GateFacts:
    passed: bool
    ruleset_hash: str = ""


@dataclass(frozen=True, slots=True)
class ReportFacts:
    final_state: str
    report_id: str = ""
    ruleset_hash: str = ""
    evidence_root: str = ""
    signature_valid: bool = True


@dataclass(frozen=True, slots=True)
class CertificateFacts:
    report_id: str = ""
    final_state: str = "VERIFIED"
    merkle_root: str = ""
    tree_size: int = 0
    ruleset_hash: str = ""
    env_fingerprint: str = ""
    signature_valid: bool = True
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceFacts:
    evidence_id: str
    task_id: str
    node_id: str
    level: str
    kind: str
    producer: str
    event_seq: int


class UnsafePlanPath(RuntimeError):
    pass


class PlanFileMissing(RuntimeError):
    pass


class FilePlanStore:
    """Read-only content-addressed plan store.

    The plan file name is the SHA-256 of its bytes.  ``resolve`` rejects
    traversal, absolute paths and symlink escapes.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def resolve(self, plan_hash: str) -> Path:
        if not isinstance(plan_hash, str) or len(plan_hash) != 64:
            raise UnsafePlanPath("plan_hash must be 64 lowercase hex characters")
        if any(ch not in "0123456789abcdef" for ch in plan_hash):
            raise UnsafePlanPath("plan_hash must be 64 lowercase hex characters")
        candidate = (self._root / f"{plan_hash}.json").resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise UnsafePlanPath("plan path escapes plan store root")
        if not candidate.is_file():
            raise PlanFileMissing(f"plan file not found: {plan_hash}")
        return candidate

    def read_bytes(self, path: Path) -> bytes:
        return Path(path).read_bytes()


@dataclass(frozen=True, slots=True)
class Ports:
    graph: GraphFactsPort | None = None
    task: TaskFactsPort | None = None
    node: NodeFactsPort | None = None
    gate: GateFactsPort | None = None
    report: ReportFactsPort | None = None
    certificate: CertificateFactsPort | None = None
    evidence: EvidenceFactsPort | None = None
    plans: PlanStorePort | None = None
    clock: ClockLike | None = None


class SqliteTaskFacts:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    def _states(self, task_id: str) -> list[str]:
        connection = connect(self._db_path)
        try:
            rows = connection.execute(
                "SELECT state FROM nodes WHERE task_id = ?", (task_id,)
            ).fetchall()
            return [str(row["state"]) for row in rows]
        finally:
            connection.close()

    def has_ready_node(self, task_id: str) -> bool:
        return "READY" in self._states(task_id)

    def execution_finished(self, task_id: str) -> bool:
        states = self._states(task_id)
        if not states:
            return False
        return not any(state in {"PLANNED", "READY", "RUNNING"} for state in states)

    def all_required_nodes_verified(self, task_id: str) -> bool:
        states = self._states(task_id)
        return bool(states) and all(state == "VERIFIED" for state in states)


class SqliteEvidenceFacts:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    def get(self, evidence_id: str) -> EvidenceFacts | None:
        connection = connect(self._db_path)
        try:
            row = connection.execute(
                "SELECT evidence_id, task_id, node_id, level, kind, producer, event_seq "
                "FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return EvidenceFacts(
            evidence_id=str(row["evidence_id"]),
            task_id=str(row["task_id"]),
            node_id=str(row["node_id"]),
            level=str(row["level"]),
            kind=str(row["kind"]),
            producer=str(row["producer"]),
            event_seq=int(row["event_seq"]),
        )

    def count(self, task_id: str) -> int:
        connection = connect(self._db_path)
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM evidence WHERE task_id = ?", (task_id,)
            ).fetchone()
            return int(row["n"])
        finally:
            connection.close()

    def is_invalidated(self, evidence_id: str) -> bool:
        connection = connect(self._db_path)
        try:
            row = connection.execute(
                "SELECT 1 FROM evidence_invalidations WHERE evidence_id = ? LIMIT 1",
                (evidence_id,),
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def verify_chain(self, task_id: str) -> object:
        raise NotImplementedError("evidence chain verification belongs to WP-07")

    def env_fingerprint(self, task_id: str) -> str | None:
        # WP-03 does not persist env fingerprints yet; fail closed by omission.
        return None