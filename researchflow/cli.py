"""ResearchFlow internal CLI (T0).

This is orchestration, not a public API: T0 deliberately does not add ``/run``
or ``/recover`` routes.  Every command reads/writes the same SQLite database the
API uses.

Commands::

    init-db      --db <path>
    serve        --db <path> --host 127.0.0.1 --port 8000
    run-task     --db <path> --task <task_id>
    verify       --db <path> --task <task_id>
    status       --db <path> --task <task_id>
    write-anchor --db <path> --out <trust_store.json>
    export-bundle --db <path> --task <task_id> --out <dir> [--trust-anchor <path>]
    invalidate   --db <path> --task <id> --node <node_id> --cause-type <T> --cause-ref <ref>
                 [--dataset-sha <sha>]
    rerun        --db <path> --task <id> --plan-hash <hash>
    recover      --db <path> --task <id> --node <node_id> --cause-type <T> --cause-ref <ref>
                 [--dataset-sha <sha>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from researchflow.persistence.db import connect
from researchflow.persistence.migrations import MigrationRunner

__all__ = ["main"]


def _default_root(db_path: Path) -> Path:
    return db_path.parent


def _open(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(db_path)
    MigrationRunner().upgrade(connection)
    connection.close()


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_init_db(args) -> int:
    db_path = Path(args.db)
    _open(db_path)
    _print({"status": "OK", "db": str(db_path)})
    return 0


def cmd_serve(args) -> int:
    from researchflow.server import serve

    return serve(Path(args.db), args.host, args.port, log_level=args.log_level)


def cmd_run_task(args) -> int:
    from researchflow.pipeline import TaskPipeline

    db_path = Path(args.db)
    _open(db_path)
    pipeline = TaskPipeline(db_path, _default_root(db_path))
    result = pipeline.run_task(args.task)
    _print(result)
    return 0 if result.get("final_state") == "VERIFIED" else 1


def cmd_verify(args) -> int:
    from researchflow.verification import VerificationService

    db_path = Path(args.db)
    _open(db_path)
    service = VerificationService(db_path, _default_root(db_path))
    outcome = service.verify(args.task)
    _print(outcome.to_dict())
    return 0 if outcome.final_state == "VERIFIED" else 1


def cmd_status(args) -> int:
    from researchflow.persistence.repositories import NodeRepository, TaskRepository
    from researchflow.persistence.records import CertificateRepository, ReportRepository

    db_path = Path(args.db)
    _open(db_path)
    connection = connect(db_path)
    try:
        task = TaskRepository().get(connection, args.task)
        if task is None:
            _print({"status": "NOT_FOUND", "task_id": args.task})
            return 1
        nodes = {row.node_id: row.state for row in NodeRepository().list_for_task(connection, args.task)}
        report = ReportRepository().latest_for_task(connection, args.task)
        certificate = CertificateRepository().latest_for_task(connection, args.task)
    finally:
        connection.close()
    _print(
        {
            "task_id": task.task_id,
            "state": task.state,
            "graph_version": task.graph_version,
            "nodes": nodes,
            "report": None
            if report is None
            else {
                "report_id": report.report_id,
                "final_state": report.final_state,
                "coverage": {
                    "required": report.coverage_required,
                    "passed": report.coverage_passed,
                    "missing": report.coverage_missing,
                },
            },
            "certificate": None
            if certificate is None
            else {"cert_id": certificate.cert_id, "merkle_root": certificate.merkle_root},
        }
    )
    return 0


def cmd_write_anchor(args) -> int:
    from researchflow.signing import KeyStore

    db_path = Path(args.db)
    root = _default_root(db_path)
    _open(db_path)
    store = KeyStore(root / "keys")
    store.load_or_create()
    path = store.write_trust_anchor(Path(args.out))
    _print({"status": "OK", "trust_anchor": str(path)})
    return 0


def cmd_export_bundle(args) -> int:
    from researchflow.bundle.export import BundleExporter

    db_path = Path(args.db)
    root = _default_root(db_path)
    _open(db_path)
    exporter = BundleExporter(db_path, root)
    manifest = exporter.export(
        args.task, Path(args.out), trust_anchor_path=Path(args.trust_anchor) if args.trust_anchor else None
    )
    _print({"status": "OK", "bundle": str(args.out), "manifest": manifest})
    return 0


def cmd_invalidate(args) -> int:
    from researchflow.recovery.service import RecoveryService

    db_path = Path(args.db)
    root = _default_root(db_path)
    _open(db_path)
    service = RecoveryService(db_path, root)
    outcome = service.invalidate(
        args.task,
        changed_node=args.node,
        cause_type=args.cause_type,
        cause_ref=args.cause_ref,
        new_dataset_sha256=args.dataset_sha,
    )
    _print(outcome)
    return 0


def cmd_rerun(args) -> int:
    from researchflow.recovery.service import RecoveryService

    db_path = Path(args.db)
    root = _default_root(db_path)
    _open(db_path)
    service = RecoveryService(db_path, root)
    outcome = service.rerun(args.task, args.plan_hash)
    _print(outcome)
    return 0


def cmd_recover(args) -> int:
    from researchflow.recovery.service import RecoveryService

    db_path = Path(args.db)
    root = _default_root(db_path)
    _open(db_path)
    service = RecoveryService(db_path, root)
    invalidated = service.invalidate(
        args.task,
        changed_node=args.node,
        cause_type=args.cause_type,
        cause_ref=args.cause_ref,
        new_dataset_sha256=args.dataset_sha,
    )
    rerun = service.rerun(args.task, invalidated["plan_hash"])
    _print({"invalidate": invalidated, "rerun": rerun})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ResearchFlow T0 internal CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    default_db = str(Path(__file__).resolve().parents[1] / "runtime" / "researchflow.db")

    init = sub.add_parser("init-db")
    init.add_argument("--db", default=default_db)
    init.set_defaults(func=cmd_init_db)

    serve = sub.add_parser("serve")
    serve.add_argument("--db", default=default_db)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=cmd_serve)

    run = sub.add_parser("run-task")
    run.add_argument("--db", default=default_db)
    run.add_argument("--task", required=True)
    run.set_defaults(func=cmd_run_task)

    verify = sub.add_parser("verify")
    verify.add_argument("--db", default=default_db)
    verify.add_argument("--task", required=True)
    verify.set_defaults(func=cmd_verify)

    status = sub.add_parser("status")
    status.add_argument("--db", default=default_db)
    status.add_argument("--task", required=True)
    status.set_defaults(func=cmd_status)

    anchor = sub.add_parser("write-anchor")
    anchor.add_argument("--db", default=default_db)
    anchor.add_argument("--out", required=True)
    anchor.set_defaults(func=cmd_write_anchor)

    export = sub.add_parser("export-bundle")
    export.add_argument("--db", default=default_db)
    export.add_argument("--task", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--trust-anchor", default=None)
    export.set_defaults(func=cmd_export_bundle)

    invalidate = sub.add_parser("invalidate")
    invalidate.add_argument("--db", default=default_db)
    invalidate.add_argument("--task", required=True)
    invalidate.add_argument("--node", required=True)
    invalidate.add_argument("--cause-type", required=True)
    invalidate.add_argument("--cause-ref", required=True)
    invalidate.add_argument("--dataset-sha", default=None)
    invalidate.set_defaults(func=cmd_invalidate)

    rerun = sub.add_parser("rerun")
    rerun.add_argument("--db", default=default_db)
    rerun.add_argument("--task", required=True)
    rerun.add_argument("--plan-hash", required=True)
    rerun.set_defaults(func=cmd_rerun)

    recover = sub.add_parser("recover")
    recover.add_argument("--db", default=default_db)
    recover.add_argument("--task", required=True)
    recover.add_argument("--node", required=True)
    recover.add_argument("--cause-type", required=True)
    recover.add_argument("--cause-ref", required=True)
    recover.add_argument("--dataset-sha", default=None)
    recover.set_defaults(func=cmd_recover)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())