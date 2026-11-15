"""T0 WP-11 signing tests: RFC 8032 vector, domain separation, Merkle proofs."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from researchflow.contracts.models import CompletionCertificate, VerificationReport
from researchflow.signing import (
    EMPTY_ROOT,
    KeyStore,
    TrustAnchorError,
    certificate_payload,
    inclusion_proof,
    leaf_hash,
    load_trust_anchor,
    merkle_root,
    report_payload,
    sign_bytes,
    sign_certificate,
    sign_report,
    verify_bytes,
    verify_certificate,
    verify_inclusion,
    verify_report,
)

RFC8032_SECRET = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
RFC8032_PUBLIC = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
RFC8032_SIGNATURE = (
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)


def _report() -> dict:
    return {
        "schema_version": "1.0",
        "report_id": "report_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
        "task_id": "task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
        "final_state": "VERIFIED",
        "l1_status": "PASS",
        "l2_status": "PASS",
        "l3_status": "PASS",
        "required_check_coverage": {"required": 5, "passed": 5, "missing": 0},
        "ruleset_hash": "a" * 64,
        "evidence_root": "b" * 64,
        "l3_coverage": 1.0,
        "issued_at": "2026-11-14T10:00:00.000000Z",
        "key_id": "rf-t0-ed25519-01",
        "signature": "",
    }


def _certificate() -> dict:
    return {
        "schema_version": "1.0",
        "cert_id": "cert_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
        "report_id": "report_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10",
        "final_state": "VERIFIED",
        "merkle_root": "b" * 64,
        "tree_size": 9,
        "ruleset_hash": "a" * 64,
        "code_hash": "c" * 64,
        "env_fingerprint": "d" * 64,
        "l3_coverage": 1.0,
        "skipped_nodes": [],
        "alg": "Ed25519",
        "key_id": "rf-t0-ed25519-01",
        "key_fingerprint": "e" * 64,
        "issued_at": "2026-11-14T10:00:01.000000Z",
        "signature": "",
    }


def test_rfc8032_test_vector_1() -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(RFC8032_SECRET))
    public_key = private_key.public_key()
    assert public_key.public_bytes_raw().hex() == RFC8032_PUBLIC
    signature = sign_bytes(private_key, b"")
    assert base64.b64decode(signature).hex() == RFC8032_SIGNATURE
    assert verify_bytes(public_key, b"", signature) is True
    assert verify_bytes(public_key, b"x", signature) is False


def test_key_store_round_trip_and_trust_anchor(tmp_path: Path) -> None:
    store = KeyStore(tmp_path / "keys")
    record = store.generate()
    loaded = store.load()
    assert loaded.fingerprint == record.fingerprint
    assert len(loaded.fingerprint) == 64

    anchor_path = tmp_path / "outside" / "trust_anchor.json"
    store.write_trust_anchor(anchor_path)
    document = json.loads(anchor_path.read_text(encoding="utf-8"))
    assert document["keys"][0]["fingerprint"] == record.fingerprint
    assert "private_key_b64" not in json.dumps(document)
    trusted = load_trust_anchor(anchor_path)
    assert record.key_id in trusted

    tampered = json.loads(anchor_path.read_text(encoding="utf-8"))
    tampered["keys"][0]["fingerprint"] = "0" * 64
    anchor_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(TrustAnchorError):
        load_trust_anchor(anchor_path)


def test_key_generation_never_overwrites(tmp_path: Path) -> None:
    store = KeyStore(tmp_path / "keys")
    store.generate()
    with pytest.raises(FileExistsError):
        store.generate()


def test_report_signature_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    key = KeyStore(tmp_path / "keys").generate()
    signed = sign_report(_report(), key.private_key)
    VerificationReport.model_validate(signed)
    assert verify_report(signed, key.public_key) is True

    tampered = dict(signed)
    tampered["final_state"] = "PARTIAL"
    assert verify_report(tampered, key.public_key) is False

    other = KeyStore(tmp_path / "other").generate()
    assert verify_report(signed, other.public_key) is False

    broken = dict(signed)
    broken["signature"] = signed["signature"][:-4]
    assert verify_report(broken, key.public_key) is False


def test_domain_separation_between_report_and_certificate(tmp_path: Path) -> None:
    key = KeyStore(tmp_path / "keys").generate()
    report = sign_report(_report(), key.private_key)
    certificate = sign_certificate(_certificate(), key.private_key)
    assert verify_report(report, key.public_key) is True
    assert verify_certificate(certificate, key.public_key) is True
    # A report signature must not verify as a certificate signature.
    cross = dict(certificate)
    cross["signature"] = report["signature"]
    assert verify_certificate(cross, key.public_key) is False
    cross_report = dict(report)
    cross_report["signature"] = certificate["signature"]
    assert verify_report(cross_report, key.public_key) is False


def test_unknown_schema_major_is_rejected() -> None:
    report = _report()
    report["schema_version"] = "2.0"
    with pytest.raises(ValueError):
        report_payload(report)
    certificate = _certificate()
    certificate["schema_version"] = "2.0"
    with pytest.raises(ValueError):
        certificate_payload(certificate)


def test_verified_report_with_missing_checks_is_rejected_by_the_contract() -> None:
    report = _report()
    report["required_check_coverage"] = {"required": 5, "passed": 4, "missing": 1}
    with pytest.raises(ValidationError):
        VerificationReport.model_validate(report)


def test_certificate_with_skipped_nodes_is_rejected_by_the_contract() -> None:
    certificate = _certificate()
    certificate["skipped_nodes"] = ["train_logistic_regression"]
    with pytest.raises(ValidationError):
        CompletionCertificate.model_validate(certificate)


def test_merkle_root_and_inclusion_proofs() -> None:
    payloads = [f"record-{index}".encode() for index in range(9)]
    root = merkle_root(payloads)
    assert len(root) == 64
    assert merkle_root(payloads) == root
    for index, payload in enumerate(payloads):
        proof = inclusion_proof(payloads, index)
        assert proof.root == root
        assert verify_inclusion(payload, proof) is True
    assert verify_inclusion(b"tampered", inclusion_proof(payloads, 0)) is False
    assert merkle_root([]) == EMPTY_ROOT
    assert merkle_root(payloads[:-1]) != root
    assert len(leaf_hash(b"record-0")) == 32