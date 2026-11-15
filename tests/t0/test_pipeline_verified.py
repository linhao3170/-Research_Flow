"""End-to-end pipeline tests for report/certificate issuance (T0 WP-09–11)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from researchflow.evidence import Collector
from researchflow.persistence.db import connect
from researchflow.persistence.records import (
    CertificateRepository,
    ReportRepository,
    list_evidence,
)
from researchflow.signing import KeyStore, merkle_root, verify_certificate, verify_report
from researchflow.signing.merkle import evidence_record_bytes
from researchflow.verification import VerificationService
from support import make_world


@pytest.fixture()
def verified(tmp_path: Path):
    world = make_world(tmp_path)
    result = world["pipeline"].run_task(world["task_id"])
    assert result["ok"] is True, result
    world["result"] = result
    return world


def _load_certificate(db_path: Path, task_id: str):
    connection = connect(db_path)
    try:
        return CertificateRepository().latest_for_task(connection, task_id)
    finally:
        connection.close()


def _load_report(db_path: Path, task_id: str):
    connection = connect(db_path)
    try:
        return ReportRepository().latest_for_task(connection, task_id)
    finally:
        connection.close()


def test_verified_task_has_signed_report_and_certificate(verified) -> None:
    db_path = verified["db_path"]
    task_id = verified["task_id"]
    key = KeyStore(verified["root"] / "keys").load()

    report = _load_report(db_path, task_id)
    assert report is not None
    assert report.final_state == "VERIFIED"
    assert report.coverage_required == 5
    assert report.coverage_passed == 5
    assert report.coverage_missing == 0
    assert report.l3_coverage == 1.0
    assert verify_report(report.report_json, key.public_key) is True

    certificate = _load_certificate(db_path, task_id)
    assert certificate is not None
    assert certificate.report_id == report.report_id
    assert certificate.final_state == "VERIFIED"
    assert certificate.key_fingerprint == key.fingerprint
    assert certificate.skipped_nodes == []
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
    assert verify_certificate(document, key.public_key) is True

    connection = connect(db_path)
    try:
        rows = list_evidence(connection, task_id)
    finally:
        connection.close()
    assert certificate.merkle_root == report.evidence_root
    assert certificate.merkle_root == merkle_root([evidence_record_bytes(row) for row in rows])
    assert certificate.tree_size == len(rows)

    collector = Collector(db_path, verified["root"])
    assert certificate.env_fingerprint == collector.env_fingerprint(task_id)


def test_final_task_and_node_states_are_terminal(verified) -> None:
    connection = connect(verified["db_path"])
    try:
        task_state = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (verified["task_id"],)
        ).fetchone()["state"]
        node_states = {
            row["node_id"]: row["state"]
            for row in connection.execute(
                "SELECT node_id, state FROM nodes WHERE task_id = ?",
                (verified["task_id"],),
            )
        }
        actions = {
            row["action"]
            for row in connection.execute(
                "SELECT action FROM audit_log WHERE task_id = ?",
                (verified["task_id"],),
            )
        }
    finally:
        connection.close()
    assert task_state == "COMPLETED"
    assert set(node_states.values()) == {"VERIFIED"}
    assert {"REPORT_ISSUED", "CERTIFICATE_ISSUED", "SIGN", "VERIFY_RUN"} <= actions


def test_verify_twice_does_not_issue_duplicate_certificates(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    execution = world["pipeline"].execute(world["task_id"])
    assert execution.ok is True
    service = VerificationService(world["db_path"], world["root"])
    first = service.verify(world["task_id"])
    second = service.verify(world["task_id"])
    assert first.final_state == "VERIFIED"
    assert second.report_id == first.report_id
    assert second.certificate_id == first.certificate_id
    assert second.report["signature"] == first.report["signature"]
    connection = connect(world["db_path"])
    try:
        reports = connection.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE task_id = ?", (world["task_id"],)
        ).fetchone()["n"]
        certificates = connection.execute(
            "SELECT COUNT(*) AS n FROM certificates"
        ).fetchone()["n"]
    finally:
        connection.close()
    assert reports == 1
    assert certificates == 1


def test_verification_failure_issues_no_certificate(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    execution = world["pipeline"].execute(world["task_id"])
    assert execution.ok is True
    predictions = (
        world["root"] / "tasks" / world["task_id"] / "attempts"
        / "train_logistic_regression" / "attempt_01" / "output" / "predictions.csv"
    )
    with predictions.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["y_pred"] = "0" if rows[0]["y_pred"] == "1" else "1"
    with predictions.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_index", "y_true", "y_pred"])
        writer.writeheader()
        writer.writerows(rows)

    outcome = VerificationService(world["db_path"], world["root"]).verify(world["task_id"])
    assert outcome.final_state != "VERIFIED"
    assert outcome.certificate is None
    assert _load_certificate(world["db_path"], world["task_id"]) is None
    gaps = [gap["code"] for gap in outcome.gaps]
    assert any(code.startswith("L1_") or code.startswith("L2_") or code.startswith("L3_") for code in gaps)


def test_broken_chain_skips_l3_and_issues_no_certificate(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    execution = world["pipeline"].execute(world["task_id"])
    assert execution.ok is True
    collector = Collector(world["db_path"], world["root"])
    rows = collector.rows(world["task_id"])
    payload_path = (
        world["root"] / "tasks" / world["task_id"] / "evidence_payloads"
        / f"{rows[0].payload_hash}.json"
    )
    payload_path.write_bytes(b'{"tampered":1}')
    outcome = VerificationService(world["db_path"], world["root"]).verify(world["task_id"])
    assert outcome.l1_status == "FAIL"
    assert outcome.l3_status == "SKIP"
    assert outcome.final_state == "FAILED"
    assert outcome.certificate is None
    assert "GAP_CHAIN_INVALID" in {gap["code"] for gap in outcome.gaps}