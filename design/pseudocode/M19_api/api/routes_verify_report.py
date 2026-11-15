"""MODULE：M19 · api/routes_verify_report.py — 验证触发、报告与凭证读取（P10 伪代码）。
阶段+追踪：P10「接入、实验与交付」｜06 §4.1/§4.3/§4.4、05 §6、OQ-P1-04、OQ-API-3、OQ-P5-03
FR+依赖：FR-007/FR-008/FR-009；依赖 M08 Gate、M09–M12 Verifier、M02 StateMachine、M19 error_map
不变量+错误码：API 只触发验证，不裁决、不写报告、不签凭证；非 VERIFIED 一律不返回凭证；
              证书不可用用 STATE_TRANSITION_DENIED(409)+reason=CERTIFICATE_NOT_AVAILABLE，不新增第 14 码；
              验签必须用包外信任锚，不得信任包内公钥；拒绝时任务状态不因读取而改变。
              SCHEMA_INVALID(422) / STATE_TRANSITION_DENIED(409) / RESOURCE_BUDGET_EXCEEDED(429) /
              SIGNATURE_INVALID(422) / REQUIRED_EVIDENCE_MISSING(409) / RULESET_VERSION_MISMATCH(409)
写入者：无。报告/凭证由 Verifier 写；本文件只读，验证触发经 StateMachine 与 Verifier 端口。
状态：伪代码；不执行 L1/L2/L3、不验真实签名、不发凭证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping, Protocol, Sequence

from .error_map import CERTIFICATE_NOT_AVAILABLE_REASON, RejectionRule, build_error_response
from .middleware_idempotency import RequestProblem, correlation_id_from_headers
from .routes_tasks import ApiResponse, HttpRequestContext

__all__ = [
    "CERTIFICATE_ROUTE",
    "REPORT_ROUTE",
    "VERIFY_ROUTE",
    "CertificateRecord",
    "ReportRecord",
    "VerifyAttempt",
    "VerifyRequest",
    "VerifyRoutes",
    "VERIFY_REJECTIONS",
    "assert_certificate_gate",
    "parse_verify_request",
]

VERIFY_ROUTE: Final[str] = "/api/v1/tasks/{task_id}/verify"
REPORT_ROUTE: Final[str] = "/api/v1/tasks/{task_id}/report"
CERTIFICATE_ROUTE: Final[str] = "/api/v1/tasks/{task_id}/certificate"
ALLOWED_CHECKS: Final[frozenset[str]] = frozenset({"L1", "L2", "L3"})
ALLOWED_BODY_KEYS: Final[frozenset[str]] = frozenset({"mode", "requested_checks"})


def _json_bytes(body: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class _NotFound(Exception):
    """路径模板不匹配；按 404 处理。"""


def _path_param(path: str, template: str) -> str:
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


def _problem_response(problem: RequestProblem, correlation_id: str) -> ApiResponse:
    if problem.code is None:
        body = {"detail": problem.message, "correlation_id": correlation_id}
        return ApiResponse(status=problem.status, headers={"content-type": "application/json; charset=utf-8"}, body=_json_bytes(body))
    status, headers, body = build_error_response(
        error_code=problem.code, message=problem.message,
        correlation_id=correlation_id, field_path=problem.field_path,
        reason=problem.reason,
    )
    return ApiResponse(status=status, headers=headers, body=_json_bytes(body))


def _error(
    code: str,
    message: str,
    correlation_id: str,
    *,
    reason: str | None = None,
    field_path: str | None = None,
    limit_kind: str | None = None,
) -> ApiResponse:
    status, headers, body = build_error_response(
        error_code=code, message=message, correlation_id=correlation_id,
        reason=reason, field_path=field_path, limit_kind=limit_kind,
    )
    return ApiResponse(status=status, headers=headers, body=_json_bytes(body))


@dataclass(frozen=True, slots=True)
class VerifyRequest:
    """验证请求。T0 只支持 mode=full；检查项只允许 L1/L2/L3 且不得重复。"""

    mode: str
    requested_checks: tuple[str, ...]


def parse_verify_request(raw_body: bytes) -> VerifyRequest:
    """strict JSON + 显式字段校验；任何错误都是 422 SCHEMA_INVALID。"""
    # 1. UTF-8 解码。
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message="请求体必须是 UTF-8 编码的 JSON。", field_path="$",
        )
    # 2. strict 解析：重复键/NaN/Infinity 在解析层拒绝。
    from researchflow.contracts.parsing import ContractJSONError, loads_strict

    try:
        payload = loads_strict(text)
    except ContractJSONError as exc:
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message=str(getattr(exc, "message", "JSON 解析失败")),
            field_path=str(getattr(exc, "pointer", "$")),
        ) from exc
    # 3. 顶层对象与未知字段。
    if not isinstance(payload, dict):
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message="请求体必须是 JSON 对象。", field_path="$",
        )
    unknown = set(payload) - ALLOWED_BODY_KEYS
    if unknown:
        name = sorted(unknown)[0]
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message=f"未知字段：{name}。", field_path=name,
        )
    # 4. mode：T0 只支持 full（OQ-API-3 未关闭，不扩取值）。
    mode = payload.get("mode", "full")
    if mode != "full":
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message="mode 只支持 full。", field_path="mode",
        )
    # 5. requested_checks：缺省为 L1/L2/L3；必须是字符串列表、非空、无重复、取值合法。
    raw_checks = payload.get("requested_checks", ["L1", "L2", "L3"])
    if not isinstance(raw_checks, list) or not raw_checks:
        raise RequestProblem(
            status=422, code="SCHEMA_INVALID",
            message="requested_checks 必须是非空数组。", field_path="requested_checks",
        )
    checks: list[str] = []
    for index, item in enumerate(raw_checks):
        if not isinstance(item, str) or item not in ALLOWED_CHECKS:
            raise RequestProblem(
                status=422, code="SCHEMA_INVALID",
                message=f"不支持的检查项：{item!r}。", field_path=f"requested_checks.{index}",
            )
        if item in checks:
            raise RequestProblem(
                status=422, code="SCHEMA_INVALID",
                message=f"检查项重复：{item}。", field_path=f"requested_checks.{index}",
            )
        checks.append(item)
    # 6. 顺序按 L1→L2→L3 归一；不改变集合语义。
    ordered = tuple(sorted(checks, key=("L1", "L2", "L3").index))
    return VerifyRequest(mode="full", requested_checks=ordered)


@dataclass(frozen=True, slots=True)
class VerifyAttempt:
    """验证端口的结果。`state_changed` 必须由实现按真实迁移填写。"""

    kind: str                 # ACCEPTED / REPORT_EXISTS / IN_PROGRESS / REFUSED
    report_id: str | None
    final_state: str | None
    gaps: tuple[Mapping[str, Any], ...]
    reason: str | None
    state_changed: bool


@dataclass(frozen=True, slots=True)
class ReportRecord:
    """报告只读记录；非 VERIFIED 的 sidecar 允许 unsigned=True。"""

    report_id: str
    task_id: str
    final_state: str
    ruleset_hash: str
    evidence_root: str
    tree_size: int
    issued_at: str
    signed: bool
    signature: str | None
    gaps: tuple[Mapping[str, Any], ...]
    attribution: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CertificateRecord:
    """凭证只读记录；字段与 05 §6/D.4 对齐，不在此重定义契约。"""

    certificate_id: str
    report_id: str
    task_id: str
    issued_at: str
    signature: str
    key_fingerprint: str
    merkle_root: str
    tree_size: int
    ruleset_hash: str


class VerificationService(Protocol):
    """验证编排端口；内部必须经 StateMachine 迁移并调用独立 Verifier。"""

    def request_verify(
        self, *, task_id: str, request: VerifyRequest, correlation_id: str
    ) -> VerifyAttempt: ...


class ReportReaderPort(Protocol):
    """只读端口；不得暴露 issue/sign/transition。"""

    def task_exists(self, task_id: str) -> bool: ...

    def get_report(self, task_id: str) -> ReportRecord | None: ...

    def get_certificate(self, task_id: str) -> CertificateRecord | None: ...


class ReportVerifierPort(Protocol):
    """验签端口；必须使用包外信任锚，不得读取包内公钥作为锚。"""

    def verify_report(self, report: ReportRecord) -> None: ...

    def verify_certificate(self, certificate: CertificateRecord, report: ReportRecord) -> None: ...


class VerifyRoutes:
    """验证/报告/凭证三条路由。"""

    def __init__(
        self,
        *,
        service: VerificationService,
        reader: ReportReaderPort,
        verifier: ReportVerifierPort,
    ) -> None:
        self.service = service
        self.reader = reader
        self.verifier = verifier

    def post_verify(self, ctx: HttpRequestContext) -> ApiResponse:
        """POST /tasks/{id}/verify：422 → 404 → 409/429 → 200。"""
        # 1. 路径参数。
        try:
            task_id = _path_param(ctx.path, VERIFY_ROUTE)
        except _NotFound:
            return _not_found("task not found", ctx)
        # 2. 请求体校验；422 优先于状态判断。
        try:
            request = parse_verify_request(ctx.raw_body)
        except RequestProblem as problem:
            return _problem_response(problem, _request_correlation(ctx))
        # 3. 任务不存在 → 404。
        if not self.reader.task_exists(task_id):
            return _not_found("task not found", ctx)
        # 4. 交给验证编排；API 不自行改状态、不自行跑 L3。
        attempt = self.service.request_verify(
            task_id=task_id, request=request, correlation_id=_request_correlation(ctx)
        )
        # 5. 拒绝面：每种原因对应固定码；拒绝时状态不变。
        if attempt.kind == "IN_PROGRESS":
            return _error(
                "STATE_TRANSITION_DENIED",
                "该任务已有验证在进行中。",
                _request_correlation(ctx),
                reason="VERIFICATION_IN_PROGRESS",
            )
        if attempt.kind == "REFUSED":
            if attempt.reason == "VERIFY_BUDGET_EXCEEDED":
                return _error(
                    "RESOURCE_BUDGET_EXCEEDED",
                    "验证预算不足，任务未进入 VERIFYING。",
                    _request_correlation(ctx),
                    reason="VERIFY_BUDGET_EXCEEDED",
                    limit_kind="VERIFY_BUDGET",
                )
            if attempt.reason in {"TASK_NOT_RUNNING", "VERIFICATION_IN_PROGRESS", "STATE_DENIED"}:
                return _error(
                    "STATE_TRANSITION_DENIED",
                    "当前任务状态不允许发起验证。",
                    _request_correlation(ctx),
                    reason=attempt.reason,
                )
            if attempt.reason == "REQUIRED_EVIDENCE_MISSING":
                return _error(
                    "REQUIRED_EVIDENCE_MISSING",
                    "必检证据不完整，验证未启动。",
                    _request_correlation(ctx),
                    reason=attempt.reason,
                )
            if attempt.reason == "RULESET_VERSION_MISMATCH":
                return _error(
                    "RULESET_VERSION_MISMATCH",
                    "规则版本不一致，验证未启动。",
                    _request_correlation(ctx),
                    reason=attempt.reason,
                )
            # 未登记原因按内部错误处理，不得猜一个码。
            raise ValueError(f"验证端口返回未登记原因：{attempt.reason!r}")
        # 6. 已受理/已有报告：200；`final_state` 由 Verifier 给，不由 API 推断。
        if attempt.kind in {"ACCEPTED", "REPORT_EXISTS"}:
            if attempt.report_id is None or attempt.final_state is None:
                raise ValueError("验证结果缺 report_id/final_state")
            body = {
                "report_id": attempt.report_id,
                "final_state": attempt.final_state,
                "gaps": [dict(gap) for gap in attempt.gaps],
                "state_changed": attempt.state_changed,
            }
            return ApiResponse(
                status=200,
                headers={"content-type": "application/json; charset=utf-8"},
                body=_json_bytes(body),
            )
        # 7. 未知结果：500，不得返回成功。
        raise ValueError(f"验证端口返回未知结果：{attempt.kind!r}")

    def get_report(self, ctx: HttpRequestContext) -> ApiResponse:
        """GET /tasks/{id}/report：404 / 422 验签失败 / 200；不改状态。"""
        # 1. 路径参数。
        try:
            task_id = _path_param(ctx.path, REPORT_ROUTE)
        except _NotFound:
            return _not_found("task not found", ctx)
        # 2. 任务/报告不存在 → 404。
        if not self.reader.task_exists(task_id):
            return _not_found("task not found", ctx)
        report = self.reader.get_report(task_id)
        if report is None:
            return _not_found("report not generated", ctx)
        # 3. VERIFIED 报告必须已签名；未签名按内部完整性错误处理。
        if report.final_state == "VERIFIED" and not report.signed:
            raise ValueError("VERIFIED 报告必须带签名；未签名报告不得对外")
        # 4. 已签名报告先验签；失败 422，不返回任何报告字段。
        if report.signed:
            try:
                self.verifier.verify_report(report)
            except Exception as exc:
                if exc.__class__.__name__ not in {"SignatureInvalid", "TrustAnchorMissing"}:
                    raise
                return _error(
                    "SIGNATURE_INVALID",
                    "报告签名或信任锚验证失败。",
                    _request_correlation(ctx),
                    reason="REPORT_SIGNATURE_INVALID",
                )
        # 5. 只读输出；gaps/attribution 是 sidecar，不写回报告。
        body = {
            "report_id": report.report_id,
            "task_id": report.task_id,
            "final_state": report.final_state,
            "ruleset_hash": report.ruleset_hash,
            "evidence_root": report.evidence_root,
            "tree_size": report.tree_size,
            "issued_at": report.issued_at,
            "signed": report.signed,
            "signature": report.signature,
            "gaps": [dict(gap) for gap in report.gaps],
            "attribution": [dict(item) for item in report.attribution],
            "certificate_available": report.final_state == "VERIFIED",
        }
        return ApiResponse(
            status=200,
            headers={"content-type": "application/json; charset=utf-8"},
            body=_json_bytes(body),
        )

    def get_certificate(self, ctx: HttpRequestContext) -> ApiResponse:
        """GET /tasks/{id}/certificate：仅 VERIFIED 返回；否则 409，不签发。"""
        # 1. 路径参数。
        try:
            task_id = _path_param(ctx.path, CERTIFICATE_ROUTE)
        except _NotFound:
            return _not_found("task not found", ctx)
        # 2. 任务不存在 → 404。
        if not self.reader.task_exists(task_id):
            return _not_found("task not found", ctx)
        # 3. 报告不存在/非 VERIFIED → 409 + reason，不返回凭证。
        report = self.reader.get_report(task_id)
        if report is None or report.final_state != "VERIFIED":
            return _error(
                "STATE_TRANSITION_DENIED",
                "Only VERIFIED tasks can receive a completion certificate.",
                _request_correlation(ctx),
                reason=CERTIFICATE_NOT_AVAILABLE_REASON,
            )
        # 4. VERIFIED 但凭证缺失：404 + CRITICAL 日志（签发链缺口，不是“不可用”）。
        certificate = self.reader.get_certificate(task_id)
        if certificate is None:
            return _not_found("certificate not issued", ctx)
        # 5. 绑定一致性：报告/凭证必须同 report_id、同 merkle_root/tree_size/ruleset。
        if (
            certificate.report_id != report.report_id
            or certificate.merkle_root != report.evidence_root
            or certificate.tree_size != report.tree_size
            or certificate.ruleset_hash != report.ruleset_hash
        ):
            return _error(
                "SIGNATURE_INVALID",
                "凭证与报告绑定字段不一致。",
                _request_correlation(ctx),
                reason="CERTIFICATE_REPORT_MISMATCH",
            )
        # 6. 用包外信任锚验签；失败 422，不返回凭证。
        try:
            self.verifier.verify_certificate(certificate, report)
        except Exception as exc:
            if exc.__class__.__name__ not in {"SignatureInvalid", "TrustAnchorMissing"}:
                raise
            return _error(
                "SIGNATURE_INVALID",
                "凭证签名或信任锚验证失败。",
                _request_correlation(ctx),
                reason="CERTIFICATE_SIGNATURE_INVALID",
            )
        # 7. 只读返回；GET 永不签发、永不重签。
        body = {
            "certificate_id": certificate.certificate_id,
            "report_id": certificate.report_id,
            "task_id": certificate.task_id,
            "issued_at": certificate.issued_at,
            "signature": certificate.signature,
            "key_fingerprint": certificate.key_fingerprint,
            "merkle_root": certificate.merkle_root,
            "tree_size": certificate.tree_size,
            "ruleset_hash": certificate.ruleset_hash,
        }
        return ApiResponse(
            status=200,
            headers={"content-type": "application/json; charset=utf-8"},
            body=_json_bytes(body),
        )


# 端点 → 拒绝条件 → 状态码/错误码 → 状态是否变化。
VERIFY_REJECTIONS: Final[tuple[RejectionRule, ...]] = (
    RejectionRule("POST /tasks/{id}/verify", "请求体非法/mode≠full/检查项重复或未知", 422, "SCHEMA_INVALID", None, False, "验证未启动"),
    RejectionRule("POST /tasks/{id}/verify", "任务不存在", 404, None, None, False, "detail=task not found"),
    RejectionRule("POST /tasks/{id}/verify", "任务不在 RUNNING", 409, "STATE_TRANSITION_DENIED", "TASK_NOT_RUNNING", False, "不得跳过执行直接验证"),
    RejectionRule("POST /tasks/{id}/verify", "同一任务验证进行中", 409, "STATE_TRANSITION_DENIED", "VERIFICATION_IN_PROGRESS", False, "不并发重复验证"),
    RejectionRule("POST /tasks/{id}/verify", "验证预算不足", 429, "RESOURCE_BUDGET_EXCEEDED", "VERIFY_BUDGET_EXCEEDED", False, "limit_kind=VERIFY_BUDGET"),
    RejectionRule("POST /tasks/{id}/verify", "StateMachine 拒绝迁移", 409, "STATE_TRANSITION_DENIED", "STATE_DENIED", False, "失败审计独立事务"),
    RejectionRule("GET /tasks/{id}/report", "任务/报告不存在", 404, None, None, False, "detail 区分 task/report"),
    RejectionRule("GET /tasks/{id}/report", "已签名报告验签失败", 422, "SIGNATURE_INVALID", "REPORT_SIGNATURE_INVALID", False, "不返回报告字段"),
    RejectionRule("GET /tasks/{id}/certificate", "任务不存在", 404, None, None, False, "detail=task not found"),
    RejectionRule("GET /tasks/{id}/certificate", "报告不存在或非 VERIFIED", 409, "STATE_TRANSITION_DENIED", "CERTIFICATE_NOT_AVAILABLE", False, "绝不返回凭证"),
    RejectionRule("GET /tasks/{id}/certificate", "VERIFIED 但凭证缺失", 404, None, None, False, "签发链缺口，记 CRITICAL"),
    RejectionRule("GET /tasks/{id}/certificate", "凭证与报告绑定不一致", 422, "SIGNATURE_INVALID", "CERTIFICATE_REPORT_MISMATCH", False, "不返回凭证"),
    RejectionRule("GET /tasks/{id}/certificate", "凭证验签/信任锚失败", 422, "SIGNATURE_INVALID", "CERTIFICATE_SIGNATURE_INVALID", False, "不返回凭证"),
)


def assert_certificate_gate() -> tuple[str, ...]:
    """静态判据：只有 VERIFIED 路径返回凭证；GET 无签发调用；信任锚来自包外。"""
    problems: list[str] = []
    # 1. 只读端口不得有签发/签名方法。
    for forbidden in ("issue", "sign", "transition", "write"):
        if forbidden in set(dir(ReportReaderPort)):
            problems.append(f"ReportReaderPort 暴露了写方法 {forbidden}")
    # 2. 验签端口必须要求外部信任锚；若签名只接受 one 参数，则可能信任包内公钥。
    #    该条由落地阶段的负例 NEG-M19-13 锁定，这里只登记人工判据。
    # 3. 非 VERIFIED 的拒绝必须是 409 + reason，不得是 200 空对象。
    for rule in VERIFY_REJECTIONS:
        if rule.endpoint.endswith("/certificate") and rule.condition.startswith("报告不存在或非 VERIFIED"):
            if rule.http_status != 409 or rule.reason != CERTIFICATE_NOT_AVAILABLE_REASON:
                problems.append("非 VERIFIED 凭证拒绝口径被改动")
    return tuple(problems)