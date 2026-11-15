"""Read-only restart inspection probe for the T0 kill/restart test.

Run as an independent process after a product process was interrupted.  It
opens the real SQLite database in read-only mode, lists every attempt directory
with its job/result facts, and enumerates live processes whose command line
still references the task.  It never imports the API or writes state.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


def _db_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _attempts(root: Path, task_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    base = root / "tasks" / task_id / "attempts"
    if not base.is_dir():
        return records
    for node_dir in sorted(base.iterdir()):
        if not node_dir.is_dir():
            continue
        for attempt_dir in sorted(node_dir.iterdir()):
            if not attempt_dir.is_dir() or not attempt_dir.name.startswith("attempt_"):
                continue
            result_path = attempt_dir / "result.json"
            result: dict[str, Any] | None = None
            if result_path.is_file():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    result = None
            records.append(
                {
                    "node_id": node_dir.name,
                    "attempt_id": attempt_dir.name,
                    "job_present": (attempt_dir / "job.json").is_file(),
                    "result_present": result_path.is_file(),
                    "result_status": None if result is None else result.get("status"),
                    "result_exit_code": None
                    if result is None
                    else result.get("exit_code"),
                    "output_files": sorted(
                        path.name
                        for path in (attempt_dir / "output").glob("*")
                        if path.is_file()
                    )
                    if (attempt_dir / "output").is_dir()
                    else [],
                }
            )
    return records


def _live_processes(task_id: str) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.Name -eq 'python.exe' -and $_.CommandLine -like '*{task_id}*' }} | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = completed.stdout.strip()
    if not text:
        return []
    payload = json.loads(text)
    rows = payload if isinstance(payload, list) else [payload]
    own_script = Path(__file__).name
    return [
        {
            "pid": int(row["ProcessId"]),
            "name": str(row.get("Name") or ""),
            "command_line": str(row.get("CommandLine") or ""),
        }
        for row in rows
        if int(row["ProcessId"]) != os.getpid()
        and own_script not in str(row.get("CommandLine") or "")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    root = Path(args.root)
    task_id = args.task
    connection = _db_readonly(db_path)
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
        evidence = [
            {
                "evidence_id": str(row["evidence_id"]),
                "event_seq": int(row["event_seq"]),
                "level": str(row["level"]),
                "kind": str(row["kind"]),
            }
            for row in connection.execute(
                "SELECT evidence_id, event_seq, level, kind FROM evidence "
                "WHERE task_id = ? ORDER BY event_seq",
                (task_id,),
            )
        ]
    finally:
        connection.close()

    payload = {
        "task_id": task_id,
        "task_state": None if task is None else str(task["state"]),
        "nodes": nodes,
        "reports": reports,
        "certificates": certificates,
        "evidence_count": len(evidence),
        "evidence": evidence,
        "attempts": _attempts(root, task_id),
        "live_task_processes": _live_processes(task_id),
        "probe_pid": os.getpid(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())