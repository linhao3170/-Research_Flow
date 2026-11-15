"""T0 API tests: read views, verification endpoint, startup guard, restart safety."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from researchflow.api.app import create_app
from researchflow.persistence.db import connect
from researchflow.persistence.records import CertificateRepository, ReportRepository
from support import make_db, make_world, task_payload

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _create(client: TestClient, models=("logistic_regression",)) -> str:
    response = client.post("/api/v1/tasks", json=task_payload(models=models, include_task_id=False))
    assert response.status_code == 201, response.text
    return response.json()["task_id"]


def test_health_ready_and_recover_route(tmp_path: Path) -> None:
    with TestClient(create_app(db_path=tmp_path / "api.db")) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 200
        assert client.post("/api/v1/tasks/task_x/recover").status_code == 404


def test_read_views_and_verify_endpoint(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime" / "researchflow.db"
    connection = make_db(db_path)
    connection.close()
    with TestClient(create_app(db_path=db_path)) as client:
        task_id = _create(client)
        # Before execution the graph is not registered yet.
        assert client.get(f"/api/v1/tasks/{task_id}/graph").status_code == 409
        assert client.get(f"/api/v1/tasks/{task_id}/report").status_code == 404
        assert client.get(f"/api/v1/tasks/{task_id}/certificate").status_code == 409

        from researchflow.pipeline import TaskPipeline

        pipeline = TaskPipeline(db_path, db_path.parent)
        execution = pipeline.execute(task_id)
        assert execution.ok is True, execution.error

        graph = client.get(f"/api/v1/tasks/{task_id}/graph")
        assert graph.status_code == 200, graph.text
        body = graph.json()
        assert body["graph_version"] == 1
        assert [node["node_id"] for node in body["nodes"]] == [
            "split_dataset",
            "train_logistic_regression",
        ]
        assert {node["state"] for node in body["nodes"]} == {"VERIFYING"}

        evidence = client.get(f"/api/v1/tasks/{task_id}/evidence")
        assert evidence.status_code == 200
        evidence_body = evidence.json()
        assert evidence_body["chain"]["ok"] is True
        assert evidence_body["count"] == len(evidence_body["items"])
        assert all(item["level"].startswith("E") for item in evidence_body["items"])
        assert client.get(f"/api/v1/tasks/{task_id}/evidence?limit=0").status_code == 422

        bad_mode = client.post(f"/api/v1/tasks/{task_id}/verify", json={"mode": "partial"})
        assert bad_mode.status_code == 422
        assert bad_mode.json()["field_path"] == "mode"
        bad_checks = client.post(
            f"/api/v1/tasks/{task_id}/verify", json={"requested_checks": ["L4"]}
        )
        assert bad_checks.status_code == 422
        assert bad_checks.json()["field_path"] == "requested_checks"

        verified = client.post(
            f"/api/v1/tasks/{task_id}/verify",
            json={"mode": "full", "requested_checks": ["L1", "L2", "L3"]},
        )
        assert verified.status_code == 200, verified.text
        verified_body = verified.json()
        assert verified_body["final_state"] == "VERIFIED"
        assert verified_body["gaps"] == []
        assert verified_body["certificate_id"]

        report = client.get(f"/api/v1/tasks/{task_id}/report")
        assert report.status_code == 200
        assert report.json()["final_state"] == "VERIFIED"
        assert report.json()["report"]["required_check_coverage"] == {
            "required": 5,
            "passed": 5,
            "missing": 0,
        }

        certificate = client.get(f"/api/v1/tasks/{task_id}/certificate")
        assert certificate.status_code == 200
        assert certificate.json()["cert_id"] == verified_body["certificate_id"]
        assert certificate.json()["alg"] == "Ed25519"

        pipeline.mark_nodes_verified(task_id)
        pipeline.complete_task(task_id)
        assert client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "COMPLETED"
        repeated = client.post(f"/api/v1/tasks/{task_id}/verify", json={})
        assert repeated.status_code == 409
        assert repeated.json()["error_code"] == "STATE_TRANSITION_DENIED"


def test_restart_keeps_unfinished_state_and_issues_no_duplicate_certificate(
    tmp_path: Path,
) -> None:
    world = make_world(tmp_path)
    task_id = world["task_id"]
    execution = world["pipeline"].execute(task_id)
    assert execution.ok is True

    # A fresh application instance (process-level restart analogue) must not
    # turn VERIFYING into COMPLETED and must not have issued a certificate.
    with TestClient(create_app(db_path=world["db_path"])) as client:
        assert client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "VERIFYING"
        assert client.get(f"/api/v1/tasks/{task_id}/report").status_code == 404
        assert client.get(f"/api/v1/tasks/{task_id}/certificate").status_code == 409
        verified = client.post(f"/api/v1/tasks/{task_id}/verify", json={})
        assert verified.status_code == 200
        assert verified.json()["final_state"] == "VERIFIED"

    world["pipeline"].mark_nodes_verified(task_id)
    world["pipeline"].complete_task(task_id)
    world["pipeline"].complete_task(task_id)  # idempotent, no second certificate

    connection = connect(world["db_path"])
    try:
        reports = connection.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE task_id = ?", (task_id,)
        ).fetchone()["n"]
        certificates = connection.execute(
            "SELECT COUNT(*) AS n FROM certificates", ()
        ).fetchone()["n"]
        from researchflow.persistence.repositories import TaskRepository

        state = TaskRepository().get(connection, task_id).state
    finally:
        connection.close()
    assert state == "COMPLETED"
    assert reports == 1
    assert certificates == 1


def test_startup_guard_refuses_non_loopback_without_token(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime" / "guard.db"
    connection = make_db(db_path)
    connection.close()
    port = _free_port()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"RESEARCHFLOW_API_TOKEN"}
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "researchflow.cli",
            "serve",
            "--db",
            str(db_path),
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
        env=environment,
    )
    assert completed.returncode != 0
    assert "non-loopback bind requires token" in completed.stderr
    assert "RESEARCHFLOW_API_TOKEN" not in completed.stderr
    with pytest.raises(OSError):
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    connection = connect(db_path)
    try:
        row = connection.execute(
            "SELECT result, error_code FROM audit_log WHERE action = 'STARTUP_GUARD'"
        ).fetchone()
        tasks = connection.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    finally:
        connection.close()
    assert row["result"] == "DENIED"
    assert row["error_code"] == "NON_LOOPBACK_BIND_REQUIRES_TOKEN"
    assert tasks == 0


def test_startup_guard_allows_token_and_serves(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime" / "serve.db"
    connection = make_db(db_path)
    connection.close()
    port = _free_port()
    environment = dict(os.environ)
    environment["RESEARCHFLOW_API_TOKEN"] = "test-token-value"
    process = subprocess.Popen(
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
        env=environment,
    )
    try:
        deadline = time.time() + 60
        status = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/readyz", timeout=1
                ) as response:
                    status = response.status
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.2)
        assert status == 200
        connection = connect(db_path)
        try:
            result = connection.execute(
                "SELECT result FROM audit_log WHERE action = 'STARTUP_GUARD' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()["result"]
        finally:
            connection.close()
        assert result == "OK"
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()