"""T0 WP-05 bundled data, template registry, ruleset and split tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from researchflow.rules import RULESET_HASH, load_ruleset, required_checks_for, ruleset_hash
from researchflow.templates.datasets import (
    data_root,
    dataset_file_sha256,
    load_dataset_frame,
    resolve_dataset,
)
from researchflow.templates.errors import (
    DatasetError,
    DatasetHashMismatch,
    DatasetPathEscape,
    DatasetUriInvalid,
    ParameterInvalid,
    TemplateNotRegistered,
)
from researchflow.templates.estimators import (
    compare_metrics,
    fit_predict,
    recompute_metrics,
    sklearn_metrics,
)
from researchflow.templates.registry import (
    lookup_node_template,
    lookup_task_template,
    validate_split_parameters,
    validate_task_parameters,
    validate_train_parameters,
)
from researchflow.templates.split import build_split, feature_columns, manifest_hash, validate_manifest
from support import DATASET_URI, dataset_sha256

DATA_DIR = Path(__file__).resolve().parents[2] / "researchflow" / "templates" / "data"


def _dataset():
    return resolve_dataset(DATASET_URI, dataset_sha256())


def _manifest(frame=None):
    dataset = _dataset()
    frame = frame if frame is not None else load_dataset_frame(dataset)
    return build_split(
        frame,
        target="diagnosis",
        seed=42,
        test_size=0.2,
        dataset_sha256=dataset.sha256,
    )


# ------------------------------------------------------------------ dataset
def test_bundled_dataset_hash_is_reproducible() -> None:
    dataset = _dataset()
    assert dataset.path.is_file()
    assert dataset_file_sha256(dataset.path) == dataset.sha256
    registry = json.loads((DATA_DIR / "registry.json").read_text(encoding="utf-8"))
    assert registry["datasets"][DATASET_URI]["sha256"] == dataset.sha256
    assert dataset.license == "CC0-1.0"
    assert dataset.rows == len(load_dataset_frame(dataset))


def test_dataset_hash_mismatch_is_rejected() -> None:
    with pytest.raises(DatasetHashMismatch) as excinfo:
        resolve_dataset(DATASET_URI, "0" * 64)
    assert excinfo.value.field_path == "dataset_ref.sha256"


def test_dataset_uri_must_be_local_and_contained() -> None:
    with pytest.raises(DatasetUriInvalid):
        resolve_dataset("https://example.com/data.csv", "0" * 64)
    with pytest.raises(DatasetUriInvalid):
        resolve_dataset("dataset://breast_cancer@sha256:" + "0" * 64, "0" * 64)
    with pytest.raises(DatasetPathEscape):
        resolve_dataset("local://datasets/../secret.csv", "0" * 64)
    with pytest.raises(DatasetError):
        resolve_dataset("local://datasets/unknown.csv", "0" * 64)


# ----------------------------------------------------------------- template
def test_template_lookup_and_required_checks() -> None:
    task = lookup_task_template("classification_benchmark@1.0.0")
    assert task.kind == "task"
    split = lookup_node_template("split_dataset@1.0.0")
    assert split.required_checks == ("executor_observed", "artifact_hash")
    assert lookup_node_template("train_classifier@1.0.0").required_checks == (
        "executor_observed",
        "artifact_hash",
        "metric_source",
    )
    with pytest.raises(TemplateNotRegistered):
        lookup_node_template("arbitrary_code@1.0.0")
    with pytest.raises(TemplateNotRegistered):
        lookup_task_template("arbitrary_code@1.0.0")


def test_task_parameters_are_validated_with_field_paths() -> None:
    columns = list(load_dataset_frame(_dataset()).columns)
    good = {
        "target": "diagnosis",
        "seed": 42,
        "test_size": 0.2,
        "models": ["logistic_regression", "random_forest"],
    }
    resolved = validate_task_parameters(good, columns)
    assert resolved["models"] == ("logistic_regression", "random_forest")

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_task_parameters({**good, "seed": -1}, columns)
    assert excinfo.value.field_path == "parameters.seed"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_task_parameters({**good, "test_size": 1.5}, columns)
    assert excinfo.value.field_path == "parameters.test_size"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_task_parameters({**good, "models": []}, columns)
    assert excinfo.value.field_path == "parameters.models"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_task_parameters({**good, "models": ["svm"]}, columns)
    assert excinfo.value.field_path == "parameters.models[0]"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_task_parameters(
            {**good, "models": ["logistic_regression", "logistic_regression"]}, columns
        )
    assert excinfo.value.field_path == "parameters.models[1]"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_task_parameters({**good, "epochs": 3}, columns)
    assert excinfo.value.field_path == "parameters.epochs"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_task_parameters({**good, "seed": True}, columns)
    assert excinfo.value.field_path == "parameters.seed"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_split_parameters({"target": "diagnosis", "seed": 1}, columns)
    assert excinfo.value.field_path == "parameters.test_size"

    with pytest.raises(ParameterInvalid) as excinfo:
        validate_train_parameters({"model": "svm", "seed": 1})
    assert excinfo.value.field_path == "parameters.model"


# ------------------------------------------------------------------- split
def test_split_is_deterministic_and_manifest_is_consistent() -> None:
    first = _manifest()
    second = _manifest()
    assert first == second
    assert first["split_hash"] == manifest_hash(first)
    assert sorted(first["train_rows"] + first["test_rows"]) == list(range(first["row_count"]))
    assert not set(first["train_rows"]) & set(first["test_rows"])
    assert not set(first["train_groups"]) & set(first["test_groups"])
    assert first["train_class_counts"]["0"] + first["train_class_counts"]["1"] == len(
        first["train_rows"]
    )
    frame = load_dataset_frame(_dataset())
    assert validate_manifest(first, frame) == []


def test_different_test_size_changes_the_split() -> None:
    dataset = _dataset()
    frame = load_dataset_frame(dataset)
    small = build_split(frame, target="diagnosis", seed=42, test_size=0.1, dataset_sha256=dataset.sha256)
    large = build_split(frame, target="diagnosis", seed=42, test_size=0.3, dataset_sha256=dataset.sha256)
    assert small["split_hash"] != large["split_hash"]
    assert len(small["test_rows"]) < len(large["test_rows"])


def _tampered(mutate):
    frame = load_dataset_frame(_dataset())
    manifest = _manifest(frame)
    mutate(manifest)
    manifest["split_hash"] = manifest_hash(manifest)
    return manifest, frame


def test_leakage_rule_r1_target_in_features() -> None:
    def mutate(manifest):
        manifest["feature_columns"] = list(manifest["feature_columns"]) + ["diagnosis"]

    manifest, frame = _tampered(mutate)
    issues = validate_manifest(manifest, frame)
    assert any(issue["rule"] == "R1_TARGET_IN_FEATURES" for issue in issues)


def test_leakage_rule_r2_row_overlap() -> None:
    def mutate(manifest):
        manifest["test_row_fingerprints"][0] = manifest["train_row_fingerprints"][0]

    manifest, frame = _tampered(mutate)
    issues = validate_manifest(manifest, frame)
    assert any(issue["rule"] == "R2_ROW_OVERLAP" for issue in issues)


def test_leakage_rule_r3_group_overlap() -> None:
    def mutate(manifest):
        manifest["test_groups"] = list(manifest["test_groups"]) + [manifest["train_groups"][0]]

    manifest, frame = _tampered(mutate)
    issues = validate_manifest(manifest, frame)
    assert any(issue["rule"] == "R3_GROUP_OVERLAP" for issue in issues)


def test_leakage_rule_r4_temporal_order() -> None:
    def mutate(manifest):
        manifest["test_time_min"] = manifest["train_time_max"]

    manifest, frame = _tampered(mutate)
    issues = validate_manifest(manifest, frame)
    assert any(issue["rule"] == "R4_TEMPORAL_ORDER" for issue in issues)


def test_leakage_rule_r5_duplicate_index() -> None:
    def mutate(manifest):
        manifest["test_rows"][1] = manifest["test_rows"][0]

    manifest, frame = _tampered(mutate)
    issues = validate_manifest(manifest, frame)
    assert any(issue["rule"] == "R5_MANIFEST_DUPLICATE" for issue in issues)


# -------------------------------------------------------------- estimators
def test_training_is_deterministic_and_metrics_recompute_consistently() -> None:
    frame = load_dataset_frame(_dataset())
    manifest = _manifest(frame)
    first_predictions, first_metrics = fit_predict(
        frame, manifest, model="logistic_regression", seed=42
    )
    second_predictions, second_metrics = fit_predict(
        frame, manifest, model="logistic_regression", seed=42
    )
    assert first_predictions == second_predictions
    assert first_metrics == second_metrics

    recomputed = recompute_metrics(
        [row["y_true"] for row in first_predictions],
        [row["y_pred"] for row in first_predictions],
    )
    assert compare_metrics(first_metrics, recomputed, tolerance=1e-9) == []
    assert first_metrics["accuracy"] == pytest.approx(recomputed["accuracy"], abs=1e-12)

    tampered = dict(second_metrics)
    tampered["accuracy"] = second_metrics["accuracy"] + 0.01
    mismatches = compare_metrics(tampered, recomputed, tolerance=1e-9)
    assert [item["metric"] for item in mismatches] == ["accuracy"]

    direct = sklearn_metrics(
        [row["y_true"] for row in first_predictions],
        [row["y_pred"] for row in first_predictions],
    )
    assert direct["accuracy"] == pytest.approx(recomputed["accuracy"], abs=1e-12)


def test_feature_columns_exclude_target_group_and_time() -> None:
    frame = load_dataset_frame(_dataset())
    features = feature_columns(frame, "diagnosis")
    assert "diagnosis" not in features
    assert "patient_id" not in features
    assert "event_time" not in features
    assert "f1" in features


# ----------------------------------------------------------------- ruleset
def test_ruleset_is_stable_and_covers_node_types() -> None:
    document = load_ruleset()
    assert ruleset_hash(document) == RULESET_HASH
    assert len(RULESET_HASH) == 64
    assert all(character in "0123456789abcdef" for character in RULESET_HASH)
    assert ruleset_hash(json.loads(json.dumps(document))) == RULESET_HASH
    assert required_checks_for("ml.split") == ("executor_observed", "artifact_hash")
    assert required_checks_for("ml.train.classifier") == (
        "executor_observed",
        "artifact_hash",
        "metric_source",
    )
    with pytest.raises(KeyError):
        required_checks_for("ml.unknown")