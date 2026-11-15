"""Whitelisted model fitting and metric recomputation (WP-05 / WP-09).

Training is executed inside the sandboxed template worker; metric
recomputation is a separate pure-Python implementation used by the Verifier so
that a reported metric is checked against the predictions rather than trusted.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from researchflow.templates.registry import WHITELIST_MODELS

__all__ = [
    "compare_metrics",
    "fit_predict",
    "load_predictions_csv",
    "prediction_rows",
    "recompute_metrics",
    "sklearn_metrics",
]


def _estimator(model: str, seed: int):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier

    if model == "logistic_regression":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression(max_iter=1000, random_state=seed)),
            ]
        )
    if model == "random_forest":
        return RandomForestClassifier(
            n_estimators=120, random_state=seed, n_jobs=1
        )
    if model == "decision_tree":
        return DecisionTreeClassifier(random_state=seed)
    raise ValueError(
        f"model {model!r} is not in the frozen whitelist {list(WHITELIST_MODELS)}"
    )


def fit_predict(
    frame,
    manifest: Mapping[str, Any],
    *,
    model: str,
    seed: int,
) -> tuple[list[dict[str, int]], dict[str, Any]]:
    import numpy as np

    features = [str(column) for column in manifest["feature_columns"]]
    target = str(manifest["target"])
    train_rows = [int(value) for value in manifest["train_rows"]]
    test_rows = [int(value) for value in manifest["test_rows"]]
    train = frame.iloc[train_rows]
    test = frame.iloc[test_rows]
    estimator = _estimator(model, seed)
    estimator.fit(train[features].to_numpy(dtype=float), train[target].to_numpy(dtype=int))
    predicted = estimator.predict(test[features].to_numpy(dtype=float))
    predictions = prediction_rows(
        test_rows, test[target].to_numpy(dtype=int), np.asarray(predicted, dtype=int)
    )
    metrics = sklearn_metrics(
        [row["y_true"] for row in predictions],
        [row["y_pred"] for row in predictions],
    )
    metrics["model"] = model
    metrics["seed"] = seed
    metrics["feature_columns"] = features
    metrics["n_train"] = len(train_rows)
    metrics["n_test"] = len(test_rows)
    return predictions, metrics


def prediction_rows(
    row_indices: Sequence[int], y_true: Sequence[int], y_pred: Sequence[int]
) -> list[dict[str, int]]:
    return [
        {"row_index": int(index), "y_true": int(truth), "y_pred": int(pred)}
        for index, truth, pred in zip(row_indices, y_true, y_pred)
    ]


def _binary_counts(
    y_true: Sequence[int], y_pred: Sequence[int]
) -> tuple[int, int, int, int]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    return tp, fp, tn, fn


def recompute_metrics(
    y_true: Sequence[int], y_pred: Sequence[int]
) -> dict[str, float]:
    """Independent pure-Python metric computation (no sklearn import)."""

    n = len(y_true)
    if n == 0 or n != len(y_pred):
        raise ValueError("y_true and y_pred must be non-empty and aligned")
    tp, fp, tn, fn = _binary_counts(y_true, y_pred)
    accuracy = (tp + tn) / n
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    for tp_i, fp_i, fn_i in ((tp, fp, fn), (tn, fn, fp)):
        precision = tp_i / (tp_i + fp_i) if (tp_i + fp_i) else 0.0
        recall = tp_i / (tp_i + fn_i) if (tp_i + fn_i) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    return {
        "accuracy": accuracy,
        "precision_macro": sum(precisions) / 2,
        "recall_macro": sum(recalls) / 2,
        "f1_macro": sum(f1s) / 2,
        "tp": float(tp),
        "fp": float(fp),
        "tn": float(tn),
        "fn": float(fn),
    }


def sklearn_metrics(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
    )

    tp, fp, tn, fn = _binary_counts(y_true, y_pred)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(
            precision_score(y_true, y_pred, average="macro", zero_division=0)
        ),
        "recall_macro": float(
            recall_score(y_true, y_pred, average="macro", zero_division=0)
        ),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
    }


_METRIC_KEYS = ("accuracy", "precision_macro", "recall_macro", "f1_macro")


def compare_metrics(
    reported: Mapping[str, Any],
    recomputed: Mapping[str, Any],
    *,
    tolerance: float,
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for key in _METRIC_KEYS:
        if key not in reported or key not in recomputed:
            mismatches.append({"metric": key, "reason": "missing"})
            continue
        reported_value = float(reported[key])
        computed_value = float(recomputed[key])
        delta = abs(reported_value - computed_value)
        if delta > tolerance:
            mismatches.append(
                {
                    "metric": key,
                    "reported": reported_value,
                    "recomputed": computed_value,
                    "delta": delta,
                }
            )
    return mismatches


def load_predictions_csv(path) -> list[dict[str, int]]:
    import csv

    rows: list[dict[str, int]] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["row_index", "y_true", "y_pred"]:
            raise ValueError(
                f"predictions.csv header must be row_index,y_true,y_pred; got {reader.fieldnames}"
            )
        for row in reader:
            rows.append(
                {
                    "row_index": int(row["row_index"]),
                    "y_true": int(row["y_true"]),
                    "y_pred": int(row["y_pred"]),
                }
            )
    return rows


def write_predictions_csv(path, predictions: Iterable[Mapping[str, int]]) -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_index", "y_true", "y_pred"])
        for row in predictions:
            writer.writerow([row["row_index"], row["y_true"], row["y_pred"]])