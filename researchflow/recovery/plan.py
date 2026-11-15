"""Deterministic recovery plan generation and content-addressed freezing (WP-R).

The plan body contains no timestamps, no random ordering and no free text: the
same (task, graph, cause, affected nodes, invalidated evidence, input hashes)
always produce the same ``plan_hash``.  ``frozen_at`` lives only in
``audit_log``.  The plan file name is its SHA-256 and it is written with
temporary file + fsync + rename, then never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from researchflow.contracts.encoding import canonical_bytes, hash_payload

__all__ = [
    "PLAN_SCHEMA_VERSION",
    "RecoveryPlan",
    "build_plan",
    "plan_path",
    "read_plan",
    "write_plan",
]

PLAN_SCHEMA_VERSION = "1.0"


class PlanError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    plan_id: str
    plan_hash: str
    document: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "document": self.document,
        }


def build_plan(
    *,
    task_id: str,
    graph_json: Mapping[str, Any],
    ruleset_hash: str,
    cause_type: str,
    cause_ref: str,
    affected: Sequence[str],
    invalidated_evidence: Sequence[str],
    dataset_uri: str,
    dataset_sha256: str,
) -> RecoveryPlan:
    nodes = {str(node["node_id"]): node for node in graph_json.get("nodes", [])}
    parameters_by_node = graph_json.get("parameters_by_node") or {}
    steps: list[dict[str, Any]] = []
    for node_id in affected:
        node = nodes.get(node_id)
        if node is None:
            raise PlanError("PLAN_UNKNOWN_NODE", f"affected node is not in the graph: {node_id}")
        steps.append(
            {
                "node_id": node_id,
                "node_type": str(node["node_type"]),
                "template_id": str(node["template_id"]),
                "parameters_hash": str(node["parameters_hash"]),
                "parameters": dict(parameters_by_node.get(node_id, {})),
                "depends_on": [str(dep) for dep in node.get("depends_on", [])],
            }
        )
    document: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "task_id": task_id,
        "graph_version": int(graph_json.get("graph_version", 1)),
        "graph_hash": str(graph_json.get("graph_hash", "")),
        "ruleset_hash": ruleset_hash,
        "cause_type": cause_type,
        "cause_ref": cause_ref,
        "dataset": {"uri": dataset_uri, "sha256": dataset_sha256},
        "affected_nodes": [step["node_id"] for step in steps],
        "invalidated_evidence": sorted({str(evidence_id) for evidence_id in invalidated_evidence}),
        "steps": steps,
    }
    plan_hash = hash_payload(document)
    plan_id = "plan_" + plan_hash[:32]
    return RecoveryPlan(plan_id=plan_id, plan_hash=plan_hash, document=document)


def plan_path(root: str | Path, plan_hash: str) -> Path:
    if len(plan_hash) != 64 or any(character not in "0123456789abcdef" for character in plan_hash):
        raise PlanError("PLAN_HASH_MISMATCH", "plan_hash is not 64 lowercase hex characters")
    return Path(root) / f"{plan_hash}.json"


def write_plan(root: str | Path, plan: RecoveryPlan) -> tuple[Path, bool]:
    """Write the plan atomically; return (path, created)."""

    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    target = plan_path(base, plan.plan_hash)
    data = canonical_bytes(plan.document)
    if target.is_file():
        if target.read_bytes() != data:
            raise PlanError(
                "PLAN_FILE_CONFLICT",
                "a plan file already exists with different bytes for this hash",
            )
        return target, False
    temporary = base / f".{plan.plan_hash}.{uuid.uuid4().hex}.tmp"
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != plan.plan_hash:
        raise PlanError("PLAN_HASH_MISMATCH", "written plan bytes do not match plan_hash")
    return target, True


def read_plan(root: str | Path, plan_hash: str) -> dict[str, Any]:
    path = plan_path(root, plan_hash)
    if not path.is_file():
        raise PlanError("PLAN_FILE_MISSING", f"plan file not found: {plan_hash}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != plan_hash:
        raise PlanError("PLAN_HASH_MISMATCH", "sha256(file bytes) != plan_hash")
    return json.loads(data)