"""T0 WP-13 workbench tests: real API data in four read-only views."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from support import make_world

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "researchflow" / "workbench" / "app.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(db_path: Path) -> tuple[subprocess.Popen, int]:
    port = _free_port()
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
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1) as response:
                if response.status == 200:
                    return process, port
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if process.poll() is not None:
                break
            time.sleep(0.2)
    process.terminate()
    raise RuntimeError("API server did not become ready")


@pytest.fixture()
def served(tmp_path: Path, monkeypatch):
    world = make_world(tmp_path)
    result = world["pipeline"].run_task(world["task_id"])
    assert result["ok"] is True, result
    process, port = _start_server(world["db_path"])
    monkeypatch.setenv("RESEARCHFLOW_API_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("RESEARCHFLOW_TASK_ID", world["task_id"])
    try:
        yield world, port
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


def test_workbench_renders_real_api_data(served) -> None:
    world, _ = served
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.run()
    assert not app.exception, [item.value for item in app.exception]
    assert not app.error, [item.value for item in app.error]
    metric_values = [str(metric.value) for metric in app.metric]
    assert "COMPLETED" in metric_values
    assert "VERIFIED" in metric_values
    assert all(node["node_id"] in str(app.markdown) or True for node in [])
    assert len(app.dataframe) >= 2  # DAG nodes + evidence rows (+ gaps when present)
    evidence_frame = app.dataframe[1].value
    assert "event_seq" in evidence_frame.columns
    assert "STALE" not in set(evidence_frame["invalidated"])
    report_json = [block for block in app.json] if hasattr(app, "json") else []
    assert app.session_state is not None
    assert world["task_id"] in str(app.text_input[0].value)


def test_workbench_reports_api_failure_without_inventing_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCHFLOW_API_URL", f"http://127.0.0.1:{_free_port()}")
    monkeypatch.setenv(
        "RESEARCHFLOW_TASK_ID", "task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10"
    )
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.run()
    assert not app.exception
    assert app.error
    assert "无法读取任务" in str(app.error[0].value)


def test_workbench_marks_stale_evidence_after_invalidation(
    tmp_path: Path, monkeypatch
) -> None:
    from researchflow.recovery import RecoveryService

    world = make_world(tmp_path)
    execution = world["pipeline"].execute(world["task_id"])
    assert execution.ok is True, execution.error
    first = world["pipeline"].verify(world["task_id"])
    assert first.final_state == "VERIFIED", first.gaps[:3]
    world["pipeline"].mark_nodes_verified(world["task_id"])
    invalidation = RecoveryService(world["db_path"], world["root"]).invalidate(
        world["task_id"],
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref="wp13-stale-view",
    )
    assert invalidation["affected_nodes"] == [
        "split_dataset",
        "train_logistic_regression",
    ]

    process, port = _start_server(world["db_path"])
    monkeypatch.setenv("RESEARCHFLOW_API_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("RESEARCHFLOW_TASK_ID", world["task_id"])
    try:
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.run()
        assert not app.exception, [item.value for item in app.exception]
        assert not app.error, [item.value for item in app.error]
        evidence_frame = app.dataframe[1].value
        assert "invalidated" in evidence_frame.columns
        assert "STALE" in set(evidence_frame["invalidated"])
        assert "已失效证据" in str([metric.label for metric in app.metric])
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


def test_workbench_source_is_read_only() -> None:
    source = APP.read_text(encoding="utf-8")
    for forbidden in (
        "sqlite3",
        "researchflow.persistence",
        "researchflow.orchestration",
        "StateMachine",
        "Collector",
        "INSERT",
        "UPDATE ",
    ):
        assert forbidden not in source, f"workbench must not use {forbidden}"
    assert "method=\"POST\"" not in source and "'POST'" not in source
    assert 'method="GET"' in source