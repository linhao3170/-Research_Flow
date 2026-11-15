"""T0 minimal recovery: invalidate descendants, freeze a plan, rerun conservatively.

There is no ``PROPOSED``/``APPROVED`` recovery state machine in T0.  Recovery is
expressed with exactly three things (05 搂9.5): ``evidence_invalidations``
(append-only), a content-addressed frozen plan, and the ``INVALIDATED 鈫?READY``
three-condition guard in the StateMachine.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from researchflow.evidence.collector import Collector
from researchflow.execution.executor import Executor
from researchflow.orchestration.sqlite_ports import build_ports
from researchflow.orchestration.state_machine import (
    Actor,
    StateMachine,
    StateTransitionDenied,
    TransitionContext,
    TransitionRequest,
)
from researchflow.orchestration.transitions import ActorRole, NodeState, ObjectType
from researchflow.persistence.db import connect, format_utc, parse_utc, transaction, utc_now
from researchflow.persistence.records import GraphRepository
from researchflow.persistence.repositories import (
    WP_R_FREEZE,
    AuditRepository,
    NodeRepository,
    TaskRepository,
)
from researchflow.recovery.impact import affected_nodes
from researchflow.recovery.plan import (
    PlanError,
    RecoveryPlan,
    build_plan,
    read_plan,
    write_plan,
)
from researchflow.rules import RULESET_HASH
from researchflow.templates.registry import TRAIN_TEMPLATE_ID

__all__ = ["RecoveryError", "RecoveryService"]

_INPUT_CAUSE = "INPUT_CHANGE"
_PREDECESSOR_CAUSE = "PREDECESSOR_CHANGE"


class RecoveryError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class RecoveryService:
    def __init__(
        self,
        db_path: str | Path,
        task_root: str | Path,
        *,
        plan_root: str | Path | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root) if task_root else self._db_path.parent
        self._plan_root = (
            Path(plan_root) if plan_root else self._task_root / "recovery_plans"
        )
        ports = build_ports(self._db_path, self._task_root)
        self._sm = StateMachine(self._db_path, ports=ports)
        self._tasks = TaskRepository()
        self._nodes = NodeRepository()
        self._graphs = GraphRepository()
        self._audit = AuditRepository()
        self._collector = Collector(self._db_path, self._task_root)
        self._executor = Executor(self._task_root)

    # ------------------------------------------------------------------ helpers
    def _task(self, task_id: str):
        connection = connect(self._db_path)
        try:
            task = self._tasks.get(connection, task_id)
        finally:
            connection.close()
        if task is None:
            raise RecoveryError("TASK_NOT_FOUND", f"task {task_id} does not exist")
        return task

    def _node(self, task_id: str, node_id: str):
        connection = connect(self._db_path)
        try:
            node = self._nodes.get(connection, task_id, node_id)
        finally:
            connection.close()
        if node is None:
            raise RecoveryError("NODE_NOT_FOUND", f"node {node_id} does not exist")
        return node

    def _graph_json(self, task_id: str) -> dict[str, Any]:
        connection = connect(self._db_path)
        try:
            graph = self._graphs.get(connection, task_id)
        finally:
            connection.close()
        if graph is None:
            raise RecoveryError("GRAPH_MISSING", f"task {task_id} has no graph")
        return graph.graph_json

    def _require_valid_evidence(self, task_id: str) -> None:
        """Refuse recovery scheduling until the evidence chain is validated.

        ``US-T0-20`` requires a restarted process to validate the database and
        evidence chain before scheduling recovery.  T0 has no boot-recovery
        state machine, so the minimal safe path is to run the existing read-only
        L1 verifier at the two recovery entry points and fail closed with the
        concrete L1 reason when the chain, artifacts, attempt results or
        parameter bindings are not intact.
        """

        from researchflow.verification.context import load_context
        from researchflow.verification.l1 import L1Verifier

        try:
            ctx = load_context(self._db_path, self._task_root, task_id)
            result = L1Verifier().run(ctx)
        except ValueError as exc:
            raise RecoveryError(
                "RECOVERY_NOT_SAFE",
                f"cannot load the verification context before recovery: {exc}",
            ) from exc
        if result.status != "PASS":
            detail = "; ".join(
                f"{issue.code}: {issue.detail}" for issue in result.issues[:5]
            )
            raise RecoveryError(
                "RECOVERY_NOT_SAFE",
                f"L1 precheck failed before recovery: {detail}",
            )

    def _evidence_for_attempt(self, task_id: str, node_id: str, attempt_seq: int):
        attempt_id = f"attempt_{attempt_seq:02d}"
        return [
            row
            for row in self._collector.rows(task_id)
            if row.node_id == node_id and row.attempt_id == attempt_id
        ]

    def _existing_invalidations(self, task_id: str, node_id: str) -> list[str]:
        from researchflow.persistence.records import list_all_invalidations

        connection = connect(self._db_path)
        try:
            rows = list_all_invalidations(connection, task_id)
        finally:
            connection.close()
        return [row.evidence_id for row in rows if row.node_id == node_id]

    def _transition(
        self,
        *,
        obj_type: ObjectType,
        task_id: str,
        node_id: str,
        next_state: str,
        role: ActorRole,
        identity: str,
        reason: str,
        correlation_id: str,
        context: TransitionContext,
    ) -> Any:
        previous = self._node(task_id, node_id).state
        return self._sm.transition(
            TransitionRequest(
                obj_type=obj_type,
                task_id=task_id,
                node_id=node_id,
                previous_state=previous,
                next_state=next_state,
                actor=Actor(role, identity),
                reason_code=reason,
                rule_version="1.0",
                correlation_id=correlation_id,
                context=context,
            )
        )

    # --------------------------------------------------------------- invalidate
    def invalidate(
        self,
        task_id: str,
        *,
        changed_node: str,
        cause_type: str,
        cause_ref: str,
        new_dataset_sha256: str | None = None,
    ) -> dict[str, Any]:
        task = self._task(task_id)
        if task.state != "VERIFYING":
            raise RecoveryError(
                "RECOVERY_NOT_SAFE",
                f"recovery requires task state VERIFYING, found {task.state}",
            )
        graph_json = self._graph_json(task_id)
        spec = json.loads(task.task_spec_json)
        if spec.get("ruleset_hash") != RULESET_HASH:
            raise RecoveryError(
                "RULESET_VERSION_MISMATCH", "task ruleset differs from the current ruleset"
            )
        self._require_valid_evidence(task_id)
        if cause_type not in {
            "INPUT_CHANGE",
            "PREDECESSOR_CHANGE",
            "GRAPH_VERSION_CHANGE",
            "RULESET_CHANGE",
        }:
            raise RecoveryError("CAUSE_INVALID", f"invalid cause_type: {cause_type}")
        try:
            affected = affected_nodes(graph_json, changed_node)
        except KeyError as exc:
            raise RecoveryError("NODE_NOT_FOUND", str(exc)) from exc

        invalidated_evidence: list[str] = []
        for node_id in affected:
            node = self._node(task_id, node_id)
            if node.state == NodeState.INVALIDATED.value:
                # Idempotent repeat: keep the already-invalidated evidence in the
                # plan so the same inputs still produce the same plan hash.
                invalidated_evidence.extend(
                    self._existing_invalidations(task_id, node_id)
                )
                continue
            if node.state != NodeState.VERIFIED.value:
                raise RecoveryError(
                    "RECOVERY_NOT_SAFE",
                    f"node {node_id} is {node.state}; only VERIFIED nodes can be invalidated",
                )
            rows = self._evidence_for_attempt(task_id, node_id, node.attempt_seq)
            if not rows:
                raise RecoveryError(
                    "RECOVERY_NOT_SAFE",
                    f"node {node_id} has no evidence for attempt_{node.attempt_seq:02d}",
                )
            evidence_ids = tuple(row.evidence_id for row in rows)
            effective_cause = _INPUT_CAUSE if node_id == changed_node else _PREDECESSOR_CAUSE
            self._transition(
                obj_type=ObjectType.NODE,
                task_id=task_id,
                node_id=node_id,
                next_state=NodeState.INVALIDATED.value,
                role=ActorRole.WP_R,
                identity="recovery",
                reason="NODE_INVALIDATED",
                correlation_id=f"invalidate-{task_id}-{node_id}",
                context=TransitionContext(
                    evidence_ids=evidence_ids,
                    cause_type=effective_cause,
                    cause_ref=cause_ref,
                ),
            )
            invalidated_evidence.extend(evidence_ids)

        dataset_ref = dict(spec.get("dataset_ref") or {})
        dataset_sha = new_dataset_sha256 or str(dataset_ref.get("sha256", ""))
        plan = build_plan(
            task_id=task_id,
            graph_json=graph_json,
            ruleset_hash=RULESET_HASH,
            cause_type=cause_type,
            cause_ref=cause_ref,
            affected=affected,
            invalidated_evidence=invalidated_evidence,
            dataset_uri=str(dataset_ref.get("uri", "")),
            dataset_sha256=dataset_sha,
        )
        path, created = write_plan(self._plan_root, plan)
        self._record_freeze(task_id=task_id, plan=plan, created=created)
        return {
            "task_id": task_id,
            "changed_node": changed_node,
            "cause_type": cause_type,
            "cause_ref": cause_ref,
            "affected_nodes": affected,
            "invalidated_evidence": sorted(set(invalidated_evidence)),
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "plan_path": str(path),
            "plan_created": created,
            "dataset_sha256": dataset_sha,
            "frozen_at": format_utc(utc_now()),
        }

    def _record_freeze(
        self, *, task_id: str, plan: RecoveryPlan, created: bool
    ) -> None:
        """Record the freeze per affected node.

        ``05 §9.3`` requires the ``INVALIDATED → READY`` guard to find a freeze
        record for *this node*; one task-level row would not satisfy the frozen
        guard query, so one row per affected node is written in one transaction.
        """

        created_at = format_utc(utc_now())
        affected = [str(node_id) for node_id in plan.document.get("affected_nodes", [])]
        connection = connect(self._db_path)
        try:
            with transaction(connection):
                for node_id in affected:
                    self._audit.append(
                        connection,
                        audit_id=uuid.uuid4().hex,
                        task_id=task_id,
                        node_id=node_id,
                        actor="wp_r:recovery",
                        action="RECOVERY_PLAN_FROZEN" if created else "RECOVERY_PLAN_REUSE",
                        previous_state=None,
                        next_state=None,
                        reason_code="RECOVERY_PLAN_FROZEN",
                        rule_version="1.0",
                        correlation_id=plan.plan_id,
                        plan_id=plan.plan_id,
                        plan_hash=plan.plan_hash,
                        result="OK",
                        error_code=None,
                        created_at=created_at,
                        capability=WP_R_FREEZE,
                    )
        finally:
            connection.close()

    def _frozen_at(self, task_id: str, plan_hash: str):
        connection = connect(self._db_path)
        try:
            row = connection.execute(
                "SELECT created_at FROM audit_log WHERE task_id = ? AND plan_hash = ? "
                "AND action IN ('RECOVERY_PLAN_FROZEN','RECOVERY_PLAN_REUSE') "
                "AND result = 'OK' ORDER BY created_at DESC LIMIT 1",
                (task_id, plan_hash),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else parse_utc(str(row["created_at"]))

    # -------------------------------------------------------------------- rerun
    def rerun(self, task_id: str, plan_hash: str) -> dict[str, Any]:
        task = self._task(task_id)
        if task.state != "VERIFYING":
            raise RecoveryError(
                "RECOVERY_NOT_SAFE",
                f"rerun requires task state VERIFYING, found {task.state}",
            )
        try:
            document = read_plan(self._plan_root, plan_hash)
        except PlanError as exc:
            raise RecoveryError(exc.code, exc.detail) from exc
        if document.get("task_id") != task_id:
            raise RecoveryError(
                "PLAN_TASK_MISMATCH", "the plan belongs to a different task"
            )
        self._require_valid_evidence(task_id)
        spec = json.loads(task.task_spec_json)
        dataset = dict(document.get("dataset") or {})
        plan_id = "plan_" + plan_hash[:32]
        dataset_ref = {
            "uri": str(dataset.get("uri", "")),
            "sha256": str(dataset.get("sha256", "")),
            "license": str((spec.get("dataset_ref") or {}).get("license", "")),
        }
        limits = dict(spec.get("limits") or {})
        frozen_at = self._frozen_at(task_id, plan_hash)
        received_at = utc_now()
        if frozen_at is not None:
            earliest = frozen_at + timedelta(milliseconds=1)
            if received_at < earliest:
                received_at = earliest

        attempts: list[dict[str, Any]] = []
        for step in document.get("steps", []):
            node_id = str(step["node_id"])
            node = self._node(task_id, node_id)
            if node.state != NodeState.INVALIDATED.value:
                raise RecoveryError(
                    "RECOVERY_NOT_SAFE",
                    f"node {node_id} is {node.state}; expected INVALIDATED",
                )
            try:
                self._transition(
                    obj_type=ObjectType.NODE,
                    task_id=task_id,
                    node_id=node_id,
                    next_state=NodeState.READY.value,
                    role=ActorRole.WP_R,
                    identity="recovery",
                    reason="NODE_READY",
                    correlation_id=f"rerun-{task_id}-{node_id}",
                    context=TransitionContext(
                        plan_id=plan_id,
                        plan_hash=plan_hash,
                        received_at=received_at,
                    ),
                )
            except StateTransitionDenied as exc:
                raise RecoveryError(exc.reason, exc.details or str(exc)) from exc
            self._transition(
                obj_type=ObjectType.NODE,
                task_id=task_id,
                node_id=node_id,
                next_state=NodeState.RUNNING.value,
                role=ActorRole.SCHEDULER,
                identity="recovery",
                reason="NODE_RUNNING",
                correlation_id=f"rerun-{task_id}-{node_id}",
                context=TransitionContext(),
            )
            node_row = self._node(task_id, node_id)
            input_artifacts: dict[str, Path] = {}
            if str(step.get("template_id")) == TRAIN_TEMPLATE_ID:
                split_row = self._node(task_id, "split_dataset")
                manifest = (
                    self._task_root / "tasks" / task_id / "attempts" / "split_dataset"
                    / f"attempt_{split_row.attempt_seq:02d}" / "output" / "split_manifest.json"
                )
                if not manifest.is_file():
                    raise RecoveryError(
                        "SPLIT_MANIFEST_MISSING",
                        f"re-run split manifest is missing before {node_id}",
                    )
                input_artifacts["split_manifest"] = manifest
            observation = self._executor.run(
                task_id=task_id,
                node_id=node_id,
                attempt_seq=node_row.attempt_seq,
                template_id=str(step["template_id"]),
                parameters=dict(step.get("parameters") or {}),
                dataset_ref=dataset_ref,
                input_artifacts=input_artifacts,
                limits=limits,
            )
            self._collector.record_observation(observation)
            attempts.append(
                {
                    "node_id": node_id,
                    "attempt_id": observation.attempt_id,
                    "status": observation.status,
                    "exit_code": observation.exit_code,
                    "artifacts": [artifact.path for artifact in observation.artifacts],
                }
            )
            if observation.succeeded and observation.worker_error is None:
                self._transition(
                    obj_type=ObjectType.NODE,
                    task_id=task_id,
                    node_id=node_id,
                    next_state=NodeState.VERIFYING.value,
                    role=ActorRole.ORCHESTRATOR,
                    identity="recovery",
                    reason="NODE_VERIFYING",
                    correlation_id=f"rerun-{task_id}-{node_id}",
                    context=TransitionContext(
                        attempt_id=observation.attempt_id,
                    ),
                )
            else:
                self._transition(
                    obj_type=ObjectType.NODE,
                    task_id=task_id,
                    node_id=node_id,
                    next_state=NodeState.FAILED.value,
                    role=ActorRole.ORCHESTRATOR,
                    identity="recovery",
                    reason="NODE_FAILED",
                    correlation_id=f"rerun-{task_id}-{node_id}",
                    context=TransitionContext(
                        failure_ref=observation.attempt_id,
                    ),
                )
                raise RecoveryError(
                    "RERUN_FAILED",
                    f"node {node_id} failed during rerun: {observation.status} "
                    f"{observation.worker_error}",
                )
        return {
            "task_id": task_id,
            "plan_id": plan_id,
            "plan_hash": plan_hash,
            "attempts": attempts,
        }
