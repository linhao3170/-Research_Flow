"""MODULE：M19 · api/routes_tasks.py — 任务创建、查询与图读取路由（P10 伪代码）。
阶段+追踪：P10「接入、实验与交付」｜06 §4.1/§4.2/§4.4/§4.5、ADR-006、05 §9.2
FR+依赖：FR-001/FR-002；依赖 M01 TaskSpec 模型与 strict parsing、M02 创建/读取端口、M19 error_map/middleware
不变量+错误码：API 不是状态机；创建只插入 CREATED，迁移只能走 StateMachine；422 先于 409；
              同键同体回放原 201、同键异体 409；GET 不得改状态。
              SCHEMA_INVALID(422) / IDEMPOTENCY_CONFLICT(409) / STATE_TRANSITION_DENIED(409)
写入者：TaskCreationPort（任务 + 幂等记录同事务）；本文件不直接写库、不写证据/报告/凭证。
状态：伪代码；不注册 FastAPI 路由、不建库、不发请求。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Final, Mapping, Protocol, Sequence

from .error_map import RejectionRule, build_error_response
from .middleware_idempotency import (
    IdempotencyBinding,
    PreparedRequest,
    RequestProblem,
    RequestValidator,
    CanonicalizeFn,
    prepare_request,
)

__all__ = [
    "CREATE_ROUTE",
    "GET_ROUTE",
    "GRAPH_ROUTE",
    "ApiResponse",
    "CreationOutcome",
    "CreationKind",
    "GraphRecord",
    "HttpRequestContext",
    "TaskCreationPort",
    "TaskReaderPort",
    "TaskRecord",
    "TaskRoutes",
    "TASK_REJECTIONS",
    "assert_task_routes_are_read_only",
]

CREATE_ROUTE: Final[str] = "/api/v1/tasks"
GET_ROUTE: Final[str] = "/api/v1/tasks/{task_id}"
GRAPH_ROUTE: Final[str] = "/api/v1/tasks/{task_id}/graph"
TASK_STATES: Final[frozenset[str]] = frozenset(
    {"CREATED", "PLANNING", "READY", "RUNNING", "VERIFYING", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}
)


class CreationKind:
    """创建端口的三种结果；REPLAYED 必须带回原始响应字节。"""

    CREATED: Final[str] = "CREATED"
    REPLAYED: Final[str] = "REPLAYED"
    CONFLICT: Final[str] = "CONFLICT"


@dataclass(frozen=True, slots=True)
class CreationOutcome:
    """创建结果。`response_body` 在 CREATED/REPLAYED 时非空且字节稳定。"""

    kind: str
    task_id: str | None
    state: str | None
    graph_version: int | None
    response_body: bytes | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {CreationKind.CREATED, CreationKind.REPLAYED, CreationKind.CONFLICT}:
            raise ValueError(f"未知创建结果：{self.kind!r}")
        if self.kind == CreationKind.CONFLICT:
            if self.task_id is not None or self.response_body is not None:
                raise ValueError("CONFLICT 不得携带任务或响应体")
        else:
            if not self.task_id or not self.state or self.graph_version is None or self.response_body is None:
                raise ValueError("CREATED/REPLAYED 必须携带完整回执")
            if self.state != "CREATED" or self.graph_version != 1:
                raise ValueError("创建只能进入 CREATED / graph_version=1")


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """任务详情只读视图；不包含运行时迁移入口。"""

    task_id: str
    state: str
    graph_version: int
    created_at: str
    spec: Mapping[str, Any]
    resource_summary: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GraphRecord:
    """DAG 只读视图；DC/SPA 在 T0 恒为空。"""

    task_id: str
    task_state: str
    graph_version: int
    graph_hash: str
    nodes: Sequence[Mapping[str, Any]]
    edges: Sequence[Mapping[str, Any]]
    dc: Sequence[Mapping[str, Any]]
    spa: Sequence[Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """框架无关的响应；由 FastAPI 适配层转成 JSONResponse。"""

    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class HttpRequestContext:
    """路由入参；`prepared` 由中间件注入，缺失时路由自行准备（测试/直调）。"""

    method: str
    path: str
    headers: Mapping[str, str]
    raw_body: bytes
    prepared: PreparedRequest | None = None
    query: Mapping[str, str] | None = None


class TaskCreationPort(Protocol):
    """创建端口。实现必须在**同一事务**插入 tasks 与 idempotency_keys。"""

    def create_initial(
        self,
        *,
        validated: Any,
        binding: IdempotencyBinding | None,
        correlation_id: str,
        now: str,
    ) -> CreationOutcome: ...


class TaskReaderPort(Protocol):
    """只读端口；实现不得暴露 update/transition 方法。"""

    def get(self, task_id: str) -> TaskRecord | None: ...

    def get_graph(self, task_id: str) -> GraphRecord | None: ...


def _json_bytes(body: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _problem_response(problem: RequestProblem, correlation_id: str) -> ApiResponse:
    """渲染请求问题；有 E.3 码走统一体，无码只用于传输层。"""
    # 1. 有码：422/409 等统一体。
    if problem.code is not None:
        status, headers, body = build_error_response(
            error_code=problem.code,
            message=problem.message,
            correlation_id=correlation_id,
            field_path=problem.field_path,
            reason=problem.reason,
        )
        return ApiResponse(status=status, headers=headers, body=_json_bytes(body))
    # 2. 无码：不伪造 error_code。
    body: dict[str, Any] = {"detail": problem.message, "correlation_id": correlation_id}
    if problem.reason is not None:
        body["reason"] = problem.reason
    return ApiResponse(
        status=problem.status,
        headers={"content-type": "application/json; charset=utf-8"},
        body=_json_bytes(body),
    )


def _error(code: str, message: str, correlation_id: str, *, reason: str | None = None, field_path: str | None = None) -> ApiResponse:
    status, headers, body = build_error_response(
        error_code=code, message=message, correlation_id=correlation_id,
        reason=reason, field_path=field_path,
    )
    return ApiResponse(status=status, headers=headers, body=_json_bytes(body))


class TaskRoutes:
    """三条只读/创建路由；不持有数据库连接，只依赖端口。"""

    def __init__(
        self,
        *,
        creator: TaskCreationPort,
        reader: TaskReaderPort,
        validator: RequestValidator,
        canonicalize: CanonicalizeFn,
        clock: Callable[[], str],
    ) -> None:
        self.creator = creator
        self.reader = reader
        self.validator = validator
        self.canonicalize = canonicalize
        self.clock = clock

    def create_task(self, ctx: HttpRequestContext) -> ApiResponse:
        """POST /api/v1/tasks：422 → 409 → 201；拒绝时任务表不新增行。"""
        # 1. 取得请求上下文；中间件已准备则复用，避免二次解析。
        prepared = ctx.prepared or prepare_request(
            raw_body=ctx.raw_body,
            headers=ctx.headers,
            method="POST",
            route_template=CREATE_ROUTE,
            validator=self.validator,
            canonicalize=self.canonicalize,
        )
        # 2. 解析/模型/键错误：422（或键非法 422），不进入创建端口。
        if prepared.problem is not None:
            return _problem_response(prepared.problem, prepared.correlation_id)
        # 3. 中间件注入的 binding 必须属于本路由；跨路由复用键是客户端错误。
        if prepared.binding is not None and prepared.binding.scope != CREATE_ROUTE:
            return _error(
                "IDEMPOTENCY_CONFLICT",
                "Idempotency-Key 的作用域与路由不匹配。",
                prepared.correlation_id,
                reason="IDEMPOTENCY_SCOPE_MISMATCH",
            )
        # 4. 交给创建端口：tasks + idempotency_keys 同事务；API 不直接写状态。
        outcome = self.creator.create_initial(
            validated=prepared.validated,
            binding=prepared.binding,
            correlation_id=prepared.correlation_id,
            now=self._now(),
        )
        # 5. 同键异体：409；不得覆盖旧任务、不得新增任务。
        if outcome.kind == CreationKind.CONFLICT:
            return _error(
                "IDEMPOTENCY_CONFLICT",
                "相同 Idempotency-Key 对应不同请求体。",
                prepared.correlation_id,
                reason=outcome.reason or "REQUEST_HASH_MISMATCH",
            )
        # 6. 新建或回放：都是 201；回放 body 必须与首次逐字节一致。
        if outcome.kind in {CreationKind.CREATED, CreationKind.REPLAYED}:
            assert outcome.task_id is not None and outcome.response_body is not None
            return ApiResponse(
                status=201,
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "location": f"/api/v1/tasks/{outcome.task_id}",
                },
                body=outcome.response_body,
            )
        # 7. 不可达：端口返回未知结果按内部错误处理，不得猜测状态。
        raise RuntimeError(f"创建端口返回未知结果：{outcome.kind!r}")

    def get_task(self, ctx: HttpRequestContext) -> ApiResponse:
        """GET /api/v1/tasks/{task_id}：404 或 200；绝不改状态。"""
        # 1. 从路径取 task_id；形态不合法也走 404，避免枚举存在性。
        try:
            task_id = _path_param(ctx.path, GET_ROUTE)
        except _NotFound:
            return _not_found("task not found", ctx)
        # 2. 只读查询；不存在即 404（无 E.3 码，传输层语义）。
        record = self.reader.get(task_id)
        if record is None:
            return _not_found("task not found", ctx)
        # 3. 防御：状态必须是运行时枚举之一；未知状态按内部错误暴露为 500。
        if record.state not in TASK_STATES:
            raise ValueError(f"任务 {task_id} 持久化了未知状态 {record.state!r}")
        # 4. 输出详情；spec 只读复制，调用方不能借响应改状态。
        body = {
            "task_id": record.task_id,
            "state": record.state,
            "graph_version": record.graph_version,
            "created_at": record.created_at,
            "spec": dict(record.spec),
            "resource_summary": dict(record.resource_summary),
        }
        return ApiResponse(
            status=200,
            headers={"content-type": "application/json; charset=utf-8"},
            body=_json_bytes(body),
        )

    def get_task_graph(self, ctx: HttpRequestContext) -> ApiResponse:
        """GET /api/v1/tasks/{task_id}/graph：404 / 409 图版本冲突 / 200。"""
        # 1. 取 task_id 与可选 version 查询参数。
        try:
            task_id = _path_param(ctx.path, GRAPH_ROUTE)
            expected_version = _expected_version((ctx.query or {}).get("version"))
        except _NotFound:
            return _not_found("task not found", ctx)
        except RequestProblem as problem:
            return _problem_response(problem, _request_correlation(ctx))
        # 2. 任务不存在 → 404。
        if self.reader.get(task_id) is None:
            return _not_found("task not found", ctx)
        # 3. 图尚未生成 → 404（不是 409；409 只表示版本冲突）。
        graph = self.reader.get_graph(task_id)
        if graph is None:
            return _not_found("graph not generated", ctx)
        # 4. 版本冲突 → 409；状态不变，不得重算或覆盖图。
        if expected_version is not None and expected_version != graph.graph_version:
            correlation_id = ctx.prepared.correlation_id if ctx.prepared else _fallback_correlation(ctx)
            return _error(
                "STATE_TRANSITION_DENIED",
                "请求的图版本与当前图版本不一致。",
                correlation_id,
                reason="GRAPH_VERSION_CONFLICT",
            )
        # 5. T0 不做 DC/SPA；非空序列即为实现错误。
        if graph.dc or graph.spa:
            raise ValueError("T0 的 graph.dc/spa 必须为空；T1/T2 才允许非空")
        # 6. 只读返回。
        body = {
            "task_id": graph.task_id,
            "task_state": graph.task_state,
            "graph_version": graph.graph_version,
            "graph_hash": graph.graph_hash,
            "nodes": [dict(node) for node in graph.nodes],
            "edges": [dict(edge) for edge in graph.edges],
            "dc": [],
            "spa": [],
        }
        return ApiResponse(
            status=200,
            headers={"content-type": "application/json; charset=utf-8"},
            body=_json_bytes(body),
        )

    def _now(self) -> str:
        """由部署层注入时钟；本文件不调用 datetime.now，便于测试冻结时间。"""
        value = self.clock()
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("ClockPort 必须返回 UTC RFC3339 的 `Z` 形式")
        return value


def _path_param(path: str, template: str) -> str:
    """从常量模板取单个路径参数；不匹配按 404 处理，而不是 422。"""
    # 1. 模板只有 `{task_id}` 一个参数；按段切分。
    prefix, suffix = template.split("{task_id}", 1)
    if not path.startswith(prefix) or not path.endswith(suffix):
        raise _NotFound("task not found")
    # 2. 取中段；空串或含 `/` 视为不存在。
    value = path[len(prefix): len(path) - len(suffix) if suffix else None]
    if not value or "/" in value:
        raise _NotFound("task not found")
    # 3. task_id 不做格式推断（ID 是不透明标识）。
    return value


class _NotFound(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _request_correlation(ctx: HttpRequestContext) -> str:
    """统一取 correlation_id：中间件已准备则复用，否则从请求头取/生成。"""
    return ctx.prepared.correlation_id if ctx.prepared else _fallback_correlation(ctx)


def _not_found(detail: str, ctx: HttpRequestContext) -> ApiResponse:
    """404 不套 E.3 码；与既有 app.py 的 `detail` 形态一致。"""
    correlation_id = _request_correlation(ctx)
    body = {"detail": detail, "correlation_id": correlation_id}
    return ApiResponse(
        status=404,
        headers={"content-type": "application/json; charset=utf-8"},
        body=_json_bytes(body),
    )


def _fallback_correlation(ctx: HttpRequestContext) -> str:
    """直调路由时没有中间件；从请求头取，取不到则生成。"""
    from .middleware_idempotency import correlation_id_from_headers

    return correlation_id_from_headers(ctx.headers)


def _expected_version(raw: str | None) -> int | None:
    """解析 `?version=`；None 表示不校验，非法整数 → 422。"""
    # 1. 未提供：不校验版本。
    if raw is None:
        return None
    # 2. 只接受十进制非负整数；不接受 `+1`、空格、浮点。
    if not raw.isdigit():
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message="version 必须是十进制非负整数。", field_path="query.version",
        )
    # 3. 上限不做业务推断；仅防超大整数。
    value = int(raw)
    if value > 2**31 - 1:
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message="version 超出支持范围。", field_path="query.version",
        )
    return value


# 端点 → 拒绝条件 → 状态码/错误码 → 状态是否变化。落地测试逐行断言。
TASK_REJECTIONS: Final[tuple[RejectionRule, ...]] = (
    RejectionRule("POST /api/v1/tasks", "JSON 非法/重复键/NaN/非对象", 422, "SCHEMA_INVALID", None, False, "field_path 指向解析位置"),
    RejectionRule("POST /api/v1/tasks", "TaskSpec 字段/类型/枚举/未知字段", 422, "SCHEMA_INVALID", None, False, "dataset_ref 字符串用固定文案"),
    RejectionRule("POST /api/v1/tasks", "Idempotency-Key 为空/超长/含空白", 422, "SCHEMA_INVALID", "IDEMPOTENCY_KEY_*", False, "header.Idempotency-Key"),
    RejectionRule("POST /api/v1/tasks", "同键不同规范化请求体", 409, "IDEMPOTENCY_CONFLICT", "REQUEST_HASH_MISMATCH", False, "不得覆盖旧任务"),
    RejectionRule("POST /api/v1/tasks", "同键不同路由作用域", 409, "IDEMPOTENCY_CONFLICT", "IDEMPOTENCY_SCOPE_MISMATCH", False, "键不得跨端点复用"),
    RejectionRule("GET /api/v1/tasks/{task_id}", "任务不存在或 ID 形态非法", 404, None, None, False, "detail=task not found"),
    RejectionRule("GET /api/v1/tasks/{task_id}/graph", "任务不存在", 404, None, None, False, "detail=task not found"),
    RejectionRule("GET /api/v1/tasks/{task_id}/graph", "图尚未生成", 404, None, None, False, "detail=graph not generated"),
    RejectionRule("GET /api/v1/tasks/{task_id}/graph", "version 非法", 422, "SCHEMA_INVALID", None, False, "query.version"),
    RejectionRule("GET /api/v1/tasks/{task_id}/graph", "version 与当前图不一致", 409, "STATE_TRANSITION_DENIED", "GRAPH_VERSION_CONFLICT", False, "不得重算/覆盖图"),
)


def assert_task_routes_are_read_only() -> tuple[str, ...]:
    """GET 路由不得依赖写端口；出现写方法即失败。"""
    problems: list[str] = []
    # 1. 只读端口不得有写方法名。
    read_names = set(dir(TaskReaderPort))
    for forbidden in ("create", "update", "transition", "delete", "write"):
        if forbidden in read_names:
            problems.append(f"TaskReaderPort 暴露了写方法 {forbidden}")
    # 2. 创建结果只允许进入 CREATED，且 graph_version 恒为 1。
    if CreationOutcome(CreationKind.CREATED, "task_x", "CREATED", 1, b"{}").state != "CREATED":
        problems.append("创建结果必须为 CREATED")
    # 3. T0 无 DC/SPA：图路由硬编码空序列。
    return tuple(problems)