"""Verifier L1: process integrity (T0 WP-09).

L1 re-derives the evidence chain from stored bytes and re-hashes every observed
artifact.  It also detects attempt-directory reuse: one artifact file path may
only belong to one attempt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from researchflow.evidence.chain import verify_chain
from researchflow.verification.context import VerificationContext

__all__ = ["L1Issue", "L1Result", "L1Verifier"]

L1_ARTIFACT_MISSING = "L1_ARTIFACT_MISSING"
L1_ARTIFACT_HASH_MISMATCH = "L1_ARTIFACT_HASH_MISMATCH"
L1_ATTEMPT_REUSE = "L1_ATTEMPT_REUSE"
L1_ATTEMPT_RESULT_MISSING = "L1_ATTEMPT_RESULT_MISSING"
L1_ATTEMPT_NOT_EXITED = "L1_ATTEMPT_NOT_EXITED"
L1_PARAMETERS_BINDING_MISMATCH = "L1_PARAMETERS_BINDING_MISMATCH"
L1_PARAMETERS_BINDING_INCOMPLETE = "L1_PARAMETERS_BINDING_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class L1Issue:
    code: str
    node_id: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "node_id": self.node_id, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class L1Result:
    status: str
    issues: tuple[L1Issue, ...]
    chain_ok: bool
    chain_issues: tuple[dict[str, Any], ...] = ()
    checks: int = 0
    evidence_root: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "chain_ok": self.chain_ok,
            "chain_issues": list(self.chain_issues),
            "checks": self.checks,
            "evidence_root": self.evidence_root,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class L1Verifier:
    def run(self, ctx: VerificationContext) -> L1Result:
        issues: list[L1Issue] = []

        def reader(payload_hash: str) -> bytes | None:
            path = (
                ctx.task_root
                / "tasks"
                / ctx.task_id
                / "evidence_payloads"
                / f"{payload_hash}.json"
            )
            return path.read_bytes() if path.is_file() else None

        chain = verify_chain(ctx.evidence, reader)
        for chain_issue in chain.issues:
            issues.append(
                L1Issue(
                    f"L1_{chain_issue.code}",
                    None,
                    f"{chain_issue.evidence_id}: {chain_issue.detail}",
                )
            )

        checks = 0
        artifact_paths: dict[str, str] = {}
        for row in ctx.evidence:
            if row.kind != "artifact_observed":
                continue
            checks += 1
            payload = ctx.payload(row.payload_hash)
            if payload is None:
                issues.append(
                    L1Issue(L1_ARTIFACT_MISSING, row.node_id, "artifact payload is missing")
                )
                continue
            node = ctx.nodes.get(row.node_id)
            attempt_seq = int(row.attempt_id.rsplit("_", 1)[-1]) if "_" in row.attempt_id else 0
            attempt_dir = ctx.attempt_dir(row.node_id, attempt_seq)
            relative = str(payload.get("artifact_path", ""))
            root = attempt_dir.resolve()
            candidate = (attempt_dir / relative).resolve()
            if root not in candidate.parents:
                issues.append(
                    L1Issue(
                        L1_ARTIFACT_MISSING,
                        row.node_id,
                        f"artifact path escapes the attempt directory: {relative}",
                    )
                )
                continue
            if not candidate.is_file():
                issues.append(
                    L1Issue(
                        L1_ARTIFACT_MISSING,
                        row.node_id,
                        f"artifact file is missing: {relative}",
                    )
                )
                continue
            actual = _sha256(candidate)
            if actual != payload.get("sha256"):
                issues.append(
                    L1Issue(
                        L1_ARTIFACT_HASH_MISMATCH,
                        row.node_id,
                        f"{relative}: expected {payload.get('sha256')}, actual {actual}",
                    )
                )
            key = candidate.as_posix()
            if key in artifact_paths:
                issues.append(
                    L1Issue(
                        L1_ATTEMPT_REUSE,
                        row.node_id,
                        f"artifact path reused by {artifact_paths[key]}: {relative}",
                    )
                )
            artifact_paths[key] = row.attempt_id

        for node_id, node in ctx.nodes.items():
            checks += 1
            attempt_dir = ctx.attempt_dir(node_id, node.attempt_seq)
            if node.attempt_seq >= 1:
                binding = ctx.parameter_binding(node_id, node.attempt_seq)
                checks += 1
                for problem in binding.problems:
                    code = (
                        L1_PARAMETERS_BINDING_INCOMPLETE
                        if problem["code"] == "PARAMETERS_BINDING_MISSING"
                        else L1_PARAMETERS_BINDING_MISMATCH
                    )
                    issues.append(L1Issue(code, node_id, problem["detail"]))
            result_path = attempt_dir / "result.json"
            if not result_path.is_file():
                issues.append(
                    L1Issue(
                        L1_ATTEMPT_RESULT_MISSING,
                        node_id,
                        f"attempt_{node.attempt_seq:02d} has no result.json",
                    )
                )
                continue
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                issues.append(
                    L1Issue(L1_ATTEMPT_NOT_EXITED, node_id, "result.json is not valid JSON")
                )
                continue
            if result.get("status") != "EXITED" or result.get("exit_code") != 0:
                issues.append(
                    L1Issue(
                        L1_ATTEMPT_NOT_EXITED,
                        node_id,
                        f"attempt status={result.get('status')} "
                        f"exit_code={result.get('exit_code')}",
                    )
                )

        return L1Result(
            status="PASS" if not issues else "FAIL",
            issues=tuple(issues),
            chain_ok=chain.ok,
            chain_issues=tuple(issue.to_dict() for issue in chain.issues),
            checks=checks,
            evidence_root="",
        )