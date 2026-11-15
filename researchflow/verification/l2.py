"""Verifier L2: result self-consistency (T0 WP-09).

L2 re-reads the model output, verifies that ``y_true`` matches the dataset's
target values for the test rows, recomputes the metrics with an independent
pure-Python implementation and checks the five leakage rules over the split
manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from researchflow.templates.datasets import load_dataset_frame, resolve_dataset
from researchflow.templates.estimators import compare_metrics, load_predictions_csv, recompute_metrics
from researchflow.templates.split import manifest_hash, validate_manifest
from researchflow.verification.context import VerificationContext

__all__ = ["L2Issue", "L2Result", "L2Verifier"]

L2_PREDICTIONS_MISSING = "L2_PREDICTIONS_MISSING"
L2_METRICS_MISSING = "L2_METRICS_MISSING"
L2_SPLIT_MANIFEST_MISSING = "L2_SPLIT_MANIFEST_MISSING"
L2_SPLIT_MANIFEST_INVALID = "L2_SPLIT_MANIFEST_INVALID"
L2_METRIC_MISMATCH = "L2_METRIC_MISMATCH"
L2_YTRUE_MISMATCH = "L2_YTRUE_MISMATCH"
L2_PREDICTION_OUT_OF_RANGE = "L2_PREDICTION_OUT_OF_RANGE"
L2_SPLIT_DATASET_MISMATCH = "L2_SPLIT_DATASET_MISMATCH"
L2_LEAKAGE = "L2_LEAKAGE"


@dataclass(frozen=True, slots=True)
class L2Issue:
    code: str
    node_id: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "node_id": self.node_id, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class L2Result:
    status: str
    issues: tuple[L2Issue, ...]
    metrics: dict[str, Any]
    recomputed: dict[str, Any]
    leakage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "metrics": self.metrics,
            "recomputed": self.recomputed,
            "leakage": self.leakage,
        }


class L2Verifier:
    def _split_manifest(
        self, ctx: VerificationContext, split_node_id: str
    ) -> dict[str, Any] | None:
        node = ctx.nodes.get(split_node_id)
        if node is None:
            return None
        path = ctx.attempt_dir(split_node_id, node.attempt_seq) / "output" / "split_manifest.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def run(self, ctx: VerificationContext) -> L2Result:
        issues: list[L2Issue] = []
        metric_nodes = ctx.metric_nodes()
        split_node_id = "split_dataset"
        manifest = self._split_manifest(ctx, split_node_id)
        dataset = None
        frame = None
        effective_sha = ctx.effective_dataset_sha256(split_node_id)
        dataset_ref = ctx.task_spec.get("dataset_ref") or {}
        if manifest is None:
            issues.append(
                L2Issue(L2_SPLIT_MANIFEST_MISSING, split_node_id, "split_manifest.json is missing")
            )
        else:
            try:
                if manifest.get("split_hash") != manifest_hash(manifest):
                    issues.append(
                        L2Issue(
                            L2_SPLIT_MANIFEST_INVALID,
                            split_node_id,
                            "split_hash does not match the manifest content",
                        )
                    )
                if effective_sha and manifest.get("dataset_sha256") != effective_sha:
                    issues.append(
                        L2Issue(
                            L2_SPLIT_DATASET_MISMATCH,
                            split_node_id,
                            "split manifest belongs to a different dataset fingerprint",
                        )
                    )
                dataset = resolve_dataset(
                    str(dataset_ref.get("uri", "")), str(effective_sha or "")
                )
                frame = load_dataset_frame(dataset)
                for issue in validate_manifest(manifest, frame):
                    issues.append(
                        L2Issue(
                            L2_LEAKAGE,
                            split_node_id,
                            f"{issue['rule']}: {issue['detail']}",
                        )
                    )
            except Exception as exc:  # DatasetError / ValueError
                issues.append(
                    L2Issue(L2_SPLIT_MANIFEST_INVALID, split_node_id, f"{type(exc).__name__}: {exc}")
                )

        metrics_by_node: dict[str, Any] = {}
        recomputed_by_node: dict[str, Any] = {}
        leakage: dict[str, Any] = {}
        tolerance = float(ctx.ruleset.get("l2", {}).get("metric_tolerance", 1e-9))

        for node_id in metric_nodes:
            node = ctx.nodes.get(node_id)
            if node is None:
                issues.append(L2Issue(L2_PREDICTIONS_MISSING, node_id, "node row is missing"))
                continue
            output = ctx.attempt_dir(node_id, node.attempt_seq) / "output"
            predictions_path = output / "predictions.csv"
            metrics_path = output / "metrics.json"
            if not predictions_path.is_file():
                issues.append(
                    L2Issue(L2_PREDICTIONS_MISSING, node_id, "predictions.csv is missing")
                )
                continue
            if not metrics_path.is_file():
                issues.append(L2Issue(L2_METRICS_MISSING, node_id, "metrics.json is missing"))
                continue
            reported = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics_by_node[node_id] = reported
            try:
                predictions = load_predictions_csv(predictions_path)
            except ValueError as exc:
                issues.append(L2Issue(L2_PREDICTIONS_MISSING, node_id, str(exc)))
                continue
            if manifest is not None and frame is not None:
                manifest = manifest if manifest is not None else {}
                expected_rows = {
                    int(index): int(frame.iloc[int(index)][manifest["target"]])
                    for index in manifest["test_rows"]
                }
                for row in predictions:
                    if int(row["row_index"]) not in expected_rows:
                        issues.append(
                            L2Issue(
                                L2_YTRUE_MISMATCH,
                                node_id,
                                f"prediction row {row['row_index']} is not in the test split",
                            )
                        )
                        break
                    if int(row["y_true"]) != expected_rows[int(row["row_index"])]:
                        issues.append(
                            L2Issue(
                                L2_YTRUE_MISMATCH,
                                node_id,
                                f"row {row['row_index']}: y_true={row['y_true']} "
                                f"but dataset target={expected_rows[int(row['row_index'])]}",
                            )
                        )
                        break
                if len(predictions) != len(manifest["test_rows"]):
                    issues.append(
                        L2Issue(
                            L2_YTRUE_MISMATCH,
                            node_id,
                            f"{len(predictions)} predictions for {len(manifest['test_rows'])} test rows",
                        )
                    )
            for row in predictions:
                if row["y_pred"] not in (0, 1):
                    issues.append(
                        L2Issue(
                            L2_PREDICTION_OUT_OF_RANGE,
                            node_id,
                            f"row {row['row_index']} predicted {row['y_pred']}",
                        )
                    )
                    break
            recomputed = recompute_metrics(
                [row["y_true"] for row in predictions],
                [row["y_pred"] for row in predictions],
            )
            recomputed_by_node[node_id] = recomputed
            mismatches = compare_metrics(reported, recomputed, tolerance=tolerance)
            for mismatch in mismatches:
                issues.append(
                    L2Issue(
                        L2_METRIC_MISMATCH,
                        node_id,
                        f"{mismatch['metric']}: reported={mismatch.get('reported')} "
                        f"recomputed={mismatch.get('recomputed')}",
                    )
                )
            leakage[node_id] = {
                "rules": list(ctx.ruleset.get("l2", {}).get("leakage_rules", [])),
                "issues": [
                    issue.to_dict() for issue in issues if issue.code == L2_LEAKAGE
                ],
            }

        return L2Result(
            status="PASS" if not issues else "FAIL",
            issues=tuple(issues),
            metrics=metrics_by_node,
            recomputed=recomputed_by_node,
            leakage=leakage,
        )