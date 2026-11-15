"""Read models and append-only repositories for the T0 evidence loop.

Every write needs an explicit capability object, mirroring WP-03's repository
style.  The capability is not a security boundary; it keeps a second public
write path from appearing by accident.

Tables are append-only: ``graph_versions``, ``reports``, ``certificates`` and
``ingestion_log`` all have ``BEFORE UPDATE``/``BEFORE DELETE`` triggers created
by migration ``0002``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from researchflow.persistence.repositories import (
    COLLECTOR_APPEND,
    Capability,
    DirectStateWriteDenied,
    EvidenceRow,
    InvalidationRow,
)

__all__ = [
    "CertificateRecord",
    "CertificateRepository",
    "GRAPH_REGISTRATION",
    "GraphRecord",
    "GraphRepository",
    "IngestionRepository",
    "ReportRecord",
    "ReportRepository",
    "VERIFIER_WRITE",
    "list_all_invalidations",
    "list_evidence",
    "node_specs",
    "task_spec_dict",
]

GRAPH_REGISTRATION = Capability("GRAPH_REGISTRATION")
VERIFIER_WRITE = Capability("VERIFIER_WRITE")


def _require(capability: Capability, expected: Capability, operation: str) -> None:
    if capability is not expected:
        raise DirectStateWriteDenied(operation)


@dataclass(frozen=True, slots=True)
class GraphRecord:
    task_id: str
    graph_version: int
    graph_hash: str
    topology_order: tuple[str, ...]
    graph_json: dict[str, Any]
    created_at: str

    @property
    def nodes(self) -> list[dict[str, Any]]:
        value = self.graph_json.get("nodes", [])
        return [dict(item) for item in value]


@dataclass(frozen=True, slots=True)
class ReportRecord:
    report_id: str
    schema_version: str
    task_id: str
    final_state: str
    l1_status: str
    l2_status: str
    l3_status: str
    coverage_required: int
    coverage_passed: int
    coverage_missing: int
    gaps: list[dict[str, Any]]
    ruleset_hash: str
    evidence_root: str
    l3_coverage: float
    issued_at: str
    key_id: str
    signature: str
    report_json: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CertificateRecord:
    cert_id: str
    schema_version: str
    report_id: str
    final_state: str
    merkle_root: str
    tree_size: int
    ruleset_hash: str
    code_hash: str
    env_fingerprint: str
    l3_coverage: float
    skipped_nodes: list[str]
    alg: str
    key_id: str
    key_fingerprint: str
    signature: str
    issued_at: str


class GraphRepository:
    def get(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        graph_version: int | None = None,
    ) -> GraphRecord | None:
        if graph_version is None:
            row = connection.execute(
                "SELECT * FROM graph_versions WHERE task_id = ? "
                "ORDER BY graph_version DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM graph_versions WHERE task_id = ? AND graph_version = ?",
                (task_id, graph_version),
            ).fetchone()
        if row is None:
            return None
        return GraphRecord(
            task_id=str(row["task_id"]),
            graph_version=int(row["graph_version"]),
            graph_hash=str(row["graph_hash"]),
            topology_order=tuple(json.loads(row["topology_order"])),
            graph_json=json.loads(row["graph_json"]),
            created_at=str(row["created_at"]),
        )

    def register(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        graph_version: int,
        graph_hash: str,
        topology_order: Iterable[str],
        graph_json: dict[str, Any],
        created_at: str,
        capability: Capability,
    ) -> None:
        _require(capability, GRAPH_REGISTRATION, "graph_register")
        connection.execute(
            "INSERT INTO graph_versions(task_id, graph_version, graph_hash, "
            "topology_order, graph_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                task_id,
                graph_version,
                graph_hash,
                json.dumps(list(topology_order), separators=(",", ":")),
                json.dumps(graph_json, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                created_at,
            ),
        )


class ReportRepository:
    def get(
        self, connection: sqlite3.Connection, report_id: str
    ) -> ReportRecord | None:
        row = connection.execute(
            "SELECT * FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        return None if row is None else _report_from_row(row)

    def latest_for_task(
        self, connection: sqlite3.Connection, task_id: str
    ) -> ReportRecord | None:
        row = connection.execute(
            "SELECT * FROM reports WHERE task_id = ? ORDER BY issued_at DESC, rowid DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return None if row is None else _report_from_row(row)

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        report: ReportRecord,
        capability: Capability,
    ) -> None:
        _require(capability, VERIFIER_WRITE, "report_append")
        connection.execute(
            "INSERT INTO reports(report_id, schema_version, task_id, final_state, "
            "l1_status, l2_status, l3_status, coverage_required, coverage_passed, "
            "coverage_missing, gaps_json, ruleset_hash, evidence_root, l3_coverage, "
            "issued_at, key_id, signature, report_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.report_id,
                report.schema_version,
                report.task_id,
                report.final_state,
                report.l1_status,
                report.l2_status,
                report.l3_status,
                report.coverage_required,
                report.coverage_passed,
                report.coverage_missing,
                json.dumps(report.gaps, ensure_ascii=False, separators=(",", ":")),
                report.ruleset_hash,
                report.evidence_root,
                report.l3_coverage,
                report.issued_at,
                report.key_id,
                report.signature,
                json.dumps(
                    report.report_json,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ),
        )


class CertificateRepository:
    def get(
        self, connection: sqlite3.Connection, cert_id: str
    ) -> CertificateRecord | None:
        row = connection.execute(
            "SELECT * FROM certificates WHERE cert_id = ?", (cert_id,)
        ).fetchone()
        return None if row is None else _certificate_from_row(row)

    def latest_for_task(
        self, connection: sqlite3.Connection, task_id: str
    ) -> CertificateRecord | None:
        row = connection.execute(
            "SELECT c.* FROM certificates c JOIN reports r ON r.report_id = c.report_id "
            "WHERE r.task_id = ? ORDER BY c.issued_at DESC, c.rowid DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return None if row is None else _certificate_from_row(row)

    def for_report(
        self, connection: sqlite3.Connection, report_id: str
    ) -> CertificateRecord | None:
        row = connection.execute(
            "SELECT * FROM certificates WHERE report_id = ?", (report_id,)
        ).fetchone()
        return None if row is None else _certificate_from_row(row)

    def apply(
        self,
        connection: sqlite3.Connection,
        *,
        certificate: CertificateRecord,
        capability: Capability,
    ) -> None:
        _require(capability, VERIFIER_WRITE, "certificate_append")
        connection.execute(
            "INSERT INTO certificates(cert_id, schema_version, report_id, final_state, "
            "merkle_root, tree_size, ruleset_hash, code_hash, env_fingerprint, "
            "l3_coverage, skipped_nodes, alg, key_id, key_fingerprint, signature, "
            "issued_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                certificate.cert_id,
                certificate.schema_version,
                certificate.report_id,
                certificate.final_state,
                certificate.merkle_root,
                certificate.tree_size,
                certificate.ruleset_hash,
                certificate.code_hash,
                certificate.env_fingerprint,
                certificate.l3_coverage,
                json.dumps(list(certificate.skipped_nodes), separators=(",", ":")),
                certificate.alg,
                certificate.key_id,
                certificate.key_fingerprint,
                certificate.signature,
                certificate.issued_at,
            ),
        )


class IngestionRepository:
    def next_delivery_seq(
        self, connection: sqlite3.Connection, evidence_id: str
    ) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(delivery_seq), 0) AS n FROM ingestion_log "
            "WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        return int(row["n"]) + 1

    def append(
        self,
        connection: sqlite3.Connection,
        *,
        ingestion_id: str,
        evidence_id: str,
        delivery_seq: int,
        received_at: str,
        capability: Capability,
    ) -> None:
        _require(capability, COLLECTOR_APPEND, "ingestion_append")
        connection.execute(
            "INSERT INTO ingestion_log(ingestion_id, evidence_id, delivery_seq, "
            "received_at) VALUES (?, ?, ?, ?)",
            (ingestion_id, evidence_id, delivery_seq, received_at),
        )


def _report_from_row(row: sqlite3.Row) -> ReportRecord:
    return ReportRecord(
        report_id=str(row["report_id"]),
        schema_version=str(row["schema_version"]),
        task_id=str(row["task_id"]),
        final_state=str(row["final_state"]),
        l1_status=str(row["l1_status"]),
        l2_status=str(row["l2_status"]),
        l3_status=str(row["l3_status"]),
        coverage_required=int(row["coverage_required"]),
        coverage_passed=int(row["coverage_passed"]),
        coverage_missing=int(row["coverage_missing"]),
        gaps=list(json.loads(row["gaps_json"])),
        ruleset_hash=str(row["ruleset_hash"]),
        evidence_root=str(row["evidence_root"]),
        l3_coverage=float(row["l3_coverage"]),
        issued_at=str(row["issued_at"]),
        key_id=str(row["key_id"]),
        signature=str(row["signature"]),
        report_json=json.loads(row["report_json"]),
    )


def _certificate_from_row(row: sqlite3.Row) -> CertificateRecord:
    return CertificateRecord(
        cert_id=str(row["cert_id"]),
        schema_version=str(row["schema_version"]),
        report_id=str(row["report_id"]),
        final_state=str(row["final_state"]),
        merkle_root=str(row["merkle_root"]),
        tree_size=int(row["tree_size"]),
        ruleset_hash=str(row["ruleset_hash"]),
        code_hash=str(row["code_hash"]),
        env_fingerprint=str(row["env_fingerprint"]),
        l3_coverage=float(row["l3_coverage"]),
        skipped_nodes=list(json.loads(row["skipped_nodes"])),
        alg=str(row["alg"]),
        key_id=str(row["key_id"]),
        key_fingerprint=str(row["key_fingerprint"]),
        signature=str(row["signature"]),
        issued_at=str(row["issued_at"]),
    )


# ------------------------------------------------------------------ read helpers
def list_evidence(connection: sqlite3.Connection, task_id: str) -> list[EvidenceRow]:
    rows = connection.execute(
        "SELECT * FROM evidence WHERE task_id = ? ORDER BY event_seq", (task_id,)
    ).fetchall()
    return [
        EvidenceRow(
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
        for row in rows
    ]


def list_all_invalidations(
    connection: sqlite3.Connection, task_id: str
) -> list[InvalidationRow]:
    rows = connection.execute(
        "SELECT * FROM evidence_invalidations WHERE task_id = ? "
        "ORDER BY created_at, invalidation_id",
        (task_id,),
    ).fetchall()
    return [
        InvalidationRow(
            invalidation_id=str(row["invalidation_id"]),
            task_id=str(row["task_id"]),
            node_id=str(row["node_id"]),
            evidence_id=str(row["evidence_id"]),
            reason_code=str(row["reason_code"]),
            cause_type=str(row["cause_type"]),
            cause_ref=None if row["cause_ref"] is None else str(row["cause_ref"]),
            plan_id=None if row["plan_id"] is None else str(row["plan_id"]),
            plan_hash=None if row["plan_hash"] is None else str(row["plan_hash"]),
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]


def task_spec_dict(connection: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT task_spec_json FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    return None if row is None else json.loads(str(row["task_spec_json"]))


def node_specs(graph: GraphRecord) -> list[dict[str, Any]]:
    return graph.nodes