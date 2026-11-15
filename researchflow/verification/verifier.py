"""Verification service: L1/L2/L3 → Gate → report → certificate (T0 WP-09/10/11).

Only an independent Verifier writes E3 evidence, VerificationReports and
CompletionCertificates.  A certificate is issued only when *all* of the frozen
conditions hold: report ``VERIFIED``, required coverage complete, L3 coverage at
the ruleset minimum, evidence chain valid and a real environment fingerprint
from the E2 records.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from researchflow.contracts.models import CompletionCertificate, VerificationReport
from researchflow.evidence.collector import Collector
from researchflow.execution.env import code_hash
from researchflow.gate.gate import Gate, GateResult
from researchflow.persistence.db import connect, format_utc, transaction, utc_now
from researchflow.persistence.records import (
    VERIFIER_WRITE,
    CertificateRecord,
    CertificateRepository,
    ReportRecord,
    ReportRepository,
    list_all_invalidations,
)
from researchflow.persistence.repositories import (
    VERIFIER_AUDIT,
    AuditRepository,
    EvidenceRepository,
)
from researchflow.rules import RULESET_HASH, load_ruleset
from researchflow.signing.keys import KeyStore
from researchflow.signing.merkle import evidence_record_bytes, merkle_root
from researchflow.signing.payloads import sign_certificate, sign_report
from researchflow.verification.context import VerificationContext, load_context
from researchflow.verification.l1 import L1Result, L1Verifier
from researchflow.verification.l2 import L2Result, L2Verifier
from researchflow.verification.l3 import L3Result, L3Verifier

__all__ = [
    "VerificationError",
    "VerificationOutcome",
    "VerificationService",
]

SCHEMA_VERSION = "1.0"

_VERIFY_LOCKS: dict[str, threading.Lock] = {}
_VERIFY_LOCKS_GUARD = threading.Lock()


def _lock_for(db_path: str) -> threading.Lock:
    with _VERIFY_LOCKS_GUARD:
        return _VERIFY_LOCKS.setdefault(db_path, threading.Lock())


class VerificationError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    task_id: str
    final_state: str
    report_id: str
    certificate_id: str | None
    report: dict[str, Any]
    certificate: dict[str, Any] | None
    gate: GateResult
    l1_status: str
    l2_status: str
    l3_status: str
    gaps: tuple[dict[str, Any], ...]
    l3: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "final_state": self.final_state,
            "report_id": self.report_id,
            "certificate_id": self.certificate_id,
            "report": self.report,
            "certificate": self.certificate,
            "gaps": list(self.gaps),
            "l1_status": self.l1_status,
            "l2_status": self.l2_status,
            "l3_status": self.l3_status,
            "gate": self.gate.to_dict(),
            "l3": self.l3,
        }


def _now() -> str:
    return format_utc(utc_now())


class VerificationService:
    def __init__(
        self,
        db_path: str | Path,
        task_root: str | Path,
        *,
        key_store: KeyStore | None = None,
        l3_verifier: L3Verifier | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root) if task_root else self._db_path.parent
        self._key_store = key_store or KeyStore(self._task_root / "keys")
        self._l3 = l3_verifier or L3Verifier(self._task_root)
        self._collector = Collector(self._db_path, self._task_root)
        self._gate = Gate(self._db_path, self._task_root)
        self._reports = ReportRepository()
        self._certificates = CertificateRepository()
        self._audit = AuditRepository()
        self._evidence = EvidenceRepository()

    # ------------------------------------------------------------------ helpers
    def _audit_row(
        self,
        *,
        task_id: str,
        action: str,
        reason_code: str,
        correlation_id: str,
        result: str = "OK",
        error_code: str | None = None,
        created_at: str | None = None,
    ) -> None:
        connection = connect(self._db_path)
        try:
            with transaction(connection):
                self._audit.append(
                    connection,
                    audit_id=uuid.uuid4().hex,
                    task_id=task_id,
                    node_id=None,
                    actor="verifier:sign",
                    action=action,
                    previous_state=None,
                    next_state=None,
                    reason_code=reason_code,
                    rule_version="1.0",
                    correlation_id=correlation_id,
                    plan_id=None,
                    plan_hash=None,
                    result=result,
                    error_code=error_code,
                    created_at=created_at or _now(),
                    capability=VERIFIER_AUDIT,
                )
        finally:
            connection.close()

    # -------------------------------------------------------------------- verify
    def verify(
        self,
        task_id: str,
        *,
        requested_checks: Sequence[str] = ("L1", "L2", "L3"),
    ) -> VerificationOutcome:
        """Verify a task, reusing an existing VERIFIED result when nothing changed.

        Re-verification of unchanged evidence must not sign a second report and
        certificate: the same request returns the existing VERIFIED outcome.  A
        process-level lock serialises concurrent verification of the same DB.
        """

        lock = _lock_for(str(self._db_path.resolve()))
        with lock:
            requested = {str(check) for check in requested_checks}
            if requested == {"L1", "L2", "L3"}:
                existing = self._existing_verified_outcome(task_id)
                if existing is not None:
                    return existing
            return self._verify_locked(task_id, requested_checks=requested_checks)

    def _certificate_document(self, record) -> dict[str, Any]:
        return {
            "schema_version": record.schema_version,
            "cert_id": record.cert_id,
            "report_id": record.report_id,
            "final_state": record.final_state,
            "merkle_root": record.merkle_root,
            "tree_size": record.tree_size,
            "ruleset_hash": record.ruleset_hash,
            "code_hash": record.code_hash,
            "env_fingerprint": record.env_fingerprint,
            "l3_coverage": record.l3_coverage,
            "skipped_nodes": list(record.skipped_nodes),
            "alg": record.alg,
            "key_id": record.key_id,
            "key_fingerprint": record.key_fingerprint,
            "signature": record.signature,
            "issued_at": record.issued_at,
        }

    def _existing_verified_outcome(self, task_id: str) -> VerificationOutcome | None:
        from researchflow.persistence.records import list_evidence
        from researchflow.persistence.repositories import NodeRepository

        connection = connect(self._db_path)
        try:
            report = self._reports.latest_for_task(connection, task_id)
            nodes = NodeRepository().list_for_task(connection, task_id)
            invalidations = list_all_invalidations(connection, task_id)
            rows = list_evidence(connection, task_id)
            certificate = (
                None
                if report is None
                else self._certificates.for_report(connection, report.report_id)
            )
        finally:
            connection.close()
        if report is None or report.final_state != "VERIFIED":
            return None
        if any(node.state == "INVALIDATED" for node in nodes):
            return None
        if any(row.created_at >= report.issued_at for row in invalidations):
            return None
        if merkle_root([evidence_record_bytes(row) for row in rows]) != report.evidence_root:
            return None
        gate = self._gate.evaluate(task_id)
        if not gate.passed:
            return None
        certificate_document = (
            None if certificate is None else self._certificate_document(certificate)
        )
        return VerificationOutcome(
            task_id=task_id,
            final_state=report.final_state,
            report_id=report.report_id,
            certificate_id=None if certificate is None else certificate.cert_id,
            report=dict(report.report_json),
            certificate=certificate_document,
            gate=gate,
            l1_status=report.l1_status,
            l2_status=report.l2_status,
            l3_status=report.l3_status,
            gaps=tuple(report.gaps),
            l3=None,
        )

    def _verify_locked(
        self,
        task_id: str,
        *,
        requested_checks: Sequence[str] = ("L1", "L2", "L3"),
    ) -> VerificationOutcome:
        requested = {str(check) for check in requested_checks}
        ctx = load_context(self._db_path, self._task_root, task_id)
        ruleset = load_ruleset()
        l1: L1Result = L1Verifier().run(ctx) if "L1" in requested else L1Result(
            status="NOT_RUN", issues=(), chain_ok=True, checks=0
        )
        l2: L2Result = L2Verifier().run(ctx) if "L2" in requested else L2Result(
            status="NOT_RUN", issues=(), metrics={}, recomputed={}, leakage={}
        )
        l3: L3Result | None = None
        l3_status = "SKIP"
        if "L3" in requested and l1.status == "PASS" and l2.status == "PASS":
            try:
                l3 = self._l3.run(ctx)
                l3_status = l3.status
            except Exception:  # noqa: BLE001 - recorded as a verification failure
                l3 = None
                l3_status = "FAIL"
        elif "L3" in requested:
            l3_status = "SKIP"

        if l3 is not None:
            for node_result in l3.nodes:
                self._collector.append_verifier_recheck(
                    task_id=task_id,
                    node_id=node_result.node_id,
                    attempt_id=f"attempt_{ctx.nodes[node_result.node_id].attempt_seq:02d}"
                    if node_result.node_id in ctx.nodes
                    else "attempt_01",
                    payload={
                        "node_id": node_result.node_id,
                        "l1_status": l1.status,
                        "l2_status": l2.status,
                        "l3_status": node_result.status,
                        "match_mode": node_result.match_mode,
                        "split_hash": node_result.split_hash,
                        "executor_split_hash": node_result.executor_split_hash,
                        "prediction_mismatches": node_result.prediction_mismatches,
                        "metric_deltas": [dict(delta) for delta in node_result.metric_deltas],
                        "l3_split_dir": node_result.l3_split_dir,
                        "l3_train_dir": node_result.l3_train_dir,
                        "split_pid": node_result.split_pid,
                        "train_pid": node_result.train_pid,
                    },
                )

        gate = self._gate.evaluate(task_id)
        gaps: list[dict[str, Any]] = [gap.to_dict() for gap in gate.gaps]
        for issue in (*l1.issues, *l2.issues):
            gaps.append(issue.to_dict())
        if l3 is not None:
            gaps.extend(issue.to_dict() for issue in l3.issues)

        minimum_coverage = float(ruleset.get("l3", {}).get("minimum_coverage", 1.0))
        statuses = (l1.status, l2.status, l3_status)
        if (
            gate.passed
            and all(status == "PASS" for status in statuses)
            and gate.missing == 0
            and gate.l3_coverage >= minimum_coverage
        ):
            final_state = "VERIFIED"
        elif any(status == "FAIL" for status in statuses):
            final_state = "FAILED"
        elif gate.missing > 0 or gate.gaps:
            final_state = "PARTIAL"
        else:
            final_state = "FAILED"

        key = self._key_store.load_or_create()
        report_id = f"report_{uuid.uuid4()}"
        issued_at = _now()
        coverage = {
            "required": gate.required,
            "passed": gate.passed_checks,
            "missing": gate.missing,
        }
        report_document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "report_id": report_id,
            "task_id": task_id,
            "final_state": final_state,
            "l1_status": l1.status,
            "l2_status": l2.status,
            "l3_status": l3_status,
            "required_check_coverage": coverage,
            "ruleset_hash": gate.ruleset_hash,
            "evidence_root": gate.evidence_root,
            "l3_coverage": gate.l3_coverage,
            "issued_at": issued_at,
            "key_id": key.key_id,
            "signature": "",
        }
        signed_report = sign_report(report_document, key.private_key)
        VerificationReport.model_validate(dict(signed_report))
        self._persist_report(
            report=signed_report,
            gaps=gaps,
            report_record=ReportRecord(
                report_id=report_id,
                schema_version=SCHEMA_VERSION,
                task_id=task_id,
                final_state=final_state,
                l1_status=l1.status,
                l2_status=l2.status,
                l3_status=l3_status,
                coverage_required=gate.required,
                coverage_passed=gate.passed_checks,
                coverage_missing=gate.missing,
                gaps=gaps,
                ruleset_hash=gate.ruleset_hash,
                evidence_root=gate.evidence_root,
                l3_coverage=gate.l3_coverage,
                issued_at=issued_at,
                key_id=key.key_id,
                signature=str(signed_report["signature"]),
                report_json=dict(signed_report),
            ),
        )
        self._audit_row(
            task_id=task_id,
            action="VERIFY_RUN",
            reason_code=f"L1={l1.status};L2={l2.status};L3={l3_status};final={final_state}",
            correlation_id=report_id,
            created_at=issued_at,
        )
        self._audit_row(
            task_id=task_id,
            action="REPORT_ISSUED",
            reason_code=f"final_state={final_state}",
            correlation_id=report_id,
            created_at=issued_at,
        )
        self._audit_row(
            task_id=task_id,
            action="SIGN",
            reason_code="report",
            correlation_id=report_id,
            created_at=issued_at,
        )

        certificate_document: dict[str, Any] | None = None
        certificate_id: str | None = None
        if final_state == "VERIFIED":
            certificate_document = self._issue_certificate(
                ctx=ctx, report=dict(signed_report), key=key, l3_coverage=gate.l3_coverage
            )
            certificate_id = str(certificate_document["cert_id"])

        return VerificationOutcome(
            task_id=task_id,
            final_state=final_state,
            report_id=report_id,
            certificate_id=certificate_id,
            report=dict(signed_report),
            certificate=certificate_document,
            gate=gate,
            l1_status=l1.status,
            l2_status=l2.status,
            l3_status=l3_status,
            gaps=tuple(gaps),
            l3=None if l3 is None else l3.to_dict(),
        )

    # ------------------------------------------------------------------ persist
    def _persist_report(
        self,
        *,
        report: Mapping[str, Any],
        gaps: Sequence[Mapping[str, Any]],
        report_record: ReportRecord,
    ) -> None:
        connection = connect(self._db_path)
        try:
            with transaction(connection):
                self._reports.apply(
                    connection, report=report_record, capability=VERIFIER_WRITE
                )
        finally:
            connection.close()

    def _issue_certificate(
        self,
        *,
        ctx: VerificationContext,
        report: Mapping[str, Any],
        key,
        l3_coverage: float,
    ) -> dict[str, Any]:
        chain = self._collector.verify_chain(ctx.task_id)
        if not chain.ok:
            raise VerificationError(
                "EVIDENCE_CHAIN_BROKEN",
                "refusing to issue a certificate for a broken evidence chain",
            )
        rows = self._collector.rows(ctx.task_id)
        env = self._collector.env_fingerprint(ctx.task_id)
        if env is None:
            raise VerificationError(
                "ENV_FINGERPRINT_MISSING",
                "no E2 environment fingerprint is available for the certificate",
            )
        issued_at = _now()
        if issued_at < str(report.get("issued_at", "")):
            raise VerificationError(
                "CERTIFICATE_INVALID",
                "certificate issued_at must not be earlier than the report issued_at",
            )
        certificate_document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "cert_id": f"cert_{uuid.uuid4()}",
            "report_id": report["report_id"],
            "final_state": "VERIFIED",
            "merkle_root": report["evidence_root"],
            "tree_size": len(rows),
            "ruleset_hash": report["ruleset_hash"],
            "code_hash": code_hash(),
            "env_fingerprint": env,
            "l3_coverage": l3_coverage,
            "skipped_nodes": [],
            "alg": "Ed25519",
            "key_id": key.key_id,
            "key_fingerprint": key.fingerprint,
            "issued_at": issued_at,
            "signature": "",
        }
        signed_certificate = sign_certificate(certificate_document, key.private_key)
        CompletionCertificate.model_validate(dict(signed_certificate))
        record = CertificateRecord(
            cert_id=str(signed_certificate["cert_id"]),
            schema_version=SCHEMA_VERSION,
            report_id=str(signed_certificate["report_id"]),
            final_state="VERIFIED",
            merkle_root=str(signed_certificate["merkle_root"]),
            tree_size=int(signed_certificate["tree_size"]),
            ruleset_hash=str(signed_certificate["ruleset_hash"]),
            code_hash=str(signed_certificate["code_hash"]),
            env_fingerprint=str(signed_certificate["env_fingerprint"]),
            l3_coverage=float(signed_certificate["l3_coverage"]),
            skipped_nodes=[],
            alg="Ed25519",
            key_id=str(signed_certificate["key_id"]),
            key_fingerprint=str(signed_certificate["key_fingerprint"]),
            signature=str(signed_certificate["signature"]),
            issued_at=issued_at,
        )
        connection = connect(self._db_path)
        try:
            with transaction(connection):
                self._certificates.apply(
                    connection, certificate=record, capability=VERIFIER_WRITE
                )
        finally:
            connection.close()
        self._audit_row(
            task_id=ctx.task_id,
            action="CERTIFICATE_ISSUED",
            reason_code="final_state=VERIFIED",
            correlation_id=str(signed_certificate["cert_id"]),
            created_at=issued_at,
        )
        self._audit_row(
            task_id=ctx.task_id,
            action="SIGN",
            reason_code="certificate",
            correlation_id=str(signed_certificate["cert_id"]),
            created_at=issued_at,
        )
        return dict(signed_certificate)