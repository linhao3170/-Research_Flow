"""Evidence Bundle exporter (T0 WP-12).

The bundle is self-contained for offline verification: task, nodes, graph,
evidence records + payloads, artifacts, invalidations, ruleset, report,
certificate, history and a signed manifest.  It never contains the private key
or the trust anchor — the verifier must receive the anchor from outside.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from researchflow.contracts.encoding import canonical_bytes
from researchflow.persistence.db import connect, format_utc, utc_now
from researchflow.persistence.records import (
    CertificateRepository,
    GraphRepository,
    ReportRepository,
    list_all_invalidations,
    list_evidence,
)
from researchflow.persistence.repositories import NodeRepository, TaskRepository
from researchflow.rules import RULESET_HASH, RULESET_VERSION, load_ruleset
from researchflow.signing.keys import KeyStore
from researchflow.signing.merkle import evidence_record_bytes, merkle_root
from researchflow.signing.payloads import sign_bytes

__all__ = [
    "BUNDLE_DOMAIN",
    "BUNDLE_MANIFEST_FIELDS",
    "BUNDLE_VERSION",
    "BundleError",
    "BundleExporter",
    "bundle_manifest_payload",
]

BUNDLE_VERSION = "1.0.0"
BUNDLE_DOMAIN = b"RF-BUNDLE-V1\x00"
BUNDLE_MANIFEST_FIELDS: tuple[str, ...] = (
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


class BundleError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def bundle_manifest_payload(manifest: dict[str, Any]) -> bytes:
    missing = [field for field in BUNDLE_MANIFEST_FIELDS if field not in manifest]
    if missing:
        raise BundleError("BUNDLE_MANIFEST_INVALID", f"manifest is missing {missing}")
    return BUNDLE_DOMAIN + canonical_bytes(
        {field: manifest[field] for field in BUNDLE_MANIFEST_FIELDS}
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class _Context:
    task: Any
    graph: Any
    nodes: list[Any]
    evidence: list[Any]
    invalidations: list[Any]
    report: Any
    certificate: Any
    reports: list[Any]
    certificates: list[Any]


class BundleExporter:
    def __init__(self, db_path: str | Path, task_root: str | Path) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root) if task_root else self._db_path.parent

    # ------------------------------------------------------------------ helpers
    def _load(self, task_id: str) -> _Context:
        connection = connect(self._db_path)
        try:
            task = TaskRepository().get(connection, task_id)
            graph = GraphRepository().get(connection, task_id)
            nodes = NodeRepository().list_for_task(connection, task_id)
            evidence = list_evidence(connection, task_id)
            invalidations = list_all_invalidations(connection, task_id)
            report = ReportRepository().latest_for_task(connection, task_id)
            reports = [
                ReportRepository().get(connection, str(row["report_id"]))
                for row in connection.execute(
                    "SELECT report_id FROM reports WHERE task_id = ? ORDER BY issued_at, rowid",
                    (task_id,),
                ).fetchall()
            ]
            certificate = (
                None
                if report is None
                else CertificateRepository().for_report(connection, report.report_id)
            )
            certificates = []
            for candidate in reports:
                if candidate is None:
                    continue
                cert = CertificateRepository().for_report(
                    connection, candidate.report_id
                )
                if cert is not None:
                    certificates.append(cert)
        finally:
            connection.close()
        if task is None:
            raise BundleError("TASK_NOT_FOUND", f"task {task_id} does not exist")
        if graph is None:
            raise BundleError("GRAPH_NOT_REGISTERED", f"task {task_id} has no graph")
        if report is None:
            raise BundleError("REPORT_MISSING", f"task {task_id} has no report")
        return _Context(
            task=task,
            graph=graph,
            nodes=nodes,
            evidence=evidence,
            invalidations=invalidations,
            report=report,
            certificate=certificate,
            reports=[item for item in reports if item is not None],
            certificates=certificates,
        )

    def _artifact_copy(
        self, bundle: Path, evidence_rows: Iterable[Any]
    ) -> int:
        copied = 0
        seen: set[Path] = set()
        for row in evidence_rows:
            if row.kind != "artifact_observed":
                continue
            payload_path = (
                self._task_root / "tasks" / row.task_id / "evidence_payloads"
                / f"{row.payload_hash}.json"
            )
            if not payload_path.is_file():
                continue
            payload = json.loads(payload_path.read_bytes())
            relative = str(payload.get("artifact_path", ""))
            attempt_seq = int(row.attempt_id.rsplit("_", 1)[-1])
            attempt_dir = (
                self._task_root / "tasks" / row.task_id / "attempts"
                / row.node_id / f"attempt_{attempt_seq:02d}"
            )
            source = (attempt_dir / relative).resolve()
            root = attempt_dir.resolve()
            if root not in source.parents or not source.is_file():
                continue
            target = (
                bundle / "artifacts" / row.node_id / row.attempt_id / relative
            ).resolve()
            if target in seen:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            seen.add(target)
            copied += 1
        return copied

    def _attempt_results(self, bundle: Path, evidence_rows: Iterable[Any]) -> None:
        seen: set[tuple[str, str]] = set()
        for row in evidence_rows:
            key = (row.node_id, row.attempt_id)
            if key in seen:
                continue
            seen.add(key)
            attempt_seq = int(row.attempt_id.rsplit("_", 1)[-1])
            result = (
                self._task_root / "tasks" / row.task_id / "attempts"
                / row.node_id / f"attempt_{attempt_seq:02d}" / "result.json"
            )
            if result.is_file():
                target = bundle / "attempts" / row.node_id / row.attempt_id / "result.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(result, target)

    # ------------------------------------------------------------------- export
    def export(
        self,
        task_id: str,
        out_dir: str | Path,
        *,
        trust_anchor_path: str | Path | None = None,
    ) -> dict[str, Any]:
        context = self._load(task_id)
        bundle = Path(out_dir)
        if bundle.exists() and any(bundle.iterdir()):
            raise BundleError(
                "BUNDLE_DIR_NOT_EMPTY", f"refusing to overwrite a non-empty directory: {bundle}"
            )
        bundle.mkdir(parents=True, exist_ok=True)

        key = KeyStore(self._task_root / "keys").load()
        if context.report.key_id and context.report.key_id != key.key_id:
            raise BundleError(
                "KEY_MISMATCH", "the report was not signed by the runtime key"
            )
        if trust_anchor_path is not None:
            from researchflow.signing.keys import load_trust_anchor

            trusted = load_trust_anchor(trust_anchor_path)
            if key.key_id not in trusted:
                raise BundleError(
                    "TRUST_ANCHOR_MISMATCH",
                    "the trust anchor does not contain the signing key",
                )
            if trusted[key.key_id].fingerprint != key.fingerprint:
                raise BundleError(
                    "TRUST_ANCHOR_MISMATCH",
                    "the trust anchor fingerprint does not match the signing key",
                )

        task_spec = json.loads(context.task.task_spec_json)
        _write_json(
            bundle / "task.json",
            {
                "task_id": context.task.task_id,
                "state": context.task.state,
                "graph_version": context.task.graph_version,
                "created_at": context.task.created_at,
                "updated_at": context.task.updated_at,
                "spec": task_spec,
            },
        )
        _write_json(
            bundle / "nodes.json",
            [
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "template_id": node.template_id,
                    "state": node.state,
                    "attempt_seq": node.attempt_seq,
                    "plan_id": node.plan_id,
                    "plan_hash": node.plan_hash,
                    "updated_at": node.updated_at,
                }
                for node in context.nodes
            ],
        )
        _write_json(
            bundle / "graph.json",
            {
                "task_id": context.graph.task_id,
                "graph_version": context.graph.graph_version,
                "graph_hash": context.graph.graph_hash,
                "topology_order": list(context.graph.topology_order),
                "created_at": context.graph.created_at,
                "graph": context.graph.graph_json,
            },
        )
        records_path = bundle / "evidence" / "records.jsonl"
        records_path.parent.mkdir(parents=True, exist_ok=True)
        with records_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in context.evidence:
                handle.write(
                    json.dumps(
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
                            "artifact_refs": None
                            if row.artifact_refs is None
                            else json.loads(row.artifact_refs),
                            "prev_hash": row.prev_hash,
                            "chain_hash": row.chain_hash,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        payload_dir = bundle / "evidence" / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        for row in context.evidence:
            source = (
                self._task_root / "tasks" / task_id / "evidence_payloads"
                / f"{row.payload_hash}.json"
            )
            if source.is_file():
                shutil.copyfile(source, payload_dir / f"{row.payload_hash}.json")
        _write_json(
            bundle / "evidence" / "invalidations.json",
            [
                {
                    "invalidation_id": row.invalidation_id,
                    "task_id": row.task_id,
                    "node_id": row.node_id,
                    "evidence_id": row.evidence_id,
                    "reason_code": row.reason_code,
                    "cause_type": row.cause_type,
                    "cause_ref": row.cause_ref,
                    "plan_id": row.plan_id,
                    "plan_hash": row.plan_hash,
                    "created_at": row.created_at,
                }
                for row in context.invalidations
            ],
        )
        artifacts = self._artifact_copy(bundle, context.evidence)
        self._attempt_results(bundle, context.evidence)
        _write_json(bundle / "report.json", context.report.report_json)
        if context.certificate is not None:
            _write_json(
                bundle / "certificate.json",
                {
                    "schema_version": context.certificate.schema_version,
                    "cert_id": context.certificate.cert_id,
                    "report_id": context.certificate.report_id,
                    "final_state": context.certificate.final_state,
                    "merkle_root": context.certificate.merkle_root,
                    "tree_size": context.certificate.tree_size,
                    "ruleset_hash": context.certificate.ruleset_hash,
                    "code_hash": context.certificate.code_hash,
                    "env_fingerprint": context.certificate.env_fingerprint,
                    "l3_coverage": context.certificate.l3_coverage,
                    "skipped_nodes": context.certificate.skipped_nodes,
                    "alg": context.certificate.alg,
                    "key_id": context.certificate.key_id,
                    "key_fingerprint": context.certificate.key_fingerprint,
                    "signature": context.certificate.signature,
                    "issued_at": context.certificate.issued_at,
                },
            )
        _write_json(bundle / "ruleset.json", load_ruleset())
        superseded_reports = [
            item.report_id
            for item in context.reports
            if item.report_id != context.report.report_id
        ]
        superseded_certificates = [
            item.cert_id
            for item in context.certificates
            if context.certificate is None or item.cert_id != context.certificate.cert_id
        ]
        _write_json(
            bundle / "history.json",
            {
                "final_report_id": context.report.report_id,
                "superseded_report_ids": superseded_reports,
                "final_certificate_id": None
                if context.certificate is None
                else context.certificate.cert_id,
                "superseded_certificate_ids": superseded_certificates,
                "note": "Superseded reports/certificates are listed by id; only the final pair is included.",
            },
        )
        _write_json(
            bundle / "gate_view.json",
            {
                "stale_evidence_ids": [row.evidence_id for row in context.invalidations],
                "note": "Gate re-evaluation happens in verify_bundle.py from records + invalidations + ruleset.",
            },
        )
        (bundle / "README.md").write_text(self._readme(), encoding="utf-8")

        files: list[dict[str, Any]] = []
        for path in sorted(bundle.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(bundle).as_posix()
            if relative in {"manifest.json", "manifest.sig.json"}:
                continue
            files.append(
                {
                    "path": relative,
                    "sha256": _file_sha256(path),
                    "size": path.stat().st_size,
                }
            )

        created_at = format_utc(utc_now())
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "bundle_version": BUNDLE_VERSION,
            "task_id": task_id,
            "report_id": context.report.report_id,
            "certificate_id": None
            if context.certificate is None
            else context.certificate.cert_id,
            "final_state": context.report.final_state,
            "merkle_root": context.report.evidence_root,
            "tree_size": len(context.evidence),
            "ruleset_hash": context.report.ruleset_hash,
            "ruleset_version": RULESET_VERSION,
            "created_at": created_at,
            "key_id": key.key_id,
            "key_fingerprint": key.fingerprint,
            "evidence_count": len(context.evidence),
            "artifact_count": artifacts,
            "files": files,
        }
        _write_json(bundle / "manifest.json", manifest)
        signature = sign_bytes(key.private_key, bundle_manifest_payload(manifest))
        _write_json(
            bundle / "manifest.sig.json",
            {
                "schema_version": "1.0",
                "key_id": key.key_id,
                "alg": "Ed25519",
                "key_fingerprint": key.fingerprint,
                "signature": signature,
            },
        )
        return manifest

    @staticmethod
    def _readme() -> str:
        return (
            "# ResearchFlow Evidence Bundle\n\n"
            "This directory is an offline evidence bundle exported by the ResearchFlow T0 product.\n\n"
            "## Verify it\n\n"
            "1. Copy `verify_bundle.py` from a **trusted, already verified** ResearchFlow source tree\n"
            "   (never run a verifier that came with an untrusted bundle).\n"
            "2. Obtain the trust anchor (public key + fingerprint) from **outside** this bundle.\n"
            "3. Run:\n\n"
            "   ```\n"
            "   python verify_bundle.py --bundle <this directory> --trust-store <trust_anchor.json>\n"
            "   ```\n\n"
            "Expected: exit code 0 and `{\"status\": \"VERIFIED\"}` with the recomputed Merkle root.\n\n"
            "## Contents\n\n"
            "- `task.json`, `nodes.json`, `graph.json`: the task, node states and the static DAG.\n"
            "- `evidence/records.jsonl`: the E0–E3 hash chain.\n"
            "- `evidence/payloads/<sha256>.json`: content-addressed payload bytes.\n"
            "- `evidence/invalidations.json`: stale evidence (kept, never deleted).\n"
            "- `artifacts/<node>/<attempt>/...`: the observed artifacts.\n"
            "- `attempts/<node>/<attempt>/result.json`: executor observations.\n"
            "- `report.json`, `certificate.json`: the signed VerificationReport and CompletionCertificate.\n"
            "- `ruleset.json`: the frozen ruleset the Gate must be re-evaluated against.\n"
            "- `manifest.json` + `manifest.sig.json`: file hashes and the signed manifest.\n\n"
            "The bundle contains no private key and no trust anchor.\n"
        )