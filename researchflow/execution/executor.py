"""Controlled executor for whitelisted templates (T0 WP-06).

Guarantees:

* a template must be registered before anything is spawned;
* every attempt gets a brand-new directory (reuse is refused, never cleaned);
* inputs are copied into the attempt directory and hashed, so a later change
  on disk cannot rewrite history;
* the child runs in a separate process with a minimal environment;
* timeout and memory overruns terminate the whole process tree;
* the executor records *observations* (exit code, artifacts, resource peaks)
  and never decides that a node succeeded.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from researchflow.execution.env import code_hash, env_fingerprint
from researchflow.execution.errors import (
    AttemptDirReused,
    ExecutionError,
    PathEscape,
    ToolNotAllowlisted,
)
from researchflow.execution.sampler import ProcessTreeSampler, descendant_pids
from researchflow.templates.errors import TemplateError
from researchflow.templates.registry import lookup_node_template

__all__ = [
    "ArtifactObservation",
    "AttemptObservation",
    "Executor",
    "attempt_dir_for",
    "read_attempt_result",
]

_INPUT_NAME_PATTERN = "abcdefghijklmnopqrstuvwxyz0123456789_"
_ALLOWED_ENV_KEYS = (
    "SYSTEMROOT",
    "WINDIR",
    "PATH",
    "PATHEXT",
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_within(base: Path, candidate: Path) -> Path:
    resolved_base = base.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_base and resolved_base not in resolved.parents:
        raise PathEscape(f"path escapes the attempt directory: {candidate}")
    return resolved


def attempt_dir_for(
    task_root: Path,
    task_id: str,
    node_id: str,
    attempt_seq: int,
    task_dir_name: str | None = None,
) -> Path:
    if attempt_seq < 1:
        raise ValueError("attempt_seq starts at 1")
    folder = task_dir_name or task_id
    return task_root / "tasks" / folder / "attempts" / node_id / f"attempt_{attempt_seq:02d}"


@dataclass(frozen=True, slots=True)
class ArtifactObservation:
    path: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True, slots=True)
class AttemptObservation:
    task_id: str
    node_id: str
    attempt_id: str
    attempt_seq: int
    attempt_dir: Path
    template_id: str
    status: str
    exit_code: int | None
    pid: int | None
    worker_pids: tuple[int, ...]
    kill_verified: bool | None
    timed_out: bool
    killed: bool
    memory_exceeded: bool
    duration_sec: float
    peak_memory_mb: float | None
    started_at: str
    ended_at: str
    stdout_path: str
    stderr_path: str
    artifacts: tuple[ArtifactObservation, ...]
    inputs: tuple[dict[str, Any], ...]
    worker_error: dict[str, Any] | None
    parameters_hash: str
    dataset_sha256: str
    env_fingerprint: str
    code_hash: str
    command: tuple[str, ...] = field(default_factory=tuple)

    @property
    def succeeded(self) -> bool:
        return self.status == "EXITED" and self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "task_id": self.task_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "attempt_seq": self.attempt_seq,
            "template_id": self.template_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "pid": self.pid,
            "worker_pids": list(self.worker_pids),
            "kill_verified": self.kill_verified,
            "timed_out": self.timed_out,
            "killed": self.killed,
            "memory_exceeded": self.memory_exceeded,
            "duration_sec": self.duration_sec,
            "peak_memory_mb": self.peak_memory_mb,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "inputs": list(self.inputs),
            "worker_error": self.worker_error,
            "parameters_hash": self.parameters_hash,
            "dataset_sha256": self.dataset_sha256,
            "env_fingerprint": self.env_fingerprint,
            "code_hash": self.code_hash,
            "command": list(self.command),
        }


def read_attempt_result(attempt_dir: Path) -> dict[str, Any] | None:
    path = Path(attempt_dir) / "result.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class Executor:
    def __init__(
        self,
        task_root: str | Path,
        *,
        python_executable: str | None = None,
        repo_root: str | Path | None = None,
        task_dir_name: str | None = None,
    ) -> None:
        self._task_root = Path(task_root).resolve()
        self._python = python_executable or sys.executable
        self._repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
        self._task_dir_name = task_dir_name

    @property
    def task_root(self) -> Path:
        return self._task_root

    def _environment(self, tmp_dir: Path) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in _ALLOWED_ENV_KEYS:
            value = os.environ.get(key)
            if value:
                env[key] = value
        env["TEMP"] = str(tmp_dir)
        env["TMP"] = str(tmp_dir)
        env["PYTHONPATH"] = str(self._repo_root)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # One BLAS/OpenMP thread per worker: keeps the two-worker cap inside the
        # 16 GB host budget and removes thread-count nondeterminism.
        for key in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            env[key] = "1"
        data_root = os.environ.get("RESEARCHFLOW_DATA_ROOT")
        if data_root:
            # The worker runs with cwd inside the attempt directory, so a
            # relative data root must be resolved by the parent first.
            env["RESEARCHFLOW_DATA_ROOT"] = str(Path(data_root).resolve())
        return env

    def _kill_tree(self, process: subprocess.Popen[bytes]) -> bool:
        try:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            killed = completed.returncode == 0
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - fallback
            killed = False
        if process.poll() is None:
            try:
                process.kill()
                killed = True
            except OSError:  # pragma: no cover
                pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass
        return killed

    def _collect_artifacts(self, output_dir: Path) -> tuple[ArtifactObservation, ...]:
        artifacts: list[ArtifactObservation] = []
        for path in sorted(output_dir.rglob("*")):
            if path.is_dir():
                continue
            _ensure_within(output_dir, path)
            relative = path.relative_to(output_dir).as_posix()
            artifacts.append(
                ArtifactObservation(
                    path=f"output/{relative}",
                    sha256=_sha256(path),
                    size=path.stat().st_size,
                )
            )
        return tuple(artifacts)

    def run(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_seq: int,
        template_id: str,
        parameters: Mapping[str, Any],
        dataset_ref: Mapping[str, Any],
        input_artifacts: Mapping[str, Path] | None = None,
        limits: Mapping[str, Any] | None = None,
        timeout_sec: float | None = None,
    ) -> AttemptObservation:
        try:
            lookup_node_template(template_id)
        except TemplateError as exc:
            raise ToolNotAllowlisted(str(exc), field_path=exc.field_path) from exc

        attempt_dir = attempt_dir_for(
            self._task_root, task_id, node_id, attempt_seq, self._task_dir_name
        )
        if attempt_dir.exists():
            raise AttemptDirReused(f"attempt directory already exists: {attempt_dir}")
        inputs_dir = attempt_dir / "inputs"
        output_dir = attempt_dir / "output"
        tmp_dir = attempt_dir / "tmp"
        for directory in (inputs_dir, output_dir, tmp_dir):
            directory.mkdir(parents=True, exist_ok=False)

        input_records: list[dict[str, Any]] = []
        job_inputs: dict[str, str] = {}
        for name, source in (input_artifacts or {}).items():
            if not name or any(character not in _INPUT_NAME_PATTERN for character in name):
                raise ExecutionError(f"invalid input artifact name: {name!r}")
            source_path = Path(source)
            if not source_path.is_file():
                raise ExecutionError(
                    f"input artifact does not exist: {source_path}", field_path=name
                )
            target = inputs_dir / name
            shutil.copyfile(source_path, target)
            digest = _sha256(target)
            if digest != _sha256(source_path):
                raise ExecutionError(f"input artifact changed while copying: {source}")
            input_records.append(
                {"name": name, "sha256": digest, "size": target.stat().st_size}
            )
            job_inputs[name] = str(target)

        parameters_hash = _hash_parameters(parameters)
        job = {
            "schema_version": "1.0",
            "task_id": task_id,
            "node_id": node_id,
            "attempt_id": f"attempt_{attempt_seq:02d}",
            "attempt_seq": attempt_seq,
            "template_id": template_id,
            "parameters": dict(parameters),
            "parameters_hash": parameters_hash,
            "dataset_ref": dict(dataset_ref),
            "input_artifacts": job_inputs,
            "output_dir": str(output_dir),
            "limits": dict(limits or {}),
        }
        job_path = attempt_dir / "job.json"
        job_path.write_text(
            json.dumps(job, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        limits = dict(limits or {})
        wall_limit = float(timeout_sec or limits.get("wall_time_sec") or 1800)
        memory_limit = limits.get("max_memory_mb")
        command = (
            self._python,
            "-B",
            "-m",
            "researchflow.execution.worker",
            "--job",
            str(job_path),
        )
        started_wall = datetime.now(timezone.utc)
        started_monotonic = time.monotonic()
        status = "EXITED"
        exit_code: int | None = None
        pid: int | None = None
        worker_pids: tuple[int, ...] = ()
        kill_verified: bool | None = None
        timed_out = False
        killed = False
        memory_exceeded = False
        peak_memory: float | None = None
        with (attempt_dir / "stdout.log").open("wb") as stdout, (
            attempt_dir / "stderr.log"
        ).open("wb") as stderr:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(attempt_dir),
                    env=self._environment(tmp_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            except OSError as exc:
                status = "SPAWN_FAILED"
                (attempt_dir / "spawn_error.txt").write_text(str(exc), encoding="utf-8")
                process = None
            if process is not None:
                pid = process.pid
                # The venv python.exe is a launcher; the real interpreter is a
                # child process, so memory must be sampled over the whole tree.
                sampler = ProcessTreeSampler(process.pid)
                sampler.start()
                try:
                    while process.poll() is None:
                        elapsed = time.monotonic() - started_monotonic
                        if elapsed > wall_limit:
                            timed_out = True
                            killed = self._kill_tree(process)
                            status = "TIMEOUT"
                            break
                        if memory_limit is not None:
                            current = sampler.current_mb()
                            if current is not None and current > float(memory_limit):
                                memory_exceeded = True
                                killed = self._kill_tree(process)
                                status = "MEMORY_EXCEEDED"
                                break
                        time.sleep(0.02)
                finally:
                    peak_memory = sampler.stop()
                    worker_pids = tuple(sampler.measured_pids())
                exit_code = process.poll()
                if killed:
                    for _ in range(40):
                        if not descendant_pids(pid):
                            break
                        time.sleep(0.05)
                    kill_verified = not descendant_pids(pid)
        ended_wall = datetime.now(timezone.utc)
        duration = round(time.monotonic() - started_monotonic, 3)

        artifacts = self._collect_artifacts(output_dir)
        worker_error: dict[str, Any] | None = None
        error_path = output_dir / "worker_error.json"
        if error_path.is_file():
            try:
                worker_error = json.loads(error_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                worker_error = {"status": "ERROR", "code": "UNREADABLE_WORKER_ERROR"}

        observation = AttemptObservation(
            task_id=task_id,
            node_id=node_id,
            attempt_id=f"attempt_{attempt_seq:02d}",
            attempt_seq=attempt_seq,
            attempt_dir=attempt_dir,
            template_id=template_id,
            status=status,
            exit_code=exit_code,
            pid=pid,
            worker_pids=worker_pids,
            kill_verified=kill_verified,
            timed_out=timed_out,
            killed=killed,
            memory_exceeded=memory_exceeded,
            duration_sec=duration,
            peak_memory_mb=peak_memory,
            started_at=_format(started_wall),
            ended_at=_format(ended_wall),
            stdout_path="stdout.log",
            stderr_path="stderr.log",
            artifacts=artifacts,
            inputs=tuple(input_records),
            worker_error=worker_error,
            parameters_hash=parameters_hash,
            dataset_sha256=str(dataset_ref.get("sha256", "")),
            env_fingerprint=env_fingerprint(str(dataset_ref.get("sha256", ""))),
            code_hash=code_hash(),
            command=("<python>", "-B", "-m", "researchflow.execution.worker", "--job", "job.json"),
        )
        _write_json(attempt_dir / "result.json", observation.to_dict())
        return observation


def _hash_parameters(parameters: Mapping[str, Any]) -> str:
    from researchflow.contracts.encoding import hash_payload

    return hash_payload(dict(parameters))


def _format(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)