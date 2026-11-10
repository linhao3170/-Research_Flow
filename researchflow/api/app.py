"""ResearchFlow HTTP 契约绑定层（T0 · WP-02）。

范围与边界：

- 只做契约到 HTTP 的绑定：TaskSpec 请求校验、201 响应、`SCHEMA_INVALID` 422
  统一错误体与字段路径映射（06 §4.2/§4.4）。
- **不是**状态机：`state` 字段是 06 §4.2 冻结响应的一部分，本层用一个显式的
  临时内存注册表承载创建回执，不实现迁移规则、不写数据库。持久化与
  `StateMachine` 由 WP-03 接管，届时替换 `_EphemeralTaskRegistry`。
- 按决议 8，T0 不注册 `POST /api/v1/tasks/{task_id}/recover`，访问应为 404。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from researchflow.contracts.models import TaskSpec, TaskSpecCreate
from researchflow.contracts.parsing import ContractJSONError, loads_strict

ERROR_CODE_SCHEMA_INVALID = "SCHEMA_INVALID"
ERROR_CODE_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"

_DATASET_REF_MESSAGE = "dataset_ref must be an object with fields uri, sha256, license."


class _EphemeralTaskRegistry:
    """WP-02 契约绑定用的临时注册表；明确非权威、非持久、非状态机。"""

    provenance = "wp-02-contract-binding-stub"

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[str, tuple[str, dict[str, Any]]] = {}

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self._tasks.get(task_id)

    def idempotent_replay(
        self, key: str, request_hash: str
    ) -> tuple[str, dict[str, Any]] | None:
        return self._idempotency.get(key)

    def remember(
        self,
        task_id: str,
        record: dict[str, Any],
        *,
        idempotency_key: str | None,
        request_hash: str,
    ) -> None:
        self._tasks[task_id] = record
        if idempotency_key is not None:
            self._idempotency[idempotency_key] = (request_hash, record)


def _canonical_request_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    """返回 (field_path, message)；固定 06 §4.2 的 dataset_ref 提示语。"""
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


def create_app() -> FastAPI:
    app = FastAPI(
        title="ResearchFlow API",
        version="1.0",
        description="T0 契约绑定层（WP-02）；状态机与持久化在 WP-03。",
    )
    registry = _EphemeralTaskRegistry()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

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

        interface_hash = _canonical_request_hash(payload)
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key is not None:
            replay = registry.idempotent_replay(idempotency_key, interface_hash)
            if replay is not None:
                replay_hash, replay_body = replay
                if replay_hash == interface_hash:
                    return JSONResponse(status_code=201, content=replay_body)
                return _error_response(
                    status_code=409,
                    error_code=ERROR_CODE_IDEMPOTENCY_CONFLICT,
                    message="相同 Idempotency-Key 对应不同请求体。",
                    field_path=None,
                )

        task_id = f"task_{uuid.uuid4()}"
        spec = TaskSpec(task_id=task_id, **create_spec.model_dump())
        record: dict[str, Any] = {
            "task_id": task_id,
            "state": "CREATED",
            "graph_version": 1,
            "spec": spec.model_dump(),
        }
        registry.remember(
            task_id,
            record,
            idempotency_key=idempotency_key,
            request_hash=interface_hash,
        )
        return JSONResponse(status_code=201, content={
            "task_id": task_id,
            "state": record["state"],
            "graph_version": record["graph_version"],
        })

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str) -> JSONResponse:
        record = registry.get(task_id)
        if record is None:
            return JSONResponse(status_code=404, content={"detail": "task not found"})
        return JSONResponse(status_code=200, content=record)

    return app


app = create_app()