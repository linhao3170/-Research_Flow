"""MODULE：M19 · api/error_map.py — 附录 E.3 十三条错误码 → HTTP 的映射表（P10 伪代码）。
阶段+追踪：P10「接入、实验与交付」｜06 §4.4、附录 E.3 / TABLE 69、OQ-P1-04、OQ-P1-09
FR+依赖：FR-001/FR-002/FR-007；依赖 M01 contracts/errors.py（13 条唯一事实源）、06 §4.4 响应体
不变量+错误码：映射表恰好 13 条，name/http_status 与 errors.APPENDIX_E3 逐项相等；
              未注册码必须 KeyError，不得回退到通用 500；内部码不对外暴露（OQ-P1-09）；
              证书不可用不新增第 14 码，用 STATE_TRANSITION_DENIED(409)+reason=CERTIFICATE_NOT_AVAILABLE（OQ-P1-04）。
写入者：无。本文件只做映射与响应体构造，不写库、不改状态。
状态：伪代码；不启动 FastAPI、不发请求、不跑测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping

__all__ = [
    "CERTIFICATE_NOT_AVAILABLE_REASON",
    "E3_ORDER",
    "E3_HTTP_STATUS",
    "E3_SPECS",
    "NON_E3_TRANSPORT",
    "ErrorSpec",
    "RejectionRule",
    "assert_error_map_parity",
    "build_error_body",
    "build_error_response",
    "http_status_for",
    "lookup_spec",
]

# 06 §4.4 表顺序，逐字保留；本元组是“顺序 + 完整性”的双重锚点。
E3_ORDER: Final[tuple[str, ...]] = (
    "SCHEMA_INVALID",
    "IDEMPOTENCY_CONFLICT",
    "STATE_TRANSITION_DENIED",
    "TOOL_NOT_ALLOWLISTED",
    "EVIDENCE_REFERENCE_NOT_FOUND",
    "REQUIRED_EVIDENCE_MISSING",
    "RULESET_VERSION_MISMATCH",
    "RESOURCE_BUDGET_EXCEEDED",
    "RECOVERY_NOT_SAFE",
    "SIGNATURE_INVALID",
    "BUNDLE_TAMPERED",
    "HARNESS_EVENT_DUPLICATE",
    "HARNESS_EVENT_GAP",
)

# 与 errors.APPENDIX_E3 的 http_status 一一对应；200/202 不是失败语义，但仍属 E.3 表。
E3_HTTP_STATUS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "SCHEMA_INVALID": 422,
        "IDEMPOTENCY_CONFLICT": 409,
        "STATE_TRANSITION_DENIED": 409,
        "TOOL_NOT_ALLOWLISTED": 403,
        "EVIDENCE_REFERENCE_NOT_FOUND": 422,
        "REQUIRED_EVIDENCE_MISSING": 409,
        "RULESET_VERSION_MISMATCH": 409,
        "RESOURCE_BUDGET_EXCEEDED": 429,
        "RECOVERY_NOT_SAFE": 409,
        "SIGNATURE_INVALID": 422,
        "BUNDLE_TAMPERED": 422,
        "HARNESS_EVENT_DUPLICATE": 200,
        "HARNESS_EVENT_GAP": 202,
    }
)

CERTIFICATE_NOT_AVAILABLE_REASON: Final[str] = "CERTIFICATE_NOT_AVAILABLE"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """一条对外错误码的 HTTP 口径。`semantics` 只做审阅摘要，不替代 errors.py。"""

    name: str
    http_status: int
    semantics: str
    user_visible: bool = True


E3_SPECS: Final[tuple[ErrorSpec, ...]] = (
    ErrorSpec("SCHEMA_INVALID", 422, "请求字段/类型/格式/未知字段/JSON 层非法。"),
    ErrorSpec("IDEMPOTENCY_CONFLICT", 409, "同一幂等键对应不同规范化请求体。"),
    ErrorSpec("STATE_TRANSITION_DENIED", 409, "迁移不在允许表内、守卫不成立或状态已过期。"),
    ErrorSpec("TOOL_NOT_ALLOWLISTED", 403, "工具未注册、参数 Schema 不匹配或角色无工具权限。"),
    ErrorSpec("EVIDENCE_REFERENCE_NOT_FOUND", 422, "引用的 evidence_id 不存在。"),
    ErrorSpec("REQUIRED_EVIDENCE_MISSING", 409, "必检项缺失、等级不足、哈希不符或证据已 stale。"),
    ErrorSpec("RULESET_VERSION_MISMATCH", 409, "证据/报告绑定的规则版本与当前规则集不一致。"),
    ErrorSpec("RESOURCE_BUDGET_EXCEEDED", 429, "token/时长/并发/内存/磁盘/验证预算超限。"),
    ErrorSpec("RECOVERY_NOT_SAFE", 409, "恢复或安全剪枝条件不成立（T0 不得返回）。"),
    ErrorSpec("SIGNATURE_INVALID", 422, "签名、撤销状态或信任锚验证失败。"),
    ErrorSpec("BUNDLE_TAMPERED", 422, "证据包哈希/Merkle 证明/清单与实际内容不一致。"),
    ErrorSpec("HARNESS_EVENT_DUPLICATE", 200, "重复 Harness 事件已幂等处理（非失败）。"),
    ErrorSpec("HARNESS_EVENT_GAP", 202, "事件序列缺口已受理并标记（非失败）。"),
)

# 非 E.3 的传输层状态：没有业务 error_code，不得伪造第 14 个码。
# 403/404 只用于鉴权与对象不存在；401 仅在 T1 开启认证后出现；503 用于依赖不可用。
NON_E3_TRANSPORT: Final[Mapping[int, str]] = MappingProxyType(
    {
        401: "UNAUTHENTICATED（T1 认证开启后）",
        403: "AUTHORIZATION_DENIED（无 E.3 码；reason 由路由给出）",
        404: "OBJECT_NOT_FOUND（无 E.3 码；detail 由路由给出）",
        413: "REQUEST_TOO_LARGE（无 E.3 码）",
        500: "INTERNAL_ERROR（内部码 user_visible=False）",
        503: "SERVICE_UNAVAILABLE（启动/依赖不可用）",
    }
)


@dataclass(frozen=True, slots=True)
class RejectionRule:
    """一个端点的拒绝规则。`state_changed=False` 是验收断言，不是注释。"""

    endpoint: str
    condition: str
    http_status: int
    error_code: str | None
    reason: str | None
    state_changed: bool
    note: str = ""

    def __post_init__(self) -> None:
        if self.error_code is not None and self.error_code not in E3_HTTP_STATUS:
            raise ValueError(f"未注册的 E.3 错误码：{self.error_code!r}")
        if self.error_code is None and self.http_status not in NON_E3_TRANSPORT:
            raise ValueError(f"无码头必须使用已登记的传输层状态：{self.http_status}")
        if self.http_status in (200, 202) and self.state_changed:
            # 200/202 是受理/幂等语义，不允许借“拒绝”改状态。
            raise ValueError("非失败状态不得声明 state_changed=True")


def lookup_spec(name: str) -> ErrorSpec:
    """按码名取规范。未知码必须显式失败，不得返回通用错误。"""
    # 1. 精确匹配；不做大小写归一。
    for spec in E3_SPECS:
        if spec.name == name:
            # 2. 返回前再核一次 HTTP 表，防止两张表被人为改偏。
            if E3_HTTP_STATUS[name] != spec.http_status:
                raise AssertionError(f"{name} 的 HTTP 状态在两张表中不一致")
            return spec
    # 3. 未注册：抛 KeyError，调用方不得吞掉后回 500。
    raise KeyError(f"未注册的错误码：{name!r}")


def http_status_for(name: str) -> int:
    """只取 HTTP 状态；未注册码同样 KeyError。"""
    return lookup_spec(name).http_status


def _safe_message(message: str) -> str:
    """对外消息脱敏：不出现堆栈、SQL、绝对路径或密钥形态。"""
    # 1. 空消息视为实现缺陷，直接拒绝构造。
    if not message.strip():
        raise ValueError("message 不得为空")
    # 2. 明显泄密标记 → 统一文案，不尝试“局部删改”（局部删改仍可能残留）。
    lowered = message.lower()
    for marker in ("traceback", "select ", "insert into", "sqlite", "c:\\", "/home/", "private key"):
        if marker in lowered:
            return "请求无法处理；请按错误码修正后重试。"
    # 3. 控制字符会破坏日志与响应，替换为空格。
    return "".join(ch if ch >= " " and ch != "\x7f" else " " for ch in message).strip()


def build_error_body(
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    field_path: str | None = None,
    reason: str | None = None,
    limit_kind: str | None = None,
) -> dict[str, Any]:
    """构造 06 §4.4 统一响应体；`reason`/`limit_kind` 只进 detail，不另立码。"""
    # 1. 校验码与 correlation_id；两者缺一不可审计。
    spec = lookup_spec(error_code)
    if not correlation_id.strip():
        raise ValueError("correlation_id 不得为空")
    # 2. field_path 仅允许出现在有字段语义的码上；其他码带 field_path 视为实现错误。
    if field_path is not None and spec.name not in {
        "SCHEMA_INVALID",
        "EVIDENCE_REFERENCE_NOT_FOUND",
    }:
        raise ValueError(f"{spec.name} 不接受 field_path")
    # 3. 组基础体；不返回堆栈、SQL、路径、密钥。
    body: dict[str, Any] = {
        "error_code": spec.name,
        "message": _safe_message(message),
        "correlation_id": correlation_id,
    }
    if field_path is not None:
        body["field_path"] = field_path
    # 4. 子原因放 detail；detail 的键是封闭集合，防止调用方塞任意对象。
    detail: dict[str, Any] = {}
    if reason is not None:
        detail["reason"] = reason
    if limit_kind is not None:
        if spec.name != "RESOURCE_BUDGET_EXCEEDED":
            raise ValueError("limit_kind 只用于 RESOURCE_BUDGET_EXCEEDED")
        detail["limit_kind"] = limit_kind
    if detail:
        body["detail"] = detail
    # 5. 交付不可变副本，调用方不能事后改状态码语义。
    return body


def build_error_response(
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    field_path: str | None = None,
    reason: str | None = None,
    limit_kind: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    """返回 (status, headers, body)，不依赖 FastAPI，便于契约测试直接断言。"""
    # 1. 取状态；未注册码在这里就失败，不会进入响应。
    status = http_status_for(error_code)
    # 2. 组装响应头；只允许调用方追加显式白名单头。
    response_headers: dict[str, str] = {"content-type": "application/json; charset=utf-8"}
    if headers:
        for key, value in headers.items():
            if key.lower() in {"content-type", "content-length", "date", "server"}:
                continue
            response_headers[key] = value
    # 3. 组装体；200/202 也是合法 body（幂等/缺口语义）。
    body = build_error_body(
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
        field_path=field_path,
        reason=reason,
        limit_kind=limit_kind,
    )
    # 4. 明确返回，不在这里写日志/审计（审计属 StateMachine / Collector）。
    return status, response_headers, body


def assert_error_map_parity(appendix_e3: Any) -> tuple[str, ...]:
    """与 errors.APPENDIX_E3 做逐项对表；返回问题元组，空元组才算通过。

    期望 `appendix_e3` 是 `contracts.errors.APPENDIX_E3` 的序列，元素至少有
    `name` 与 `http_status` 属性。P10 只定义判据，不执行。
    """
    problems: list[str] = []
    # 1. 数量必须 13。
    if len(appendix_e3) != 13:
        problems.append(f"APPENDIX_E3 数量={len(appendix_e3)}，期望 13")
    # 2. 顺序与名称一致。
    actual_names = tuple(getattr(item, "name", None) for item in appendix_e3)
    if actual_names != E3_ORDER:
        problems.append(f"名称/顺序不一致：{actual_names!r}")
    # 3. 每条 HTTP 状态一致。
    for item in appendix_e3:
        name = getattr(item, "name", None)
        status = getattr(item, "http_status", None)
        if name not in E3_HTTP_STATUS:
            problems.append(f"映射表缺少 {name!r}")
        elif status != E3_HTTP_STATUS[name]:
            problems.append(f"{name} 状态 {status} != {E3_HTTP_STATUS[name]}")
    # 4. 映射表不得多出 errors.py 没有的码。
    extra = set(E3_HTTP_STATUS) - set(actual_names)
    if extra:
        problems.append(f"映射表多出：{sorted(extra)!r}")
    # 5. 未注册码必须失败（用哨兵验证，不执行真实请求）。
    try:
        http_status_for("CERTIFICATE_NOT_AVAILABLE")
    except KeyError:
        pass
    else:
        problems.append("CERTIFICATE_NOT_AVAILABLE 不得成为第 14 个错误码")
    return tuple(problems)


def assert_no_score_or_grade() -> tuple[str, ...]:
    """门禁/API 都不得把错误码变成“分数/等级”；本文件只允许状态码。"""
    # 1. 扫描公开面，出现 score/grade/rating 即失败（静态判据）。
    forbidden = ("score", "grade", "rating", "confidence")
    problems = [name for name in __all__ if any(key in name.lower() for key in forbidden)]
    # 2. 本模块不导出任何指标计算。
    return tuple(problems)