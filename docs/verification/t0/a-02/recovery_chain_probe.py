"""A-02 sensitivity probe: recovery must validate evidence before scheduling.

Two scenarios are exercised against a real verified task:

* ``broken_chain``     -- an evidence payload file is removed.
* ``missing_result``   -- the current split attempt's ``result.json`` is removed.

Each scenario runs twice:

* ``pre-fix simulation`` -- ``RecoveryService._require_valid_evidence`` is
  monkeypatched to a no-op, reproducing the code path before the A-02 fix.
* ``post-fix``          -- the real guard, which must raise ``RECOVERY_NOT_SAFE``
  with the concrete L1 reason and leave node states/plans untouched.

A third post-fix case breaks the chain after a valid invalidation and proves
that ``rerun`` also refuses before creating any new attempt.

Run with the project interpreter from the repository root::

    D:\\ResearchFlow-project\\.venv\\Scripts\\python.exe -B \
        docs/verification/t0/a-02/recovery_chain_probe.py
"""

from __future__ import annotations

import json
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests" / "t0"))
sys.path.insert(0, str(ROOT))

from support import make_world  # noqa: E402

from researchflow.evidence import Collector  # noqa: E402
from researchflow.persistence.db import connect  # noqa: E402
from researchflow.recovery import RecoveryError, RecoveryService  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _build_verified_world(base: Path) -> dict[str, Any]:
    world = make_world(base)
    execution = world["pipeline"].execute(world["task_id"])
    if not execution.ok:
        raise RuntimeError(f"execution failed: {execution.error}")
    outcome = world["pipeline"].verify(world["task_id"])
    if outcome.final_state != "VERIFIED":
        raise RuntimeError(f"verification failed: {outcome.gaps[:3]}")
    world["pipeline"].mark_nodes_verified(world["task_id"])
    world["recovery"] = RecoveryService(world["db_path"], world["root"])
    return world


def _states(world: dict[str, Any]) -> dict[str, str]:
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


def _freeze_rows(world: dict[str, Any]) -> int:
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


def _attempt_02_dirs(world: dict[str, Any]) -> list[str]:
    base = world["root"] / "tasks" / world["task_id"] / "attempts"
    return sorted(str(path.relative_to(world["root"])) for path in base.glob("*/attempt_02"))


def _break_chain(world: dict[str, Any]) -> dict[str, Any]:
    collector = Collector(world["db_path"], world["root"])
    before = collector.verify_chain(world["task_id"])
    if not before.ok:
        raise RuntimeError("chain was already broken before the scenario")
    row = collector.rows(world["task_id"])[-1]
    payload = (
        world["root"] / "tasks" / world["task_id"] / "evidence_payloads"
        / f"{row.payload_hash}.json"
    )
    payload.unlink()
    after = collector.verify_chain(world["task_id"])
    return {
        "payload_hash": row.payload_hash,
        "chain_before_ok": before.ok,
        "chain_after_ok": after.ok,
        "chain_after_issues": [issue.to_dict() for issue in after.issues[:3]],
    }


def _remove_split_result(world: dict[str, Any]) -> str:
    path = (
        world["root"] / "tasks" / world["task_id"] / "attempts"
        / "split_dataset" / "attempt_01" / "result.json"
    )
    path.unlink()
    return str(path.relative_to(world["root"]))


def _run_invalidate(
    *,
    mode: str,
    scenario: str,
    base: Path,
) -> dict[str, Any]:
    started_at = _now()
    started = time.perf_counter()
    world = _build_verified_world(base)
    if scenario == "broken_chain":
        damage = _break_chain(world)
    elif scenario == "missing_result":
        damage = {"removed": _remove_split_result(world)}
    else:  # pragma: no cover - guarded by main
        raise ValueError(scenario)

    original = RecoveryService._require_valid_evidence
    try:
        if mode == "pre-fix":
            RecoveryService._require_valid_evidence = lambda self, task_id: None
        try:
            outcome = world["recovery"].invalidate(
                world["task_id"],
                changed_node="split_dataset",
                cause_type="INPUT_CHANGE",
                cause_ref=f"a02-{scenario}-{mode}",
            )
            result = {
                "decision": "PROCEEDED",
                "affected_nodes": outcome.get("affected_nodes"),
                "plan_hash": outcome.get("plan_hash"),
                "exception_code": None,
                "exception_detail": None,
            }
        except RecoveryError as exc:
            result = {
                "decision": "REFUSED",
                "affected_nodes": None,
                "plan_hash": None,
                "exception_code": exc.code,
                "exception_detail": exc.detail,
            }
    finally:
        RecoveryService._require_valid_evidence = original

    return {
        "mode": mode,
        "scenario": scenario,
        "simulated_pre_fix": mode == "pre-fix",
        "started_at": started_at,
        "duration_sec": round(time.perf_counter() - started, 3),
        "damage": damage,
        "result": result,
        "node_states_after": _states(world),
        "freeze_rows_after": _freeze_rows(world),
        "attempt_02_dirs_after": _attempt_02_dirs(world),
        "task_id": world["task_id"],
    }


