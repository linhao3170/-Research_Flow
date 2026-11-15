"""Measure the T0 concurrency cap (2 workers) and host memory headroom.

Runs a real two-model task through the pipeline (split, then two training nodes
scheduled in parallel), then reports:

* the declared and observed concurrency (interval overlap of the two attempts);
* each attempt's peak working set and their sum;
* the host's total/available physical memory.

The output JSON is evidence for the "concurrency cap 2 / 16 GB host" claim.
Areas that were not measured stay explicitly marked as not measured.

Usage::

    python scripts/measure_concurrency.py --out docs/verification/t0/e2e/concurrency.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests" / "t0") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "t0"))

from researchflow.contracts.models import TaskSpecCreate  # noqa: E402
from researchflow.contracts.encoding import hash_payload  # noqa: E402
from researchflow.orchestration.creation import TaskCreationService  # noqa: E402
from researchflow.orchestration.sqlite_ports import build_ports  # noqa: E402
from researchflow.orchestration.state_machine import StateMachine  # noqa: E402
from researchflow.persistence.db import connect  # noqa: E402
from researchflow.persistence.migrations import MigrationRunner  # noqa: E402
from researchflow.pipeline import TaskPipeline  # noqa: E402
from support import task_payload  # noqa: E402


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def host_memory() -> dict[str, float] | None:
    if sys.platform != "win32":
        return None
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        return None
    return {
        "total_mb": round(status.ullTotalPhys / (1024 * 1024), 1),
        "available_mb": round(status.ullAvailPhys / (1024 * 1024), 1),
        "load_percent": float(status.dwMemoryLoad),
    }


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _overlap_seconds(first: dict, second: dict) -> float:
    start = max(_parse(first["started_at"]), _parse(second["started_at"]))
    end = min(_parse(first["ended_at"]), _parse(second["ended_at"]))
    return max(0.0, (end - start).total_seconds())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(ROOT / "docs" / "verification" / "t0" / "e2e" / "concurrency.json")
    )
    args = parser.parse_args()

    base = ROOT / "runtime" / f"measure-concurrency-{uuid.uuid4().hex[:8]}"
    runtime = base / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    db_path = runtime / "researchflow.db"
    connection = connect(db_path)
    MigrationRunner().upgrade(connection)
    connection.close()

    state_machine = StateMachine(db_path, ports=build_ports(db_path, runtime))
    service = TaskCreationService(db_path, state_machine)
    payload = task_payload(models=("logistic_regression", "random_forest"), include_task_id=False)
    task_id = service.create_task(
        create_spec=TaskSpecCreate.model_validate(payload),
        request_hash=hash_payload(payload),
        idempotency_key=None,
    ).task_id
    pipeline = TaskPipeline(db_path, runtime)
    execution = pipeline.execute(task_id)
    if not execution.ok:
        print(json.dumps({"status": "FAILED", "error": execution.error}, ensure_ascii=False))
        return 1

    results = []
    for node_id in ("train_logistic_regression", "train_random_forest"):
        result_path = runtime / "tasks" / task_id / "attempts" / node_id / "attempt_01" / "result.json"
        results.append(json.loads(result_path.read_text(encoding="utf-8")))
    overlap = _overlap_seconds(results[0], results[1])
    peak_sum = sum(float(item.get("peak_memory_mb") or 0.0) for item in results)
    report = {
        "schema_version": "1.0",
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "interpreter": sys.version,
        "platform": platform.platform(),
        "declared_max_workers": 2,
        "graph": ["split_dataset", "train_logistic_regression", "train_random_forest"],
        "attempts": [
            {
                "node_id": item["node_id"],
                "attempt_id": item["attempt_id"],
                "launcher_pid": item.get("pid"),
                "worker_pids": item.get("worker_pids", []),
                "started_at": item["started_at"],
                "ended_at": item["ended_at"],
                "duration_sec": item["duration_sec"],
                "peak_memory_mb": item.get("peak_memory_mb"),
                "exit_code": item["exit_code"],
            }
            for item in results
        ],
        "observed_overlap_seconds": round(overlap, 3),
        "observed_concurrency": 2 if overlap > 0.05 else 1,
        "peak_worker_memory_sum_mb": round(peak_sum, 3),
        "host_memory": host_memory(),
        "notes": [
            "Two training nodes were scheduled in parallel because limits.max_workers=2.",
            "The venv python.exe is a launcher; peak_memory_mb is the maximum working set across the launcher and its real interpreter child (ProcessTreeSampler).",
            "No GPU, distributed or multi-tenant measurement is claimed for T0.",
        ],
        "workspace": str(base),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["observed_concurrency"] == 2 else 1


if __name__ == "__main__":
    sys.exit(main())