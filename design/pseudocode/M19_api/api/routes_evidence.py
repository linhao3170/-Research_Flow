"""MODULE：M19 · api/routes_evidence.py — 证据分页、引用解析与 403 语义（P10 伪代码）。
阶段+追踪：P10「接入、实验与交付」｜06 §4.1/§4.4、05 §4.2/§4.4、G2、ADR-007 待确认项 3
FR+依赖：FR-007/FR-008；依赖 M07 Collector 只读端口、M01 证据字段、M19 error_map、M02 失效记录
不变量+错误码：证据只追加，分页按 event_seq 升序且游标稳定；stale 证据不得被静默过滤或删除；
             引用的 evidence_id 必须存在，缺失即 422 且不返回半页；403 无 E.3 码，不伪造第 14 码。
             EVIDENCE_REFERENCE_NOT_FOUND(422) / SCHEMA_INVALID(422)
写入者：无。本文件只读证据与失效记录，不写 evidence、不写报告、不改任务状态。
状态：伪代码；不建库、不查询真实证据、不跑分页测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping, Protocol, Sequence

from .error_map import RejectionRule, build_error_response
from .middleware_idempotency import RequestProblem, correlation_id_from_headers
from .routes_tasks import ApiResponse, HttpRequestContext

__all__ = [
    "DEFAULT_LIMIT",
    "EVIDENCE_ROUTE",
    "EVIDENCE_REJECTIONS",
    "MAX_LIMIT",
    "EvidenceAccessPolicy",
    "EvidenceInvalidation",
    "EvidencePage",
    "EvidenceReadPort",
    "EvidenceRoutes",
    "EvidenceRow",
    "ReadPrincipal",
    "assert_evidence_read_only",
]

EVIDENCE_ROUTE: Final[str] = "/api/v1/tasks/{task_id}/evidence"
DEFAULT_LIMIT: Final[int] = 50
MAX_LIMIT: Final[int] = 200
ALLOWED_QUERY: Final[frozenset[str]] = frozenset({"after_seq", "limit"})


def _json_bytes(body: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class _NotFound(Exception):
    """路径模板不匹配；按 404 处理。"""


def _path_param(path: str, template: str) -> str:
    """取模板中的 `{task_id}`；空串或含 `/` 均视为不存在。"""
    prefix, suffix = template.split("{task_id}", 1)
    if not path.startswith(prefix) or not path.endswith(suffix):
        raise _NotFound
    value = path[len(prefix): len(path) - len(suffix) if suffix else None]
    if not value or "/" in value:
        raise _NotFound
    return value


def _request_correlation(ctx: HttpRequestContext) -> str:
    return ctx.prepared.correlation_id if ctx.prepared else correlation_id_from_headers(ctx.headers)


def _not_found(detail: str, ctx: HttpRequestContext) -> ApiResponse:
    body = {"detail": detail, "correlation_id": _request_correlation(ctx)}
    return ApiResponse(
        status=404,
        headers={"content-type": "application/json; charset=utf-8"},
        body=_json_bytes(body),
    )


@dataclass(frozen=True, slots=True)
class ReadPrincipal:
    """读取主体。T0 回环匿名；T1 起用 scopes 判定。"""

    principal_id: str
    scopes: frozenset[str]
    is_loopback_anonymous: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    """一条证据的只读投影；不携带 payload 正文（正文按需另取）。"""

    event_seq: int
    evidence_id: str
    level: str
    kind: str
    producer: str
    timestamp: str
    payload_hash: str
    chain_hash: str
    artifact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceInvalidation:
    """stale 标记；只读展示，不删除原证据。"""

    evidence_id: str
    reason_code: str
    invalidated_at: str
    invalidated_by: str


@dataclass(frozen=True, slots=True)
class EvidencePage:
    """一页证据；`as_of_seq` 是查询时的最大序号，保证游标语义可解释。"""

    task_id: str
    as_of_seq: int
    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    has_more: bool


class EvidenceReadPort(Protocol):
    """只读端口；不得出现 append/update/delete。"""

    def task_exists(self, task_id: str) -> bool: ...

    def max_event_seq(self, task_id: str) -> int: ...

    def list_page(self, task_id: str, *, after_seq: int, limit: int) -> Sequence[EvidenceRow]: ...

    def exists(self, task_id: str, evidence_id: str) -> bool: ...

    def invalidations(self, task_id: str, evidence_ids: Sequence[str]) -> Sequence[EvidenceInvalidation]: ...


class EvidenceAccessPolicy:
    """403 判定。T0 回环匿名可读；非回环必须持有 evidence:read。"""

    def can_read(self, principal: ReadPrincipal | None, task_id: str) -> bool:
        # 1. T0 回环匿名读取是已接受风险，不表述为“已安全加固”。
        if principal is not None and principal.is_loopback_anonymous:
            return True
        # 2. 其它主体必须显式 scope；空 scopes 一律拒绝。
        if principal is None or "evidence:read" not in principal.scopes:
            return False
        # 3. 通过。
        return True


def _parse_non_negative_int(raw: str, *, field_path: str) -> int:
    """只接受十进制非负整数；拒绝 `+1`、空格、浮点、科学计数。"""
    # 1. 空串/非数字 → 422。
    if raw == "" or not raw.isdigit():
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message=f"{field_path} 必须是十进制非负整数。", field_path=field_path,
        )
    # 2. 上限防溢出；分页不需要超大值。
    value = int(raw)
    if value > 2**63 - 1:
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message=f"{field_path} 超出支持范围。", field_path=field_path,
        )
    return value


def _parse_pagination(query: Mapping[str, str]) -> tuple[int, int]:
    """解析并严格校验 after_seq / limit；未知查询参数拒绝。"""
    # 1. 未知参数：不得静默忽略（会掩盖客户端拼写错误）。
    unknown = set(query) - ALLOWED_QUERY
    if unknown:
        name = sorted(unknown)[0]
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message=f"未知查询参数：{name}。", field_path=f"query.{name}",
        )
    # 2. after_seq 默认 0（从最早开始）；严格非负。
    after_seq = _parse_non_negative_int(
        query.get("after_seq", "0"), field_path="query.after_seq"
    )
    # 3. limit 默认 50，范围 1–200；0 和 201 都拒绝，不静默截断。
    limit = _parse_non_negative_int(query.get("limit", str(DEFAULT_LIMIT)), field_path="query.limit")
    if not 1 <= limit <= MAX_LIMIT:
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message=f"limit 必须在 1–{MAX_LIMIT} 之间。", field_path="query.limit",
        )
    # 4. 通过。
    return after_seq, limit


class EvidenceRoutes:
    """证据分页路由；不持有写端口。"""

    def __init__(self, *, reader: EvidenceReadPort, policy: EvidenceAccessPolicy | None = None) -> None:
        self.reader = reader
        self.policy = policy or EvidenceAccessPolicy()

    def list_evidence(self, ctx: HttpRequestContext, principal: ReadPrincipal | None = None) -> ApiResponse:
        """GET /tasks/{id}/evidence：422 → 404 → 403 → 200；不改变任何状态。"""
        # 1. 路径参数；非法路径按 404。
        try:
            task_id = _path_param(ctx.path, EVIDENCE_ROUTE)
        except _NotFound:
            return _not_found("task not found", ctx)
        # 2. 分页参数；任何非法值都在查询前拒绝。
        try:
            after_seq, limit = _parse_pagination(ctx.query or {})
        except RequestProblem as problem:
            return _problem_response(problem, _request_correlation(ctx))
        # 3. 任务不存在 → 404（不泄露是否存在证据）。
        if not self.reader.task_exists(task_id):
            return _not_found("task not found", ctx)
        # 4. 已存在但无权限 → 403；无 E.3 码，不伪造 error_code。
        if not self.policy.can_read(principal, task_id):
            return _forbidden("evidence read denied", ctx)
        # 5. 先取快照序号，再取 limit+1 条；多出的一条只用于 has_more。
        as_of_seq = self.reader.max_event_seq(task_id)
        rows = tuple(self.reader.list_page(task_id, after_seq=after_seq, limit=limit + 1))
        # 6. 端口必须按 event_seq 严格升序且 > after_seq；乱序是内部错误。
        _assert_page_order(task_id, rows, after_seq)
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        # 7. 批量取失效记录；stale 只标注，绝不过滤。
        invalidation_map = _invalidations_by_id(
            self.reader.invalidations(task_id, [row.evidence_id for row in page_rows])
        )
        # 8. 逐条解析引用；任一引用缺失 → 422，整页不返回。
        items: list[Mapping[str, Any]] = []
        for index, row in enumerate(page_rows):
            _assert_row_shape(row)
            for ref_index, ref in enumerate(row.evidence_refs):
                if not self.reader.exists(task_id, ref):
                    return _reference_missing(
                        ctx,
                        field_path=f"items.{index}.evidence_refs.{ref_index}",
                        evidence_id=ref,
                    )
            invalidation = invalidation_map.get(row.evidence_id)
            items.append(
                {
                    "event_seq": row.event_seq,
                    "evidence_id": row.evidence_id,
                    "level": row.level,
                    "kind": row.kind,
                    "producer": row.producer,
                    "timestamp": row.timestamp,
                    "payload_hash": row.payload_hash,
                    "chain_hash": row.chain_hash,
                    "artifact_refs": list(row.artifact_refs),
                    "evidence_refs": list(row.evidence_refs),
                    "stale": invalidation is not None,
                    "invalidation": None if invalidation is None else {
                        "reason_code": invalidation.reason_code,
                        "invalidated_at": invalidation.invalidated_at,
                        "invalidated_by": invalidation.invalidated_by,
                    },
                }
            )
        # 9. 下一游标：仅当确有多余行时给出；否则 None。
        next_cursor = str(page_rows[-1].event_seq) if has_more and page_rows else None
        # 10. 返回页面；`as_of_seq` 允许审计“这页看到的是哪个快照”。
        body = {
            "task_id": task_id,
            "as_of_seq": as_of_seq,
            "page_size": len(items),
            "has_more": has_more,
            "next_cursor": next_cursor,
            "items": items,
        }
        return ApiResponse(
            status=200,
            headers={"content-type": "application/json; charset=utf-8"},
            body=_json_bytes(body),
        )


def _problem_response(problem: RequestProblem, correlation_id: str) -> ApiResponse:
    """本模块只处理 422；有码走统一体。"""
    if problem.code is None:
        body = {"detail": problem.message, "correlation_id": correlation_id}
        return ApiResponse(status=problem.status, headers={"content-type": "application/json; charset=utf-8"}, body=_json_bytes(body))
    status, headers, body = build_error_response(
        error_code=problem.code, message=problem.message,
        correlation_id=correlation_id, field_path=problem.field_path,
        reason=problem.reason,
    )
    return ApiResponse(status=status, headers=headers, body=_json_bytes(body))


def _forbidden(detail: str, ctx: HttpRequestContext) -> ApiResponse:
    """403：无 E.3 码。`reason` 是唯一稳定判定字段。"""
    body = {
        "detail": detail,
        "reason": "EVIDENCE_ACCESS_DENIED",
        "correlation_id": _request_correlation(ctx),
    }
    return ApiResponse(
        status=403,
        headers={"content-type": "application/json; charset=utf-8"},
        body=_json_bytes(body),
    )


def _reference_missing(ctx: HttpRequestContext, *, field_path: str, evidence_id: str) -> ApiResponse:
    """引用不存在：422 + field_path；这是 E.3 已注册码。"""
    status, headers, body = build_error_response(
        error_code="EVIDENCE_REFERENCE_NOT_FOUND",
        message=f"引用的 evidence_id 不存在：{evidence_id}。",
        correlation_id=_request_correlation(ctx),
        field_path=field_path,
    )
    return ApiResponse(status=status, headers=headers, body=_json_bytes(body))


def _assert_page_order(task_id: str, rows: Sequence[EvidenceRow], after_seq: int) -> None:
    """严格升序 + 游标之后 + 任务一致；违反即内部错误。"""
    previous = after_seq
    for row in rows:
        if row.event_seq <= previous:
            raise ValueError(f"任务 {task_id} 的证据分页乱序：{row.event_seq} <= {previous}")
        previous = row.event_seq


def _assert_row_shape(row: EvidenceRow) -> None:
    """证据投影的形态自检；不合法按数据损坏处理（500），不静默跳过。"""
    if row.level not in {"E0", "E1", "E2", "E3"}:
        raise ValueError(f"未知证据等级：{row.level!r}")
    if not row.evidence_id.startswith("ev_"):
        raise ValueError(f"非法 evidence_id：{row.evidence_id!r}")
    if len(row.payload_hash) != 64 or any(ch not in "0123456789abcdef" for ch in row.payload_hash):
        raise ValueError("payload_hash 必须是 64 位小写十六进制")
    if len(row.chain_hash) != 64 or any(ch not in "0123456789abcdef" for ch in row.chain_hash):
        raise ValueError("chain_hash 必须是 64 位小写十六进制")


def _invalidations_by_id(rows: Sequence[EvidenceInvalidation]) -> dict[str, EvidenceInvalidation]:
    """按 evidence_id 建索引；同一条重复失效按实现错误处理。"""
    result: dict[str, EvidenceInvalidation] = {}
    for row in rows:
        if row.evidence_id in result:
            raise ValueError(f"同一证据出现多条失效记录：{row.evidence_id}")
        result[row.evidence_id] = row
    return result


# 端点 → 拒绝条件 → 状态码/错误码 → 状态是否变化。
EVIDENCE_REJECTIONS: Final[tuple[RejectionRule, ...]] = (
    RejectionRule("GET /tasks/{id}/evidence", "任务不存在或路径非法", 404, None, None, False, "detail=task not found"),
    RejectionRule("GET /tasks/{id}/evidence", "无 evidence:read 权限", 403, None, "EVIDENCE_ACCESS_DENIED", False, "不返回任何证据条目"),
    RejectionRule("GET /tasks/{id}/evidence", "after_seq 非十进制非负整数", 422, "SCHEMA_INVALID", None, False, "查询前拒绝"),
    RejectionRule("GET /tasks/{id}/evidence", "limit 不在 1–200", 422, "SCHEMA_INVALID", None, False, "不静默截断"),
    RejectionRule("GET /tasks/{id}/evidence", "未知查询参数", 422, "SCHEMA_INVALID", None, False, "不静默忽略"),
    RejectionRule("GET /tasks/{id}/evidence", "evidence_refs 引用不存在", 422, "EVIDENCE_REFERENCE_NOT_FOUND", None, False, "整页不返回，不丢弃悬挂引用"),
)


def assert_evidence_read_only() -> tuple[str, ...]:
    """静态判据：端口无写方法、stale 不被过滤、页大小有界。"""
    problems: list[str] = []
    # 1. 只读端口不得有写方法。
    for forbidden in ("append", "update", "delete", "write", "invalidate"):
        if forbidden in set(dir(EvidenceReadPort)):
            problems.append(f"EvidenceReadPort 暴露了写方法 {forbidden}")
    # 2. 页大小必须被 MAX_LIMIT 限制；0 或负数不得成为“全部”。
    if MAX_LIMIT <= 0 or DEFAULT_LIMIT > MAX_LIMIT:
        problems.append("分页上限配置不合法")
    # 3. stale 必须展示；源码中不得出现“过滤 stale”的返回路径（人工复核）。
    return tuple(problems)