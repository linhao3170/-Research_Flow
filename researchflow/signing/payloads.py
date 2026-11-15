"""Domain-separated signed payloads for reports and certificates (T0 WP-11).

Only the whitelisted fields from ``05_CONTRACTS_AND_STATES.md`` §1.5 enter the
payload; the field set is a constant so adding an object field cannot silently
change what is signed.  ``schema_version`` is always included and the verifier
must reject an unknown MAJOR version.
"""

from __future__ import annotations

import base64
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from researchflow.contracts.encoding import canonical_bytes

__all__ = [
    "CERT_DOMAIN",
    "CERT_FIELDS",
    "REPORT_DOMAIN",
    "REPORT_FIELDS",
    "certificate_payload",
    "report_payload",
    "sign_bytes",
    "sign_certificate",
    "sign_report",
    "verify_bytes",
    "verify_certificate",
    "verify_report",
]

REPORT_DOMAIN = b"RF-REPORT-V1\x00"
CERT_DOMAIN = b"RF-CERT-V1\x00"

REPORT_FIELDS: tuple[str, ...] = (
    "schema_version",
    "report_id",
    "task_id",
    "final_state",
    "l1_status",
    "l2_status",
    "l3_status",
    "required_check_coverage",
    "ruleset_hash",
    "evidence_root",
    "l3_coverage",
    "issued_at",
    "key_id",
)

CERT_FIELDS: tuple[str, ...] = (
    "schema_version",
    "cert_id",
    "report_id",
    "final_state",
    "merkle_root",
    "tree_size",
    "ruleset_hash",
    "code_hash",
    "env_fingerprint",
    "l3_coverage",
    "skipped_nodes",
    "alg",
    "key_id",
    "key_fingerprint",
    "issued_at",
)

SUPPORTED_MAJOR = {"1"}


def _payload(document: Mapping[str, Any], fields: Sequence[str], domain: bytes) -> bytes:
    missing = [field for field in fields if field not in document]
    if missing:
        raise ValueError(f"signed payload is missing fields: {missing}")
    body = {field: document[field] for field in fields}
    major = str(body.get("schema_version", "")).split(".")[0]
    if major not in SUPPORTED_MAJOR:
        raise ValueError(f"unsupported schema MAJOR version: {body.get('schema_version')}")
    return domain + canonical_bytes(body)


def report_payload(report: Mapping[str, Any]) -> bytes:
    return _payload(report, REPORT_FIELDS, REPORT_DOMAIN)


def certificate_payload(certificate: Mapping[str, Any]) -> bytes:
    return _payload(certificate, CERT_FIELDS, CERT_DOMAIN)


def sign_bytes(private_key: Ed25519PrivateKey, payload: bytes) -> str:
    return base64.b64encode(private_key.sign(payload)).decode("ascii")


def verify_bytes(public_key: Ed25519PublicKey, payload: bytes, signature_b64: str) -> bool:
    try:
        public_key.verify(base64.b64decode(signature_b64), payload)
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_report(report: Mapping[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    document = dict(report)
    document["signature"] = sign_bytes(private_key, report_payload(document))
    return document


def verify_report(report: Mapping[str, Any], public_key: Ed25519PublicKey) -> bool:
    signature = report.get("signature")
    if not isinstance(signature, str) or not signature:
        return False
    return verify_bytes(public_key, report_payload(report), signature)


def sign_certificate(
    certificate: Mapping[str, Any], private_key: Ed25519PrivateKey
) -> dict[str, Any]:
    document = dict(certificate)
    document["signature"] = sign_bytes(private_key, certificate_payload(document))
    return document


def verify_certificate(
    certificate: Mapping[str, Any], public_key: Ed25519PublicKey
) -> bool:
    signature = certificate.get("signature")
    if not isinstance(signature, str) or not signature:
        return False
    return verify_bytes(public_key, certificate_payload(certificate), signature)