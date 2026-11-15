"""Deterministic temporal/group split and its leakage checks (WP-05/WP-09).

The split is a pure function of (dataset bytes, target, seed, test_size).  It
never uses randomness that depends on wall-clock time or dict iteration order,
so the executor and the L3 replay derive byte-identical manifests from the raw
dataset.

Leakage rules R1–R5 are implemented here as data checks over the dataset frame
and the manifest, so both L2 and the offline bundle verifier can share them.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from researchflow.contracts.encoding import hash_payload
from researchflow.templates.errors import SplitError
from researchflow.templates.registry import GROUP_COLUMN, RESERVED_COLUMNS, TIME_COLUMN

__all__ = [
    "SPLIT_SCHEMA_VERSION",
    "SPLIT_STRATEGY",
    "build_split",
    "feature_columns",
    "manifest_hash",
    "row_fingerprint",
    "validate_manifest",
]

SPLIT_SCHEMA_VERSION = "1.0"
SPLIT_STRATEGY = "temporal_group_split"


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = str(value)
    try:
        numeric = float(text)
    except (TypeError, ValueError):
        return text
    return repr(numeric)


def row_fingerprint(values: Iterable[Any]) -> str:
    payload = [_scalar_text(value) for value in values]
    return hashlib.sha256(hash_payload(payload).encode("ascii")).hexdigest()


def feature_columns(frame, target: str) -> list[str]:
    from pandas.api.types import is_numeric_dtype

    columns = [
        str(column)
        for column in frame.columns
        if str(column) != target and str(column) not in RESERVED_COLUMNS
    ]
    return [column for column in columns if is_numeric_dtype(frame[column])]


def _target_values(frame, target: str) -> list[int]:
    raw = sorted({int(value) for value in frame[target].tolist()})
    if len(raw) < 2:
        raise SplitError(
            f"target {target!r} has fewer than two classes",
            field_path="parameters.target",
        )
    if set(raw) != {0, 1}:
        raise SplitError(
            f"target {target!r} must be binary 0/1 for this template; got {raw}",
            field_path="parameters.target",
        )
    return raw


def build_split(
    frame,
    *,
    target: str,
    seed: int,
    test_size: float,
    dataset_sha256: str,
) -> dict[str, Any]:
    if target not in frame.columns:
        raise SplitError(
            f"target column {target!r} is missing", field_path="parameters.target"
        )
    if GROUP_COLUMN not in frame.columns or TIME_COLUMN not in frame.columns:
        raise SplitError(
            f"dataset must contain {GROUP_COLUMN!r} and {TIME_COLUMN!r} columns",
            field_path="dataset_ref.uri",
        )
    _target_values(frame, target)
    features = feature_columns(frame, target)
    if not features:
        raise SplitError(
            "dataset has no numeric feature columns", field_path="dataset_ref.uri"
        )

    groups = [str(value) for value in frame[GROUP_COLUMN].tolist()]
    times = [str(value) for value in frame[TIME_COLUMN].tolist()]

    # Order groups by their latest observation, tie-broken by a hash of
    # (seed, group) so the seed is meaningful but the order stays deterministic.
    latest: dict[str, str] = {}
    for group, time in zip(groups, times):
        if group not in latest or time > latest[group]:
            latest[group] = time
    ordered_groups = sorted(
        latest,
        key=lambda group: (
            latest[group],
            hashlib.sha256(f"{seed}:{group}".encode("utf-8")).hexdigest(),
        ),
    )
    group_count = len(ordered_groups)
    test_group_count = int(round(group_count * test_size))
    test_group_count = max(1, min(test_group_count, group_count - 1))
    train_groups = ordered_groups[: group_count - test_group_count]
    test_groups = ordered_groups[group_count - test_group_count :]
    train_set = set(train_groups)
    test_set = set(test_groups)

    feature_matrix = [
        [frame.iloc[index][feature] for feature in features]
        for index in range(len(frame))
    ]
    train_rows = [index for index, group in enumerate(groups) if group in train_set]
    test_rows = [index for index, group in enumerate(groups) if group in test_set]
    if not train_rows or not test_rows:
        raise SplitError(
            "split produced an empty train or test partition",
            field_path="parameters.test_size",
        )

    fingerprints = {
        index: row_fingerprint(
            [frame.iloc[index][column] for column in frame.columns if column != target]
        )
        for index in range(len(frame))
    }
    target_series = [int(value) for value in frame[target].tolist()]

    def _class_counts(rows: Sequence[int]) -> dict[str, int]:
        counts = {"0": 0, "1": 0}
        for index in rows:
            counts[str(target_series[index])] += 1
        return counts

    manifest: dict[str, Any] = {
        "schema_version": SPLIT_SCHEMA_VERSION,
        "strategy": SPLIT_STRATEGY,
        "dataset_sha256": dataset_sha256,
        "target": target,
        "seed": seed,
        "test_size": test_size,
        "row_count": len(frame),
        "feature_columns": features,
        "group_column": GROUP_COLUMN,
        "time_column": TIME_COLUMN,
        "train_rows": train_rows,
        "test_rows": test_rows,
        "train_groups": train_groups,
        "test_groups": test_groups,
        "train_row_fingerprints": [fingerprints[index] for index in train_rows],
        "test_row_fingerprints": [fingerprints[index] for index in test_rows],
        "train_class_counts": _class_counts(train_rows),
        "test_class_counts": _class_counts(test_rows),
        "train_time_max": max(times[index] for index in train_rows),
        "test_time_min": min(times[index] for index in test_rows),
    }
    manifest["split_hash"] = manifest_hash(manifest)
    return manifest


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "split_hash"}
    return hash_payload(dict(payload))


def _issue(rule: str, detail: str) -> dict[str, str]:
    return {"rule": rule, "detail": detail}


def validate_manifest(manifest: Mapping[str, Any], frame) -> list[dict[str, str]]:
    """Return the leakage/integrity issues for ``manifest`` over ``frame``.

    The five rule ids match ``ruleset.v1.json``; ``MANIFEST_STRUCTURE`` groups
    shape problems (missing keys, wrong coverage, duplicate indices).
    """

    issues: list[dict[str, str]] = []
    required_keys = {
        "dataset_sha256",
        "target",
        "seed",
        "test_size",
        "row_count",
        "feature_columns",
        "train_rows",
        "test_rows",
        "train_groups",
        "test_groups",
        "train_row_fingerprints",
        "test_row_fingerprints",
        "train_time_max",
        "test_time_min",
        "split_hash",
    }
    missing = sorted(required_keys - set(manifest))
    if missing:
        issues.append(_issue("MANIFEST_STRUCTURE", f"missing keys: {missing}"))
        return issues

    if int(manifest["row_count"]) != len(frame):
        issues.append(
            _issue(
                "MANIFEST_STRUCTURE",
                f"row_count {manifest['row_count']} != dataset rows {len(frame)}",
            )
        )

    if manifest.get("split_hash") != manifest_hash(manifest):
        issues.append(_issue("MANIFEST_STRUCTURE", "split_hash does not match content"))

    if manifest["target"] in manifest["feature_columns"]:
        issues.append(
            _issue(
                "R1_TARGET_IN_FEATURES",
                f"target {manifest['target']!r} appears in feature_columns",
            )
        )

    train_rows = [int(value) for value in manifest["train_rows"]]
    test_rows = [int(value) for value in manifest["test_rows"]]
    if len(set(train_rows)) != len(train_rows) or len(set(test_rows)) != len(test_rows):
        issues.append(
            _issue("R5_MANIFEST_DUPLICATE", "duplicate row index inside a partition")
        )
    if set(train_rows) & set(test_rows):
        issues.append(_issue("R5_MANIFEST_DUPLICATE", "row index in both partitions"))
    if sorted(train_rows + test_rows) != list(range(len(frame))):
        issues.append(
            _issue(
                "MANIFEST_STRUCTURE",
                "train_rows + test_rows do not cover every dataset row exactly once",
            )
        )

    train_groups = {str(value) for value in manifest["train_groups"]}
    test_groups = {str(value) for value in manifest["test_groups"]}
    if train_groups & test_groups:
        issues.append(
            _issue(
                "R3_GROUP_OVERLAP",
                f"{sorted(train_groups & test_groups)[:3]} appear in both partitions",
            )
        )

    train_fingerprints = {str(value) for value in manifest["train_row_fingerprints"]}
    test_fingerprints = {str(value) for value in manifest["test_row_fingerprints"]}
    if train_fingerprints & test_fingerprints:
        issues.append(
            _issue("R2_ROW_OVERLAP", "identical rows appear in both partitions")
        )

    try:
        train_max = datetime.fromisoformat(str(manifest["train_time_max"]))
        test_min = datetime.fromisoformat(str(manifest["test_time_min"]))
    except ValueError:
        issues.append(
            _issue("R4_TEMPORAL_ORDER", "train_time_max/test_time_min are not ISO times")
        )
    else:
        if not train_max < test_min:
            issues.append(
                _issue(
                    "R4_TEMPORAL_ORDER",
                    f"test_time_min {test_min.isoformat()} <= train_time_max {train_max.isoformat()}",
                )
            )
    return issues