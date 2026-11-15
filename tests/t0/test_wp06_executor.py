"""T0 WP-06 executor tests: real subprocesses, real timeout kills, real artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from researchflow.execution import (
    AttemptDirReused,
    ExecutionError,
    Executor,
    ToolNotAllowlisted,
    attempt_dir_for,
    read_attempt_result,
)
from researchflow.execution.sampler import ProcessTreeSampler
from support import DATASET_URI, dataset_sha256

TASK_ID = "task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10"
NODE_ID = "split_dataset"
DATASET_REF = {
    "uri": DATASET_URI,
    "sha256": dataset_sha256(),
    "license": "CC0-1.0",
}
LIMITS = {"wall_time_sec": 300, "max_workers": 2, "max_memory_mb": 4096}


def _executor(tmp_path: Path) -> Executor:
    return Executor(tmp_path / "runtime")


def _split(tmp_path: Path, *, attempt_seq: int = 1, **overrides):
    parameters = {"target": "diagnosis", "seed": 42, "test_size": 0.2}
    parameters.update(overrides.pop("parameters", {}))
    return _executor(tmp_path).run(
        task_id=TASK_ID,
        node_id=NODE_ID,
        attempt_seq=attempt_seq,
        template_id="split_dataset@1.0.0",
        parameters=parameters,
        dataset_ref=DATASET_REF,
        limits=overrides.pop("limits", LIMITS),
        **overrides,
    )


def test_split_attempt_produces_real_artifacts(tmp_path: Path) -> None:
    observation = _split(tmp_path)
    assert observation.status == "EXITED"
    assert observation.exit_code == 0
    assert observation.succeeded is True
    assert observation.timed_out is False
    assert observation.duration_sec >= 0
    artifact_paths = {artifact.path for artifact in observation.artifacts}
    assert "output/split_manifest.json" in artifact_paths
    assert (observation.attempt_dir / "output" / "split_manifest.json").is_file()
    assert (observation.attempt_dir / "result.json").is_file()
    assert (observation.attempt_dir / "stdout.log").is_file()
    assert (observation.attempt_dir / "stderr.log").is_file()
    assert len(observation.env_fingerprint) == 64
    assert len(observation.code_hash) == 64
    assert observation.worker_error is None
    if observation.peak_memory_mb is not None:
        assert observation.peak_memory_mb > 0

    result = read_attempt_result(observation.attempt_dir)
    assert result is not None
    assert result["status"] == "EXITED"
    # The executor records observations; it must not publish a completion verdict.
    assert "succeeded" not in result
    assert "verified" not in result


def test_train_attempt_consumes_the_split_manifest(tmp_path: Path) -> None:
    split = _split(tmp_path)
    manifest_path = split.attempt_dir / "output" / "split_manifest.json"
    observation = _executor(tmp_path).run(
        task_id=TASK_ID,
        node_id="train_logistic_regression",
        attempt_seq=1,
        template_id="train_classifier@1.0.0",
        parameters={"model": "logistic_regression", "seed": 42},
        dataset_ref=DATASET_REF,
        input_artifacts={"split_manifest": manifest_path},
        limits=LIMITS,
    )
    assert observation.succeeded is True
    artifact_paths = {artifact.path for artifact in observation.artifacts}
    assert {"output/metrics.json", "output/predictions.csv"} <= artifact_paths
    metrics = json.loads(
        (observation.attempt_dir / "output" / "metrics.json").read_text(encoding="utf-8")
    )
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert observation.inputs[0]["name"] == "split_manifest"
    assert len(observation.inputs[0]["sha256"]) == 64


def test_unregistered_template_is_rejected_before_spawning(tmp_path: Path) -> None:
    executor = _executor(tmp_path)
    with pytest.raises(ToolNotAllowlisted) as excinfo:
        executor.run(
            task_id=TASK_ID,
            node_id="evil",
            attempt_seq=1,
            template_id="run_arbitrary_python@1.0.0",
            parameters={},
            dataset_ref=DATASET_REF,
            limits=LIMITS,
        )
    assert excinfo.value.code == "TOOL_NOT_ALLOWLISTED"
    assert not attempt_dir_for(tmp_path / "runtime", TASK_ID, "evil", 1).exists()


def test_attempt_directory_reuse_is_refused(tmp_path: Path) -> None:
    _split(tmp_path)
    with pytest.raises(AttemptDirReused) as excinfo:
        _split(tmp_path)
    assert excinfo.value.code == "ATTEMPT_DIR_REUSED"


def test_timeout_kills_the_process_tree(tmp_path: Path) -> None:
    observation = _split(tmp_path, limits={"wall_time_sec": 0.001})
    assert observation.timed_out is True
    assert observation.status == "TIMEOUT"
    assert observation.succeeded is False
    # taskkill terminates the process; the raw exit code is non-zero, never a success.
    assert observation.exit_code != 0
    assert observation.kill_verified is True
    assert observation.duration_sec < 60


def test_tree_sampler_measures_a_real_memory_blob(tmp_path: Path) -> None:
    """Calibration: the sampler must see a real ~200 MB allocation, not a constant."""

    script = (
        "import time\n"
        "buf = bytearray(200 * 1024 * 1024)\n"
        "for i in range(0, len(buf), 4096):\n"
        "    buf[i] = 1\n"
        "print('READY', flush=True)\n"
        "time.sleep(5)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"
        sampler = ProcessTreeSampler(process.pid)
        sampler.start()
        time.sleep(0.5)
        peak = sampler.stop()
        pids = sampler.measured_pids()
    finally:
        process.kill()
        process.wait()
    assert peak is not None
    assert 150.0 <= peak <= 600.0, f"sampler reported {peak} MB for a 200 MB allocation"
    # The uv venv launcher spawns the real interpreter, so more than one pid is
    # expected and both must have been measured.
    assert len(pids) >= 1
    assert any(pid != process.pid for pid in pids), "the child interpreter was not sampled"


def test_memory_limit_is_observed_on_a_real_worker(tmp_path: Path) -> None:
    split = _split(tmp_path)
    manifest_path = split.attempt_dir / "output" / "split_manifest.json"
    observation = _executor(tmp_path).run(
        task_id=TASK_ID,
        node_id="train_logistic_regression",
        attempt_seq=1,
        template_id="train_classifier@1.0.0",
        parameters={"model": "logistic_regression", "seed": 42},
        dataset_ref=DATASET_REF,
        input_artifacts={"split_manifest": manifest_path},
        limits={"wall_time_sec": 300, "max_memory_mb": 8},
    )
    assert observation.memory_exceeded is True
    assert observation.status == "MEMORY_EXCEEDED"
    assert observation.peak_memory_mb is not None
    assert observation.peak_memory_mb >= 8
    assert observation.worker_pids, "no real worker process was sampled"


def test_worker_error_is_propagated_not_swallowed(tmp_path: Path) -> None:
    observation = _executor(tmp_path).run(
        task_id=TASK_ID,
        node_id=NODE_ID,
        attempt_seq=1,
        template_id="split_dataset@1.0.0",
        parameters={"target": "diagnosis", "seed": 42, "test_size": 0.2},
        dataset_ref={**DATASET_REF, "sha256": "0" * 64},
        limits=LIMITS,
    )
    assert observation.succeeded is False
    assert observation.exit_code == 4
    assert observation.worker_error is not None
    assert observation.worker_error["code"] == "DATASET_HASH_MISMATCH"
    assert observation.worker_error["field_path"] == "dataset_ref.sha256"
    assert "output/worker_error.json" in {a.path for a in observation.artifacts}


def test_invalid_input_artifact_name_is_rejected(tmp_path: Path) -> None:
    split = _split(tmp_path)
    manifest_path = split.attempt_dir / "output" / "split_manifest.json"
    with pytest.raises(ExecutionError) as excinfo:
        _executor(tmp_path).run(
            task_id=TASK_ID,
            node_id="train_logistic_regression",
            attempt_seq=1,
            template_id="train_classifier@1.0.0",
            parameters={"model": "logistic_regression", "seed": 42},
            dataset_ref=DATASET_REF,
            input_artifacts={"../escape": manifest_path},
            limits=LIMITS,
        )
    assert "invalid input artifact name" in str(excinfo.value)


def test_worker_cannot_be_asked_to_run_with_unknown_parameters(tmp_path: Path) -> None:
    observation = _split(tmp_path, parameters={"epochs": 3})
    assert observation.succeeded is False
    assert observation.worker_error is not None
    assert observation.worker_error["code"] == "PARAM_INVALID"
    assert observation.worker_error["field_path"] == "parameters.epochs"