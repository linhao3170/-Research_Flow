"""Sandboxed template worker (T0 WP-06).

The worker is launched by :class:`researchflow.execution.executor.Executor` in a
fresh attempt directory and computes one whitelisted node.  It never writes
state, evidence or reports and never decides whether the node succeeded: it
exits 0 on success and non-zero with ``worker_error.json`` on failure.

Exit codes: 0 ok, 3 template not allowlisted, 4 invalid parameter/input,
1 unexpected error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from researchflow.templates.datasets import load_dataset_frame, resolve_dataset
from researchflow.templates.errors import SplitError, TemplateError
from researchflow.templates.estimators import fit_predict, write_predictions_csv
from researchflow.templates.registry import (
    SPLIT_TEMPLATE_ID,
    TRAIN_TEMPLATE_ID,
    lookup_node_template,
    validate_split_parameters,
    validate_train_parameters,
)
from researchflow.templates.split import build_split, manifest_hash, validate_manifest

__all__ = ["main", "run_job"]

EXIT_TEMPLATE = 3
EXIT_INPUT = 4
EXIT_UNEXPECTED = 1


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_error(output_dir: Path, code: str, message: str, field_path: str | None) -> None:
    _write_json(
        output_dir / "worker_error.json",
        {"status": "ERROR", "code": code, "message": message, "field_path": field_path},
    )


def _dataset(job: dict[str, Any]):
    ref = job["dataset_ref"]
    return resolve_dataset(str(ref["uri"]), str(ref["sha256"]))


def _run_split(job: dict[str, Any], output_dir: Path) -> None:
    dataset = _dataset(job)
    frame = load_dataset_frame(dataset)
    parameters = validate_split_parameters(job["parameters"], list(dataset.columns))
    manifest = build_split(
        frame,
        target=parameters["target"],
        seed=parameters["seed"],
        test_size=parameters["test_size"],
        dataset_sha256=dataset.sha256,
    )
    issues = validate_manifest(manifest, frame)
    if issues:
        raise SplitError(f"split manifest is inconsistent: {issues}")
    _write_json(output_dir / "split_manifest.json", manifest)


def _run_train(job: dict[str, Any], output_dir: Path) -> None:
    parameters = validate_train_parameters(job["parameters"])
    dataset = _dataset(job)
    frame = load_dataset_frame(dataset)
    inputs = job.get("input_artifacts") or {}
    manifest_path = inputs.get("split_manifest")
    if not manifest_path:
        raise SplitError("train job requires the split_manifest input artifact")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("split_hash") != manifest_hash(manifest):
        raise SplitError("split manifest hash does not match its content")
    if manifest.get("dataset_sha256") != dataset.sha256:
        raise SplitError("split manifest belongs to a different dataset fingerprint")
    issues = validate_manifest(manifest, frame)
    if issues:
        raise SplitError(f"split manifest failed leakage checks: {issues}")
    predictions, metrics = fit_predict(
        frame, manifest, model=parameters["model"], seed=parameters["seed"]
    )
    write_predictions_csv(output_dir / "predictions.csv", predictions)
    _write_json(output_dir / "metrics.json", metrics)


def run_job(job: dict[str, Any]) -> int:
    template_id = str(job.get("template_id", ""))
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        lookup_node_template(template_id)
        if template_id == SPLIT_TEMPLATE_ID:
            _run_split(job, output_dir)
        elif template_id == TRAIN_TEMPLATE_ID:
            _run_train(job, output_dir)
        else:  # pragma: no cover - registry lookup already rejects this
            raise TemplateError(f"template is not executable: {template_id}")
        _write_json(
            output_dir / "worker_status.json",
            {"status": "OK", "template_id": template_id},
        )
        return 0
    except TemplateError as exc:
        _write_error(output_dir, exc.code, str(exc), exc.field_path)
        if exc.code == "TEMPLATE_NOT_REGISTERED":
            return EXIT_TEMPLATE
        return EXIT_INPUT
    except Exception as exc:  # noqa: BLE001 - reported to the executor
        _write_error(
            output_dir, "WORKER_FAILED", f"{type(exc).__name__}: {exc}", None
        )
        return EXIT_UNEXPECTED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ResearchFlow template worker")
    parser.add_argument("--job", required=True, help="path to job.json")
    args = parser.parse_args(argv)
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    return run_job(job)


if __name__ == "__main__":
    sys.exit(main())