"""Ed25519 signing, Merkle proofs and trust anchors (WP-11)."""

from __future__ import annotations

from researchflow.signing.keys import (
    DEFAULT_KEY_ID,
    KeyRecord,
    KeyStore,
    TrustAnchorError,
    TrustedKey,
    load_trust_anchor,
    public_key_fingerprint,
)
from researchflow.signing.merkle import (
    EMPTY_ROOT,
    InclusionProof,
    evidence_record_bytes,
    inclusion_proof,
    leaf_hash,
    merkle_root,
    verify_inclusion,
)
from researchflow.signing.payloads import (
    CERT_DOMAIN,
    CERT_FIELDS,
    REPORT_DOMAIN,
    REPORT_FIELDS,
    certificate_payload,
    report_payload,
    sign_bytes,
    sign_certificate,
    sign_report,
    verify_bytes,
    verify_certificate,
    verify_report,
)

__all__ = [
    "CERT_DOMAIN",
    "CERT_FIELDS",
    "DEFAULT_KEY_ID",
    "EMPTY_ROOT",
    "InclusionProof",
    "KeyRecord",
    "KeyStore",
    "REPORT_DOMAIN",
    "REPORT_FIELDS",
    "TrustAnchorError",
    "TrustedKey",
    "certificate_payload",
    "evidence_record_bytes",
    "inclusion_proof",
    "leaf_hash",
    "load_trust_anchor",
    "merkle_root",
    "public_key_fingerprint",
    "report_payload",
    "sign_bytes",
    "sign_certificate",
    "sign_report",
    "verify_bytes",
    "verify_certificate",
    "verify_inclusion",
    "verify_report",
]