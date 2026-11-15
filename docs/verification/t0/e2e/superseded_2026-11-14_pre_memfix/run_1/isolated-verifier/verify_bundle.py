#!/usr/bin/env python3
"""Standalone ResearchFlow Evidence Bundle verifier (T0 · G6-T0).

This tool is intentionally independent of the ResearchFlow package, the
database and the models: it imports only the standard library and
``cryptography``.  It never executes code from the bundle and never trusts a
public key that ships inside the bundle — the trust anchor must be supplied from
an external path.

Usage::

    python verify_bundle.py --bundle <dir> --trust-store <trust_anchor.json>
    python verify_bundle.py --bundle <dir> --trust-store <file> --allow-non-verified

Exit codes: 0 = verified, 3 = rejected (the JSON output names the exact check).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BUNDLE_DOMAIN = b"RF-BUNDLE-V1\x00"
REPORT_DOMAIN = b"RF-REPORT-V1\x00"
CERT_DOMAIN = b"RF-CERT-V1\x00"

REPORT_FIELDS = (
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
CERT_FIELDS = (
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
BUNDLE_FIELDS = (
    "schema_version",
    "bundle_version",
    "task_id",
    "report_id",
    "certificate_id",
    "final_state",
    "merkle_root",
    "tree_size",
    "ruleset_hash",
    "ruleset_version",
    "created_at",
    "key_id",
    "key_fingerprint",
    "evidence_count",
    "artifact_count",
    "files",
)
SUPPORTED_MAJOR = {"1"}
EXIT_REJECTED = 3


class Rejected(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# ---------------------------------------------------------------- canonical JSON
def _utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be")


def _canonical_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_number(value: int | float) -> str:
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError("NaN/Infinity are not valid JSON numbers")
    if value == 0:
        return "0"
    if 1e-6 <= abs(value) < 1e21:
        text = format(Decimal(repr(value)), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if text in {"-0", ""} else text
    text = repr(value).lower()
    if "e" not in text:
        text = format(Decimal(text), "e")
    mantissa, exponent = text.split("e", 1)
    exponent_int = int(exponent)
    sign = "+" if exponent_int >= 0 else "-"
    return f"{mantissa}e{sign}{abs(exponent_int)}"


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return _canonical_number(value)
    if isinstance(value, float):
        return _canonical_number(value)
    if isinstance(value, str):
        return _canonical_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("object keys must be strings")
        keys = sorted(value.keys(), key=_utf16_key)
        return (
            "{"
            + ",".join(
                _canonical_string(key) + ":" + _canonical(value[key]) for key in keys
            )
            + "}"
        )
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    return _canonical(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jcs_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


# -------------------------------------------------------------------- merkle
def _leaf(payload: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + payload).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def merkle_root(payloads: list[bytes]) -> str:
    if not payloads:
        return sha256_hex(b"")
    layer = [_leaf(payload) for payload in payloads]
    while len(layer) > 1:
        parents: list[bytes] = []
        for index in range(0, len(layer), 2):
            left = layer[index]
            right = layer[index + 1] if index + 1 < len(layer) else left
            parents.append(_node(left, right))
        layer = parents
    return layer[0].hex()


# --------------------------------------------------------------------- helpers
def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejected("BUNDLE_UNREADABLE", f"{path.name}: {exc}") from exc


def _signed_payload(document: dict[str, Any], fields: tuple[str, ...], domain: bytes) -> bytes:
    missing = [field for field in fields if field not in document]
    if missing:
        raise Rejected("PAYLOAD_INCOMPLETE", f"signed payload is missing {missing}")
    major = str(document.get("schema_version", "")).split(".")[0]
    if major not in SUPPORTED_MAJOR:
        raise Rejected(
            "SCHEMA_VERSION_UNSUPPORTED", f"schema_version {document.get('schema_version')!r}"
        )
    return domain + canonical_bytes({field: document[field] for field in fields})


def _verify_ed25519(public_key: Ed25519PublicKey, payload: bytes, signature_b64: str) -> bool:
    try:
        public_key.verify(base64.b64decode(signature_b64), payload)
        return True
    except (InvalidSignature, ValueError):
        return False


def _load_trust_store(path: Path, bundle: Path) -> dict[str, dict[str, Any]]:
    anchor_path = path.resolve()
    bundle_path = bundle.resolve()
    if anchor_path == bundle_path or bundle_path in anchor_path.parents:
        raise Rejected(
            "TRUST_ANCHOR_INSIDE_BUNDLE",
            "the trust store must come from outside the evidence bundle",
        )
    document = _read_json(anchor_path)
    if document.get("schema_version") != "1.0":
        raise Rejected("TRUST_ANCHOR_INVALID", "unsupported trust anchor version")
    keys: dict[str, dict[str, Any]] = {}
    for entry in document.get("keys", []):
        if entry.get("alg") != "Ed25519":
            raise Rejected("TRUST_ANCHOR_INVALID", f"unsupported alg {entry.get('alg')!r}")
        raw = base64.b64decode(entry["public_key_b64"])
        public_key = Ed25519PublicKey.from_public_bytes(raw)
        fingerprint = jcs_hash(
            {"alg": "Ed25519", "public_key_b64": entry["public_key_b64"]}
        )
        if fingerprint != entry.get("fingerprint"):
            raise Rejected("TRUST_ANCHOR_INVALID", "anchor fingerprint does not match key")
        keys[str(entry["key_id"])] = {
            "public_key": public_key,
            "fingerprint": fingerprint,
        }
    if not keys:
        raise Rejected("TRUST_ANCHOR_INVALID", "trust anchor contains no keys")
    return keys


def _evidence_bytes(record: dict[str, Any]) -> bytes:
    return canonical_bytes(
        {
            "schema_version": "1.0",
            "evidence_id": record["evidence_id"],
            "task_id": record["task_id"],
            "node_id": record["node_id"],
            "attempt_id": record["attempt_id"],
            "event_seq": record["event_seq"],
            "level": record["level"],
            "kind": record["kind"],
            "producer": record["producer"],
            "timestamp": record["timestamp"],
            "payload_hash": record["payload_hash"],
            "artifact_refs": record["artifact_refs"],
            "prev_hash": record["prev_hash"],
            "chain_hash": record["chain_hash"],
        }
    )


def _chain_hash(record: dict[str, Any]) -> str:
    return sha256_hex(
        canonical_bytes(
            {
                "schema_version": "1.0",
                "evidence_id": record["evidence_id"],
                "task_id": record["task_id"],
                "node_id": record["node_id"],
                "attempt_id": record["attempt_id"],
                "event_seq": record["event_seq"],
                "level": record["level"],
                "kind": record["kind"],
                "producer": record["producer"],
                "timestamp": record["timestamp"],
                "payload_hash": record["payload_hash"],
                "artifact_refs": record["artifact_refs"],
                "prev_hash": record["prev_hash"],
            }
        )
    )


LEVEL_RULES = {
    "E0": ("collector", {"agent_claim"}),
    "E1": ("collector", {"tool_invocation", "harness_trace"}),
    "E2": ("collector", {"executor_launch", "executor_process_exit", "artifact_observed"}),
    "E3": ("verifier", {"verifier_recheck"}),
}
GENESIS = "0" * 64


def verify_bundle(
    bundle: Path, trust_store: Path, *, require_verified: bool = True
) -> dict[str, Any]:
    bundle = bundle.resolve()
    if not bundle.is_dir():
        raise Rejected("BUNDLE_MISSING", f"bundle directory does not exist: {bundle}")
    keys = _load_trust_store(trust_store, bundle)

    manifest = _read_json(bundle / "manifest.json")
    signature_document = _read_json(bundle / "manifest.sig.json")
    signer = keys.get(str(manifest.get("key_id")))
    if signer is None:
        raise Rejected("SIGNATURE_INVALID", "manifest key_id is not in the trust anchor")
    if signer["fingerprint"] != manifest.get("key_fingerprint"):
        raise Rejected(
            "SIGNATURE_INVALID", "manifest key fingerprint does not match the trust anchor"
        )
    if not _verify_ed25519(
        signer["public_key"],
        BUNDLE_DOMAIN + canonical_bytes({field: manifest[field] for field in BUNDLE_FIELDS}),
        str(signature_document.get("signature", "")),
    ):
        raise Rejected("SIGNATURE_INVALID", "bundle manifest signature is invalid")

    for entry in manifest.get("files", []):
        path = (bundle / entry["path"]).resolve()
        if bundle not in path.parents:
            raise Rejected("BUNDLE_PATH_ESCAPE", f"manifest path escapes the bundle: {entry['path']}")
        if not path.is_file():
            raise Rejected("BUNDLE_FILE_MISSING", f"listed file is missing: {entry['path']}")
        data = path.read_bytes()
        if sha256_hex(data) != entry.get("sha256"):
            raise Rejected("BUNDLE_TAMPERED", f"hash mismatch for {entry['path']}")
        if len(data) != entry.get("size"):
            raise Rejected("BUNDLE_TAMPERED", f"size mismatch for {entry['path']}")

    report = _read_json(bundle / "report.json")
    certificate = _read_json(bundle / "certificate.json") if (bundle / "certificate.json").is_file() else None
    if report.get("report_id") != manifest.get("report_id"):
        raise Rejected("BUNDLE_TAMPERED", "manifest report_id does not match report.json")
    if certificate is None:
        raise Rejected("CERTIFICATE_MISSING", "bundle has no certificate.json")
    if certificate.get("cert_id") != manifest.get("certificate_id"):
        raise Rejected("BUNDLE_TAMPERED", "manifest certificate_id does not match certificate.json")

    if not _verify_ed25519(
        signer["public_key"],
        _signed_payload(report, REPORT_FIELDS, REPORT_DOMAIN),
        str(report.get("signature", "")),
    ):
        raise Rejected("SIGNATURE_INVALID", "report signature is invalid")
    if not _verify_ed25519(
        signer["public_key"],
        _signed_payload(certificate, CERT_FIELDS, CERT_DOMAIN),
        str(certificate.get("signature", "")),
    ):
        raise Rejected("SIGNATURE_INVALID", "certificate signature is invalid")

    records: list[dict[str, Any]] = []
    records_path = bundle / "evidence" / "records.jsonl"
    if not records_path.is_file():
        raise Rejected("EVIDENCE_MISSING", "evidence/records.jsonl is missing")
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    if not records:
        raise Rejected("EVIDENCE_MISSING", "the bundle contains no evidence records")

    previous_hash = GENESIS
    previous_timestamp: str | None = None
    for index, record in enumerate(records, start=1):
        if record.get("event_seq") != index:
            raise Rejected(
                "EVIDENCE_CHAIN_INVALID",
                f"event_seq gap at record {index}: {record.get('event_seq')}",
            )
        if record.get("prev_hash") != previous_hash:
            raise Rejected(
                "EVIDENCE_CHAIN_INVALID", f"prev_hash mismatch at record {index}"
            )
        if _chain_hash(record) != record.get("chain_hash"):
            raise Rejected(
                "EVIDENCE_CHAIN_INVALID", f"chain_hash mismatch at record {index}"
            )
        payload_path = bundle / "evidence" / "payloads" / f"{record.get('payload_hash')}.json"
        if not payload_path.is_file():
            raise Rejected(
                "EVIDENCE_PAYLOAD_MISSING",
                f"payload {record.get('payload_hash')} is missing",
            )
        if sha256_hex(payload_path.read_bytes()) != record.get("payload_hash"):
            raise Rejected(
                "BUNDLE_TAMPERED",
                f"payload bytes do not hash to payload_hash at record {index}",
            )
        expected_producer, expected_kinds = LEVEL_RULES.get(str(record.get("level")), ("", set()))
        if (
            record.get("producer") != expected_producer
            or record.get("kind") not in expected_kinds
        ):
            raise Rejected(
                "EVIDENCE_LEVEL_INVALID",
                f"record {index}: level {record.get('level')} cannot come from "
                f"producer {record.get('producer')} kind {record.get('kind')}",
            )
        if previous_timestamp is not None and record.get("timestamp") < previous_timestamp:
            raise Rejected("EVIDENCE_CHAIN_INVALID", f"timestamp order at record {index}")
        previous_timestamp = record.get("timestamp")
        previous_hash = record.get("chain_hash")

    recomputed_root = merkle_root([_evidence_bytes(record) for record in records])
    if recomputed_root != manifest.get("merkle_root"):
        raise Rejected("MERKLE_ROOT_MISMATCH", "evidence root does not match the manifest")
    if recomputed_root != report.get("evidence_root"):
        raise Rejected("MERKLE_ROOT_MISMATCH", "evidence root does not match the report")
    if recomputed_root != certificate.get("merkle_root"):
        raise Rejected("MERKLE_ROOT_MISMATCH", "evidence root does not match the certificate")
    if certificate.get("tree_size") != len(records):
        raise Rejected("CERTIFICATE_INVALID", "certificate tree_size does not match the evidence count")
    if manifest.get("tree_size") != len(records):
        raise Rejected("BUNDLE_TAMPERED", "manifest tree_size does not match the evidence count")

    ruleset = _read_json(bundle / "ruleset.json")
    ruleset_hash = jcs_hash(ruleset)
    task = _read_json(bundle / "task.json")
    graph = _read_json(bundle / "graph.json")
    nodes = {str(node["node_id"]): node for node in _read_json(bundle / "nodes.json")}
    invalidations = _read_json(bundle / "evidence" / "invalidations.json")
    invalidated_ids = {str(row["evidence_id"]) for row in invalidations}

    if ruleset_hash != report.get("ruleset_hash"):
        raise Rejected("RULESET_VERSION_MISMATCH", "report ruleset_hash does not match ruleset.json")
    if str(task.get("spec", {}).get("ruleset_hash")) != ruleset_hash:
        raise Rejected(
            "RULESET_VERSION_MISMATCH", "task spec ruleset_hash does not match ruleset.json"
        )
    graph_body = graph.get("graph", {})
    graph_payload = {
        "schema_version": "1.0",
        "nodes": sorted(graph_body.get("nodes", []), key=lambda item: str(item["node_id"])),
        "edges": sorted(
            {(str(edge[0]), str(edge[1])) for edge in graph_body.get("edges", [])}
        ),
    }
    if jcs_hash(graph_payload) != graph.get("graph_hash"):
        raise Rejected("GRAPH_INVALID", "graph_hash does not match the bundled graph")
    if graph.get("graph_hash") != graph_body.get("graph_hash"):
        raise Rejected("GRAPH_INVALID", "graph.json is inconsistent with the graph snapshot")

    payloads: dict[str, dict[str, Any]] = {
        str(record["payload_hash"]): json.loads(
            (bundle / "evidence" / "payloads" / f"{record['payload_hash']}.json").read_bytes()
        )
        for record in records
    }
    gaps: list[dict[str, str]] = []
    required = 0
    passed = 0
    metric_required = 0
    metric_verified = 0
    for node in sorted(graph_body.get("nodes", []), key=lambda item: str(item["node_id"])):
        node_id = str(node["node_id"])
        checks = ruleset.get("required_checks", {}).get(str(node["node_type"]))
        if not checks:
            gaps.append({"code": "GAP_NODE_TYPE_UNKNOWN", "node_id": node_id, "check": ""})
            continue
        row = nodes.get(node_id)
        if row is None:
            gaps.append({"code": "GAP_NODE_ROW_MISSING", "node_id": node_id, "check": ""})
            required += len(checks)
            continue
        attempt_id = f"attempt_{int(row['attempt_seq']):02d}"
        for check in checks:
            required += 1
            definition = ruleset.get("check_definitions", {}).get(str(check), {})
            level = str(definition.get("level", ""))
            kinds = set(definition.get("kinds", []))
            if check == "metric_source":
                metric_required += 1
            node_records = [record for record in records if record["node_id"] == node_id]
            candidates = [
                record
                for record in node_records
                if record["level"] == level and record["kind"] in kinds
            ]
            current = [record for record in candidates if record["attempt_id"] == attempt_id]
            live = [record for record in current if record["evidence_id"] not in invalidated_ids]
            if not candidates:
                gaps.append({"code": "GAP_E2_MISSING" if level == "E2" else "GAP_E3_MISSING", "node_id": node_id, "check": str(check)})
                continue
            if not current:
                gaps.append({"code": "GAP_STALE_ATTEMPT", "node_id": node_id, "check": str(check)})
                continue
            if not live:
                gaps.append({"code": "GAP_EVIDENCE_STALE", "node_id": node_id, "check": str(check)})
                continue
            if check == "executor_observed":
                launches = [record for record in live if record["kind"] == "executor_launch"]
                exits = [record for record in live if record["kind"] == "executor_process_exit"]
                if not launches or not exits:
                    gaps.append({"code": "GAP_E2_MISSING", "node_id": node_id, "check": str(check)})
                    continue
                payload = payloads.get(str(exits[-1]["payload_hash"]), {})
                if payload.get("status") != "EXITED" or payload.get("exit_code") != 0:
                    gaps.append({"code": "GAP_E2_NOT_SUCCESS", "node_id": node_id, "check": str(check)})
                    continue
                passed += 1
            elif check == "artifact_hash":
                ok = True
                for record in live:
                    payload = payloads.get(str(record["payload_hash"]), {})
                    relative = str(payload.get("artifact_path", ""))
                    expected = str(payload.get("sha256", ""))
                    path = (bundle / "artifacts" / node_id / attempt_id / relative).resolve()
                    artifact_root = (bundle / "artifacts").resolve()
                    if artifact_root not in path.parents or not path.is_file():
                        gaps.append({"code": "GAP_ARTIFACT_MISSING", "node_id": node_id, "check": str(check)})
                        ok = False
                        break
                    if sha256_hex(path.read_bytes()) != expected:
                        gaps.append({"code": "GAP_ARTIFACT_HASH_MISMATCH", "node_id": node_id, "check": str(check)})
                        ok = False
                        break
                if ok:
                    passed += 1
            elif check == "metric_source":
                ok = False
                for record in live:
                    payload = payloads.get(str(record["payload_hash"]), {})
                    if payload.get("node_id") == node_id and payload.get("l3_status") == "PASS":
                        ok = True
                        break
                if ok:
                    passed += 1
                    metric_verified += 1
                else:
                    gaps.append({"code": "GAP_E3_NOT_PASS", "node_id": node_id, "check": str(check)})
            else:
                gaps.append({"code": "GAP_CHECK_UNKNOWN", "node_id": node_id, "check": str(check)})

    if gaps:
        raise Rejected(
            "REQUIRED_EVIDENCE_MISSING",
            "the bundled evidence does not satisfy the ruleset: "
            + ", ".join(f"{gap['code']}@{gap['node_id']}" for gap in gaps[:5]),
        )

    coverage = report.get("required_check_coverage", {})
    if coverage.get("required") != required or coverage.get("passed") != passed:
        raise Rejected(
            "COVERAGE_MISMATCH",
            f"report coverage {coverage} != recomputed required={required} passed={passed}",
        )
    minimum = float(ruleset.get("l3", {}).get("minimum_coverage", 1.0))
    l3_coverage = metric_verified / metric_required if metric_required else 0.0
    if l3_coverage < minimum:
        raise Rejected(
            "L3_COVERAGE_BELOW_MINIMUM",
            f"recomputed L3 coverage {l3_coverage} < {minimum}",
        )
    if abs(float(report.get("l3_coverage", 0.0)) - l3_coverage) > 1e-12:
        raise Rejected("COVERAGE_MISMATCH", "report l3_coverage does not match the evidence")

    if require_verified and report.get("final_state") != "VERIFIED":
        raise Rejected(
            "REPORT_NOT_VERIFIED", f"report final_state is {report.get('final_state')}"
        )
    if certificate.get("final_state") != "VERIFIED":
        raise Rejected("CERTIFICATE_INVALID", "certificate final_state is not VERIFIED")
    if certificate.get("report_id") != report.get("report_id"):
        raise Rejected("CERTIFICATE_INVALID", "certificate does not belong to the report")
    if certificate.get("ruleset_hash") != report.get("ruleset_hash"):
        raise Rejected("CERTIFICATE_INVALID", "certificate ruleset_hash mismatch")
    if certificate.get("key_fingerprint") != signer["fingerprint"]:
        raise Rejected("SIGNATURE_INVALID", "certificate key fingerprint is not trusted")
    if certificate.get("alg") != "Ed25519":
        raise Rejected("CERTIFICATE_INVALID", "certificate algorithm is not Ed25519")
    if certificate.get("skipped_nodes"):
        raise Rejected("CERTIFICATE_INVALID", "T0 certificates must not skip nodes")

    return {
        "status": "VERIFIED",
        "task_id": report.get("task_id"),
        "report_id": report.get("report_id"),
        "certificate_id": certificate.get("cert_id"),
        "final_state": report.get("final_state"),
        "merkle_root": recomputed_root,
        "tree_size": len(records),
        "evidence_count": len(records),
        "required_checks": required,
        "passed_checks": passed,
        "l3_coverage": l3_coverage,
        "invalidated_evidence": len(invalidated_ids),
        "key_id": manifest.get("key_id"),
        "key_fingerprint": signer["fingerprint"],
        "trust_anchor_source": "external",
        "bundle_version": manifest.get("bundle_version"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a ResearchFlow evidence bundle offline")
    parser.add_argument("--bundle", required=True, help="bundle directory")
    parser.add_argument("--trust-store", required=True, help="trust anchor JSON outside the bundle")
    parser.add_argument(
        "--allow-non-verified",
        action="store_true",
        help="accept a signed report whose final_state is not VERIFIED",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        summary = verify_bundle(
            Path(args.bundle),
            Path(args.trust_store),
            require_verified=not args.allow_non_verified,
        )
    except Rejected as rejected:
        print(
            json.dumps(
                {"status": "REJECTED", "code": rejected.code, "detail": rejected.detail},
                ensure_ascii=False,
            )
        )
        return EXIT_REJECTED
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "REJECTED", "code": "BUNDLE_MALFORMED", "detail": str(exc)},
                ensure_ascii=False,
            )
        )
        return EXIT_REJECTED
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())