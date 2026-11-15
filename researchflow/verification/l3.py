"""Verifier L3: independent replay from raw data (T0 WP-10).

L3 never reads the executor's predictions as an input.  In a fresh directory it
runs the split template and then the training template in separate subprocesses
from the original dataset, and compares the replayed split hash, predictions
and metrics with the executor's observed results.  Any attempt to point L3 at
the executor's attempt directory, at the verifier's own process, or at reused
executor output is rejected before comparison.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from researchflow.execution.executor import Executor, AttemptObservation
from researchflow.templates.datasets import resolve_dataset
from researchflow.templates.estimators import compare_metrics, load_predictions_csv
from researchflow.templates.split import manifest_hash
from researchflow.verification.context import VerificationContext

__all__ = [
    "L3Issue",
    "L3IsolationError",
    "L3NodeResult",
    "L3Result",
    "L3Verifier",
]

L3_DIR_NOT_ISOLATED = "L3_DIR_NOT_ISOLATED"
L3_REUSED_EXECUTOR_OUTPUT = "L3_REUSED_EXECUTOR_OUTPUT"
L3_IN_PROCESS_STATE = "L3_IN_PROCESS_STATE"
L3_SPLIT_MISMATCH = "L3_SPLIT_MISMATCH"
L3_METRIC_MISMATCH = "L3_METRIC_MISMATCH"
L3_PREDICTION_MISMATCH = "L3_PREDICTION_MISMATCH"
L3_RERUN_FAILED = "L3_RERUN_FAILED"
L3_MISSING_EXECUTOR_OUTPUT = "L3_MISSING_EXECUTOR_OUTPUT"
L3_PARAMETERS_BINDING_MISMATCH = "L3_PARAMETERS_BINDING_MISMATCH"
L3_PARAMETERS_BINDING_INCOMPLETE = "L3_PARAMETERS_BINDING_INCOMPLETE"


class L3IsolationError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class L3Issue:
    code: str
    node_id: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "node_id": self.node_id, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class L3NodeResult:
    node_id: str
    status: str
    match_mode: str
    split_hash: str
    executor_split_hash: str
    prediction_mismatches: int
    metric_deltas: tuple[dict[str, Any], ...]
    l3_split_dir: str
    l3_train_dir: str
    split_pid: int | None
    train_pid: int | None
    issues: tuple[L3Issue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "match_mode": self.match_mode,
            "split_hash": self.split_hash,
            "executor_split_hash": self.executor_split_hash,
            "prediction_mismatches": self.prediction_mismatches,
            "metric_deltas": [dict(delta) for delta in self.metric_deltas],
            "l3_split_dir": self.l3_split_dir,
            "l3_train_dir": self.l3_train_dir,
            "split_pid": self.split_pid,
            "train_pid": self.train_pid,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class L3Result:
    status: str
    coverage: float
    nodes: tuple[L3NodeResult, ...]
    issues: tuple[L3Issue, ...]
    verification_root: str
    processes: tuple[int | None, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "coverage": self.coverage,
            "nodes": [node.to_dict() for node in self.nodes],
            "issues": [issue.to_dict() for issue in self.issues],
            "verification_root": self.verification_root,
            "processes": list(self.processes),
        }


class L3Verifier:
    def __init__(
        self,
        task_root: str | Path,
        *,
        python_executable: str | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        self._task_root = Path(task_root)
        self._python = python_executable
        self._repo_root = repo_root

    # ------------------------------------------------------------------ helpers
    def _run_root(self, ctx: VerificationContext) -> Path:
        # A short directory name keeps the nested attempt paths below the
        # Windows MAX_PATH limit while still being a fresh directory per run.
        return self._task_root / "verification" / f"l3-{uuid.uuid4().hex[:10]}"

    def validate_isolation(
        self,
        observation: AttemptObservation,
        *,
        executor_attempt_dir: Path,
    ) -> None:
        executor_root = executor_attempt_dir.resolve()
        attempt_dir = Path(observation.attempt_dir).resolve()
        if attempt_dir == executor_root or executor_root in attempt_dir.parents:
            raise L3IsolationError(
                L3_DIR_NOT_ISOLATED,
                f"L3 attempt directory is inside the executor attempt: {attempt_dir}",
            )
        if observation.pid is None or observation.pid == os.getpid():
            raise L3IsolationError(
                L3_IN_PROCESS_STATE,
                "L3 rerun must happen in a separate process",
            )
        for name in (observation.inputs or ()):
            source = str(name.get("name", ""))
            if "executor" in source:
                raise L3IsolationError(
                    L3_REUSED_EXECUTOR_OUTPUT,
                    f"L3 input appears to come from executor output: {source}",
                )

    def _dataset_ref(self, ctx: VerificationContext) -> dict[str, Any]:
        dataset_ref = dict(ctx.task_spec.get("dataset_ref") or {})
        effective = ctx.effective_dataset_sha256("split_dataset")
        if effective:
            dataset_ref["sha256"] = effective
        return dataset_ref

    def run(self, ctx: VerificationContext) -> L3Result:
        metric_nodes = ctx.metric_nodes()
        bound_parameters, binding_issues = self._preflight(ctx)
        if binding_issues:
            # Fail closed before creating a verification directory or spawning
            # any subprocess: a rerun started from unattested parameters would
            # make the replay meaningless even if its results matched.
            return L3Result(
                status="FAIL",
                coverage=0.0,
                nodes=(),
                issues=binding_issues,
                verification_root="",
                processes=(),
            )
        run_root = self._run_root(ctx)
        run_root.mkdir(parents=True, exist_ok=False)
        executor = Executor(
            run_root,
            python_executable=self._python,
            repo_root=self._repo_root,
            task_dir_name="l3",
        )
        dataset_ref = self._dataset_ref(ctx)
        limits = dict(ctx.task_spec.get("limits") or {"wall_time_sec": 1800})

        # Replay the split from raw data first (fresh directory, fresh process).
        split_observation = executor.run(
            task_id=ctx.task_id,
            node_id="l3_split",
            attempt_seq=1,
            template_id="split_dataset@1.0.0",
            parameters=dict(bound_parameters["split_dataset"]),
            dataset_ref=dataset_ref,
            limits=limits,
        )
        self.validate_isolation(
            split_observation,
            executor_attempt_dir=ctx.attempt_dir("split_dataset", 1),
        )
        if not split_observation.succeeded:
            issue = L3Issue(
                L3_RERUN_FAILED,
                "l3_split",
                f"L3 split rerun failed: {split_observation.status} "
                f"{split_observation.worker_error}",
            )
            return L3Result(
                status="FAIL",
                coverage=0.0,
                nodes=(),
                issues=(issue,),
                verification_root=str(run_root),
                processes=(split_observation.pid,),
            )
        l3_split_manifest = json.loads(
            (split_observation.attempt_dir / "output" / "split_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        executor_split_manifest = self._executor_split_manifest(ctx)

        tolerance = float(ctx.ruleset.get("l3", {}).get("metric_tolerance", 1e-9))
        mismatch_limit = int(
            ctx.ruleset.get("l3", {}).get("prediction_mismatch_limit", 0)
        )
        node_results: list[L3NodeResult] = []
        issues: list[L3Issue] = []
        coverage_ok = 0
        processes: list[int | None] = [split_observation.pid]

        for node_id in metric_nodes:
            node = ctx.nodes.get(node_id)
            node_issues: list[L3Issue] = []
            if node is None:
                node_issues.append(L3Issue(L3_MISSING_EXECUTOR_OUTPUT, node_id, "node row is missing"))
                node_results.append(
                    self._failed_node(node_id, run_root, split_observation.pid, node_issues)
                )
                issues.extend(node_issues)
                continue
            executor_output = ctx.attempt_dir(node_id, node.attempt_seq) / "output"
            executor_metrics_path = executor_output / "metrics.json"
            executor_predictions_path = executor_output / "predictions.csv"
            executor_split_hash = (
                str(executor_split_manifest.get("split_hash", ""))
                if executor_split_manifest
                else ""
            )
            if not executor_metrics_path.is_file() or not executor_predictions_path.is_file():
                node_issues.append(
                    L3Issue(
                        L3_MISSING_EXECUTOR_OUTPUT,
                        node_id,
                        "executor metrics/predictions are missing",
                    )
                )
                node_results.append(
                    self._failed_node(node_id, run_root, split_observation.pid, node_issues)
                )
                issues.extend(node_issues)
                continue

            parameters = dict(bound_parameters[node_id])
            train_observation = executor.run(
                task_id=ctx.task_id,
                node_id=node_id,
                attempt_seq=1,
                template_id="train_classifier@1.0.0",
                parameters=parameters,
                dataset_ref=dataset_ref,
                input_artifacts={
                    "split_manifest": split_observation.attempt_dir / "output" / "split_manifest.json"
                },
                limits=limits,
            )
            self.validate_isolation(
                train_observation,
                executor_attempt_dir=ctx.attempt_dir(node_id, node.attempt_seq),
            )
            processes.append(train_observation.pid)
            if not train_observation.succeeded:
                node_issues.append(
                    L3Issue(
                        L3_RERUN_FAILED,
                        node_id,
                        f"L3 train rerun failed: {train_observation.status} "
                        f"{train_observation.worker_error}",
                    )
                )
                node_results.append(
                    L3NodeResult(
                        node_id=node_id,
                        status="FAIL",
                        match_mode="MISMATCH",
                        split_hash=str(l3_split_manifest.get("split_hash", "")),
                        executor_split_hash=executor_split_hash,
                        prediction_mismatches=-1,
                        metric_deltas=(),
                        l3_split_dir=str(split_observation.attempt_dir),
                        l3_train_dir=str(train_observation.attempt_dir),
                        split_pid=split_observation.pid,
                        train_pid=train_observation.pid,
                        issues=tuple(node_issues),
                    )
                )
                issues.extend(node_issues)
                continue

            l3_metrics = json.loads(
                (train_observation.attempt_dir / "output" / "metrics.json").read_text(
                    encoding="utf-8"
                )
            )
            l3_predictions = load_predictions_csv(
                train_observation.attempt_dir / "output" / "predictions.csv"
            )
            executor_metrics = json.loads(executor_metrics_path.read_text(encoding="utf-8"))
            executor_predictions = load_predictions_csv(executor_predictions_path)

            split_hash = str(l3_split_manifest.get("split_hash", ""))
            if split_hash != executor_split_hash:
                node_issues.append(
                    L3Issue(
                        L3_SPLIT_MISMATCH,
                        node_id,
                        f"L3 split_hash {split_hash} != executor split_hash {executor_split_hash}",
                    )
                )

            mismatch_count = sum(
                1
                for left, right in zip(l3_predictions, executor_predictions)
                if left != right
            ) + abs(len(l3_predictions) - len(executor_predictions))
            if mismatch_count > mismatch_limit:
                node_issues.append(
                    L3Issue(
                        L3_PREDICTION_MISMATCH,
                        node_id,
                        f"{mismatch_count} predictions differ from the executor run",
                    )
                )

            deltas: list[dict[str, Any]] = []
            for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro"):
                if key not in l3_metrics or key not in executor_metrics:
                    deltas.append({"metric": key, "reason": "missing"})
                    continue
                left = float(l3_metrics[key])
                right = float(executor_metrics[key])
                deltas.append(
                    {
                        "metric": key,
                        "executor": right,
                        "l3": left,
                        "delta": abs(left - right),
                        "within_tolerance": abs(left - right) <= tolerance,
                    }
                )
            metric_mismatches = [
                delta for delta in deltas if not delta.get("within_tolerance", False)
            ]
            if metric_mismatches:
                node_issues.append(
                    L3Issue(
                        L3_METRIC_MISMATCH,
                        node_id,
                        f"{len(metric_mismatches)} metrics exceed tolerance {tolerance}",
                    )
                )

            exact = (
                mismatch_count == 0
                and all(
                    float(l3_metrics[key]) == float(executor_metrics[key])
                    for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro")
                )
            )
            status = "PASS" if not node_issues else "FAIL"
            if status == "PASS":
                coverage_ok += 1
            node_results.append(
                L3NodeResult(
                    node_id=node_id,
                    status=status,
                    match_mode="EXACT" if status == "PASS" and exact else (
                        "TOLERANCE" if status == "PASS" else "MISMATCH"
                    ),
                    split_hash=split_hash,
                    executor_split_hash=executor_split_hash,
                    prediction_mismatches=mismatch_count,
                    metric_deltas=tuple(deltas),
                    l3_split_dir=str(split_observation.attempt_dir),
                    l3_train_dir=str(train_observation.attempt_dir),
                    split_pid=split_observation.pid,
                    train_pid=train_observation.pid,
                    issues=tuple(node_issues),
                )
            )
            issues.extend(node_issues)

        coverage = coverage_ok / len(metric_nodes) if metric_nodes else 0.0
        minimum = float(ctx.ruleset.get("l3", {}).get("minimum_coverage", 1.0))
        status = "PASS" if issues == [] and coverage >= minimum and metric_nodes else "FAIL"
        return L3Result(
            status=status,
            coverage=coverage,
            nodes=tuple(node_results),
            issues=tuple(issues),
            verification_root=str(run_root),
            processes=tuple(processes),
        )

    # ----------------------------------------------------------------- helpers
    def _executor_split_manifest(self, ctx: VerificationContext) -> dict[str, Any]:
        node = ctx.nodes.get("split_dataset")
        if node is None:
            return {}
        path = ctx.attempt_dir("split_dataset", node.attempt_seq) / "output" / "split_manifest.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _preflight(
        self, ctx: VerificationContext
    ) -> tuple[dict[str, dict[str, Any]], tuple[L3Issue, ...]]:
        """Bind every node the replay will execute to its declared parameters.

        The replay must not start until the split node and every metric node
        prove that ``job.json``, its recomputed hash, ``result.json``, the E2
        launch evidence and the registered NodeSpec all agree.  Running first
        and inferring tampering from equal-looking metrics is not acceptable.
        """

        parameters: dict[str, dict[str, Any]] = {}
        issues: list[L3Issue] = []
        node_ids = ["split_dataset"]
        node_ids.extend(ctx.metric_nodes())
        for node_id in node_ids:
            node = ctx.nodes.get(node_id)
            if node is None:
                if node_id == "split_dataset":
                    issues.append(
                        L3Issue(
                            L3_MISSING_EXECUTOR_OUTPUT,
                            node_id,
                            "split_dataset node row is missing",
                        )
                    )
                continue
            binding = ctx.parameter_binding(node_id, node.attempt_seq)
            for problem in binding.problems:
                code = (
                    L3_PARAMETERS_BINDING_INCOMPLETE
                    if problem["code"] == "PARAMETERS_BINDING_MISSING"
                    else L3_PARAMETERS_BINDING_MISMATCH
                )
                issues.append(L3Issue(code, node_id, problem["detail"]))
            bound = binding.parameters()
            if bound is not None:
                parameters[node_id] = bound
        return parameters, tuple(issues)

    def _failed_node(
        self,
        node_id: str,
        run_root: Path,
        split_pid: int | None,
        issues: Sequence[L3Issue],
    ) -> L3NodeResult:
        return L3NodeResult(
            node_id=node_id,
            status="FAIL",
            match_mode="MISMATCH",
            split_hash="",
            executor_split_hash="",
            prediction_mismatches=-1,
            metric_deltas=(),
            l3_split_dir=str(run_root),
            l3_train_dir="",
            split_pid=split_pid,
            train_pid=None,
            issues=tuple(issues),
        )