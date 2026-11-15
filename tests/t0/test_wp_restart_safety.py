"""A-02: restart safety after a real kill and recovery refusal negatives.

The restart test starts the product CLI as an independent process, interrupts it
at a deterministic checkpoint (split attempt finished, train attempt running),
kills the whole process tree, and then uses *new* processes to read the real
SQLite database, attempt directories and evidence.  It asserts that ``RUNNING``
is not turned into ``COMPLETED`` and that no report/certificate is issued.

The recovery negatives prove that T0 refuses to schedule recovery when the
evidence chain is broken or the current attempt's required evidence is missing,
and that the refusal names the concrete L1 reason.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from researchflow.evidence import Collector
from researchflow.persistence.db import connect
from researchflow.recovery import RecoveryError, RecoveryService
from support import make_world

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).resolve().parent / "restart_probe.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _readonly(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _snapshot(db_path: Path, root: Path, task_id: str) -> dict:
    connection = _readonly(db_path)
    try:
        task = connection.execute(
            "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        nodes = {
            str(row["node_id"]): {
                "state": str(row["state"]),
                "attempt_seq": int(row["attempt_seq"]),
            }
            for row in connection.execute(
                "SELECT node_id, state, attempt_seq FROM nodes WHERE task_id = ?",
                (task_id,),
            )
        }
        reports = int(
            connection.execute(
                "SELECT COUNT(*) AS n FROM reports WHERE task_id = ?", (task_id,)
            ).fetchone()["n"]
        )
        certificates = int(
            connection.execute("SELECT COUNT(*) AS n FROM certificates").fetchone()["n"]
        )
    finally:
        connection.close()
    attempts = []
    base = root / "tasks" / task_id / "attempts"
    if base.is_dir():
        for node_dir in base.iterdir():
            if not node_dir.is_dir():
                continue
            for attempt_dir in node_dir.iterdir():
                if not attempt_dir.is_dir():
                    continue
                attempts.append(
                    {
                        "node_id": node_dir.name,
                        "attempt_id": attempt_dir.name,
                        "job_present": (attempt_dir / "job.json").is_file(),
                        "result_present": (attempt_dir / "result.json").is_file(),
                    }
                )
    return {
        "task_state": None if task is None else str(task["state"]),
        "nodes": nodes,
        "reports": reports,
        "certificates": certificates,
        "attempts": attempts,
    }


def _interrupted_checkpoint(
    db_path: Path, root: Path, task_id: str, process: subprocess.Popen, timeout: float
) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return None
        try:
            snapshot = _snapshot(db_path, root, task_id)
        except sqlite3.OperationalError:
            time.sleep(0.05)
            continue
        if snapshot["task_state"] != "RUNNING":
            time.sleep(0.01)
            continue
        split = snapshot["nodes"].get("split_dataset", {})
        if split.get("state") not in {"VERIFYING", "VERIFIED"}:
            time.sleep(0.01)
            continue
        for node_id, node in snapshot["nodes"].items():
            if not node_id.startswith("train_") or node["state"] != "RUNNING":
                continue
            attempt_dir = (
                root / "tasks" / task_id / "attempts" / node_id
                / f"attempt_{node['attempt_seq']:02d}"
            )
            if (attempt_dir / "job.json").is_file() and not (
                attempt_dir / "result.json"
            ).is_file():
                return {
                    "node_id": node_id,
                    "attempt_dir": attempt_dir,
                    "snapshot": snapshot,
                }
        time.sleep(0.01)
    return None


def _kill_tree(process: subprocess.Popen) -> None:
    completed = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    try:
        process.communicate(timeout=60)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()
        process.communicate()


def _run_probe(db_path: Path, root: Path, task_id: str) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(PROBE),
            "--db",
            str(db_path),
            "--root",
            str(root),
            "--task",
            task_id,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def _http(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _wait_ready(port: int, process: subprocess.Popen, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"server exited early: {stdout}\n{stderr}")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/readyz", timeout=1
            ) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.2)
    raise AssertionError("server did not become ready")


def _start_server(db_path: Path, port: int) -> subprocess.Popen:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "RESEARCHFLOW_API_TOKEN"
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "researchflow.cli",
            "serve",
            "--db",
            str(db_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process


def _stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()
        process.wait(timeout=30)


def test_kill_restart_keeps_running_and_issues_no_certificate(tmp_path: Path) -> None:
    checkpoint = None
    world = None
    process = None
    for attempt in range(2):
        world = make_world(
            tmp_path / f"kill-{attempt}",
            models=("logistic_regression", "random_forest"),
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "researchflow.cli",
                "run-task",
                "--db",
                str(world["db_path"]),
                "--task",
                world["task_id"],
            ],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        checkpoint = _interrupted_checkpoint(
            world["db_path"], world["root"], world["task_id"], process, timeout=120
        )
        if checkpoint is not None:
            break
        process.kill()
        process.communicate()
        process = None
    assert checkpoint is not None, "could not interrupt at a partial-attempt checkpoint"
    assert process is not None and world is not None

    # The split attempt is complete; the interrupted train attempt is in flight.
    split_attempt = world["root"] / "tasks" / world["task_id"] / "attempts" / "split_dataset" / "attempt_01"
    assert (split_attempt / "result.json").is_file()
    assert (checkpoint["attempt_dir"] / "job.json").is_file()
    assert not (checkpoint["attempt_dir"] / "result.json").is_file()

    _kill_tree(process)

    probe = _run_probe(world["db_path"], world["root"], world["task_id"])
    assert probe["task_state"] == "RUNNING"
    assert probe["reports"] == 0
    assert probe["certificates"] == 0
    assert probe["evidence_count"] > 0
    assert probe["nodes"]["split_dataset"]["state"] in {"VERIFYING", "VERIFIED"}
    assert probe["nodes"][checkpoint["node_id"]]["state"] == "RUNNING"
    assert probe["live_task_processes"] == []
    assert any(
        item["result_present"] and item["node_id"] == "split_dataset"
        for item in probe["attempts"]
    )
    assert any(
        item["job_present"]
        and not item["result_present"]
        and item["node_id"] == checkpoint["node_id"]
        for item in probe["attempts"]
    )

    # A second, independent product process serves the same SQLite/evidence.
    port = _free_port()
    server = _start_server(world["db_path"], port)
    try:
        _wait_ready(port, server)
        base = f"http://127.0.0.1:{port}"
        status, task_body = _http(
            "GET", f"{base}/api/v1/tasks/{world['task_id']}"
        )
        assert status == 200 and task_body["state"] == "RUNNING"

        status, graph_body = _http(
            "GET", f"{base}/api/v1/tasks/{world['task_id']}/graph"
        )
        assert status == 200
        graph_states = {node["node_id"]: node["state"] for node in graph_body["nodes"]}
        assert graph_states[checkpoint["node_id"]] == "RUNNING"
        assert graph_states["split_dataset"] in {"VERIFYING", "VERIFIED"}

        status, evidence_body = _http(
            "GET", f"{base}/api/v1/tasks/{world['task_id']}/evidence"
        )
        assert status == 200
        assert evidence_body["chain"]["ok"] is True
        assert evidence_body["count"] > 0

        status, _ = _http("GET", f"{base}/api/v1/tasks/{world['task_id']}/report")
        assert status == 404
        status, certificate_body = _http(
            "GET", f"{base}/api/v1/tasks/{world['task_id']}/certificate"
        )
        assert status == 409
        assert certificate_body["error_code"] == "CERTIFICATE_NOT_AVAILABLE"

        status, verify_body = _http(
            "POST", f"{base}/api/v1/tasks/{world['task_id']}/verify", {}
        )
        assert status == 409
        assert verify_body["error_code"] == "STATE_TRANSITION_DENIED"
        assert "VERIFYING" in verify_body["message"]
    finally:
        _stop_server(server)

    after = _run_probe(world["db_path"], world["root"], world["task_id"])
    assert after["task_state"] == "RUNNING"
    assert after["reports"] == 0
    assert after["certificates"] == 0
    assert after["live_task_processes"] == []


@pytest.fixture()
def verified_world(tmp_path: Path):
    world = make_world(tmp_path)
    execution = world["pipeline"].execute(world["task_id"])
    assert execution.ok is True, execution.error
    outcome = world["pipeline"].verify(world["task_id"])
    assert outcome.final_state == "VERIFIED", outcome.gaps[:3]
    world["pipeline"].mark_nodes_verified(world["task_id"])
    world["recovery"] = RecoveryService(world["db_path"], world["root"])
    return world


def _node_states(world) -> dict[str, str]:
    connection = connect(world["db_path"])
    try:
        return {
            str(row["node_id"]): str(row["state"])
            for row in connection.execute(
                "SELECT node_id, state FROM nodes WHERE task_id = ?",
                (world["task_id"],),
            )
        }
    finally:
        connection.close()


def _freeze_rows(world) -> int:
    connection = connect(world["db_path"])
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) AS n FROM audit_log "
                "WHERE action IN ('RECOVERY_PLAN_FROZEN','RECOVERY_PLAN_REUSE')"
            ).fetchone()["n"]
        )
    finally:
        connection.close()


def _break_chain(world) -> str:
    collector = Collector(world["db_path"], world["root"])
    assert collector.verify_chain(world["task_id"]).ok is True
    row = collector.rows(world["task_id"])[-1]
    payload = (
        world["root"] / "tasks" / world["task_id"] / "evidence_payloads"
        / f"{row.payload_hash}.json"
    )
    payload.unlink()
    chain = collector.verify_chain(world["task_id"])
    assert chain.ok is False
    assert "CHAIN_PAYLOAD_MISSING" in {issue.code for issue in chain.issues}
    return row.payload_hash


def test_recovery_refuses_broken_chain_before_invalidate(verified_world) -> None:
    world = verified_world
    _break_chain(world)
    with pytest.raises(RecoveryError) as excinfo:
        world["recovery"].invalidate(
            world["task_id"],
            changed_node="split_dataset",
            cause_type="INPUT_CHANGE",
            cause_ref="broken-chain",
        )
    assert excinfo.value.code == "RECOVERY_NOT_SAFE"
    assert "L1_CHAIN_PAYLOAD_MISSING" in excinfo.value.detail
    assert set(_node_states(world).values()) == {"VERIFIED"}
    assert _freeze_rows(world) == 0


def test_recovery_refuses_missing_attempt_evidence_before_invalidate(
    verified_world,
) -> None:
    world = verified_world
    (
        world["root"] / "tasks" / world["task_id"] / "attempts"
        / "split_dataset" / "attempt_01" / "result.json"
    ).unlink()
    with pytest.raises(RecoveryError) as excinfo:
        world["recovery"].invalidate(
            world["task_id"],
            changed_node="split_dataset",
            cause_type="INPUT_CHANGE",
            cause_ref="missing-result",
        )
    assert excinfo.value.code == "RECOVERY_NOT_SAFE"
    assert "L1_ATTEMPT_RESULT_MISSING" in excinfo.value.detail
    assert set(_node_states(world).values()) == {"VERIFIED"}
    assert _freeze_rows(world) == 0


def test_rerun_refuses_broken_chain(verified_world) -> None:
    world = verified_world
    invalidation = world["recovery"].invalidate(
        world["task_id"],
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref="valid-invalidation",
    )
    assert set(_node_states(world).values()) == {"INVALIDATED"}
    _break_chain(world)
    with pytest.raises(RecoveryError) as excinfo:
        world["recovery"].rerun(world["task_id"], invalidation["plan_hash"])
    assert excinfo.value.code == "RECOVERY_NOT_SAFE"
    assert "L1_CHAIN_PAYLOAD_MISSING" in excinfo.value.detail
    assert set(_node_states(world).values()) == {"INVALIDATED"}
    attempt_02 = list(
        (world["root"] / "tasks" / world["task_id"] / "attempts").glob(
            "*/attempt_02"
        )
    )
    assert attempt_02 == []