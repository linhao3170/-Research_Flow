"""T0 WP-12 bundle tests: true bundle passes, tampering is rejected with the right cause."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from researchflow.bundle import BundleExporter
from researchflow.signing import KeyStore, sign_bytes
from researchflow.signing.keys import load_trust_anchor
from support import make_world

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "verify_bundle.py"


def _run_verify(bundle: Path, anchor: Path, *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-E", str(VERIFY), "--bundle", str(bundle), "--trust-store", str(anchor)],
        capture_output=True,
        text=True,
        cwd=str(cwd or ROOT),
        timeout=300,
    )


def _reject_code(completed: subprocess.CompletedProcess) -> str:
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["status"] == "REJECTED", completed.stdout
    return str(payload["code"])


@pytest.fixture(scope="module")
def bundle_world(tmp_path_factory):
    base = tmp_path_factory.mktemp("bundle-world")
    world = make_world(base)
    result = world["pipeline"].run_task(world["task_id"])
    assert result["ok"] is True, result
    store = KeyStore(world["root"] / "keys")
    store.load_or_create()
    anchor = base / "trust_store.json"
    store.write_trust_anchor(anchor)
    bundle = base / "bundle"
    BundleExporter(world["db_path"], world["root"]).export(
        world["task_id"], bundle, trust_anchor_path=anchor
    )
    return {
        **world,
        "base": base,
        "anchor": anchor,
        "bundle": bundle,
        "key": store.load(),
    }


def _copy_bundle(bundle_world, tmp_path: Path, name: str = "copy") -> Path:
    target = tmp_path / name
    shutil.copytree(bundle_world["bundle"], target)
    return target


def _update_manifest_and_sign(bundle: Path, key) -> None:
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = []
    for entry in manifest["files"]:
        path = bundle / entry["path"]
        import hashlib

        data = path.read_bytes()
        files.append(
            {
                "path": entry["path"],
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    manifest["files"] = files
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    from researchflow.bundle.export import BUNDLE_DOMAIN
    from researchflow.contracts.encoding import canonical_bytes
    from researchflow.bundle.export import BUNDLE_MANIFEST_FIELDS

    payload = BUNDLE_DOMAIN + canonical_bytes(
        {field: manifest[field] for field in BUNDLE_MANIFEST_FIELDS}
    )
    signature = sign_bytes(key.private_key, payload)
    signature_document = json.loads((bundle / "manifest.sig.json").read_text(encoding="utf-8"))
    signature_document["signature"] = signature
    (bundle / "manifest.sig.json").write_text(
        json.dumps(signature_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_true_bundle_verifies_offline(bundle_world) -> None:
    completed = _run_verify(bundle_world["bundle"], bundle_world["anchor"])
    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout.strip().splitlines()[-1])
    assert summary["status"] == "VERIFIED"
    assert summary["final_state"] == "VERIFIED"
    assert summary["trust_anchor_source"] == "external"
    assert summary["l3_coverage"] == 1.0
    assert summary["key_fingerprint"] == bundle_world["key"].fingerprint


def test_verifier_runs_from_an_isolated_directory(bundle_world, tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    shutil.copyfile(VERIFY, isolated / "verify_bundle.py")
    shutil.copytree(bundle_world["bundle"], isolated / "bundle")
    shutil.copyfile(bundle_world["anchor"], isolated / "trust_store.json")
    completed = subprocess.run(
        [
            sys.executable,
            "-E",
            str(isolated / "verify_bundle.py"),
            "--bundle",
            str(isolated / "bundle"),
            "--trust-store",
            str(isolated / "trust_store.json"),
        ],
        capture_output=True,
        text=True,
        cwd=str(isolated),
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1])["status"] == "VERIFIED"


def test_private_key_is_not_in_the_bundle(bundle_world) -> None:
    key = bundle_world["key"]
    seed_b64 = __import__("base64").b64encode(
        key.private_key.private_bytes_raw()
    ).decode("ascii")
    for path in bundle_world["bundle"].rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert seed_b64.encode() not in data, f"private key leaked into {path}"
            assert b"private_key_b64" not in data, f"private key document leaked into {path}"


def test_missing_file_is_rejected(bundle_world, tmp_path: Path) -> None:
    bundle = _copy_bundle(bundle_world, tmp_path)
    (bundle / "report.json").unlink()
    completed = _run_verify(bundle, bundle_world["anchor"])
    assert completed.returncode != 0
    assert _reject_code(completed) == "BUNDLE_FILE_MISSING"


def test_tampered_payload_is_rejected(bundle_world, tmp_path: Path) -> None:
    bundle = _copy_bundle(bundle_world, tmp_path)
    payloads = sorted((bundle / "evidence" / "payloads").glob("*.json"))
    payloads[0].write_bytes(b'{"tampered":true}')
    completed = _run_verify(bundle, bundle_world["anchor"])
    assert completed.returncode != 0
    assert _reject_code(completed) == "BUNDLE_TAMPERED"


def test_manifest_signature_tamper_is_rejected(bundle_world, tmp_path: Path) -> None:
    bundle = _copy_bundle(bundle_world, tmp_path)
    document = json.loads((bundle / "manifest.sig.json").read_text(encoding="utf-8"))
    signature = document["signature"]
    document["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    (bundle / "manifest.sig.json").write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    completed = _run_verify(bundle, bundle_world["anchor"])
    assert completed.returncode != 0
    assert _reject_code(completed) == "SIGNATURE_INVALID"


def test_trust_anchor_inside_bundle_is_rejected(bundle_world, tmp_path: Path) -> None:
    bundle = _copy_bundle(bundle_world, tmp_path)
    inside = bundle / "trust_store.json"
    shutil.copyfile(bundle_world["anchor"], inside)
    completed = _run_verify(bundle, inside)
    assert completed.returncode != 0
    assert _reject_code(completed) == "TRUST_ANCHOR_INSIDE_BUNDLE"


def test_wrong_trust_anchor_is_rejected(bundle_world, tmp_path: Path) -> None:
    other = KeyStore(tmp_path / "other-keys")
    other.generate()
    other_anchor = tmp_path / "other_anchor.json"
    other.write_trust_anchor(other_anchor)
    completed = _run_verify(bundle_world["bundle"], other_anchor)
    assert completed.returncode != 0
    assert _reject_code(completed) == "SIGNATURE_INVALID"


def test_tampered_report_signature_is_rejected(bundle_world, tmp_path: Path) -> None:
    bundle = _copy_bundle(bundle_world, tmp_path)
    report = json.loads((bundle / "report.json").read_text(encoding="utf-8"))
    signature = report["signature"]
    report["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    (bundle / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _update_manifest_and_sign(bundle, bundle_world["key"])
    completed = _run_verify(bundle, bundle_world["anchor"])
    assert completed.returncode != 0
    assert _reject_code(completed) == "SIGNATURE_INVALID"


def test_merkle_root_mismatch_is_rejected(bundle_world, tmp_path: Path) -> None:
    bundle = _copy_bundle(bundle_world, tmp_path)
    records_path = bundle / "evidence" / "records.jsonl"
    lines = records_path.read_text(encoding="utf-8").splitlines()
    records_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    _update_manifest_and_sign(bundle, bundle_world["key"])
    completed = _run_verify(bundle, bundle_world["anchor"])
    assert completed.returncode != 0
    assert _reject_code(completed) == "MERKLE_ROOT_MISMATCH"


def test_failed_report_export_has_no_certificate(tmp_path: Path) -> None:
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
    from researchflow.verification import VerificationService

    outcome = VerificationService(world["db_path"], world["root"]).verify(world["task_id"])
    assert outcome.certificate is None
    store = KeyStore(world["root"] / "keys")
    store.load_or_create()
    anchor = tmp_path / "trust_store.json"
    store.write_trust_anchor(anchor)
    bundle = tmp_path / "failed_bundle"
    BundleExporter(world["db_path"], world["root"]).export(world["task_id"], bundle)
    completed = _run_verify(bundle, anchor)
    assert completed.returncode != 0
    assert _reject_code(completed) == "CERTIFICATE_MISSING"