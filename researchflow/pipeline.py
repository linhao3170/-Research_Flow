"""T0 orchestration pipeline: task → DAG → executor → collector → verifier.

The pipeline is *internal orchestration*; it does not invent public API routes.
Every state change goes through ``StateMachine.transition()`` with production
fact ports, so the same guards that protect the API protect the pipeline.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from researchflow.dag import DagError, build_graph, register_graph
from researchflow.evidence.collector import Collector
from researchflow.execution.executor import Executor
from researchflow.gate.gate import Gate
from researchflow.orchestration.ports import Ports
from researchflow.orchestration.sqlite_ports import build_ports
from researchflow.orchestration.state_machine import (
    Actor,
    StateMachine,
    StateTransitionDenied,
    TransitionContext,
    TransitionRequest,
)
from researchflow.orchestration.transitions import ActorRole, NodeState, ObjectType, TaskState
from researchflow.persistence.db import connect, transaction
from researchflow.persistence.records import GraphRecord
from researchflow.persistence.repositories import NodeRepository, TaskRepository
from researchflow.rules import RULESET_HASH
from researchflow.signing.keys import KeyStore
from researchflow.templates.registry import SPLIT_TEMPLATE_ID, TRAIN_TEMPLATE_ID
from researchflow.verification.verifier import VerificationOutcome, VerificationService

__all__ = ["PipelineError", "PipelineResult", "TaskPipeline"]


class PipelineError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class PipelineResult:
    task_id: str
    ok: bool
    state: str
    final_state: str
    report_id: str | None
    certificate_id: str | None
    attempts: tuple[dict[str, Any], ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "ok": self.ok,
            "state": self.state,
            "final_state": self.final_state,
            "report_id": self.report_id,
            "certificate_id": self.certificate_id,
            "attempts": list(self.attempts),
            "error": self.error,
        }


class TaskPipeline:
    def __init__(
        self,
        db_path: str | Path,
        task_root: str | Path,
        *,
        key_store: KeyStore | None = None,
        executor: Executor | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._task_root = Path(task_root) if task_root else self._db_path.parent
        self._key_store = key_store or KeyStore(self._task_root / "keys")
        self._executor = executor or Executor(self._task_root)
        self._collector = Collector(self._db_path, self._task_root)
        self._tasks = TaskRepository()
        self._nodes = NodeRepository()
        self._ports: Ports = build_ports(self._db_path, self._task_root)
        self._sm = StateMachine(self._db_path, ports=self._ports)

    # ------------------------------------------------------------------ helpers
    def _task_row(self, task_id: str):
        connection = connect(self._db_path)
        try:
            row = self._tasks.get(connection, task_id)
        finally:
            connection.close()
        if row is None:
            raise PipelineError("TASK_NOT_FOUND", f"task {task_id} does not exist")
        return row

    def _node_row(self, task_id: str, node_id: str):
        connection = connect(self._db_path)
        try:
            row = self._nodes.get(connection, task_id, node_id)
        finally:
            connection.close()
        if row is None:
            raise PipelineError("NODE_NOT_FOUND", f"node {node_id} does not exist")
        return row

    def _transition(
        self,
        *,
        obj_type: ObjectType,
        task_id: str,
        next_state: str,
        actor_role: ActorRole,
        identity: str,
        reason: str,
        correlation_id: str,
        node_id: str | None = None,
        context: TransitionContext | None = None,
    ):
        if obj_type is ObjectType.TASK:
            previous = self._task_row(task_id).state
        else:
            assert node_id is not None
            previous = self._node_row(task_id, node_id).state
        request = TransitionRequest(
            obj_type=obj_type,
            task_id=task_id,
            node_id=node_id,
            previous_state=previous,
            next_state=next_state,
            actor=Actor(actor_role, identity),
            reason_code=reason,
            rule_version="1.0",
            correlation_id=correlation_id,
            context=context or TransitionContext(),
        )
        return self._sm.transition(request)

    def _graph_json(self, task_id: str) -> dict[str, Any]:
        from researchflow.persistence.records import GraphRepository

        connection = connect(self._db_path)
        try:
            graph = GraphRepository().get(connection, task_id)
        finally:
            connection.close()
        if graph is None:
            raise PipelineError("GRAPH_MISSING", f"graph is not registered for {task_id}")
        return graph.graph_json

    # --------------------------------------------------------------------- plan
    def _mark_ready(self, task_id: str, node_id: str) -> None:
        self._transition(
            obj_type=ObjectType.NODE,
            task_id=task_id,
            node_id=node_id,
            next_state=NodeState.READY.value,
            actor_role=ActorRole.SCHEDULER,
            identity="pipeline",
            reason="NODE_READY",
            correlation_id=f"node-{node_id}",
        )

    def _node_parameters(
        self, graph_json: Mapping[str, Any], node_id: str, node_spec: Mapping[str, Any]
    ) -> dict[str, Any]:
        stored = (graph_json.get("parameters_by_node") or {}).get(node_id)
        if stored:
            return dict(stored)
        task_spec = json.loads(self._task_row(str(graph_json.get("task_id"))).task_spec_json)
        parameters = dict(task_spec.get("parameters") or {})
        if node_spec.get("template_id") == SPLIT_TEMPLATE_ID:
            return {
                "target": parameters.get("target"),
                "seed": parameters.get("seed"),
                "test_size": parameters.get("test_size"),
            }
        if node_spec.get("template_id") == TRAIN_TEMPLATE_ID:
            model = node_id.removeprefix("train_")
            return {"model": model, "seed": parameters.get("seed")}
        raise PipelineError(
            "PARAMETERS_NOT_STORED", f"no parameters are known for node {node_id}"
        )

    def ensure_graph(self, task_id: str) -> GraphRecord:
        from researchflow.persistence.records import GraphRepository

        task = self._task_row(task_id)
        spec = json.loads(task.task_spec_json)
        if spec.get("ruleset_hash") != RULESET_HASH:
            raise PipelineError(
                "RULESET_VERSION_MISMATCH",
                f"task ruleset_hash {spec.get('ruleset_hash')} != current {RULESET_HASH}",
            )
        try:
            graph = build_graph(spec)
        except DagError as exc:
            raise PipelineError(exc.code, str(exc)) from exc
        connection = connect(self._db_path)
        try:
            with transaction(connection):
                record = register_graph(connection, graph)
                existing = {
                    row.node_id for row in self._nodes.list_for_task(connection, task_id)
                }
                from researchflow.contracts.models import NodeSpec

                for node in graph.nodes:
                    if node.node_id in existing:
                        continue
                    self._sm.create_initial(
                        obj_type="node",
                        task_id=task_id,
                        node_id=node.node_id,
                        actor=Actor(ActorRole.ORCHESTRATOR, "pipeline"),
                        correlation_id=f"plan-{task_id}-{node.node_id}",
                        node_spec=NodeSpec.model_validate(node.to_spec_dict()),
                        connection=connection,
                    )
        finally:
            connection.close()
        return record

    def plan(self, task_id: str) -> GraphRecord:
        graph = self.ensure_graph(task_id)
        task = self._task_row(task_id)
        if task.state == TaskState.CREATED.value:
            self._transition(
                obj_type=ObjectType.TASK,
                task_id=task_id,
                next_state=TaskState.PLANNING.value,
                actor_role=ActorRole.ORCHESTRATOR,
                identity="pipeline",
                reason="TASK_PLANNING_STARTED",
                correlation_id=f"plan-{task_id}",
            )
            task = self._task_row(task_id)
        if task.state == TaskState.PLANNING.value:
            self._transition(
                obj_type=ObjectType.TASK,
                task_id=task_id,
                next_state=TaskState.READY.value,
                actor_role=ActorRole.ORCHESTRATOR,
                identity="pipeline",
                reason="TASK_READY",
                correlation_id=f"plan-{task_id}",
                context=TransitionContext(graph_version=graph.graph_version),
            )
        return graph

    # ------------------------------------------------------------------ execute
    def execute(self, task_id: str) -> PipelineResult:
        graph = self.plan(task_id)
        graph_json = graph.graph_json
        specs = {str(node["node_id"]): node for node in graph_json["nodes"]}
        parameters_by_node = {
            str(key): dict(value)
            for key, value in (graph_json.get("parameters_by_node") or {}).items()
        }
        order = [str(node_id) for node_id in graph_json["topology_order"]]

        for node_id in order:
            spec = specs[node_id]
            if not spec.get("depends_on"):
                self._mark_ready(task_id, node_id)
        task = self._task_row(task_id)
        if task.state == TaskState.READY.value:
            self._transition(
                obj_type=ObjectType.TASK,
                task_id=task_id,
                next_state=TaskState.RUNNING.value,
                actor_role=ActorRole.ORCHESTRATOR,
                identity="pipeline",
                reason="TASK_RUNNING",
                correlation_id=f"run-{task_id}",
            )

        attempts: list[dict[str, Any]] = []
        task_spec = json.loads(self._task_row(task_id).task_spec_json)
        dataset_ref = dict(task_spec["dataset_ref"])
        limits = dict(task_spec["limits"])
        max_workers = max(1, int(limits.get("max_workers", 1)))
        pending = list(order)
        executed: set[str] = set()
        while pending:
            runnable = [
                node_id
                for node_id in pending
                if all(
                    dependency in executed
                    for dependency in specs[node_id].get("depends_on", [])
                )
            ]
            if not runnable:
                raise PipelineError(
                    "DAG_SCHEDULER_STALL",
                    f"no runnable node among {pending}",
                )
            batch = runnable[:max_workers]
            for node_id in batch:
                if self._node_row(task_id, node_id).state == NodeState.PLANNED.value:
                    self._mark_ready(task_id, node_id)
            if len(batch) == 1:
                results = [
                    self._execute_node(
                        task_id,
                        batch[0],
                        specs[batch[0]],
                        parameters_by_node,
                        graph_json,
                        dataset_ref,
                        limits,
                    )
                ]
            else:
                with ThreadPoolExecutor(
                    max_workers=len(batch), thread_name_prefix="rf-node"
                ) as pool:
                    results = list(
                        pool.map(
                            lambda node_id: self._execute_node(
                                task_id,
                                node_id,
                                specs[node_id],
                                parameters_by_node,
                                graph_json,
                                dataset_ref,
                                limits,
                            ),
                            batch,
                        )
                    )
            attempts.extend(results)
            failure = next((item for item in results if not item["ok"]), None)
            if failure is not None:
                try:
                    self._transition(
                        obj_type=ObjectType.TASK,
                        task_id=task_id,
                        next_state=TaskState.FAILED.value,
                        actor_role=ActorRole.ORCHESTRATOR,
                        identity="pipeline",
                        reason="TASK_FAILED",
                        correlation_id=f"run-{task_id}",
                        context=TransitionContext(failure_ref=failure["attempt_id"]),
                    )
                except StateTransitionDenied:
                    pass
                return PipelineResult(
                    task_id=task_id,
                    ok=False,
                    state=self._task_row(task_id).state,
                    final_state="FAILED",
                    report_id=None,
                    certificate_id=None,
                    attempts=tuple(attempts),
                    error=failure["error"],
                )
            for node_id in batch:
                executed.add(node_id)
                pending.remove(node_id)

        self._transition(
            obj_type=ObjectType.TASK,
            task_id=task_id,
            next_state=TaskState.VERIFYING.value,
            actor_role=ActorRole.ORCHESTRATOR,
            identity="pipeline",
            reason="TASK_VERIFYING",
            correlation_id=f"run-{task_id}",
        )
        return PipelineResult(
            task_id=task_id,
            ok=True,
            state=self._task_row(task_id).state,
            final_state="RUNNING",
            report_id=None,
            certificate_id=None,
            attempts=tuple(attempts),
        )

    # ------------------------------------------------------------------- verify
    def _execute_node(
        self,
        task_id: str,
        node_id: str,
        spec: Mapping[str, Any],
        parameters_by_node: Mapping[str, dict[str, Any]],
        graph_json: Mapping[str, Any],
        dataset_ref: Mapping[str, Any],
        limits: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._transition(
            obj_type=ObjectType.NODE,
            task_id=task_id,
            node_id=node_id,
            next_state=NodeState.RUNNING.value,
            actor_role=ActorRole.SCHEDULER,
            identity="pipeline",
            reason="NODE_RUNNING",
            correlation_id=f"run-{node_id}",
        )
        node_row = self._node_row(task_id, node_id)
        try:
            input_artifacts: dict[str, Path] = {}
            if spec["template_id"] == TRAIN_TEMPLATE_ID:
                split_row = self._node_row(task_id, "split_dataset")
                manifest = (
                    self._task_root / "tasks" / task_id / "attempts" / "split_dataset"
                    / f"attempt_{split_row.attempt_seq:02d}" / "output" / "split_manifest.json"
                )
                if not manifest.is_file():
                    raise PipelineError(
                        "SPLIT_MANIFEST_MISSING",
                        f"split manifest is missing before {node_id}",
                    )
                input_artifacts["split_manifest"] = manifest
            parameters = parameters_by_node.get(node_id) or self._node_parameters(
                graph_json, node_id, spec
            )
            observation = self._executor.run(
                task_id=task_id,
                node_id=node_id,
                attempt_seq=node_row.attempt_seq,
                template_id=str(spec["template_id"]),
                parameters=parameters,
                dataset_ref=dataset_ref,
                input_artifacts=input_artifacts,
                limits=limits,
            )
            self._collector.record_observation(observation)
        except Exception as exc:  # noqa: BLE001 - converted into a node failure
            self._transition(
                obj_type=ObjectType.NODE,
                task_id=task_id,
                node_id=node_id,
                next_state=NodeState.FAILED.value,
                actor_role=ActorRole.ORCHESTRATOR,
                identity="pipeline",
                reason="NODE_FAILED",
                correlation_id=f"run-{node_id}",
                context=TransitionContext(failure_ref=f"exception:{node_id}"),
            )
            return {
                "node_id": node_id,
                "attempt_id": f"attempt_{node_row.attempt_seq:02d}",
                "status": "EXCEPTION",
                "exit_code": None,
                "duration_sec": 0.0,
                "artifacts": [],
                "ok": False,
                "error": f"node {node_id} raised {type(exc).__name__}: {exc}",
            }
        record = {
            "node_id": node_id,
            "attempt_id": observation.attempt_id,
            "status": observation.status,
            "exit_code": observation.exit_code,
            "duration_sec": observation.duration_sec,
            "artifacts": [artifact.path for artifact in observation.artifacts],
        }
        if observation.succeeded and observation.worker_error is None:
            self._transition(
                obj_type=ObjectType.NODE,
                task_id=task_id,
                node_id=node_id,
                next_state=NodeState.VERIFYING.value,
                actor_role=ActorRole.ORCHESTRATOR,
                identity="pipeline",
                reason="NODE_VERIFYING",
                correlation_id=f"run-{node_id}",
                context=TransitionContext(attempt_id=observation.attempt_id),
            )
            return {**record, "ok": True}
        self._transition(
            obj_type=ObjectType.NODE,
            task_id=task_id,
            node_id=node_id,
            next_state=NodeState.FAILED.value,
            actor_role=ActorRole.ORCHESTRATOR,
            identity="pipeline",
            reason="NODE_FAILED",
            correlation_id=f"run-{node_id}",
            context=TransitionContext(failure_ref=observation.attempt_id),
        )
        return {
            **record,
            "ok": False,
            "error": f"node {node_id} failed: {observation.status} "
            f"{observation.worker_error}",
        }

    # ------------------------------------------------------------------- verify
    def verify(self, task_id: str) -> VerificationOutcome:
        task = self._task_row(task_id)
        if task.state not in {TaskState.VERIFYING.value}:
            raise PipelineError(
                "STATE_TRANSITION_DENIED",
                f"verification requires task state VERIFYING, found {task.state}",
            )
        service = VerificationService(
            self._db_path, self._task_root, key_store=self._key_store
        )
        return service.verify(task_id)

    def mark_nodes_verified(self, task_id: str) -> None:
        graph = self._graph_json(task_id)
        for node_id in [str(item) for item in graph["topology_order"]]:
            row = self._node_row(task_id, node_id)
            if row.state == NodeState.VERIFYING.value:
                self._transition(
                    obj_type=ObjectType.NODE,
                    task_id=task_id,
                    node_id=node_id,
                    next_state=NodeState.VERIFIED.value,
                    actor_role=ActorRole.ORCHESTRATOR,
                    identity="pipeline",
                    reason="NODE_VERIFIED",
                    correlation_id=f"verify-{task_id}-{node_id}",
                )

    def complete_task(self, task_id: str) -> None:
        task = self._task_row(task_id)
        if task.state == TaskState.COMPLETED.value:
            return
        self._transition(
            obj_type=ObjectType.TASK,
            task_id=task_id,
            next_state=TaskState.COMPLETED.value,
            actor_role=ActorRole.ORCHESTRATOR,
            identity="pipeline",
            reason="TASK_COMPLETED",
            correlation_id=f"complete-{task_id}",
        )

    # -------------------------------------------------------------------- run it
    def run_task(self, task_id: str) -> dict[str, Any]:
        execution = self.execute(task_id)
        if not execution.ok:
            return execution.to_dict()
        outcome = self.verify(task_id)
        result: dict[str, Any] = {
            **execution.to_dict(),
            "verification": outcome.to_dict(),
        }
        if outcome.final_state != "VERIFIED":
            result["ok"] = False
            result["final_state"] = outcome.final_state
            return result
        self.mark_nodes_verified(task_id)
        self.complete_task(task_id)
        result["state"] = self._task_row(task_id).state
        result["final_state"] = outcome.final_state
        result["report_id"] = outcome.report_id
        result["certificate_id"] = outcome.certificate_id
        return result

    def gate(self, task_id: str):
        return Gate(self._db_path, self._task_root).evaluate(task_id)