"""ResearchFlow HTTP contract layer (T0: WP-03 creation + WP-04…WP-12 views).

Endpoints follow ``06_DATA_AND_API.md`` §4.1.  ``POST /recover`` is deliberately
not registered in T0 (decision 8): requesting it returns 404.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from researchflow.contracts.encoding import hash_payload
from researchflow.contracts.errors import API_ERROR_STATUS
from researchflow.contracts.models import TaskSpecCreate
from researchflow.contracts.parsing import ContractJSONError, loads_strict
from researchflow.evidence.collector import Collector
from researchflow.orchestration.creation import TaskCreationService
from researchflow.orchestration.ports import Ports
from researchflow.orchestration.sqlite_ports import build_ports
from researchflow.orchestration.state_machine import Actor, StateMachine
from researchflow.persistence.db import connect
from researchflow.persistence.idempotency import (
    InvalidIdempotencyKey,
    validate_idempotency_key,
)
from researchflow.persistence.migrations import MigrationRunner
from researchflow.persistence.records import (
    CertificateRepository,
    GraphRepository,
    ReportRepository,
)
from researchflow.persistence.repositories import NodeRepository, TaskRepository
from researchflow.gate.gate import Gate
from researchflow.verification.verifier import VerificationError, VerificationService

ERROR_CODE_SCHEMA_INVALID = "SCHEMA_INVALID"
ERROR_CODE_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
ERROR_CODE_CERTIFICATE_NOT_AVAILABLE = "CERTIFICATE_NOT_AVAILABLE"
ERROR_CODE_STATE_TRANSITION_DENIED = "STATE_TRANSITION_DENIED"

_DATASET_REF_MESSAGE = "dataset_ref must be an object with fields uri, sha256, license."
_SUPPORTED_CHECKS = {"L1", "L2", "L3"}


def _resolve_db_path(db_path: str | Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    configured = os.environ.get("RESEARCHFLOW_DB_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "runtime" / "researchflow.db"


def _field_path(location: tuple[Any, ...]) -> str:
    parts = [str(part) for part in location if part != "body"]
    return ".".join(parts) if parts else "$"


def _error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    field_path: str | None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "correlation_id": f"req-{uuid.uuid4().hex}",
    }
    if field_path is not None:
        body["field_path"] = field_path
    return JSONResponse(status_code=status_code, content=body)


def _schema_invalid(field_path: str, message: str) -> JSONResponse:
    return _error_response(
        status_code=422,
        error_code=ERROR_CODE_SCHEMA_INVALID,
        message=message,
        field_path=field_path,
    )


def _validation_message(exc: ValidationError) -> tuple[str, str]:
    first = exc.errors()[0]
    path = _field_path(tuple(first.get("loc", ())))
    error_type = str(first.get("type", ""))
    if path == "dataset_ref" and error_type in {
        "string_type",
        "model_type",
        "model_attributes_type",
        "dict_type",
    }:
        return path, _DATASET_REF_MESSAGE
    detail = str(first.get("msg", "字段校验失败"))
    return path, f"{path}: {detail}" if path != "$" else detail


def _certificate_document(certificate) -> dict[str, Any]:
    return {
        "schema_version": certificate.schema_version,
        "cert_id": certificate.cert_id,
        "report_id": certificate.report_id,
        "final_state": certificate.final_state,
        "merkle_root": certificate.merkle_root,
        "tree_size": certificate.tree_size,
        "ruleset_hash": certificate.ruleset_hash,
        "code_hash": certificate.code_hash,
        "env_fingerprint": certificate.env_fingerprint,
        "l3_coverage": certificate.l3_coverage,
        "skipped_nodes": certificate.skipped_nodes,
        "alg": certificate.alg,
        "key_id": certificate.key_id,
        "key_fingerprint": certificate.key_fingerprint,
        "signature": certificate.signature,
        "issued_at": certificate.issued_at,
    }


def _evidence_document(row, invalidated_ids: set[str]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evidence_id": row.evidence_id,
        "task_id": row.task_id,
        "node_id": row.node_id,
        "attempt_id": row.attempt_id,
        "event_seq": row.event_seq,
        "level": row.level,
        "kind": row.kind,
        "producer": row.producer,
        "timestamp": row.timestamp,
        "payload_hash": row.payload_hash,
        "artifact_refs": None if row.artifact_refs is None else json.loads(row.artifact_refs),
        "prev_hash": row.prev_hash,
        "chain_hash": row.chain_hash,
        "invalidated": row.evidence_id in invalidated_ids,
    }


def create_app(db_path: str | Path | None = None) -> FastAPI:
    resolved_db_path = _resolve_db_path(db_path)
    task_root = resolved_db_path.parent

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect(resolved_db_path)
        try:
            MigrationRunner().upgrade(connection)
        finally:
            connection.close()
        ports: Ports = build_ports(resolved_db_path, task_root)
        state_machine = StateMachine(resolved_db_path, ports=ports)
        application.state.service = TaskCreationService(
            resolved_db_path, state_machine
        )
        application.state.collector = Collector(resolved_db_path, task_root)
        application.state.verification = VerificationService(
            resolved_db_path, task_root
        )
        application.state.db_path = resolved_db_path
        application.state.task_root = task_root
        yield

    app = FastAPI(
        title="ResearchFlow API",
        version="1.0",
        description="T0 契约绑定层：任务、DAG、证据、验证、报告与凭证。",
        lifespan=lifespan,
    )

    def _service() -> TaskCreationService | None:
        return getattr(app.state, "service", None)

    def _state(name: str):
        return getattr(app.state, name, None)

    def _task_exists(db: Path, task_id: str) -> bool:
        connection = connect(db)
        try:
            return TaskRepository().get(connection, task_id) is not None
        finally:
            connection.close()

    def _is_stale(db: Path, task_id: str, issued_at: str) -> bool:
        """A report is stale once a node is INVALIDATED or newer invalidations exist."""

        connection = connect(db)
        try:
            invalidated_node = connection.execute(
                "SELECT 1 FROM nodes WHERE task_id = ? AND state = 'INVALIDATED' LIMIT 1",
                (task_id,),
            ).fetchone()
            later = connection.execute(
                "SELECT 1 FROM evidence_invalidations WHERE task_id = ? AND created_at >= ? LIMIT 1",
                (task_id, issued_at),
            ).fetchone()
            return bool(invalidated_node or later)
        finally:
            connection.close()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        service = _service()
        if service is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})
        ready = await run_in_threadpool(service.ready)
        if not ready:
            return JSONResponse(status_code=503, content={"detail": "database not ready"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    # ------------------------------------------------------------------ creation
    @app.post("/api/v1/tasks", status_code=201)
    async def create_task(request: Request) -> JSONResponse:
        raw = await request.body()
        try:
            payload = loads_strict(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return _schema_invalid("$", "请求体必须是 UTF-8 编码的 JSON。")
        except ContractJSONError as exc:
            return _schema_invalid(exc.pointer, exc.message)

        if not isinstance(payload, dict):
            return _schema_invalid("$", "请求体必须是 JSON 对象。")

        try:
            create_spec = TaskSpecCreate.model_validate(payload)
        except ValidationError as exc:
            field_path, message = _validation_message(exc)
            return _schema_invalid(field_path, message)

        try:
            idempotency_key = validate_idempotency_key(
                request.headers.get("Idempotency-Key")
            )
        except InvalidIdempotencyKey as exc:
            return _schema_invalid(exc.field_path, str(exc))

        service = _service()
        if service is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})

        request_hash = hash_payload(payload)
        outcome = await run_in_threadpool(
            service.create_task,
            create_spec=create_spec,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
        )
        if outcome.kind == "CONFLICT":
            return _error_response(
                status_code=API_ERROR_STATUS[ERROR_CODE_IDEMPOTENCY_CONFLICT],
                error_code=ERROR_CODE_IDEMPOTENCY_CONFLICT,
                message="相同 Idempotency-Key 对应不同请求体。",
                field_path=None,
            )
        body = outcome.public_body()
        if body is None:
            return JSONResponse(status_code=500, content={"detail": "creation failed"})
        return JSONResponse(status_code=201, content=body)

    # --------------------------------------------------------------------- views
    @app.get("/api/v1/tasks/{task_id}")
    async def get_task(task_id: str) -> JSONResponse:
        service = _service()
        if service is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})
        detail = await run_in_threadpool(service.get_task, task_id)
        if detail is None:
            return JSONResponse(status_code=404, content={"detail": "task not found"})
        return JSONResponse(status_code=200, content=detail)

    @app.get("/api/v1/tasks/{task_id}/graph")
    async def get_graph(task_id: str) -> JSONResponse:
        db = _state("db_path")
        if db is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})
        if not await run_in_threadpool(_task_exists, db, task_id):
            return JSONResponse(status_code=404, content={"detail": "task not found"})

        def _read() -> dict[str, Any] | None:
            connection = connect(db)
            try:
                graph = GraphRepository().get(connection, task_id)
                nodes = {row.node_id: row for row in NodeRepository().list_for_task(connection, task_id)}
            finally:
                connection.close()
            if graph is None:
                return None
            specs = {str(node["node_id"]): node for node in graph.nodes}
            ordered = [
                {
                    "node_id": node_id,
                    "node_type": str(specs[node_id]["node_type"]),
                    "template_id": str(specs[node_id]["template_id"]),
                    "depends_on": list(specs[node_id]["depends_on"]),
                    "required_checks": list(specs[node_id]["required_checks"]),
                    "parameters_hash": str(specs[node_id]["parameters_hash"]),
                    "state": nodes[node_id].state if node_id in nodes else "MISSING",
                    "attempt_seq": nodes[node_id].attempt_seq if node_id in nodes else 0,
                }
                for node_id in graph.topology_order
            ]
            return {
                "task_id": task_id,
                "graph_version": graph.graph_version,
                "graph_hash": graph.graph_hash,
                "topology_order": list(graph.topology_order),
                "dataset": graph.graph_json.get("dataset", {}),
                "nodes": ordered,
            }

        body = await run_in_threadpool(_read)
        if body is None:
            return _error_response(
                status_code=409,
                error_code=ERROR_CODE_STATE_TRANSITION_DENIED,
                message="图尚未登记；先执行任务（内部编排）再查看 DAG。",
                field_path=None,
            )
        return JSONResponse(status_code=200, content=body)

    @app.get("/api/v1/tasks/{task_id}/evidence")
    async def get_evidence(task_id: str, limit: int = 50, offset: int = 0) -> JSONResponse:
        db = _state("db_path")
        if db is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})
        if limit < 1 or limit > 200:
            return _schema_invalid("limit", "limit 必须在 1–200 之间。")
        if offset < 0:
            return _schema_invalid("offset", "offset 必须 >= 0。")
        if not await run_in_threadpool(_task_exists, db, task_id):
            return JSONResponse(status_code=404, content={"detail": "task not found"})

        collector = _state("collector")

        def _read() -> dict[str, Any]:
            rows = collector.rows(task_id)
            connection = connect(db)
            try:
                invalidated = {
                    str(row["evidence_id"])
                    for row in connection.execute(
                        "SELECT evidence_id FROM evidence_invalidations WHERE task_id = ?",
                        (task_id,),
                    )
                }
            finally:
                connection.close()
            chain = collector.verify_chain(task_id)
            page = rows[offset : offset + limit]
            return {
                "task_id": task_id,
                "count": len(rows),
                "limit": limit,
                "offset": offset,
                "items": [_evidence_document(row, invalidated) for row in page],
                "invalidated_evidence_ids": sorted(invalidated),
                "chain": {
                    "ok": chain.ok,
                    "count": chain.count,
                    "last_seq": chain.last_seq,
                    "issues": [issue.to_dict() for issue in chain.issues],
                },
            }

        return JSONResponse(status_code=200, content=await run_in_threadpool(_read))

    # ------------------------------------------------------------------- verify
    @app.post("/api/v1/tasks/{task_id}/verify")
    async def verify_task(task_id: str, request: Request) -> JSONResponse:
        db = _state("db_path")
        if db is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})
        raw = await request.body()
        try:
            payload = loads_strict(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ContractJSONError) as exc:
            return _schema_invalid("$", f"请求体不是合法 JSON：{exc}")
        if not isinstance(payload, dict):
            return _schema_invalid("$", "请求体必须是 JSON 对象。")
        mode = payload.get("mode", "full")
        if mode != "full":
            return _schema_invalid("mode", "T0 只支持 mode=full。")
        requested = payload.get("requested_checks", ["L1", "L2", "L3"])
        if (
            not isinstance(requested, list)
            or not requested
            or any(str(check) not in _SUPPORTED_CHECKS for check in requested)
        ):
            return _schema_invalid(
                "requested_checks", "requested_checks 必须是 L1/L2/L3 的非空子集。"
            )

        if not await run_in_threadpool(_task_exists, db, task_id):
            return JSONResponse(status_code=404, content={"detail": "task not found"})

        def _state_of_task() -> str:
            connection = connect(db)
            try:
                task = TaskRepository().get(connection, task_id)
            finally:
                connection.close()
            return "" if task is None else task.state

        task_state = await run_in_threadpool(_state_of_task)
        if task_state != "VERIFYING":
            return _error_response(
                status_code=409,
                error_code=ERROR_CODE_STATE_TRANSITION_DENIED,
                message=f"验证要求任务处于 VERIFYING，当前为 {task_state}。",
                field_path=None,
            )
        verification = _state("verification")
        try:
            outcome = await run_in_threadpool(
                verification.verify, task_id, requested_checks=tuple(str(c) for c in requested)
            )
        except ValueError as exc:
            return _error_response(
                status_code=409,
                error_code=ERROR_CODE_STATE_TRANSITION_DENIED,
                message=str(exc),
                field_path=None,
            )
        except VerificationError as exc:
            return _error_response(
                status_code=409,
                error_code=ERROR_CODE_STATE_TRANSITION_DENIED,
                message=f"{exc.code}: {exc.detail}",
                field_path=None,
            )
        except Exception:  # noqa: BLE001 - never leak stack traces to clients
            return JSONResponse(status_code=500, content={"detail": "verification failed"})
        return JSONResponse(
            status_code=200,
            content={
                "report_id": outcome.report_id,
                "final_state": outcome.final_state,
                "gaps": list(outcome.gaps),
                "certificate_id": outcome.certificate_id,
                "l1_status": outcome.l1_status,
                "l2_status": outcome.l2_status,
                "l3_status": outcome.l3_status,
            },
        )

    @app.get("/api/v1/tasks/{task_id}/report")
    async def get_report(task_id: str) -> JSONResponse:
        db = _state("db_path")
        if db is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})
        if not await run_in_threadpool(_task_exists, db, task_id):
            return JSONResponse(status_code=404, content={"detail": "task not found"})

        def _read():
            connection = connect(db)
            try:
                report = ReportRepository().latest_for_task(connection, task_id)
            finally:
                connection.close()
            if report is None:
                return None
            stale = _is_stale(db, task_id, report.issued_at)
            return report, stale

        loaded = await run_in_threadpool(_read)
        if loaded is None:
            return JSONResponse(status_code=404, content={"detail": "report not found"})
        report, stale = loaded
        return JSONResponse(
            status_code=200,
            content={
                "report_id": report.report_id,
                "final_state": report.final_state,
                "stale": stale,
                "report": report.report_json,
                "gaps": report.gaps,
            },
        )

    @app.get("/api/v1/tasks/{task_id}/certificate")
    async def get_certificate(task_id: str) -> JSONResponse:
        db = _state("db_path")
        if db is None:
            return JSONResponse(status_code=503, content={"detail": "not started"})
        if not await run_in_threadpool(_task_exists, db, task_id):
            return JSONResponse(status_code=404, content={"detail": "task not found"})

        def _read():
            connection = connect(db)
            try:
                report = ReportRepository().latest_for_task(connection, task_id)
                if report is None or report.final_state != "VERIFIED":
                    return None
                certificate = CertificateRepository().for_report(connection, report.report_id)
                if certificate is None:
                    return None
                document = _certificate_document(certificate)
            finally:
                connection.close()
            document["stale"] = _is_stale(db, task_id, report.issued_at)
            return document

        document = await run_in_threadpool(_read)
        if document is None:
            return _error_response(
                status_code=409,
                error_code=ERROR_CODE_CERTIFICATE_NOT_AVAILABLE,
                message="Only VERIFIED tasks can receive a completion certificate.",
                field_path=None,
            )
        return JSONResponse(status_code=200, content=document)

    return app


app = create_app()