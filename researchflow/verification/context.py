"""Read-only context used by the L1/L2/L3 verifiers (T0 WP-09/WP-10)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from researchflow.contracts.encoding import hash_payload
from researchflow.persistence.db import connect
from researchflow.persistence.repositories import EvidenceRow, InvalidationRow, NodeRow, NodeRepository, TaskRepository
from researchflow.persistence.records import (
    GraphRecord,
    GraphRepository,
    list_all_invalidations,
    list_evidence,
)
from researchflow.rules import load_ruleset

__all__ = [
    "PARAMETERS_BINDING_MISSING",
    "PARAMETERS_HASH_MISMATCH",
    "ParameterBinding",
    "VerificationContext",
    "load_context",
]

PARAMETERS_BINDING_MISSING = "PARAMETERS_BINDING_MISSING"
PARAMETERS_HASH_MISMATCH = "PARAMETERS_HASH_MISMATCH"


@dataclass(frozen=True, slots=True)
class ParameterBinding:
    """Parameter facts for one node attempt, cross-checked read-only.

    The authoritative declaration is the NodeSpec ``parameters_hash`` stored in
    the registered graph.  The execution facts are the attempt ``job.json``
    (both the stored hash and a fresh hash of its ``parameters``), the attempt
    ``result.json`` and the E2 ``executor_launch`` evidence.  Every available
    fact must agree; a missing or mismatching fact makes the binding fail.
    """

    node_id: str
    attempt_id: str
    nodespec_parameters_hash: str | None
    job_declared_parameters_hash: str | None
    job_recomputed_parameters_hash: str | None
    result_parameters_hash: str | None
    e2_launch_parameters_hash: str | None
    job_parameters: dict[str, Any] | None
    problems: tuple[dict[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def parameters(self) -> dict[str, Any] | None:
        """Return the executed parameters only when every binding fact agrees."""

        if not self.ok or self.job_parameters is None:
            return None
        return dict(self.job_parameters)


@dataclass(frozen=True, slots=True)
class VerificationContext:
    task_id: str
    db_path: Path
    task_root: Path
    graph: GraphRecord
    task_spec: dict[str, Any]
    nodes: dict[str, NodeRow]
    evidence: list[EvidenceRow]
    invalidations: list[InvalidationRow]
    ruleset: dict[str, Any]

    @property
    def invalidated_ids(self) -> set[str]:
        return {row.evidence_id for row in self.invalidations}

    def attempt_dir(self, node_id: str, attempt_seq: int) -> Path:
        return (
            self.task_root / "tasks" / self.task_id / "attempts" / node_id
            / f"attempt_{attempt_seq:02d}"
        )

    def payload(self, payload_hash: str) -> dict[str, Any] | None:
        path = (
            self.task_root / "tasks" / self.task_id / "evidence_payloads"
            / f"{payload_hash}.json"
        )
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_bytes())
        except json.JSONDecodeError:
            return None

    def evidence_for(self, node_id: str) -> list[EvidenceRow]:
        return [row for row in self.evidence if row.node_id == node_id]

    def latest_payload(
        self, node_id: str, level: str, kind: str
    ) -> dict[str, Any] | None:
        matches = [
            row
            for row in self.evidence
            if row.node_id == node_id and row.level == level and row.kind == kind
        ]
        if not matches:
            return None
        return self.payload(matches[-1].payload_hash)

    def parameter_binding(self, node_id: str, attempt_seq: int) -> ParameterBinding:
        """Cross-check the parameters of the current attempt against NodeSpec/E2.

        This deliberately trusts no single source: the NodeSpec hash is the
        declaration, while ``job.json``/``result.json``/E2 are execution facts.
        A verifier must reject the attempt when any of them is missing or
        disagrees instead of inferring parameter identity from results.
        """

        attempt_id = f"attempt_{attempt_seq:02d}"
        problems: list[dict[str, str]] = []

        spec = next(
            (node for node in self.graph.nodes if str(node.get("node_id")) == node_id),
            None,
        )
        nodespec_hash = None
        if spec is None:
            problems.append(
                {
                    "code": PARAMETERS_BINDING_MISSING,
                    "detail": f"graph NodeSpec is missing for node {node_id}",
                }
            )
        else:
            value = str(spec.get("parameters_hash") or "")
            if value:
                nodespec_hash = value
            else:
                problems.append(
                    {
                        "code": PARAMETERS_BINDING_MISSING,
                        "detail": f"NodeSpec parameters_hash is empty for node {node_id}",
                    }
                )

        attempt_dir = self.attempt_dir(node_id, attempt_seq)
        job_parameters: dict[str, Any] | None = None
        job_declared: str | None = None
        job_recomputed: str | None = None
        job_path = attempt_dir / "job.json"
        if not job_path.is_file():
            problems.append(
                {
                    "code": PARAMETERS_BINDING_MISSING,
                    "detail": f"{node_id} {attempt_id} job.json is missing",
                }
            )
        else:
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(
                    {
                        "code": PARAMETERS_BINDING_MISSING,
                        "detail": f"{node_id} {attempt_id} job.json is unreadable: {exc}",
                    }
                )
            else:
                if not isinstance(job, dict) or not isinstance(job.get("parameters"), dict):
                    problems.append(
                        {
                            "code": PARAMETERS_BINDING_MISSING,
                            "detail": f"{node_id} {attempt_id} job.json has no parameters object",
                        }
                    )
                else:
                    job_parameters = dict(job["parameters"])
                    job_recomputed = hash_payload(job_parameters)
                    declared = job.get("parameters_hash")
                    if isinstance(declared, str) and declared:
                        job_declared = declared
                    else:
                        problems.append(
                            {
                                "code": PARAMETERS_BINDING_MISSING,
                                "detail": f"{node_id} {attempt_id} job.json has no parameters_hash",
                            }
                        )
        if job_declared is not None and job_recomputed is not None:
            if job_declared != job_recomputed:
                problems.append(
                    {
                        "code": PARAMETERS_HASH_MISMATCH,
                        "detail": (
                            f"{node_id} {attempt_id} job.parameters_hash {job_declared} "
                            f"!= hash_payload(job.parameters) {job_recomputed}"
                        ),
                    }
                )

        result_hash: str | None = None
        result_path = attempt_dir / "result.json"
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result = None
            value = result.get("parameters_hash") if isinstance(result, dict) else None
            if isinstance(value, str) and value:
                result_hash = value
            else:
                problems.append(
                    {
                        "code": PARAMETERS_BINDING_MISSING,
                        "detail": f"{node_id} {attempt_id} result.json has no parameters_hash",
                    }
                )

        e2_hash: str | None = None
        launch_row: EvidenceRow | None = None
        for row in self.evidence:
            if (
                row.node_id == node_id
                and row.attempt_id == attempt_id
                and row.level == "E2"
                and row.kind == "executor_launch"
            ):
                launch_row = row
        if launch_row is None:
            problems.append(
                {
                    "code": PARAMETERS_BINDING_MISSING,
                    "detail": f"{node_id} {attempt_id} E2 executor_launch is missing",
                }
            )
        else:
            payload = self.payload(launch_row.payload_hash)
            value = payload.get("parameters_hash") if isinstance(payload, dict) else None
            if isinstance(value, str) and value:
                e2_hash = value
            else:
                problems.append(
                    {
                        "code": PARAMETERS_BINDING_MISSING,
                        "detail": (
                            f"{node_id} {attempt_id} E2 executor_launch "
                            "has no parameters_hash"
                        ),
                    }
                )

        if nodespec_hash is not None:
            for label, actual in (
                ("job.parameters_hash", job_declared),
                ("hash_payload(job.parameters)", job_recomputed),
                ("result.json.parameters_hash", result_hash),
                ("E2 executor_launch.parameters_hash", e2_hash),
            ):
                if actual is not None and actual != nodespec_hash:
                    problems.append(
                        {
                            "code": PARAMETERS_HASH_MISMATCH,
                            "detail": (
                                f"{node_id} {attempt_id} {label} {actual} "
                                f"!= NodeSpec parameters_hash {nodespec_hash}"
                            ),
                        }
                    )

        return ParameterBinding(
            node_id=node_id,
            attempt_id=attempt_id,
            nodespec_parameters_hash=nodespec_hash,
            job_declared_parameters_hash=job_declared,
            job_recomputed_parameters_hash=job_recomputed,
            result_parameters_hash=result_hash,
            e2_launch_parameters_hash=e2_hash,
            job_parameters=job_parameters,
            problems=tuple(problems),
        )

    def effective_dataset_sha256(self, node_id: str) -> str | None:
        """Dataset fingerprint the node actually executed against (E2 evidence)."""

        payload = self.latest_payload(node_id, "E2", "executor_launch")
        if payload and payload.get("dataset_sha256"):
            return str(payload["dataset_sha256"])
        payload = self.latest_payload(node_id, "E2", "executor_process_exit")
        if payload and payload.get("dataset_sha256"):
            return str(payload["dataset_sha256"])
        dataset_ref = self.task_spec.get("dataset_ref") or {}
        return None if not dataset_ref else str(dataset_ref.get("sha256", ""))

    def metric_nodes(self) -> list[str]:
        ruleset = self.ruleset
        metric_types = set(ruleset.get("l3", {}).get("metric_node_types", []))
        return [
            str(node["node_id"])
            for node in sorted(self.graph.nodes, key=lambda item: str(item["node_id"]))
            if str(node["node_type"]) in metric_types
        ]


def load_context(
    db_path: str | Path,
    task_root: str | Path,
    task_id: str,
) -> VerificationContext:
    db_path = Path(db_path)
    task_root = Path(task_root)
    connection = connect(db_path)
    try:
        task = TaskRepository().get(connection, task_id)
        graph = GraphRepository().get(connection, task_id)
        nodes = {row.node_id: row for row in NodeRepository().list_for_task(connection, task_id)}
        evidence = list_evidence(connection, task_id)
        invalidations = list_all_invalidations(connection, task_id)
    finally:
        connection.close()
    if task is None:
        raise ValueError(f"task not found: {task_id}")
    if graph is None:
        raise ValueError(f"graph not registered for task: {task_id}")
    return VerificationContext(
        task_id=task_id,
        db_path=db_path,
        task_root=task_root,
        graph=graph,
        task_spec=json.loads(task.task_spec_json),
        nodes=nodes,
        evidence=evidence,
        invalidations=invalidations,
        ruleset=load_ruleset(),
    )