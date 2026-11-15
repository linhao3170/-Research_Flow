"""Capture the four real-data workbench screenshots and the API-down view.

Evidence tooling for WP-13/A-03.  It copies the completed run_1 task database
and its evidence payloads into an ignored ``runtime/`` directory, starts the
real API server and the real Streamlit workbench as separate processes, and
drives headless Chrome against the four view URLs plus one API-unreachable run.

The historical ``docs/verification/t0/e2e/run_1`` tree is never modified: only
a copy is used, and the copy contains no private keys.

Run from the repository root with the project interpreter::

    D:\\ResearchFlow-project\\.venv\\Scripts\\python.exe -B \
        docs/verification/t0/wp-13/capture_screenshots.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cdp_capture import CDPChrome, find_browser as find_cdp_browser

ROOT = Path(__file__).resolve().parents[4]
SOURCE_RUNTIME = (
    ROOT
    / "docs"
    / "verification"
    / "t0"
    / "e2e"
    / "superseded_2026-11-15_pre_a01"
    / "run_1"
    / "runtime"
)
OUT_DIR = ROOT / "docs" / "verification" / "t0" / "wp-13"
SHOT_DIR = OUT_DIR / "screenshots"
CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"process exited early: {stdout}\n{stderr}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError(f"timed out waiting for {url}")


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()
        process.wait(timeout=30)


def _find_browser() -> Path:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise RuntimeError("no headless Chrome/Edge found")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image_info(path: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        gray = image.convert("L")
        histogram = gray.histogram()
        total = sum(histogram)
        nonwhite = sum(histogram[:-8]) / total if total else 0.0
        low, high = gray.getextrema()
        return {
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "luma_min": low,
            "luma_max": high,
            "nonwhite_fraction": round(nonwhite, 4),
        }


def _browser_flags(profile: Path, window: tuple[int, int], virtual_time_ms: int) -> list[str]:
    return [
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        "--disable-background-networking",
        "--run-all-compositor-stages-before-draw",
        f"--user-data-dir={profile}",
        f"--window-size={window[0]},{window[1]}",
        f"--virtual-time-budget={virtual_time_ms}",
    ]


def _dump_dom(
    browser: Path,
    url: str,
    target: Path,
    expected: list[str],
    *,
    window: tuple[int, int] = (1440, 1200),
    virtual_time_ms: int = 20000,
) -> dict[str, Any]:
    profile = ROOT / "runtime" / f"chrome-dom-{uuid.uuid4().hex[:8]}"
    command = [
        str(browser),
        *_browser_flags(profile, window, virtual_time_ms),
        "--dump-dom",
        url,
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(ROOT),
    )
    shutil.rmtree(profile, ignore_errors=True)
    text = completed.stdout
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    missing = [item for item in expected if item not in text]
    return {
        "command": command,
        "exit_code": completed.returncode,
        "duration_sec": round(time.perf_counter() - started, 3),
        "target": str(target.relative_to(ROOT)),
        "bytes": len(text.encode("utf-8")),
        "expected": expected,
        "missing": missing,
    }


def _screenshot(
    browser: Path,
    url: str,
    target: Path,
    *,
    window: tuple[int, int] = (1440, 1200),
    virtual_time_ms: int = 20000,
) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    profile = ROOT / "runtime" / f"chrome-profile-{uuid.uuid4().hex[:8]}"
    command = [
        str(browser),
        *_browser_flags(profile, window, virtual_time_ms),
        f"--screenshot={target}",
        url,
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(ROOT),
    )
    elapsed = round(time.perf_counter() - started, 3)
    if target.is_file():
        shutil.rmtree(profile, ignore_errors=True)
        return {
            "command": command,
            "exit_code": completed.returncode,
            "duration_sec": elapsed,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-4000:],
            "target": str(target.relative_to(ROOT)),
            "sha256": _sha256(target),
            "bytes": target.stat().st_size,
            **_image_info(target),
        }
    shutil.rmtree(profile, ignore_errors=True)
    raise RuntimeError(
        f"browser produced no screenshot for {url}\n"
        f"exit={completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )


def _prepare_runtime() -> tuple[Path, str]:
    runtime = ROOT / "runtime" / "wp13-screenshots"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    source_db = SOURCE_RUNTIME / "researchflow.db"
    target_db = runtime / "researchflow.db"
    shutil.copy2(source_db, target_db)
    connection = sqlite3.connect(f"file:{target_db.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        task_id = str(
            connection.execute(
                "SELECT task_id FROM tasks ORDER BY rowid LIMIT 1"
            ).fetchone()["task_id"]
        )
    finally:
        connection.close()
    source_payloads = (
        SOURCE_RUNTIME / "tasks" / task_id / "evidence_payloads"
    )
    target_payloads = runtime / "tasks" / task_id / "evidence_payloads"
    shutil.copytree(source_payloads, target_payloads)
    return runtime, task_id


def _start_ui(
    port: int,
    api_url: str,
    task_id: str,
    timeout_sec: float,
    log_path: Path,
):
    environment = dict(os.environ)
    environment["RESEARCHFLOW_API_URL"] = api_url
    environment["RESEARCHFLOW_TASK_ID"] = task_id
    environment["RESEARCHFLOW_API_TIMEOUT"] = str(timeout_sec)
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["no_proxy"] = "127.0.0.1,localhost"
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "streamlit",
            "run",
            "researchflow/workbench/app.py",
            "--server.headless=true",
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none",
        ],
        cwd=str(ROOT),
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log


def main() -> int:
    started_at = _now()
    started = time.perf_counter()
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_cdp_browser()
    browser_version = subprocess.run(
        [str(browser), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    ).stdout.strip()
    runtime, task_id = _prepare_runtime()
    db_path = runtime / "researchflow.db"

    api_port = _free_port()
    ui_port = _free_port()
    api_log = (OUT_DIR / "screenshots_api.log").open("w", encoding="utf-8")
    api_process = subprocess.Popen(
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
            str(api_port),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        stdout=api_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    ui_process, ui_log = _start_ui(
        ui_port,
        f"http://127.0.0.1:{api_port}",
        task_id,
        10.0,
        OUT_DIR / "screenshots_streamlit.log",
    )

    shots: list[dict[str, Any]] = []
    doms: list[dict[str, Any]] = []
    expected_dom = {
        "task": ["Task 状态", "COMPLETED", task_id],
        "dag": ["确定性拓扑序", "split_dataset", "train_logistic_regression"],
        "evidence": ["证据条数", "链校验", "已失效证据", "32", "16"],
        "report": ["报告状态", "VERIFIED", "L3 覆盖", "CompletionCertificate"],
        "overview": ["任务", "DAG", "证据", "报告"],
        "api_unreachable": ["无法读取任务", "无法连接 API"],
    }
    capture = None
    ui2 = None
    ui2_log = None
    try:
        _wait_http(f"http://127.0.0.1:{api_port}/readyz", api_process, 60)
        _wait_http(f"http://127.0.0.1:{ui_port}/_stcore/health", ui_process, 120)
        capture = CDPChrome(runtime / "cdp")
        base = f"http://127.0.0.1:{ui_port}/?task_id={task_id}"
        for name in ("task", "dag", "evidence", "report"):
            url = f"{base}&view={name}"
            text = capture.goto_and_wait(url, expected_dom[name])
            target = SHOT_DIR / f"{name}.png"
            shot = capture.screenshot(target)
            shot["target"] = str(target.relative_to(ROOT))
            shot.update(_image_info(target))
            shots.append(shot)
            dom = capture.dom(SHOT_DIR / "dom" / f"{name}.html")
            dom["target"] = str((SHOT_DIR / "dom" / f"{name}.html").relative_to(ROOT))
            dom["expected"] = expected_dom[name]
            dom["missing"] = [
                item for item in expected_dom[name] if item not in text
            ]
            doms.append(dom)

        text = capture.goto_and_wait(base, expected_dom["overview"])
        target = SHOT_DIR / "overview.png"
        shot = capture.screenshot(target)
        shot["target"] = str(target.relative_to(ROOT))
        shot.update(_image_info(target))
        shots.append(shot)
        dom = capture.dom(SHOT_DIR / "dom" / "overview.html")
        dom["target"] = str((SHOT_DIR / "dom" / "overview.html").relative_to(ROOT))
        dom["expected"] = expected_dom["overview"]
        dom["missing"] = [
            item for item in expected_dom["overview"] if item not in text
        ]
        doms.append(dom)

        # API-unreachable view: a second workbench instance points at a port
        # where nothing listens, so the error is rendered on the first run.
        unused_port = _free_port()
        ui2_port = _free_port()
        ui2, ui2_log = _start_ui(
            ui2_port,
            f"http://127.0.0.1:{unused_port}",
            task_id,
            0.2,
            OUT_DIR / "screenshots_streamlit_unreachable.log",
        )
        _wait_http(f"http://127.0.0.1:{ui2_port}/_stcore/health", ui2, 120)
        time.sleep(1.0)
        unreachable_url = (
            f"http://127.0.0.1:{ui2_port}/?task_id={task_id}&view=task"
        )
        text = capture.goto_and_wait(
            unreachable_url, expected_dom["api_unreachable"], timeout=60
        )
        target = SHOT_DIR / "api_unreachable.png"
        shot = capture.screenshot(target)
        shot["target"] = str(target.relative_to(ROOT))
        shot.update(_image_info(target))
        shots.append(shot)
        dom = capture.dom(SHOT_DIR / "dom" / "api_unreachable.html")
        dom["target"] = str(
            (SHOT_DIR / "dom" / "api_unreachable.html").relative_to(ROOT)
        )
        dom["expected"] = expected_dom["api_unreachable"]
        dom["missing"] = [
            item for item in expected_dom["api_unreachable"] if item not in text
        ]
        doms.append(dom)
    finally:
        if capture is not None:
            capture.close()
        if ui2 is not None:
            _stop(ui2)
        if ui2_log is not None:
            ui2_log.close()
        _stop(ui_process)
        _stop(api_process)
        api_log.close()
        ui_log.close()

    dom_ok = all(not dom["missing"] for dom in doms)
    images_ok = all(shot["nonwhite_fraction"] > 0.01 for shot in shots)
    verdict = "PASS" if dom_ok and images_ok else "FAIL"

    report = {
        "purpose": "WP-13 four-view screenshots from real API data",
        "command": (
            f"{sys.executable} -B docs/verification/t0/wp-13/capture_screenshots.py"
        ),
        "cwd": str(ROOT),
        "interpreter": sys.executable,
        "python_version": sys.version,
        "browser": str(browser),
        "browser_version": browser_version,
        "started_at": started_at,
        "ended_at": _now(),
        "duration_sec": round(time.perf_counter() - started, 3),
        "source_runtime": str(SOURCE_RUNTIME.relative_to(ROOT)),
        "capture_runtime": str(runtime.relative_to(ROOT)),
        "task_id": task_id,
        "api_port": api_port,
        "streamlit_port": ui_port,
        "screenshots": shots,
        "dom_checks": doms,
        "dom_ok": dom_ok,
        "images_ok": images_ok,
        "verdict": verdict,
        "notes": [
            "The source e2e run_1 tree was copied, never modified.",
            "The copy contains the task database and evidence payloads only; no keys.",
            "Each screenshot is a fresh headless browser run against the real Streamlit app and real API.",
            "DOM dumps are saved next to the screenshots so the expected visible text is machine-checkable.",
        ],
        "exit_code": 0 if verdict == "PASS" else 1,
    }
    (OUT_DIR / "screenshots.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())