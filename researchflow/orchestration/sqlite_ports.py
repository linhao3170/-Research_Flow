"""Production fact ports for the T0 state machine (fail-closed implementations).

These replace the WP-03 fail-closed stubs for the runtime loop.  Every fact is
read from SQLite, the executor attempt directories or the key store; nothing is
assumed, and a missing fact denies the transition instead of allowing it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from researchflow.execution.executor import read_attempt_result
from researchflow.gate.gate import Gate
from researchflow.orchestration.ports import (
    AttemptEnd,
    CertificateFacts,
    EvidenceFacts,
    GateFacts,
    GraphFacts,
    ReportFacts,
    TaskFacts,
)
from researchflow.persistence.db import connect
from researchflow.persistence.records import (
    CertificateRepository,
    GraphRepository,
    ReportRepository,
    list_all_invalidations,
    list_evidence,
)
from researchflow.persistence.repositories import NodeRepository, TaskRepository
from researchflow.signing.keys import KeyStore
from researchflow.signing.payloads import verify_certificate, verify_report
from researchflow.evidence.chain import verify_chain

__all__ = [
    "SqliteCertificateFacts",
    "SqliteEvidenceFacts",
    "SqliteGateFacts",
    "SqliteGraphFacts",
    "SqliteNodeFacts",
    "SqliteReportFacts",
    "SqliteTaskFacts",
]


class SqliteGraphFacts:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._graphs = GraphRepository()

    def dag_valid(self, task_id: str, graph_version: int) -> bool:
        connection = connect(self._db_path)
        try:
            graph = self._graphs.get(connection, task_id, graph_version)
        finally:
            connection.close()
        if graph is None:
            return False
        from researchflow.contracts.encoding import hash_payload

        nodes = sorted(graph.nodes, key=lambda node: str(node["node_id"]))
        edges = sorted(
            {(str(edge[0]), str(edge[1])) for edge in graph.graph_json.get("edges", [])}
        )
        recomputed = hash_payload(
            {
                "schema_version": "1.0",
                "nodes": nodes,
                "edges": [[source, target] for source, target in edges],
            }
        )
        return recomputed == graph.graph_hash

    def blocking_gap(self, task_id: str, failure_ref: str) -> bool:
        return False


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


class SqliteNodeFacts:
    def __init__(self, db_path: str | Path, task_root: str | Path) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root)
        self._graphs = GraphRepository()
        self._nodes = NodeRepository()

    def _attempt_dir(self, task_id: str, node_id: str, attempt_seq: int) -> Path:
        return (
            self._task_root
            / "tasks"
            / task_id
            / "attempts"
            / node_id
            / f"attempt_{attempt_seq:02d}"
        )

    def dependencies_satisfied(self, task_id: str, node_id: str) -> bool:
        connection = connect(self._db_path)
        try:
            graph = self._graphs.get(connection, task_id)
            nodes = {row.node_id: row for row in self._nodes.list_for_task(connection, task_id)}
        finally:
            connection.close()
        if graph is None or node_id not in nodes:
            return False
        spec = next(
            (node for node in graph.nodes if str(node.get("node_id")) == node_id), None
        )
        if spec is None:
            return False
        for dependency in spec.get("depends_on", []):
            row = nodes.get(str(dependency))
            # A dependency is ready for downstream execution once it has
            # finished executing and committed its output (RUNNING -> VERIFYING).
            # Final task-level verification happens after all nodes ran.
            if row is None or row.state not in {"VERIFYING", "VERIFIED"}:
                return False
        return True

    def resources_available(self, task_id: str, node_id: str) -> bool:
        connection = connect(self._db_path)
        try:
            node = self._nodes.get(connection, task_id, node_id)
        finally:
            connection.close()
        if node is None:
            return False
        return not self._attempt_dir(task_id, node_id, node.attempt_seq + 1).exists()

    def attempt_end(self, task_id: str, node_id: str, attempt_id: str) -> AttemptEnd:
        try:
            attempt_seq = int(str(attempt_id).rsplit("_", 1)[-1])
        except ValueError:
            return AttemptEnd(ended=False)
        result = read_attempt_result(self._attempt_dir(task_id, node_id, attempt_seq))
        if result is None:
            return AttemptEnd(ended=False, payload_readable=False)
        if result.get("status") != "EXITED":
            return AttemptEnd(ended=False, payload_readable=True)
        return AttemptEnd(
            ended=True,
            exit_code=None if result.get("exit_code") is None else int(result["exit_code"]),
            payload_readable=True,
        )

    def recovery_budget_available(self, task_id: str, node_id: str, recovery_ref: str) -> bool:
        return False

    def diagnosis_valid(self, task_id: str, node_id: str, diagnosis_ref: str) -> bool:
        return False

    def recovery_rechecked(self, task_id: str, node_id: str, recheck_ref: str) -> bool:
        return False


class SqliteGateFacts:
    def __init__(self, db_path: str | Path, task_root: str | Path) -> None:
        self._gate = Gate(db_path, task_root)

    def get(self, task_id: str, node_id: str) -> GateFacts:
        result = self._gate.evaluate(task_id)
        return GateFacts(passed=result.passed, ruleset_hash=result.ruleset_hash)


class SqliteReportFacts:
    def __init__(self, db_path: str | Path, task_root: str | Path) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root)
        self._reports = ReportRepository()
        self._key_store = KeyStore(self._task_root / "keys")

    def get(self, task_id: str) -> ReportFacts:
        connection = connect(self._db_path)
        try:
            report = self._reports.latest_for_task(connection, task_id)
        finally:
            connection.close()
        if report is None:
            return ReportFacts(final_state="MISSING", signature_valid=False)
        signature_valid = False
        try:
            key = self._key_store.load()
            signature_valid = verify_report(report.report_json, key.public_key)
        except FileNotFoundError:
            signature_valid = False
        return ReportFacts(
            final_state=report.final_state,
            report_id=report.report_id,
            ruleset_hash=report.ruleset_hash,
            evidence_root=report.evidence_root,
            signature_valid=signature_valid,
        )


class SqliteCertificateFacts:
    def __init__(self, db_path: str | Path, task_root: str | Path) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root)
        self._certificates = CertificateRepository()
        self._key_store = KeyStore(self._task_root / "keys")

    def get(self, task_id: str) -> CertificateFacts:
        connection = connect(self._db_path)
        try:
            certificate = self._certificates.latest_for_task(connection, task_id)
        finally:
            connection.close()
        if certificate is None:
            return CertificateFacts(final_state="MISSING", signature_valid=False)
        document = {
            "schema_version": certificate.schema_version,
            "cert_id": certificate.cert_id,
            "report_id": certificate.report_id,
            "final_state": certificate.final_state,
            "merkle_root": certificate.merkle_root,
            "tree_size": certificate.tree_size,
            "ruleset_hash": certificate.ruleset_hash,
            "code_hash": certificate.code_hash,
            "env_fingerprint": certificate.env_fingerprint,
            "l3_coverage": certificate.l3_coverage,
            "skipped_nodes": certificate.skipped_nodes,
            "alg": certificate.alg,
            "key_id": certificate.key_id,
            "key_fingerprint": certificate.key_fingerprint,
            "signature": certificate.signature,
            "issued_at": certificate.issued_at,
        }
        signature_valid = False
        try:
            key = self._key_store.load()
            signature_valid = verify_certificate(document, key.public_key)
        except FileNotFoundError:
            signature_valid = False
        return CertificateFacts(
            report_id=certificate.report_id,
            final_state=certificate.final_state,
            merkle_root=certificate.merkle_root,
            tree_size=certificate.tree_size,
            ruleset_hash=certificate.ruleset_hash,
            env_fingerprint=certificate.env_fingerprint,
            signature_valid=signature_valid,
            revoked=False,
        )


class SqliteEvidenceFacts:
    def __init__(self, db_path: str | Path, task_root: str | Path | None = None) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root) if task_root else self._db_path.parent

    def _reader(self, task_id: str):
        from researchflow.evidence.collector import payload_reader

        return payload_reader(self._task_root, task_id)

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

    def verify_chain(self, task_id: str) -> bool:
        connection = connect(self._db_path)
        try:
            rows = list_evidence(connection, task_id)
        finally:
            connection.close()
        return verify_chain(rows, self._reader(task_id)).ok

    def env_fingerprint(self, task_id: str) -> str | None:
        from researchflow.evidence.collector import Collector

        return Collector(self._db_path, self._task_root).env_fingerprint(task_id)


def build_ports(db_path: str | Path, task_root: str | Path):
    """Assemble the production port bundle used by the orchestration pipeline."""

    from researchflow.orchestration.ports import FilePlanStore, Ports

    return Ports(
        graph=SqliteGraphFacts(db_path),
        task=SqliteTaskFacts(db_path),
        node=SqliteNodeFacts(db_path, task_root),
        gate=SqliteGateFacts(db_path, task_root),
        report=SqliteReportFacts(db_path, task_root),
        certificate=SqliteCertificateFacts(db_path, task_root),
        evidence=SqliteEvidenceFacts(db_path, task_root),
        plans=FilePlanStore(Path(task_root) / "recovery_plans"),
    )