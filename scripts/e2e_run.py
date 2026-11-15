"""Run the T0 offline end-to-end scenario three times in isolated directories.

Each run performs the real user path:

1. start the API on loopback (no token, no outbound network);
2. ``POST /api/v1/tasks`` (idempotency key recorded);
3. internal orchestration executes the DAG (split + two classifiers in parallel);
4. ``POST /verify`` produces a signed report and certificate;
5. an input change invalidates the verified nodes, freezes a deterministic plan
   and re-runs the affected nodes conservatively;
6. the task is verified again, completed, exported as an Evidence Bundle;
7. the bundle is verified offline from an isolated directory with its own copy
   of ``verify_bundle.py`` and an external trust anchor.

Every HTTP call, attempt, plan, report, certificate and verifier run is written
under ``docs/verification/t0/e2e/run_N/`` and never overwritten.

Usage::

    python scripts/e2e_run.py                    # three runs
    python scripts/e2e_run.py --runs 1 --out runtime/e2e-dev
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests" / "t0") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "t0"))

from researchflow.contracts.encoding import hash_payload  # noqa: E402
from researchflow.contracts.models import TaskSpecCreate  # noqa: E402
from researchflow.evidence import Collector  # noqa: E402
from researchflow.execution.env import code_hash  # noqa: E402
from researchflow.orchestration.creation import TaskCreationService  # noqa: E402
from researchflow.orchestration.sqlite_ports import build_ports  # noqa: E402
from researchflow.orchestration.state_machine import StateMachine  # noqa: E402
from researchflow.persistence.db import connect  # noqa: E402
from researchflow.persistence.migrations import MigrationRunner  # noqa: E402
from researchflow.pipeline import TaskPipeline  # noqa: E402
from researchflow.recovery import RecoveryService  # noqa: E402
from researchflow.rules import RULESET_HASH, RULESET_VERSION  # noqa: E402
from researchflow.signing import KeyStore  # noqa: E402
from support import task_payload  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "verification" / "t0" / "e2e"
MODELS = ("logistic_regression", "random_forest")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class HttpLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("", encoding="utf-8")

    def call(self, method: str, url: str, payload: dict | None = None, headers: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = {"Accept": "application/json"}
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        status = 0
        body: object = None
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                status = response.status
                raw = response.read().decode("utf-8")
                body = json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8")
            body = json.loads(raw) if raw else None
        record = {
            "at": _now(),
            "method": method,
            "url": url,
            "request": payload,
            "status": status,
            "response": body,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return status, body


def _wait_ready(port: int, process: subprocess.Popen, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("API server exited before becoming ready")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError("API server did not become ready")


def run_once(index: int, out_root: Path) -> dict:
    run_dir = out_root / f"run_{index}"
    if run_dir.exists():
        raise SystemExit(
            f"refusing to overwrite existing evidence directory: {run_dir} "
            "(move it away or choose a different --out)"
        )
    data_dir = run_dir / "data"
    runtime = run_dir / "runtime"
    logs = run_dir / "logs"
    for directory in (data_dir, runtime, logs):
        directory.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_template_dataset as btd

    started_at = _now()
    dataset_v1 = btd.write_dataset(data_dir, 20261114)
    v1_sha = dataset_v1["datasets"]["local://datasets/synthetic_breast_cancer.csv"]["sha256"]

    db_path = runtime / "researchflow.db"
    connection = connect(db_path)
    MigrationRunner().upgrade(connection)
    connection.close()

    environment = dict(os.environ)
    environment["RESEARCHFLOW_DATA_ROOT"] = str(data_dir.resolve())
    environment.pop("RESEARCHFLOW_API_TOKEN", None)
    environment["HTTP_PROXY"] = "http://127.0.0.1:9"
    environment["HTTPS_PROXY"] = "http://127.0.0.1:9"
    environment["ALL_PROXY"] = "http://127.0.0.1:9"
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["RESEARCHFLOW_DATA_ROOT"] = str(data_dir.resolve())

    port = _free_port()
    server_log = (logs / "server.log").open("w", encoding="utf-8")
    server_error = (logs / "server_error.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "researchflow.cli",
            "serve",
            "--db",
            str(db_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=server_log,
        stderr=server_error,
        cwd=str(ROOT),
        env=environment,
    )
    base_url = f"http://127.0.0.1:{port}"
    http = HttpLog(logs / "http.jsonl")
    try:
        _wait_ready(port, server)
        _write_json(logs / "environment.json", {
            "run": index,
            "started_at": started_at,
            "interpreter": sys.version,
            "platform": platform.platform(),
            "api_base": base_url,
            "declared_max_workers": 2,
            "ruleset_hash": RULESET_HASH,
            "ruleset_version": RULESET_VERSION,
            "code_hash": code_hash(),
            "dataset_sha256_v1": v1_sha,
            "offline_controls": {
                "proxies_blackholed": True,
                "no_token": True,
                "loopback_only": True,
                "model_provider": "none (T0 has no LLM client)",
            },
        })

        idempotency_key = f"e2e-{index}-{uuid.uuid4().hex[:12]}"
        status, created = http.call(
            "POST",
            f"{base_url}/api/v1/tasks",
            task_payload(models=MODELS, include_task_id=False),
            {"Idempotency-Key": idempotency_key},
        )
        if status != 201 or not created:
            raise RuntimeError(f"task creation failed: HTTP {status} {created}")
        task_id = created["task_id"]

        pipeline = TaskPipeline(db_path, runtime)
        state_machine = StateMachine(db_path, ports=build_ports(db_path, runtime))
        collector = Collector(db_path, runtime)

        execution = pipeline.execute(task_id)
        _write_json(logs / "execution.json", execution.to_dict())
        if not execution.ok:
            raise RuntimeError(f"execution failed: {execution.error}")

        status, verify1 = http.call("POST", f"{base_url}/api/v1/tasks/{task_id}/verify", {"mode": "full"})
        _write_json(logs / "verify_1.json", {"status": status, "body": verify1})
        if status != 200 or verify1["final_state"] != "VERIFIED":
            raise RuntimeError(f"first verification failed: HTTP {status} {verify1}")

        pipeline.mark_nodes_verified(task_id)
        status, graph_after_verify = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}/graph")
        _write_json(logs / "graph_after_verify_1.json", graph_after_verify)

        dataset_v2 = btd.write_dataset(data_dir, 7)
        v2_sha = dataset_v2["datasets"]["local://datasets/synthetic_breast_cancer.csv"]["sha256"]
        recovery = RecoveryService(db_path, runtime)
        invalidation = recovery.invalidate(
            task_id,
            changed_node="split_dataset",
            cause_type="INPUT_CHANGE",
            cause_ref=v2_sha,
            new_dataset_sha256=v2_sha,
        )
        _write_json(logs / "invalidation.json", invalidation)

        status, graph_stale = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}/graph")
        _write_json(logs / "graph_after_invalidation.json", graph_stale)
        status, evidence_stale = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}/evidence?limit=200")
        _write_json(logs / "evidence_after_invalidation.json", {
            "status": status,
            "count": evidence_stale["count"],
            "chain": evidence_stale["chain"],
            "invalidated_evidence_ids": evidence_stale["invalidated_evidence_ids"],
            "levels": [item["level"] for item in evidence_stale["items"]],
        })

        rerun = recovery.rerun(task_id, invalidation["plan_hash"])
        _write_json(logs / "rerun.json", rerun)

        status, verify2 = http.call("POST", f"{base_url}/api/v1/tasks/{task_id}/verify", {"mode": "full"})
        _write_json(logs / "verify_2.json", {"status": status, "body": verify2})
        if status != 200 or verify2["final_state"] != "VERIFIED":
            raise RuntimeError(f"second verification failed: HTTP {status} {verify2}")

        pipeline.mark_nodes_verified(task_id)
        pipeline.complete_task(task_id)

        status, task_view = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}")
        _write_json(logs / "task.json", task_view)
        status, graph_view = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}/graph")
        _write_json(logs / "graph.json", graph_view)
        status, evidence_view = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}/evidence?limit=200")
        _write_json(logs / "evidence.json", evidence_view)
        status, report_view = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}/report")
        _write_json(logs / "report.json", report_view)
        status, certificate_view = http.call("GET", f"{base_url}/api/v1/tasks/{task_id}/certificate")
        _write_json(logs / "certificate.json", certificate_view)
        if task_view["state"] != "COMPLETED":
            raise RuntimeError(f"task did not complete: {task_view['state']}")

        store = KeyStore(runtime / "keys")
        store.load_or_create()
        trust_store = run_dir / "trust_store.json"
        store.write_trust_anchor(trust_store)

        from researchflow.bundle import BundleExporter

        bundle_dir = run_dir / "bundle"
        manifest = BundleExporter(db_path, runtime).export(
            task_id, bundle_dir, trust_anchor_path=trust_store
        )

        isolated = run_dir / "isolated-verifier"
        isolated.mkdir()
        shutil.copyfile(ROOT / "verify_bundle.py", isolated / "verify_bundle.py")
        shutil.copytree(bundle_dir, isolated / "bundle")
        shutil.copyfile(trust_store, isolated / "trust_store.json")
        verify_completed = subprocess.run(
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
            timeout=600,
        )
        (logs / "verify_bundle.stdout.log").write_text(verify_completed.stdout, encoding="utf-8")
        (logs / "verify_bundle.stderr.log").write_text(verify_completed.stderr, encoding="utf-8")
        verify_summary = (
            json.loads(verify_completed.stdout.strip().splitlines()[-1])
            if verify_completed.stdout.strip()
            else {}
        )
        _write_json(logs / "verify_bundle.json", {
            "exit_code": verify_completed.returncode,
            "summary": verify_summary,
        })
        if verify_completed.returncode != 0 or verify_summary.get("status") != "VERIFIED":
            raise RuntimeError(
                f"offline verification failed: exit {verify_completed.returncode} {verify_summary}"
            )

        connection = connect(db_path)
        try:
            from researchflow.persistence.records import ReportRepository, list_evidence

            rows = list_evidence(connection, task_id)
            report = ReportRepository().latest_for_task(connection, task_id)
        finally:
            connection.close()
        chain = collector.verify_chain(task_id)
        completed_at = _now()
        summary = {
            "schema_version": "1.0",
            "run": index,
            "task_id": task_id,
            "idempotency_key": idempotency_key,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_sec": round(
                (
                    datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                    - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                ).total_seconds(),
                2,
            ),
            "dataset_sha256_v1": v1_sha,
            "dataset_sha256_v2": v2_sha,
            "final_task_state": task_view["state"],
            "final_report_state": report.final_state,
            "report_id": report.report_id,
            "certificate_id": certificate_view["cert_id"],
            "coverage": {
                "required": report.coverage_required,
                "passed": report.coverage_passed,
                "missing": report.coverage_missing,
            },
            "l3_coverage": report.l3_coverage,
            "evidence_total": len(rows),
            "evidence_invalidated": len(invalidation["invalidated_evidence"]),
            "chain_ok": chain.ok,
            "attempts": [item["attempt_id"] for item in rerun["attempts"]],
            "plan_hash": invalidation["plan_hash"],
            "merkle_root": report.evidence_root,
            "bundle_manifest_files": len(manifest["files"]),
            "bundle_verify_exit": verify_completed.returncode,
            "bundle_verify_status": verify_summary.get("status"),
            "bundle_verify_recomputed_root": verify_summary.get("merkle_root"),
            "bundle_verify_l3_coverage": verify_summary.get("l3_coverage"),
            "http_requests": sum(
                1 for _ in (logs / "http.jsonl").read_text(encoding="utf-8").splitlines()
            ),
        }
        _write_json(logs / "run_summary.json", summary)
        return summary
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover
            server.kill()
        server_log.close()
        server_error.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    summaries = []
    for index in range(1, args.runs + 1):
        print(f"=== e2e run {index} ===")
        summary = run_once(index, out_root)
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    comparable_keys = (
        "final_task_state",
        "final_report_state",
        "coverage",
        "l3_coverage",
        "evidence_total",
        "evidence_invalidated",
        "chain_ok",
        "attempts",
        "bundle_manifest_files",
        "bundle_verify_exit",
        "bundle_verify_status",
        "bundle_verify_l3_coverage",
    )
    normalized = [{key: summary[key] for key in comparable_keys} for summary in summaries]
    consistent = all(item == normalized[0] for item in normalized[1:])
    aggregate = {
        "schema_version": "1.0",
        "generated_at": _now(),
        "runs": summaries,
        "comparable_fields": list(comparable_keys),
        "consistent": consistent,
    }
    _write_json(out_root / "runs_summary.json", aggregate)
    print(json.dumps({"consistent": consistent, "runs": len(summaries)}, ensure_ascii=False))
    return 0 if consistent else 1


if __name__ == "__main__":
    sys.exit(main())
