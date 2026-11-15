"""Shared helpers for the T0 work-package tests.

Everything here builds on the real bundled dataset and real SQLite migrations;
there is no in-memory substitute for persistence or evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "researchflow" / "templates" / "data"
DATASET_URI = "local://datasets/synthetic_breast_cancer.csv"
TASK_ID = "task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10"


def dataset_sha256(data_dir: Path | None = None) -> str:
    registry_path = (data_dir or DATA_DIR) / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    return str(registry["datasets"][DATASET_URI]["sha256"])


def task_payload(
    *,
    models: Iterable[str] = ("logistic_regression",),
    seed: int = 42,
    test_size: float = 0.2,
    task_id: str = TASK_ID,
    dataset_sha: str | None = None,
    ruleset_hash: str | None = None,
    wall_time_sec: int = 600,
    include_task_id: bool = True,
) -> dict[str, Any]:
    if ruleset_hash is None:
        from researchflow.rules import RULESET_HASH

        ruleset_hash = RULESET_HASH
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "domain_pack": "tabular_ml@1.0.0",
        "goal": "Train and compare tabular classifiers on the bundled synthetic dataset.",
        "dataset_ref": {
            "uri": DATASET_URI,
            "sha256": dataset_sha or dataset_sha256(),
            "license": "CC0-1.0",
        },
        "template_id": "classification_benchmark@1.0.0",
        "parameters": {
            "target": "diagnosis",
            "seed": seed,
            "test_size": test_size,
            "models": list(models),
        },
        "ruleset_hash": ruleset_hash,
        "limits": {
            "wall_time_sec": wall_time_sec,
            "max_workers": 2,
            "max_memory_mb": 4096,
        },
    }
    if include_task_id:
        payload["task_id"] = task_id
    return payload


def make_db(path: Path):
    """Create a migrated SQLite database and return an open connection."""

    from researchflow.persistence.db import connect
    from researchflow.persistence.migrations import MigrationRunner

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    MigrationRunner().upgrade(connection)
    return connection


def build_ports(db_path: Path):
    from researchflow.orchestration.ports import (
        Ports,
        SqliteEvidenceFacts,
        SqliteTaskFacts,
    )

    return Ports(
        task=SqliteTaskFacts(db_path),
        evidence=SqliteEvidenceFacts(db_path),
    )


def create_task_via_service(
    db_path: Path,
    root: Path,
    *,
    models: Iterable[str] = ("logistic_regression",),
    idempotency_key: str | None = None,
    ruleset_hash: str | None = None,
) -> str:
    """Create a task through the real creation service (no graph/nodes yet)."""

    from researchflow.contracts.encoding import hash_payload
    from researchflow.contracts.models import TaskSpecCreate
    from researchflow.orchestration.creation import TaskCreationService
    from researchflow.orchestration.sqlite_ports import build_ports
    from researchflow.orchestration.state_machine import StateMachine

    payload = task_payload(
        models=models, include_task_id=False, ruleset_hash=ruleset_hash
    )
    state_machine = StateMachine(db_path, ports=build_ports(db_path, root))
    service = TaskCreationService(db_path, state_machine)
    outcome = service.create_task(
        create_spec=TaskSpecCreate.model_validate(payload),
        request_hash=hash_payload(payload),
        idempotency_key=idempotency_key,
    )
    assert outcome.task_id is not None
    return outcome.task_id


def make_world(tmp_path: Path, *, models: Iterable[str] = ("logistic_regression",)):
    """Prepare a migrated runtime with one created task and a pipeline."""

    from researchflow.pipeline import TaskPipeline

    root = tmp_path / "runtime"
    db_path = root / "researchflow.db"
    connection = make_db(db_path)
    connection.close()
    task_id = create_task_via_service(db_path, root, models=models)
    pipeline = TaskPipeline(db_path, root)
    return {
        "root": root,
        "db_path": db_path,
        "task_id": task_id,
        "pipeline": pipeline,
    }


def tamper_job_parameters(
    root: Path,
    task_id: str,
    node_id: str,
    attempt_seq: int,
    mutate,
    *,
    update_declared_hash: bool = True,
) -> dict[str, Any]:
    """Rewrite an executor ``job.json`` to simulate an attacker with file access.

    When ``update_declared_hash`` is true the attacker also recomputes the
    stored ``parameters_hash``; the only remaining defence is the cross-check
    against the registered NodeSpec and the E2 launch evidence.
    """

    from researchflow.contracts.encoding import hash_payload

    path = (
        root
        / "tasks"
        / task_id
        / "attempts"
        / node_id
        / f"attempt_{attempt_seq:02d}"
        / "job.json"
    )
    job = json.loads(path.read_text(encoding="utf-8"))
    mutate(job["parameters"])
    if update_declared_hash:
        job["parameters_hash"] = hash_payload(job["parameters"])
    path.write_text(
        json.dumps(job, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return job


def resign_bundle_manifest(bundle: Path, key) -> None:
    """Recompute manifest file hashes and re-sign it (test helper for tampering)."""

    import hashlib

    from researchflow.bundle.export import BUNDLE_DOMAIN, BUNDLE_MANIFEST_FIELDS
    from researchflow.contracts.encoding import canonical_bytes
    from researchflow.signing import sign_bytes

    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = []
    for entry in manifest["files"]:
        path = bundle / entry["path"]
        data = path.read_bytes()
        files.append(
            {
                "path": entry["path"],
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    manifest["files"] = files
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload = BUNDLE_DOMAIN + canonical_bytes(
        {field: manifest[field] for field in BUNDLE_MANIFEST_FIELDS}
    )
    signature_document = json.loads((bundle / "manifest.sig.json").read_text(encoding="utf-8"))
    signature_document["signature"] = sign_bytes(key.private_key, payload)
    (bundle / "manifest.sig.json").write_text(
        json.dumps(signature_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def create_task_with_graph(
    db_path: Path,
    *,
    models: Iterable[str] = ("logistic_regression",),
    task_id: str = TASK_ID,
    ruleset_hash: str | None = None,
):
    """Create a real task row, its graph version and one node row per graph node."""

    from researchflow.contracts.models import TaskSpec
    from researchflow.dag import build_graph, register_graph
    from researchflow.orchestration.state_machine import Actor, StateMachine
    from researchflow.orchestration.transitions import ActorRole
    from researchflow.persistence.db import connect, transaction

    spec = TaskSpec.model_validate(
        task_payload(models=models, task_id=task_id, ruleset_hash=ruleset_hash)
    )
    graph = build_graph(spec)
    state_machine = StateMachine(db_path)
    connection = connect(db_path)
    try:
        with transaction(connection):
            state_machine.create_initial(
                obj_type="task",
                task_id=task_id,
                actor=Actor(ActorRole.API, "create"),
                correlation_id="req-task",
                task_spec=spec,
                connection=connection,
            )
            register_graph(connection, graph)
            for node in graph.nodes:
                state_machine.create_initial(
                    obj_type="node",
                    task_id=task_id,
                    node_id=node.node_id,
                    actor=Actor(ActorRole.ORCHESTRATOR, "test"),
                    correlation_id=f"req-{node.node_id}",
                    node_spec=node.to_node_spec(),
                    connection=connection,
                )
    finally:
        connection.close()
    return graph