def _run_rerun_case(base: Path) -> dict[str, Any]:
    started_at = _now()
    started = time.perf_counter()
    world = _build_verified_world(base)
    invalidation = world["recovery"].invalidate(
        world["task_id"],
        changed_node="split_dataset",
        cause_type="INPUT_CHANGE",
        cause_ref="a02-rerun-valid-invalidation",
    )
    damage = _break_chain(world)
    try:
        world["recovery"].rerun(world["task_id"], invalidation["plan_hash"])
        result = {
            "decision": "PROCEEDED",
            "exception_code": None,
            "exception_detail": None,
        }
    except RecoveryError as exc:
        result = {
            "decision": "REFUSED",
            "exception_code": exc.code,
            "exception_detail": exc.detail,
        }
    return {
        "mode": "post-fix",
        "scenario": "rerun_broken_chain",
        "started_at": started_at,
        "duration_sec": round(time.perf_counter() - started, 3),
        "plan_hash": invalidation["plan_hash"],
        "damage": damage,
        "result": result,
        "node_states_after": _states(world),
        "freeze_rows_after": _freeze_rows(world),
        "attempt_02_dirs_after": _attempt_02_dirs(world),
        "task_id": world["task_id"],
    }


def main() -> int:
    started_at = _now()
    started = time.perf_counter()
    base_root = ROOT / "runtime" / f"a02-probe-{uuid.uuid4().hex[:8]}"
    base_root.mkdir(parents=True)
    cases: list[dict[str, Any]] = []
    for scenario in ("broken_chain", "missing_result"):
        for mode in ("pre-fix", "post-fix"):
            cases.append(
                _run_invalidate(
                    mode=mode,
                    scenario=scenario,
                    base=base_root / f"{scenario}-{mode}",
                )
            )
    cases.append(_run_rerun_case(base_root / "rerun-broken-chain"))

    expected = {
        ("broken_chain", "pre-fix"): "PROCEEDED",
        ("broken_chain", "post-fix"): "REFUSED",
        ("missing_result", "pre-fix"): "PROCEEDED",
        ("missing_result", "post-fix"): "REFUSED",
        ("rerun_broken_chain", "post-fix"): "REFUSED",
    }
    checks: list[dict[str, Any]] = []
    for case in cases:
        key = (case["scenario"], case["mode"])
        checks.append(
            {
                "scenario": case["scenario"],
                "mode": case["mode"],
                "expected": expected[key],
                "actual": case["result"]["decision"],
                "ok": case["result"]["decision"] == expected[key],
            }
        )
    post_chain = next(
        case
        for case in cases
        if case["scenario"] == "broken_chain" and case["mode"] == "post-fix"
    )
    post_missing = next(
        case
        for case in cases
        if case["scenario"] == "missing_result" and case["mode"] == "post-fix"
    )
    rerun_case = next(case for case in cases if case["scenario"] == "rerun_broken_chain")
    reasons_ok = (
        "L1_CHAIN_PAYLOAD_MISSING" in str(post_chain["result"]["exception_detail"])
        and "L1_ATTEMPT_RESULT_MISSING" in str(post_missing["result"]["exception_detail"])
        and "L1_CHAIN_PAYLOAD_MISSING" in str(rerun_case["result"]["exception_detail"])
    )
    states_untouched = (
        set(post_chain["node_states_after"].values()) == {"VERIFIED"}
        and set(post_missing["node_states_after"].values()) == {"VERIFIED"}
        and set(rerun_case["node_states_after"].values()) == {"INVALIDATED"}
    )
    no_new_attempts = rerun_case["attempt_02_dirs_after"] == []
    verdict = (
        "PASS"
        if all(check["ok"] for check in checks)
        and reasons_ok
        and states_untouched
        and no_new_attempts
        else "FAIL"
    )

    report = {
        "purpose": "A-02 recovery evidence-validation sensitivity probe",
        "command": (
            f"{sys.executable} -B docs/verification/t0/a-02/recovery_chain_probe.py"
        ),
        "cwd": str(ROOT),
        "interpreter": sys.executable,
        "python_version": platform.python_version(),
        "started_at": started_at,
        "ended_at": _now(),
        "duration_sec": round(time.perf_counter() - started, 3),
        "pre_fix_note": (
            "pre-fix mode monkeypatches RecoveryService._require_valid_evidence "
            "to a no-op; it reproduces the code path before the A-02 fix and is "
            "labelled simulated. The actual pre-fix code was also observed in "
            "this session before the guard was added (invalidate proceeded with "
            "a broken chain and wrote two freeze rows)."
        ),
        "checks": checks,
        "reasons_ok": reasons_ok,
        "states_untouched": states_untouched,
        "no_new_attempts": no_new_attempts,
        "cases": cases,
        "verdict": verdict,
        "exit_code": 0,
    }
    out_dir = ROOT / "docs" / "verification" / "t0" / "a-02"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "probe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())