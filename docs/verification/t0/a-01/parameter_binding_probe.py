"""A-01 sensitivity probe: parameter binding before/after the fix.

This is evidence tooling, not product code.  It creates a real execution,
tampers the train attempt's ``job.json`` exactly like an attacker with file
access would (seed 42 -> 43 and a recomputed declared hash), then:

1. Simulates the removed check by making ``VerificationContext.parameter_binding``
   trust the job file unconditionally.  L1 and L3 must both PASS -- this is the
   pre-fix behaviour that the review reproduced for real.
2. Restores the real binding check.  L1 must FAIL with
   ``L1_PARAMETERS_BINDING_MISMATCH`` and L3 must FAIL with
   ``L3_PARAMETERS_BINDING_MISMATCH`` *before* creating an L3 directory or
   spawning a subprocess.

Run with the project interpreter from the repository root::

    D:\\ResearchFlow-project\\.venv\\Scripts\\python.exe -B \
        docs/verification/t0/a-01/parameter_binding_probe.py
"""

from __future__ import annotations

import hashlib
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

from support import make_world, tamper_job_parameters  # noqa: E402

from researchflow.contracts.encoding import hash_payload  # noqa: E402
from researchflow.verification.context import ParameterBinding, VerificationContext  # noqa: E402
from researchflow.verification.l1 import L1Verifier  # noqa: E402
from researchflow.verification.l3 import L3Verifier  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _l1_summary(result) -> dict[str, Any]:
    return {
        "status": result.status,
        "codes": [issue.code for issue in result.issues],
        "details": [issue.detail for issue in result.issues[:6]],
    }


def _l3_summary(result) -> dict[str, Any]:
    return {
        "status": result.status,
        "coverage": result.coverage,
        "node_count": len(result.nodes),
        "issues": [issue.to_dict() for issue in result.issues],
        "processes": list(result.processes),
        "verification_root": result.verification_root,
    }


def _trusting_binding(original: Any):
    """Return a binding that trusts job.json -- the removed pre-fix behaviour."""

    def binding(self: VerificationContext, node_id: str, attempt_seq: int) -> ParameterBinding:
        attempt_id = f"attempt_{attempt_seq:02d}"
        job_path = self.attempt_dir(node_id, attempt_seq) / "job.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        parameters = dict(job["parameters"])
        digest = hash_payload(parameters)
        return ParameterBinding(
            node_id=node_id,
            attempt_id=attempt_id,
            nodespec_parameters_hash=digest,
            job_declared_parameters_hash=str(job.get("parameters_hash") or digest),
            job_recomputed_parameters_hash=digest,
            result_parameters_hash=None,
            e2_launch_parameters_hash=digest,
            job_parameters=parameters,
            problems=(),
        )

    return binding


def main() -> int:
    started_at = _now()
    started = time.perf_counter()
    base = ROOT / "runtime" / f"a01-probe-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    world = make_world(base, models=("logistic_regression",))
    task_id = world["task_id"]
    execution = world["pipeline"].execute(task_id)
    if not execution.ok:
        print(json.dumps({"error": "execution failed", "detail": execution.error}))
        return 2
    from researchflow.verification.context import load_context

    ctx = load_context(world["db_path"], world["root"], task_id)
    node_id = "train_logistic_regression"
    attempt_seq = 1
    original_binding = ctx.parameter_binding(node_id, attempt_seq)
    original_job_hash = original_binding.job_declared_parameters_hash
    original_job_sha = _sha256(
        ctx.attempt_dir(node_id, attempt_seq) / "job.json"
    )

    job = tamper_job_parameters(
        world["root"],
        task_id,
        node_id,
        attempt_seq,
        lambda parameters: parameters.__setitem__("seed", 43),
    )
    tampered_hash = str(job["parameters_hash"])
    tampered_job_sha = _sha256(
        ctx.attempt_dir(node_id, attempt_seq) / "job.json"
    )
    fresh = load_context(world["db_path"], world["root"], task_id)
    real_binding = fresh.parameter_binding(node_id, attempt_seq)

    verification_root = world["root"] / "verification"
    dirs_before = (
        {path.name for path in verification_root.glob("l3-*")}
        if verification_root.is_dir()
        else set()
    )

    # --- pre-fix simulation: the check is removed, job.json is trusted.
    original_method = VerificationContext.parameter_binding
    try:
        VerificationContext.parameter_binding = _trusting_binding(original_method)
        l1_pre = L1Verifier().run(fresh)
        l3_pre = L3Verifier(world["root"]).run(fresh)
        pre_fix = {
            "simulated": True,
            "method": (
                "monkeypatched VerificationContext.parameter_binding to trust "
                "job.json, reproducing the code path before the A-01 fix"
            ),
            "l1": _l1_summary(l1_pre),
            "l3": _l3_summary(l3_pre),
        }
    finally:
        VerificationContext.parameter_binding = original_method

    # --- post-fix: the real binding check must reject before any replay.
    dirs_before_post = (
        {path.name for path in verification_root.glob("l3-*")}
        if verification_root.is_dir()
        else set()
    )
    l1_post = L1Verifier().run(fresh)
    l3_post = L3Verifier(world["root"]).run(fresh)
    dirs_after_post = (
        {path.name for path in verification_root.glob("l3-*")}
        if verification_root.is_dir()
        else set()
    )
    post_fix = {
        "l1": _l1_summary(l1_post),
        "l3": _l3_summary(l3_post),
        "new_l3_directories": sorted(dirs_after_post - dirs_before_post),
        "no_replay_side_effect": dirs_after_post == dirs_before_post,
    }

    ended_at = _now()
    report = {
        "purpose": "A-01 parameter binding sensitivity probe",
        "command": (
            f"{sys.executable} -B "
            "docs/verification/t0/a-01/parameter_binding_probe.py"
        ),
        "cwd": str(ROOT),
        "interpreter": sys.executable,
        "python_version": platform.python_version(),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_sec": round(time.perf_counter() - started, 3),
        "task_id": task_id,
        "node_id": node_id,
        "attempt_id": "attempt_01",
        "original_job_sha256": original_job_sha,
        "tampered_job_sha256": tampered_job_sha,
        "job_bytes_changed": original_job_sha != tampered_job_sha,
        "original_parameters_hash": original_job_hash,
        "tampered_parameters_hash": tampered_hash,
        "nodespec_parameters_hash": real_binding.nodespec_parameters_hash,
        "e2_launch_parameters_hash": real_binding.e2_launch_parameters_hash,
        "binding_problem_codes": [problem["code"] for problem in real_binding.problems],
        "pre_fix_simulation": pre_fix,
        "post_fix": post_fix,
        "verdict": (
            "PASS"
            if (
                pre_fix["l1"]["status"] == "PASS"
                and pre_fix["l3"]["status"] == "PASS"
                and "L1_PARAMETERS_BINDING_MISMATCH" in post_fix["l1"]["codes"]
                and any(
                    issue["code"] == "L3_PARAMETERS_BINDING_MISMATCH"
                    for issue in post_fix["l3"]["issues"]
                )
                and post_fix["no_replay_side_effect"]
            )
            else "FAIL"
        ),
        "exit_code": 0,
    }
    out_dir = ROOT / "docs" / "verification" / "t0" / "a-01"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "probe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())