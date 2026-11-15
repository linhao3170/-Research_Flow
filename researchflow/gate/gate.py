"""Evidence Gate (T0 WP-08).

The Gate decides whether every required check of every graph node is backed by
live, current-attempt evidence.  It is a pure read-side evaluator over:
``graph_versions``, ``nodes``, ``evidence``, ``evidence_invalidations``,
``audit_log`` and the frozen ruleset.

Key rules:

* a required check is only satisfied by evidence of the level/kind that the
  ruleset declares — E0 claims and E1 tool traces can never satisfy an
  execution check;
* evidence from an older attempt of the same node is stale by construction, and
  evidence listed in ``evidence_invalidations`` is stale even if it is still
  present and its hash is still valid;
* stale evidence is never deleted or edited;
* a ``ruleset_hash`` mismatch fails the gate immediately, even if every piece of
  evidence is present.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from researchflow.evidence.chain import ChainReport, verify_chain
from researchflow.persistence.db import connect, format_utc, utc_now
from researchflow.persistence.repositories import EvidenceRow, InvalidationRow, NodeRow, NodeRepository, TaskRepository
from researchflow.persistence.records import GraphRecord, GraphRepository, list_all_invalidations, list_evidence
from researchflow.rules import RULESET_HASH, load_ruleset
from researchflow.signing.merkle import evidence_record_bytes, merkle_root

__all__ = [
    "GAP_ARTIFACT_HASH_MISMATCH",
    "GAP_ARTIFACT_MISSING",
    "GAP_CHAIN_INVALID",
    "GAP_E2_MISSING",
    "GAP_E2_NOT_SUCCESS",
    "GAP_E3_MISSING",
    "GAP_E3_NOT_PASS",
    "GAP_EVIDENCE_STALE",
    "GAP_GRAPH_MISSING",
    "GAP_NODE_ROW_MISSING",
    "GAP_STALE_ATTEMPT",
    "Gate",
    "GateGap",
    "GateResult",
]

GAP_E2_MISSING = "GAP_E2_MISSING"
GAP_E2_NOT_SUCCESS = "GAP_E2_NOT_SUCCESS"
GAP_E3_MISSING = "GAP_E3_MISSING"
GAP_E3_NOT_PASS = "GAP_E3_NOT_PASS"
GAP_ARTIFACT_MISSING = "GAP_ARTIFACT_MISSING"
GAP_ARTIFACT_HASH_MISMATCH = "GAP_ARTIFACT_HASH_MISMATCH"
GAP_EVIDENCE_STALE = "GAP_EVIDENCE_STALE"
GAP_STALE_ATTEMPT = "GAP_STALE_ATTEMPT"
GAP_GRAPH_MISSING = "GAP_GRAPH_MISSING"
GAP_GRAPH_HASH_MISMATCH = "GAP_GRAPH_HASH_MISMATCH"
GAP_NODE_ROW_MISSING = "GAP_NODE_ROW_MISSING"
GAP_NODE_TYPE_UNKNOWN = "GAP_NODE_TYPE_UNKNOWN"
GAP_CHAIN_INVALID = "GAP_CHAIN_INVALID"
GAP_RULESET_MISMATCH = "RULESET_VERSION_MISMATCH"
GAP_RULESET_INVALID = "GAP_RULESET_INVALID"
GAP_E3_NOT_BOUND = "GAP_E3_NOT_BOUND"

# Hard lower bounds from 05 §4.5 / I-02: a ruleset edit must not be able to let
# E0/E1 satisfy an execution check or a non-E3 record satisfy metric_source.
_CHECK_MINIMUM_LEVEL = {
    "executor_observed": "E2",
    "artifact_hash": "E2",
    "metric_source": "E3",
}


@dataclass(frozen=True, slots=True)
class GateGap:
    code: str
    node_id: str | None
    check: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "node_id": self.node_id,
            "check": self.check,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    task_id: str
    graph_version: int | None
    ruleset_hash: str
    task_ruleset_hash: str
    evidence_root: str
    required: int
    passed_checks: int
    missing: int
    gaps: tuple[GateGap, ...]
    stale_evidence_ids: tuple[str, ...]
    evaluated_at: str
    passed: bool
    l3_coverage: float = 0.0
    metric_nodes_required: int = 0
    metric_nodes_verified: int = 0
    chain: ChainReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "graph_version": self.graph_version,
            "ruleset_hash": self.ruleset_hash,
            "task_ruleset_hash": self.task_ruleset_hash,
            "evidence_root": self.evidence_root,
            "required": self.required,
            "passed": self.passed_checks,
            "missing": self.missing,
            "l3_coverage": self.l3_coverage,
            "metric_nodes_required": self.metric_nodes_required,
            "metric_nodes_verified": self.metric_nodes_verified,
            "passed_gate": self.passed,
            "gaps": [gap.to_dict() for gap in self.gaps],
            "stale_evidence_ids": list(self.stale_evidence_ids),
            "evaluated_at": self.evaluated_at,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_from_sql(row: sqlite3.Row) -> EvidenceRow:
    return EvidenceRow(
        evidence_id=str(row["evidence_id"]),
        task_id=str(row["task_id"]),
        node_id=str(row["node_id"]),
        attempt_id=str(row["attempt_id"]),
        event_seq=int(row["event_seq"]),
        level=str(row["level"]),
        kind=str(row["kind"]),
        producer=str(row["producer"]),
        timestamp=str(row["timestamp"]),
        payload_hash=str(row["payload_hash"]),
        artifact_refs=None if row["artifact_refs"] is None else str(row["artifact_refs"]),
        prev_hash=str(row["prev_hash"]),
        chain_hash=str(row["chain_hash"]),
    )


class Gate:
    def __init__(self, db_path: str | Path, task_root: str | Path | None = None) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root) if task_root else self._db_path.parent
        self._tasks = TaskRepository()
        self._nodes = NodeRepository()
        self._graphs = GraphRepository()
        # Deep copy: load_ruleset() is cached, and a Gate instance must never be
        # able to mutate the shared ruleset document.
        self._ruleset = json.loads(json.dumps(load_ruleset()))
        self._ruleset_hash = RULESET_HASH

    # ------------------------------------------------------------------ helpers
    def _payload(self, task_id: str, payload_hash: str) -> dict[str, Any] | None:
        path = (
            self._task_root / "tasks" / task_id / "evidence_payloads" / f"{payload_hash}.json"
        )
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_bytes())
        except json.JSONDecodeError:
            return None

    def _payload_reader(self, task_id: str):
        def _read(payload_hash: str) -> bytes | None:
            path = (
                self._task_root
                / "tasks"
                / task_id
                / "evidence_payloads"
                / f"{payload_hash}.json"
            )
            return path.read_bytes() if path.is_file() else None

        return _read

    def _graph_payload(self, graph: GraphRecord) -> dict[str, Any]:
        nodes = sorted(graph.nodes, key=lambda node: str(node["node_id"]))
        edges = sorted({(str(edge[0]), str(edge[1])) for edge in graph.graph_json.get("edges", [])})
        return {
            "schema_version": "1.0",
            "nodes": nodes,
            "edges": [[source, target] for source, target in edges],
        }

    def _attempt_dir(self, task_id: str, node_id: str, attempt_seq: int) -> Path:
        return (
            self._task_root
            / "tasks"
            / task_id
            / "attempts"
            / node_id
            / f"attempt_{attempt_seq:02d}"
        )

    # ----------------------------------------------------------------- evaluate
    def evaluate(self, task_id: str) -> GateResult:
        connection = connect(self._db_path)
        try:
            task = self._tasks.get(connection, task_id)
            graph = self._graphs.get(connection, task_id)
            node_rows = {row.node_id: row for row in self._nodes.list_for_task(connection, task_id)}
            evidence = list_evidence(connection, task_id)
            invalidations = list_all_invalidations(connection, task_id)
        finally:
            connection.close()

        gaps: list[GateGap] = []
        invalidated_ids = {row.evidence_id for row in invalidations}
        evidence_root = merkle_root([evidence_record_bytes(row) for row in evidence])
        evaluated_at = format_utc(utc_now())

        if task is None:
            return GateResult(
                task_id=task_id,
                graph_version=None,
                ruleset_hash=self._ruleset_hash,
                task_ruleset_hash="",
                evidence_root=evidence_root,
                required=0,
                passed_checks=0,
                missing=0,
                gaps=(GateGap("TASK_NOT_FOUND", None, None, "task does not exist"),),
                stale_evidence_ids=tuple(sorted(invalidated_ids)),
                evaluated_at=evaluated_at,
                passed=False,
            )

        task_spec = json.loads(task.task_spec_json)
        task_ruleset = str(task_spec.get("ruleset_hash", ""))
        if task_ruleset != self._ruleset_hash:
            gaps.append(
                GateGap(
                    GAP_RULESET_MISMATCH,
                    None,
                    "ruleset_binding",
                    f"task ruleset_hash {task_ruleset} != current {self._ruleset_hash}",
                )
            )

        if graph is None:
            gaps.append(
                GateGap(GAP_GRAPH_MISSING, None, "graph", "no graph version registered")
            )
            return GateResult(
                task_id=task_id,
                graph_version=None,
                ruleset_hash=self._ruleset_hash,
                task_ruleset_hash=task_ruleset,
                evidence_root=evidence_root,
                required=0,
                passed_checks=0,
                missing=0,
                gaps=tuple(gaps),
                stale_evidence_ids=tuple(sorted(invalidated_ids)),
                evaluated_at=evaluated_at,
                passed=False,
            )

        if self._graph_hash(graph) != graph.graph_hash:
            gaps.append(
                GateGap(
                    GAP_GRAPH_HASH_MISMATCH,
                    None,
                    "graph",
                    "graph_hash does not match the stored graph payload",
                )
            )

        chain = verify_chain(evidence, self._payload_reader(task_id))
        if not chain.ok:
            for issue in chain.issues:
                gaps.append(
                    GateGap(
                        GAP_CHAIN_INVALID,
                        None,
                        "evidence_chain",
                        f"{issue.code}: {issue.detail}",
                    )
                )

        required = 0
        passed_checks = 0
        metric_required = 0
        metric_verified = 0
        split_manifest = self._split_manifest(graph, node_rows, evidence, invalidated_ids)
        for node in sorted(graph.nodes, key=lambda item: str(item["node_id"])):
            node_id = str(node["node_id"])
            node_type = str(node["node_type"])
            checks = self._ruleset.get("required_checks", {}).get(node_type)
            if not checks:
                gaps.append(
                    GateGap(
                        GAP_NODE_TYPE_UNKNOWN,
                        node_id,
                        None,
                        f"ruleset has no required checks for node type {node_type}",
                    )
                )
                continue
            row = node_rows.get(node_id)
            if row is None:
                gaps.append(
                    GateGap(GAP_NODE_ROW_MISSING, node_id, None, "node row is missing")
                )
                required += len(checks)
                continue
            attempt_id = f"attempt_{row.attempt_seq:02d}"
            for check in checks:
                required += 1
                if check == "metric_source":
                    metric_required += 1
                ok, gap = self._check_required(
                    task_id=task_id,
                    node_id=node_id,
                    attempt_id=attempt_id,
                    attempt_seq=row.attempt_seq,
                    check=str(check),
                    evidence=evidence,
                    invalidated_ids=invalidated_ids,
                    split_manifest=split_manifest,
                )
                if gap is not None:
                    gaps.append(gap)
                if ok:
                    passed_checks += 1
                    if check == "metric_source":
                        metric_verified += 1

        missing = required - passed_checks
        l3_coverage = (
            metric_verified / metric_required if metric_required else 0.0
        )
        return GateResult(
            task_id=task_id,
            graph_version=graph.graph_version,
            ruleset_hash=self._ruleset_hash,
            task_ruleset_hash=task_ruleset,
            evidence_root=evidence_root,
            required=required,
            passed_checks=passed_checks,
            missing=missing,
            gaps=tuple(gaps),
            stale_evidence_ids=tuple(sorted(invalidated_ids)),
            evaluated_at=evaluated_at,
            passed=(not gaps and missing == 0 and chain.ok),
            l3_coverage=l3_coverage,
            metric_nodes_required=metric_required,
            metric_nodes_verified=metric_verified,
            chain=chain,
        )

    @staticmethod
    def _graph_hash(graph: GraphRecord) -> str:
        from researchflow.contracts.encoding import hash_payload

        nodes = sorted(graph.nodes, key=lambda node: str(node["node_id"]))
        edges = sorted(
            {(str(edge[0]), str(edge[1])) for edge in graph.graph_json.get("edges", [])}
        )
        return hash_payload(
            {
                "schema_version": "1.0",
                "nodes": nodes,
                "edges": [[source, target] for source, target in edges],
            }
        )

    def _split_manifest(
        self,
        graph: GraphRecord,
        node_rows: Mapping[str, NodeRow],
        evidence: Sequence[EvidenceRow],
        invalidated_ids: set[str],
    ) -> dict[str, Any] | None:
        """Read the current split manifest so E3 records can be bound to it."""

        split_node = next(
            (
                node
                for node in graph.nodes
                if str(node.get("node_type")) == "ml.split"
            ),
            None,
        )
        if split_node is None:
            return None
        node_id = str(split_node["node_id"])
        row = node_rows.get(node_id)
        if row is None:
            return None
        attempt_id = f"attempt_{row.attempt_seq:02d}"
        for record in evidence:
            if (
                record.node_id != node_id
                or record.kind != "artifact_observed"
                or record.attempt_id != attempt_id
                or record.evidence_id in invalidated_ids
            ):
                continue
            payload = self._payload(record.task_id, record.payload_hash)
            if payload is None:
                continue
            relative = str(payload.get("artifact_path", ""))
            if not relative.endswith("split_manifest.json"):
                continue
            path = self._attempt_dir(record.task_id, node_id, row.attempt_seq) / relative
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return None
        return None

    def _check_required(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        attempt_seq: int,
        check: str,
        evidence: Sequence[EvidenceRow],
        invalidated_ids: set[str],
        split_manifest: Mapping[str, Any] | None = None,
    ) -> tuple[bool, GateGap | None]:
        definition = self._ruleset.get("check_definitions", {}).get(check, {})
        level = str(definition.get("level", ""))
        kinds = set(definition.get("kinds", []))
        minimum = _CHECK_MINIMUM_LEVEL.get(check)
        if minimum is not None and level != minimum:
            return False, GateGap(
                GAP_RULESET_INVALID,
                node_id,
                check,
                f"ruleset declares level {level!r} but {check} requires at least {minimum}",
            )
        node_evidence = [row for row in evidence if row.node_id == node_id]
        candidates = [
            row for row in node_evidence if row.level == level and row.kind in kinds
        ]
        current = [row for row in candidates if row.attempt_id == attempt_id]
        live = [row for row in current if row.evidence_id not in invalidated_ids]
        stale_current = [row for row in current if row.evidence_id in invalidated_ids]

        if not candidates:
            return False, GateGap(
                GAP_E2_MISSING if level == "E2" else GAP_E3_MISSING,
                node_id,
                check,
                f"no {level} evidence of kinds {sorted(kinds)}",
            )
        if not current:
            return False, GateGap(
                GAP_STALE_ATTEMPT,
                node_id,
                check,
                f"evidence only exists for older attempts, current is {attempt_id}",
            )
        if not live:
            return False, GateGap(
                GAP_EVIDENCE_STALE,
                node_id,
                check,
                f"{len(stale_current)} matching evidence records are invalidated",
            )

        if check == "executor_observed":
            launches = [row for row in live if row.kind == "executor_launch"]
            exits = [row for row in live if row.kind == "executor_process_exit"]
            if not launches or not exits:
                return False, GateGap(
                    GAP_E2_MISSING,
                    node_id,
                    check,
                    "need both executor_launch and executor_process_exit evidence",
                )
            exit_payload = self._payload(task_id, exits[-1].payload_hash)
            if exit_payload is None:
                return False, GateGap(
                    GAP_E2_MISSING,
                    node_id,
                    check,
                    "executor_process_exit payload is missing",
                )
            if exit_payload.get("status") != "EXITED" or exit_payload.get("exit_code") != 0:
                return False, GateGap(
                    GAP_E2_NOT_SUCCESS,
                    node_id,
                    check,
                    f"attempt status={exit_payload.get('status')} "
                    f"exit_code={exit_payload.get('exit_code')}",
                )
            return True, None

        if check == "artifact_hash":
            if not live:
                return False, GateGap(GAP_ARTIFACT_MISSING, node_id, check, "no artifacts")
            attempt_dir = self._attempt_dir(task_id, node_id, attempt_seq)
            for row in live:
                payload = self._payload(task_id, row.payload_hash)
                if payload is None:
                    return False, GateGap(
                        GAP_ARTIFACT_MISSING, node_id, check, "artifact payload is missing"
                    )
                relative = str(payload.get("artifact_path", ""))
                expected = str(payload.get("sha256", ""))
                root = attempt_dir.resolve()
                candidate = (attempt_dir / relative).resolve()
                if root not in candidate.parents:
                    return False, GateGap(
                        GAP_ARTIFACT_MISSING,
                        node_id,
                        check,
                        f"artifact path escapes the attempt directory: {relative}",
                    )
                if not candidate.is_file():
                    return False, GateGap(
                        GAP_ARTIFACT_MISSING,
                        node_id,
                        check,
                        f"artifact file is missing: {relative}",
                    )
                actual = _sha256_file(candidate)
                if actual != expected:
                    return False, GateGap(
                        GAP_ARTIFACT_HASH_MISMATCH,
                        node_id,
                        check,
                        f"{relative}: expected {expected}, actual {actual}",
                    )
            return True, None

        if check == "metric_source":
            expected_split = (
                None if split_manifest is None else str(split_manifest.get("split_hash", ""))
            )
            if expected_split is None:
                return False, GateGap(
                    GAP_E3_NOT_BOUND,
                    node_id,
                    check,
                    "the current split manifest is unavailable; E3 cannot be bound",
                )
            for row in live:
                payload = self._payload(task_id, row.payload_hash)
                if payload is None:
                    continue
                if payload.get("node_id") != node_id or payload.get("l3_status") != "PASS":
                    continue
                if str(payload.get("executor_split_hash", "")) != expected_split:
                    continue
                if not isinstance(payload.get("train_pid"), int):
                    continue
                if not payload.get("l3_split_dir"):
                    continue
                return True, None
            return False, GateGap(
                GAP_E3_NOT_BOUND,
                node_id,
                check,
                "no live E3 bound to the current split manifest and L3 process",
            )

        return False, GateGap(
            GAP_E2_MISSING,
            node_id,
            check,
            f"unsupported required check {check!r}",
        )