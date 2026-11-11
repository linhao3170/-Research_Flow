"""M02 · orchestration/state_machine.py — 唯一状态写入口（P2 伪代码）。

阶段：P2｜状态：`transition()` 的校验顺序、守卫、事务、审计与失败降级；
**不执行迁移、不连接数据库、不派发任务**。

唯一公开写入口：
    StateMachine.transition(obj_type, obj_id, to_state, actor, reason_code, ctx)

它只处理 **Task / Node** 的运行时状态。Evidence 的 `RECEIVED→VALIDATED→APPENDED`
由 Collector/Verifier 在摄入流水线执行（06 §3），本入口对 `obj_type=evidence` 一律拒绝，
避免把“证据只追加”改成“证据状态可更新”。

一次成功迁移的顺序（不可交换）：
  1. 校验参数/角色/边/`previous_state`（只读）；
  2. 校验守卫（只读；含 plan_hash 三条件）；
  3. `BEGIN IMMEDIATE`；
  4. 事务内重读状态，防 TOCTOU；
  5. 如 `VERIFIED→INVALIDATED`：先追加 `evidence_invalidations`；
  6. **先插入 `audit_log(result=OK)`**（DB 触发器要求状态更新前存在同事务审计）；
  7. `UPDATE ... WHERE state = :expected_from`；受影响行数必须为 1；
  8. `COMMIT`。

一次失败迁移的顺序（ADR-005 / 决议 7）：
  1. 状态事务回滚（不留半条迁移、不留下成功的 OK 审计）；
  2. **新事务**写 `audit_log(result=DENIED)`，字段含
     `previous_state`、`next_state`、`actor`、`reason_code`、`rule_version`、
     `correlation_id`、`error_code`（以及 task_id/node_id/plan_id/plan_hash）；
  3. 若 DENIED 也写失败：向 stderr 写单行结构化 JSON（`audit_write_failed=true`），
     并抛 `AuditWriteFailed`；不得静默吞掉，也不得写成通过。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, NoReturn, Protocol

from ..persistence.repositories import (
    AuditRow,
    DirectStateWriteDenied,
    EvidenceMetaRepository,
    InvalidationRow,
    NodeRepository,
    NodeRow,
    Repositories,
    STATE_MACHINE_WRITE,
    TaskRepository,
    TaskRow,
)
from .transitions import (
    ActorRole,
    GuardId,
    IllegalTransition,
    NON_WRITER_ROLES,
    ObjectType,
    ReasonCode,
    Transition,
    lookup_transition,
)

__all__ = [
    "AUDIT_FIELDS",
    "AUDIT_SENTINEL",
    "AUDIT_UNKNOWN",
    "DENIED_AUDIT_REQUIRED",
    "PUBLIC_WRITE_ENTRYPOINTS",
    "Actor",
    "AttemptEnd",
    "AuditWriteFailed",
    "CertificateFacts",
    "GateFacts",
    "GuardPorts",
    "PlanFileMissing",
    "PlanStorePort",
    "ReportFacts",
    "StateMachine",
    "StateTransitionDenied",
    "SystemClock",
    "TransitionContext",
    "TransitionResult",
    "UnsafePlanPath",
    "assert_single_write_entrypoint",
    "format_utc",
    "parse_utc",
]

PUBLIC_WRITE_ENTRYPOINTS: Final[tuple[str, ...]] = ("transition",)

# 参数缺失时仍要写 DENIED 审计；用显式哨兵，不用 NULL（否则违反 audit_log 的
# STATE_TRANSITION 必填 CHECK）。哨兵只用于 DENIED，成功迁移必须用真实值。
AUDIT_SENTINEL: Final[str] = "<missing>"
AUDIT_UNKNOWN: Final[str] = "<unknown>"

AUDIT_FIELDS: Final[tuple[str, ...]] = (
    "audit_id", "task_id", "node_id", "actor", "action",
    "previous_state", "next_state", "reason_code", "rule_version",
    "correlation_id", "plan_id", "plan_hash", "result", "error_code", "created_at",
)

# 提示要求的失败审计六项 + error_code（task/node/plan 另由上下文补）
DENIED_AUDIT_REQUIRED: Final[tuple[str, ...]] = (
    "previous_state", "next_state", "actor", "reason_code",
    "rule_version", "correlation_id", "error_code",
)


# ---------------------------------------------------------------------------
# 0. 时间与身份
# ---------------------------------------------------------------------------
def format_utc(value: datetime) -> str:
    """UTC、微秒精度、Z 结尾；固定 27 字符（ENCODING_RULES §3）。"""
    if value.tzinfo is None:
        raise ValueError("拒绝 naive datetime；必须带时区")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(text: str) -> datetime:
    """解析本系统写入的 27 字符 UTC 时间；非法即抛 ValueError。"""
    if not isinstance(text, str) or len(text) != 27 or not text.endswith("Z"):
        raise ValueError(f"非法 UTC 时间：{text!r}")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _ClockLike(Protocol):
    def now(self) -> datetime:
        ...


_IDENTITY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True, slots=True)
class Actor:
    """角色 + 身份；审计写 `role:identity`，例如 `wp_r:local`。"""

    role: ActorRole
    identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, ActorRole):
            raise ValueError(f"未知角色：{self.role!r}")
        if not _IDENTITY_PATTERN.fullmatch(self.identity):
            raise ValueError("actor.identity 必须是 1–64 位字母/数字/._-，且不含冒号")

    @property
    def audit_value(self) -> str:
        return f"{self.role.value}:{self.identity}"


# ---------------------------------------------------------------------------
# 1. 上下文与返回值
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TransitionContext:
    """一次迁移请求的上下文。

    `previous_state` 是 05 §9.7 的必填项；本入口**不接受**调用方省略它，
    也不把“先读再写”当作幂等：它是乐观并发的期望前态。
    """

    previous_state: str
    rule_version: str
    correlation_id: str
    task_id: str | None = None          # Node 必填；Task 可省略（= obj_id）
    plan_id: str | None = None
    plan_hash: str | None = None
    cause_type: str | None = None
    cause_ref: str | None = None
    evidence_ids: tuple[str, ...] = ()
    attempt_id: str | None = None
    report_id: str | None = None
    cert_id: str | None = None
    gate_result_ref: str | None = None
    failure_ref: str | None = None
    graph_version: int | None = None
    diagnosis_ref: str | None = None
    recovery_ref: str | None = None
    recheck_ref: str | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    ok: bool
    obj_type: ObjectType
    obj_id: str
    previous_state: str
    next_state: str
    audit_id: str
    applied_at: str
    correlation_id: str
    attempt_seq: int | None = None
    plan_id: str | None = None
    plan_hash: str | None = None


class StateTransitionDenied(RuntimeError):
    """公开的迁移拒绝异常；HTTP 状态按错误码映射（默认 409）。"""

    _HTTP_STATUS: Final[Mapping[str, int]] = MappingProxyType(
        {
            "STATE_TRANSITION_DENIED": 409,
            "PLAN_HASH_MISMATCH": 409,
            "REQUIRED_EVIDENCE_MISSING": 409,
            "RULESET_VERSION_MISMATCH": 409,
            "SIGNATURE_INVALID": 422,
            "ENV_FINGERPRINT_MISMATCH": 409,
            "RESOURCE_BUDGET_EXCEEDED": 429,
        }
    )

    def __init__(
        self,
        *,
        error_code: str,
        reason: ReasonCode | str,
        obj_type: ObjectType | str,
        obj_id: str,
        previous_state: str | None,
        next_state: str | None,
        correlation_id: str | None,
        audit_id: str | None = None,
        audit_degraded: bool = False,
        details: str = "",
    ) -> None:
        self.error_code = error_code
        self.reason = reason.value if isinstance(reason, ReasonCode) else str(reason)
        self.obj_type = obj_type
        self.obj_id = obj_id
        self.previous_state = previous_state
        self.next_state = next_state
        self.correlation_id = correlation_id
        self.audit_id = audit_id
        self.audit_degraded = audit_degraded
        self.http_status = self._HTTP_STATUS.get(error_code, 409)
        self.details = details
        suffix = f"；{details}" if details else ""
        super().__init__(
            f"{error_code}：{obj_type} {obj_id} "
            f"{previous_state} → {next_state}（{self.reason}）{suffix}"
        )


class AuditWriteFailed(RuntimeError):
    """状态已回滚，DENIED 审计二次写入也失败；已降级到 stderr。"""

    error_code = "AUDIT_WRITE_FAILED"
    http_status = 500

    def __init__(
        self,
        *,
        original_error_code: str,
        correlation_id: str | None,
        audit_write_failed: bool = True,
    ) -> None:
        self.original_error_code = original_error_code
        self.correlation_id = correlation_id
        self.audit_write_failed = audit_write_failed
        super().__init__(
            "DENIED 审计写入失败；已写结构化 stderr，测试报告必须计为测试缺口"
        )


class PlanFileMissing(RuntimeError):
    """计划文件不存在/不可读；由 PlanStorePort 抛出。"""


class UnsafePlanPath(RuntimeError):
    """计划路径逃逸出 plan_store_root（../、绝对路径、符号链接）。"""


class _Denial(Exception):
    """内部拒绝信号；由 transition() 统一写 DENIED 审计并转公开异常。"""

    def __init__(
        self,
        reason: ReasonCode,
        *,
        error_code: str = "STATE_TRANSITION_DENIED",
        details: str = "",
        previous_state: str | None = None,
        next_state: str | None = None,
    ) -> None:
        self.reason = reason
        self.error_code = error_code
        self.details = details
        self.previous_state = previous_state
        self.next_state = next_state
        super().__init__(f"{error_code}/{reason.value}: {details}")


class _ConcurrentModification(Exception):
    def __init__(self, actual_state: str) -> None:
        self.actual_state = actual_state
        super().__init__(f"并发修改：实际状态为 {actual_state}")


# ---------------------------------------------------------------------------
# 2. 只读事实端口（实现由 WP-03/04/07/08/11 提供；M02 不计算 Gate/签名）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GateFacts:
    gate_result_ref: str
    passed: bool
    node_results: Mapping[str, bool]
    missing: tuple[str, ...]
    ruleset_hash: str
    l3_min_coverage: float


@dataclass(frozen=True, slots=True)
class ReportFacts:
    report_id: str
    task_id: str
    final_state: str
    ruleset_hash: str
    evidence_root: str
    l3_coverage: float
    signature_valid: bool


@dataclass(frozen=True, slots=True)
class CertificateFacts:
    cert_id: str
    report_id: str
    final_state: str
    merkle_root: str
    tree_size: int
    ruleset_hash: str
    env_fingerprint: str
    signature_valid: bool
    revoked: bool


@dataclass(frozen=True, slots=True)
class AttemptEnd:
    attempt_id: str
    ended: bool
    exit_code: int | None
    evidence_chain_ok: bool
    last_event_seq: int | None


class GraphFactsPort(Protocol):
    def dag_valid(self, task_id: str, graph_version: int) -> bool:
        ...

    def blocking_gap(self, task_id: str, failure_ref: str) -> bool:
        ...


class TaskFactsPort(Protocol):
    def has_ready_node(self, task_id: str) -> bool:
        ...

    def execution_finished(self, task_id: str) -> bool:
        ...

    def all_required_nodes_verified(self, task_id: str) -> bool:
        ...


class NodeFactsPort(Protocol):
    def dependencies_satisfied(self, task_id: str, node_id: str) -> bool:
        ...

    def resources_available(self, task_id: str, node_id: str) -> bool:
        ...

    def attempt_end(self, task_id: str, node_id: str, attempt_id: str) -> AttemptEnd:
        ...

    def recovery_budget_available(
        self, task_id: str, node_id: str, recovery_ref: str
    ) -> bool:
        ...

    def diagnosis_valid(self, task_id: str, node_id: str, diagnosis_ref: str) -> bool:
        ...

    def recovery_rechecked(self, task_id: str, node_id: str, recheck_ref: str) -> bool:
        ...


class GateFactsPort(Protocol):
    def get(self, gate_result_ref: str) -> GateFacts:
        ...


class ReportFactsPort(Protocol):
    def get(self, report_id: str) -> ReportFacts:
        ...


class CertificateFactsPort(Protocol):
    def get(self, cert_id: str) -> CertificateFacts:
        ...


class EvidenceFactsPort(Protocol):
    def verify_chain(self, task_id: str) -> Any:
        """返回 `ChainReport`；此处用 Any 避免与持久层类型循环。"""
        ...

    def count(self, task_id: str) -> int:
        ...

    def get(self, evidence_id: str) -> Any:
        ...

    def is_invalidated(self, evidence_id: str) -> bool:
        ...

    def env_fingerprint(self, task_id: str) -> str:
        ...


class PlanStorePort(Protocol):
    def resolve(self, plan_hash: str) -> Path:
        """返回内容寻址路径；必须拒绝 ../、绝对路径与符号链接逃逸。"""
        ...

    def read_bytes(self, path: Path) -> bytes:
        ...


@dataclass(frozen=True, slots=True)
class GuardPorts:
    graph: GraphFactsPort
    tasks: TaskFactsPort
    nodes: NodeFactsPort
    gate: GateFactsPort
    reports: ReportFactsPort
    certificates: CertificateFactsPort
    evidence: EvidenceFactsPort
    plans: PlanStorePort


# ---------------------------------------------------------------------------
# 3. 唯一写入口
# ---------------------------------------------------------------------------
class StateMachine:
    PUBLIC_WRITE_ENTRYPOINTS = PUBLIC_WRITE_ENTRYPOINTS

    def __init__(
        self,
        *,
        repos: Repositories,
        ports: GuardPorts,
        clock: _ClockLike | None = None,
    ) -> None:
        self._repos = repos
        self._ports = ports
        self._clock = clock or SystemClock()

    # -- 唯一公开写入口 ---------------------------------------------------
    def transition(
        self,
        obj_type: ObjectType | str,
        obj_id: str,
        to_state: str,
        actor: Actor,
        reason_code: ReasonCode | str,
        ctx: TransitionContext,
    ) -> TransitionResult:
        """修改一个 Task/Node 的状态。**这是本类唯一的公开写入口。**

        失败一定抛 `StateTransitionDenied`；若 DENIED 审计也失败，抛
        `AuditWriteFailed`（原始错误码在 `.original_error_code`）。
        """
        received_at = self._clock.now()
        try:
            fallback_type: ObjectType | None = ObjectType(obj_type)
        except (ValueError, TypeError):
            fallback_type = None
        # 先构造一个“尽力而为”的请求骨架：即使参数校验失败，DENIED 审计也要尽量
        # 记录 actor / correlation_id / reason_code / previous_state / next_state。
        fallback = _Request(
            obj_type=fallback_type,
            obj_id=obj_id if isinstance(obj_id, str) else "",
            to_state=to_state if isinstance(to_state, str) else "",
            actor=actor if isinstance(actor, Actor) else None,
            reason_code=(
                reason_code.value
                if isinstance(reason_code, ReasonCode)
                else (str(reason_code) if reason_code is not None else "")
            ),
            ctx=ctx if isinstance(ctx, TransitionContext) else None,
            received_at=received_at,
            task_id=ctx.task_id if isinstance(ctx, TransitionContext) else None,
            node_id=(
                obj_id
                if isinstance(obj_id, str)
                and fallback_type is ObjectType.NODE
                else None
            ),
        )
        request: _Request = fallback
        try:
            request = self._validate_request(
                obj_type=obj_type,
                obj_id=obj_id,
                to_state=to_state,
                actor=actor,
                reason_code=reason_code,
                ctx=ctx,
                received_at=received_at,
            )
            obj = self._load_object(request)
            edge = self._select_transition(request, obj)
            self._check_role(request, edge)
            self._evaluate_guard(request, obj, edge)
            return self._apply_success(request, obj, edge)
        except _Denial as denial:
            return self._deny(request, denial, received_at)
        except _ConcurrentModification as concurrent:
            denial = _Denial(
                ReasonCode.STALE_PREVIOUS_STATE,
                error_code="STATE_TRANSITION_DENIED",
                details=f"实际状态={concurrent.actual_state}",
                previous_state=concurrent.actual_state,
            )
            return self._deny(request, denial, received_at)
        except Exception as exc:
            denial = _Denial(
                ReasonCode.GUARD_FAILED,
                error_code="STATE_TRANSITION_DENIED",
                details=f"未预期失败：{type(exc).__name__}",
            )
            return self._deny(request, denial, received_at)

    # -- 1. 参数校验 ------------------------------------------------------
    def _validate_request(
        self,
        *,
        obj_type: ObjectType | str,
        obj_id: str,
        to_state: str,
        actor: Actor,
        reason_code: ReasonCode | str,
        ctx: TransitionContext,
        received_at: datetime,
    ) -> "_Request":
        try:
            obj_type = ObjectType(obj_type)
        except ValueError as exc:
            raise _Denial(ReasonCode.UNKNOWN_OBJECT_TYPE) from exc

        if obj_type not in (ObjectType.TASK, ObjectType.NODE):
            raise _Denial(
                ReasonCode.OBJECT_TYPE_NOT_MANAGED,
                details="Evidence 状态由 Collector/Verifier 摄入流水线管理，"
                        "StateMachine 不得写 evidence 表",
            )
        if not isinstance(obj_id, str) or not obj_id:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="obj_id 为空")
        if not isinstance(actor, Actor):
            raise _Denial(ReasonCode.ROLE_NOT_ALLOWED, details="actor 必须是 Actor")
        if actor.role in NON_WRITER_ROLES:
            raise _Denial(
                ReasonCode.ROLE_NOT_ALLOWED,
                details=f"{actor.role.value} 不是 Task/Node 状态写者",
            )
        if not isinstance(ctx, TransitionContext):
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="ctx 类型错误")
        if not ctx.previous_state:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="previous_state 缺失")
        if not ctx.rule_version:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="rule_version 缺失")
        if not ctx.correlation_id:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="correlation_id 缺失")
        if not to_state:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="to_state 缺失")
        if reason_code is None:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="reason_code 缺失")
        reason = reason_code.value if isinstance(reason_code, ReasonCode) else str(reason_code)
        if not reason:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="reason_code 缺失")

        task_id = ctx.task_id or (obj_id if obj_type is ObjectType.TASK else None)
        if obj_type is ObjectType.NODE and not task_id:
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                details="Node 迁移必须在 ctx.task_id 给出任务 ID",
            )
        node_id = obj_id if obj_type is ObjectType.NODE else None

        return _Request(
            obj_type=obj_type,
            obj_id=obj_id,
            to_state=to_state,
            actor=actor,
            reason_code=reason,
            ctx=ctx,
            received_at=received_at,
            task_id=task_id,
            node_id=node_id,
        )

    def _load_object(self, req: "_Request") -> TaskRow | NodeRow:
        if req.obj_type is None:
            raise _Denial(ReasonCode.UNKNOWN_OBJECT_TYPE)
        if req.actor is None or req.ctx is None:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="actor/ctx 缺失")
        if req.obj_type is ObjectType.TASK:
            obj = self._repos.tasks.get(req.obj_id)
            if obj is None:
                raise _Denial(ReasonCode.OBJECT_NOT_FOUND)
            req.task_id = obj.task_id
            return obj
        assert req.task_id is not None and req.node_id is not None
        node = self._repos.nodes.get(req.task_id, req.node_id)
        if node is None:
            raise _Denial(ReasonCode.OBJECT_NOT_FOUND)
        return node

    def _select_transition(self, req: "_Request", obj: TaskRow | NodeRow) -> Transition:
        if req.ctx.previous_state != obj.state:
            raise _Denial(
                ReasonCode.STALE_PREVIOUS_STATE,
                details=f"ctx.previous_state={req.ctx.previous_state}，实际={obj.state}",
                previous_state=obj.state,
            )
        try:
            edge = lookup_transition(req.obj_type, obj.state, req.to_state)
        except IllegalTransition as exc:
            raise _Denial(
                exc.reason,
                error_code=exc.error_code,
                details=exc.detail,
                previous_state=obj.state,
            ) from exc
        self._check_context_requirements(req, edge)
        return edge

    def _check_context_requirements(self, req: "_Request", edge: Transition) -> None:
        ctx = req.ctx
        if ctx is None:
            raise _Denial(ReasonCode.MISSING_PARAMETER, details="ctx 缺失")
        for name in edge.requires:
            value = getattr(ctx, name, None)
            if value is None or (isinstance(value, (str, tuple)) and not value):
                raise _Denial(
                    ReasonCode.MISSING_PARAMETER,
                    details=f"迁移 {edge.from_state}→{edge.to_state} 缺少 {name}",
                )
        has_plan = ctx.plan_id is not None or ctx.plan_hash is not None
        if has_plan and edge.guard_id is not GuardId.PLAN_THREE_GUARDS:
            raise _Denial(
                ReasonCode.PLAN_FIELDS_NOT_ALLOWED,
                details="plan_id/plan_hash 只允许在 INVALIDATED→READY 携带（05 §9.7）",
            )
        if edge.guard_id is GuardId.PLAN_THREE_GUARDS:
            if not ctx.plan_id or not ctx.plan_hash:
                raise _Denial(
                    ReasonCode.MISSING_PARAMETER,
                    details="INVALIDATED→READY 必须同时给出 plan_id 与 plan_hash",
                )

    def _check_role(self, req: "_Request", edge: Transition) -> None:
        if req.actor is None:
            raise _Denial(ReasonCode.ROLE_NOT_ALLOWED, details="actor 缺失")
        if req.actor.role not in edge.allowed_roles:
            raise _Denial(
                ReasonCode.ROLE_NOT_ALLOWED,
                details=f"{req.actor.role.value} 不允许 {edge.from_state}→{edge.to_state}",
            )

    # -- 2. 守卫 ----------------------------------------------------------
    def _evaluate_guard(
        self, req: "_Request", obj: TaskRow | NodeRow, edge: Transition
    ) -> None:
        ctx = req.ctx
        guard = edge.guard_id
        if guard is GuardId.NONE:
            return
        if guard is GuardId.DAG_VALID:
            if ctx.graph_version is None or not self._ports.graph.dag_valid(
                req.task_id, ctx.graph_version
            ):
                raise _Denial(
                    ReasonCode.DAG_INVALID,
                    details="DAG 未通过静态校验或 graph_version 缺失",
                )
            return
        if guard is GuardId.DAG_BLOCKING_GAP:
            if not self._ports.graph.blocking_gap(req.task_id, ctx.failure_ref or ""):
                raise _Denial(
                    ReasonCode.DAG_INVALID,
                    details="没有可引用的阻塞缺口",
                )
            return
        if guard is GuardId.AT_LEAST_ONE_NODE_READY:
            if not self._ports.tasks.has_ready_node(req.task_id):
                raise _Denial(ReasonCode.NO_READY_NODE)
            return
        if guard is GuardId.EXECUTION_FINISHED:
            if not self._ports.tasks.execution_finished(req.task_id):
                raise _Denial(
                    ReasonCode.ATTEMPT_NOT_ENDED,
                    details="仍有执行节点未结束；执行未结束不能进入最终验证",
                )
            return
        if guard is GuardId.TASK_COMPLETION_PREREQUISITES:
            self._guard_task_completion(req)
            return
        if guard is GuardId.DEPENDENCIES_SATISFIED:
            if not self._ports.nodes.dependencies_satisfied(req.task_id, req.obj_id):
                raise _Denial(ReasonCode.DEPENDENCIES_UNSATISFIED)
            return
        if guard is GuardId.RESOURCES_AVAILABLE:
            if not self._ports.nodes.resources_available(req.task_id, req.obj_id):
                raise _Denial(ReasonCode.RESOURCE_NOT_AVAILABLE)
            return
        if guard is GuardId.ATTEMPT_ENDED_SUCCESS:
            self._guard_attempt_ended(req, edge)
            return
        if guard is GuardId.VERIFIED_PREREQUISITES:
            self._guard_verified_prerequisites(req)
            return
        if guard is GuardId.RECOVERY_BUDGET_AVAILABLE:
            if not self._ports.nodes.recovery_budget_available(
                req.task_id, req.obj_id, ctx.recovery_ref or ""
            ):
                raise _Denial(ReasonCode.RECOVERY_BUDGET_EXHAUSTED_DENIED)
            return
        if guard is GuardId.DIAGNOSIS_VALID:
            if not self._ports.nodes.diagnosis_valid(
                req.task_id, req.obj_id, ctx.diagnosis_ref or ""
            ):
                raise _Denial(ReasonCode.DIAGNOSIS_INVALID)
            return
        if guard is GuardId.RECOVERY_RECHECKED:
            if not self._ports.nodes.recovery_rechecked(
                req.task_id, req.obj_id, ctx.recheck_ref or ""
            ):
                raise _Denial(ReasonCode.RECOVERY_FAILED)
            return
        if guard is GuardId.STALE_CAUSE_PRESENT:
            self._guard_stale_cause(req)
            return
        if guard is GuardId.PLAN_THREE_GUARDS:
            self._guard_plan_three(req)
            return
        if guard is GuardId.FAILURE_EVIDENCE_PRESENT:
            if not ctx.failure_ref:
                raise _Denial(ReasonCode.MISSING_PARAMETER, details="failure_ref 缺失")
            return
        if guard is GuardId.EVIDENCE_CHAIN_VALID:
            # StateMachine 不执行 Evidence 迁移；此守卫仅供 WP-07 使用。
            raise _Denial(
                ReasonCode.OBJECT_TYPE_NOT_MANAGED,
                details="Evidence 守卫不属于 StateMachine",
            )
        raise _Denial(ReasonCode.GUARD_FAILED, details=f"未知守卫 {guard!r}")

    def _guard_attempt_ended(self, req: "_Request", edge: Transition) -> None:
        attempt_id = req.ctx.attempt_id or ""
        attempt = self._ports.nodes.attempt_end(req.task_id, req.obj_id, attempt_id)
        if not attempt.ended:
            raise _Denial(
                ReasonCode.ATTEMPT_NOT_ENDED,
                details="没有 attempt 结束事件；不得用进程存活/日志猜测",
            )
        if not attempt.evidence_chain_ok:
            raise _Denial(
                ReasonCode.EVIDENCE_CHAIN_BROKEN,
                error_code="EVIDENCE_CHAIN_BROKEN",
                details="attempt 证据链不完整",
            )
        if attempt.exit_code is None or attempt.exit_code != 0:
            raise _Denial(
                ReasonCode.EXIT_CODE_NONZERO,
                details=f"exit_code={attempt.exit_code!r}；非 0 不得进入 VERIFYING",
            )

    def _guard_task_completion(self, req: "_Request") -> None:
        report, cert = self._verified_bundle(req, node_id=None)
        if report.final_state != "VERIFIED":
            raise _Denial(
                ReasonCode.REPORT_NOT_VERIFIED,
                details=f"报告 final_state={report.final_state}",
            )
        if not self._ports.tasks.all_required_nodes_verified(req.task_id):
            raise _Denial(
                ReasonCode.TASK_COMPLETION_PREREQUISITES,
                details="仍有非跳过节点不是 VERIFIED（T0 无 SPA，skipped_nodes 必须为空）",
            )
        if cert.tree_size != self._ports.evidence.count(req.task_id):
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                details="证书 tree_size 与证据条数不一致",
            )

    def _guard_verified_prerequisites(self, req: "_Request") -> None:
        report, cert = self._verified_bundle(req, node_id=req.obj_id)
        if report.final_state != "VERIFIED":
            raise _Denial(
                ReasonCode.REPORT_NOT_VERIFIED,
                details=f"报告 final_state={report.final_state}",
            )
        if cert.tree_size != self._ports.evidence.count(req.task_id):
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                details="证书 tree_size 与证据条数不一致",
            )

    def _verified_bundle(
        self, req: "_Request", *, node_id: str | None
    ) -> tuple[ReportFacts, CertificateFacts]:
        """三条件：Gate PASS + Verifier VERIFIED + 有效凭证；缺一即拒绝。

        本函数只读取已持久化的 Gate/Report/Certificate 事实，**不计算 Gate、
        不验签、不签名**；签名有效性由 `CertificateFacts.signature_valid` 提供。
        """
        ctx = req.ctx
        gate = self._ports.gate.get(ctx.gate_result_ref or "")
        if not gate.passed:
            raise _Denial(ReasonCode.GATE_NOT_PASS, details="Gate 未 PASS")
        if gate.missing:
            raise _Denial(
                ReasonCode.REQUIRED_EVIDENCE_MISSING,
                error_code="REQUIRED_EVIDENCE_MISSING",
                details=f"Gate 仍有缺口：{gate.missing!r}",
            )
        if node_id is not None and not gate.node_results.get(node_id, False):
            raise _Denial(
                ReasonCode.GATE_NOT_PASS,
                details=f"Gate 未对该节点 PASS：{node_id}",
            )
        report = self._ports.reports.get(ctx.report_id or "")
        if report.task_id != req.task_id:
            raise _Denial(ReasonCode.REPORT_NOT_VERIFIED, details="报告不属于该任务")
        if report.ruleset_hash != gate.ruleset_hash:
            raise _Denial(
                ReasonCode.RULE_VERSION_MISMATCH,
                error_code="RULESET_VERSION_MISMATCH",
                details="报告与 Gate 的 ruleset_hash 不一致",
            )
        if not report.signature_valid:
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                error_code="SIGNATURE_INVALID",
                details="报告签名无效",
            )
        if report.l3_coverage < gate.l3_min_coverage:
            raise _Denial(
                ReasonCode.REQUIRED_EVIDENCE_MISSING,
                error_code="REQUIRED_EVIDENCE_MISSING",
                details="L3 覆盖率未达规则集阈值（I-04）",
            )
        cert = self._ports.certificates.get(ctx.cert_id or "")
        if cert.report_id != report.report_id or cert.final_state != "VERIFIED":
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                details="凭证不是由该 VERIFIED 报告生成",
            )
        if cert.revoked:
            raise _Denial(ReasonCode.CERTIFICATE_INVALID, details="凭证已撤销")
        if not cert.signature_valid:
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                error_code="SIGNATURE_INVALID",
                details="凭证签名无效",
            )
        if cert.merkle_root != report.evidence_root:
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                details="cert.merkle_root != report.evidence_root",
            )
        if cert.ruleset_hash != report.ruleset_hash:
            raise _Denial(
                ReasonCode.RULE_VERSION_MISMATCH,
                error_code="RULESET_VERSION_MISMATCH",
                details="凭证与报告的 ruleset_hash 不一致",
            )
        if cert.env_fingerprint != self._ports.evidence.env_fingerprint(req.task_id):
            raise _Denial(
                ReasonCode.ENV_FINGERPRINT_MISMATCH,
                error_code="ENV_FINGERPRINT_MISMATCH",
                details="凭证 env_fingerprint 与 E2 环境不一致",
            )
        chain = self._ports.evidence.verify_chain(req.task_id)
        if not chain.ok:
            raise _Denial(
                ReasonCode.EVIDENCE_CHAIN_BROKEN,
                error_code="EVIDENCE_CHAIN_BROKEN",
                details=f"证据链失败：{chain.reason}@{chain.at_event_seq}",
            )
        return report, cert

    def _guard_stale_cause(self, req: "_Request") -> None:
        ctx = req.ctx
        valid_causes = {
            "INPUT_CHANGE", "PREDECESSOR_CHANGE", "GRAPH_VERSION_CHANGE", "RULESET_CHANGE",
        }
        if ctx.cause_type not in valid_causes:
            raise _Denial(ReasonCode.CAUSE_INVALID, details=f"cause_type={ctx.cause_type!r}")
        if not ctx.evidence_ids:
            raise _Denial(ReasonCode.NO_STALE_EVIDENCE, details="evidence_ids 为空")
        for evidence_id in ctx.evidence_ids:
            row = self._ports.evidence.get(evidence_id)
            if row is None:
                raise _Denial(
                    ReasonCode.NO_STALE_EVIDENCE,
                    details=f"evidence_id 不存在：{evidence_id}",
                )
            if row.task_id != req.task_id or row.node_id != req.obj_id:
                raise _Denial(
                    ReasonCode.NO_STALE_EVIDENCE,
                    details=f"evidence_id 不属于该节点：{evidence_id}",
                )
            if self._ports.evidence.is_invalidated(evidence_id):
                raise _Denial(
                    ReasonCode.NO_STALE_EVIDENCE,
                    details=f"evidence_id 已失效：{evidence_id}",
                )

    def _guard_plan_three(self, req: "_Request") -> None:
        """INVALIDATED→READY 三条守卫；任一条失败 → PLAN_HASH_MISMATCH。

        ① 计划文件存在、是普通文件、可读、路径不逃逸；
        ② sha256(文件字节) == plan_hash，且 plan_id/plan_hash 与 audit 冻结记录一致；
        ③ 冻结事件 created_at 严格早于本次请求 received_at（相等也拒绝）。
        """
        ctx = req.ctx
        plan_id, plan_hash = ctx.plan_id or "", ctx.plan_hash or ""
        if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
            raise _Denial(
                ReasonCode.PLAN_HASH_MISMATCH,
                error_code="PLAN_HASH_MISMATCH",
                details="plan_hash 不是 64 位小写十六进制",
            )
        if not plan_id or "/" in plan_id or "\\" in plan_id:
            raise _Denial(
                ReasonCode.UNSAFE_PLAN_PATH,
                error_code="PLAN_HASH_MISMATCH",
                details="plan_id 为空或含路径分隔符",
            )
        try:
            path = self._ports.plans.resolve(plan_hash)
        except UnsafePlanPath as exc:
            raise _Denial(
                ReasonCode.UNSAFE_PLAN_PATH,
                error_code="PLAN_HASH_MISMATCH",
                details=str(exc),
            ) from exc
        except PlanFileMissing as exc:
            raise _Denial(
                ReasonCode.PLAN_FILE_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details=str(exc),
            ) from exc
        if not path.is_file():
            raise _Denial(
                ReasonCode.PLAN_FILE_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details="计划路径不是普通文件",
            )
        try:
            data = self._ports.plans.read_bytes(path)
        except OSError as exc:
            raise _Denial(
                ReasonCode.PLAN_FILE_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details="计划文件不可读",
            ) from exc
        actual = hashlib.sha256(data).hexdigest()
        if actual != plan_hash:
            raise _Denial(
                ReasonCode.PLAN_HASH_MISMATCH,
                error_code="PLAN_HASH_MISMATCH",
                details="sha256(文件字节) != plan_hash",
            )

        freeze = self._repos.audit.latest_freeze(
            task_id=req.task_id, node_id=req.obj_id, plan_hash=plan_hash
        )
        if freeze is None or freeze.action != "RECOVERY_PLAN_FROZEN" or freeze.result != "OK":
            raise _Denial(
                ReasonCode.PLAN_FREEZE_RECORD_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details="缺少 RECOVERY_PLAN_FROZEN(result=OK) 审计",
            )
        if freeze.plan_hash != plan_hash:
            raise _Denial(
                ReasonCode.PLAN_HASH_MISMATCH,
                error_code="PLAN_HASH_MISMATCH",
                details="冻结记录的 plan_hash 与请求不一致",
            )
        if freeze.plan_id != plan_id:
            raise _Denial(
                ReasonCode.PLAN_ID_MISMATCH,
                error_code="PLAN_HASH_MISMATCH",
                details="冻结记录的 plan_id 与请求不一致",
            )
        try:
            frozen_at = parse_utc(freeze.created_at)
        except ValueError as exc:
            raise _Denial(
                ReasonCode.PLAN_FREEZE_RECORD_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details="冻结记录时间不可解析",
            ) from exc
        if not frozen_at < req.received_at:
            raise _Denial(
                ReasonCode.PLAN_FROZEN_AFTER_RERUN,
                error_code="PLAN_HASH_MISMATCH",
                details="冻结事件不早于本次重跑（相等也拒绝）",
            )

    # -- 3. 成功写入 ------------------------------------------------------
    def _apply_success(
        self, req: "_Request", obj: TaskRow | NodeRow, edge: Transition
    ) -> TransitionResult:
        now = self._clock.now()
        now_text = format_utc(now)
        audit_id = str(uuid.uuid4())
        plan_id = req.ctx.plan_id if edge.guard_id is GuardId.PLAN_THREE_GUARDS else None
        plan_hash = req.ctx.plan_hash if edge.guard_id is GuardId.PLAN_THREE_GUARDS else None
        attempt_delta = (
            1
            if req.obj_type is ObjectType.NODE
            and edge.from_state == "READY"
            and edge.to_state == "RUNNING"
            else 0
        )
        graph_version = (
            req.ctx.graph_version
            if req.obj_type is ObjectType.TASK and edge.to_state == "READY"
            else None
        )

        transition_row = self._audit_row(
            req=req,
            audit_id=audit_id,
            previous_state=obj.state,
            next_state=edge.to_state,
            result="OK",
            error_code=None,
            created_at=now_text,
            plan_id=plan_id,
            plan_hash=plan_hash,
        )
        invalidation_rows: tuple[InvalidationRow, ...] = ()
        if edge.guard_id is GuardId.STALE_CAUSE_PRESENT:
            invalidation_rows = tuple(
                InvalidationRow(
                    invalidation_id=str(uuid.uuid4()),
                    task_id=req.task_id,
                    node_id=req.obj_id,
                    evidence_id=evidence_id,
                    reason_code=req.reason_code,
                    cause_type=req.ctx.cause_type or "",
                    cause_ref=req.ctx.cause_ref,
                    plan_id=req.ctx.plan_id,
                    plan_hash=req.ctx.plan_hash,
                    created_at=now_text,
                )
                for evidence_id in req.ctx.evidence_ids
            )

        try:
            with self._repos.uow.immediate():
                current = self._read_state(req)
                if current != obj.state:
                    raise _ConcurrentModification(current)

                if invalidation_rows:
                    self._repos.evidence._append_invalidations(
                        invalidation_rows, capability=STATE_MACHINE_WRITE
                    )
                # 先审计、后改状态：DB 触发器要求同事务 OK 审计已存在。
                self._repos.audit._append(transition_row, capability=STATE_MACHINE_WRITE)
                if invalidation_rows:
                    self._repos.audit._append(
                        self._audit_row(
                            req=req,
                            audit_id=str(uuid.uuid4()),
                            previous_state=obj.state,
                            next_state=edge.to_state,
                            result="OK",
                            error_code=None,
                            created_at=now_text,
                            plan_id=plan_id,
                            plan_hash=plan_hash,
                            action="NODE_INVALIDATED",
                        ),
                        capability=STATE_MACHINE_WRITE,
                    )

                if req.obj_type is ObjectType.TASK:
                    rowcount = self._repos.tasks._apply_transition(
                        task_id=req.task_id,
                        expected_from=obj.state,
                        to_state=edge.to_state,
                        updated_at=now_text,
                        graph_version=graph_version,
                        capability=STATE_MACHINE_WRITE,
                    )
                else:
                    rowcount = self._repos.nodes._apply_transition(
                        task_id=req.task_id,
                        node_id=req.obj_id,
                        expected_from=obj.state,
                        to_state=edge.to_state,
                        updated_at=now_text,
                        attempt_seq_delta=attempt_delta,
                        plan_id=plan_id,
                        plan_hash=plan_hash,
                        capability=STATE_MACHINE_WRITE,
                    )
                if rowcount != 1:
                    raise _ConcurrentModification(self._read_state(req))
        except DirectStateWriteDenied as exc:
            raise _Denial(
                ReasonCode.ROLE_NOT_ALLOWED,
                details="仓储拒绝非 StateMachine 写入",
            ) from exc
        except sqlite3.IntegrityError as exc:
            raise _Denial(
                ReasonCode.GUARD_FAILED,
                details=f"数据库约束/触发器拒绝：{exc}",
            ) from exc
        except sqlite3.OperationalError as exc:
            raise _Denial(
                ReasonCode.WRITE_LOCK_TIMEOUT,
                details="写锁超时或数据库不可写",
            ) from exc

        attempt_seq = None
        if req.obj_type is ObjectType.NODE and attempt_delta:
            refreshed = self._repos.nodes.get(req.task_id, req.obj_id)
            attempt_seq = refreshed.attempt_seq if refreshed is not None else None

        return TransitionResult(
            ok=True,
            obj_type=req.obj_type,
            obj_id=req.obj_id,
            previous_state=obj.state,
            next_state=edge.to_state,
            audit_id=audit_id,
            applied_at=now_text,
            correlation_id=req.ctx.correlation_id,
            attempt_seq=attempt_seq,
            plan_id=plan_id,
            plan_hash=plan_hash,
        )

    # -- 4. 失败审计 ------------------------------------------------------
    def _deny(
        self,
        request: "_Request",
        denial: _Denial,
        received_at: datetime,
    ) -> NoReturn:
        # 先确保没有悬挂事务；状态事务在这里之前已回滚。
        self._repos.uow.rollback_if_needed()
        req = request
        actual_state = denial.previous_state
        if (
            req.obj_type in (ObjectType.TASK, ObjectType.NODE)
            and req.task_id
            and req.ctx is not None
        ):
            try:
                actual_state = self._read_state(req)
            except Exception:  # noqa: BLE001 - 审计优先，不掩盖原始拒绝
                actual_state = denial.previous_state or req.ctx.previous_state
        previous_state = actual_state or (
            req.ctx.previous_state if req.ctx is not None else None
        )
        next_state = req.to_state or denial.next_state
        audit_id = str(uuid.uuid4())
        row = self._audit_row(
            req=req,
            audit_id=audit_id,
            previous_state=previous_state or AUDIT_UNKNOWN,
            next_state=next_state or AUDIT_SENTINEL,
            result="DENIED",
            error_code=denial.error_code,
            created_at=format_utc(self._clock.now()),
            plan_id=req.ctx.plan_id if req.ctx is not None else None,
            plan_hash=req.ctx.plan_hash if req.ctx is not None else None,
            reason_code=denial.reason,
        )
        try:
            with self._repos.uow.immediate():
                self._repos.audit._append(row, capability=STATE_MACHINE_WRITE)
        except Exception as exc:  # noqa: BLE001 - 二次失败必须降级
            self._degrade_audit(row, denial)
            raise AuditWriteFailed(
                original_error_code=denial.error_code,
                correlation_id=req.ctx.correlation_id if req.ctx is not None else None,
            ) from exc

        raise StateTransitionDenied(
            error_code=denial.error_code,
            reason=denial.reason,
            obj_type=req.obj_type.value if req.obj_type is not None else "unknown",
            obj_id=req.obj_id,
            previous_state=previous_state,
            next_state=next_state,
            correlation_id=req.ctx.correlation_id if req.ctx is not None else None,
            audit_id=audit_id,
            details=denial.details,
        )

    def _audit_row(
        self,
        *,
        req: "_Request",
        audit_id: str,
        previous_state: str | None,
        next_state: str | None,
        result: str,
        error_code: str | None,
        created_at: str,
        plan_id: str | None,
        plan_hash: str | None,
        action: str = "STATE_TRANSITION",
        reason_code: ReasonCode | str | None = None,
    ) -> AuditRow:
        reason = reason_code
        if reason is None:
            reason = req.reason_code
        if isinstance(reason, ReasonCode):
            reason = reason.value
        rule_version = req.ctx.rule_version if req.ctx is not None else None
        correlation_id = req.ctx.correlation_id if req.ctx is not None else None
        if result == "DENIED":
            # 失败审计必须可写入：缺字段用显式哨兵，不用 NULL。
            rule_version = rule_version or AUDIT_SENTINEL
            correlation_id = correlation_id or AUDIT_SENTINEL
        # audit_log 的 plan 字段成对约束：只有 plan_id/plan_hash 都有效才落库；
        # 只有一半时宁可都不写，也不要让 DENIED 审计因 CHECK 失败而丢失。
        if (plan_id is None) != (plan_hash is None):
            plan_id = None
            plan_hash = None
        return AuditRow(
            audit_id=audit_id,
            task_id=req.task_id,
            node_id=req.node_id,
            actor=req.actor.audit_value if req.actor is not None else "unknown:unknown",
            action=action,
            previous_state=previous_state,
            next_state=next_state,
            reason_code=str(reason) if reason else None,
            rule_version=rule_version,
            correlation_id=correlation_id,
            plan_id=plan_id,
            plan_hash=plan_hash,
            result=result,
            error_code=error_code,
            created_at=created_at,
        )

    def _degrade_audit(self, row: AuditRow, denial: _Denial) -> None:
        """DENIED 审计也失败：单行 JSON 到 stderr；不含堆栈/SQL/路径/密钥。"""
        payload = {
            "event": "AUDIT_WRITE_FAILED",
            "audit_write_failed": True,
            "error_code": "AUDIT_WRITE_FAILED",
            "original_error_code": denial.error_code,
            "original_reason_code": denial.reason.value,
            "audit_id": row.audit_id,
            "task_id": row.task_id,
            "node_id": row.node_id,
            "actor": row.actor,
            "action": row.action,
            "previous_state": row.previous_state,
            "next_state": row.next_state,
            "reason_code": row.reason_code,
            "rule_version": row.rule_version,
            "correlation_id": row.correlation_id,
            "created_at": row.created_at,
        }
        sys.stderr.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        sys.stderr.flush()

    def _read_state(self, req: "_Request") -> str:
        if req.obj_type is ObjectType.TASK:
            return self._repos.tasks.get_state(req.task_id)
        assert req.task_id is not None and req.node_id is not None
        return self._repos.nodes.get_state(req.task_id, req.node_id)


@dataclass(slots=True)
class _Request:
    obj_type: ObjectType | None
    obj_id: str
    to_state: str
    actor: Actor | None
    reason_code: str
    ctx: TransitionContext | None
    received_at: datetime
    task_id: str | None
    node_id: str | None


# ---------------------------------------------------------------------------
# 4. 自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
def assert_single_write_entrypoint() -> list[str]:
    problems: list[str] = []
    if StateMachine.PUBLIC_WRITE_ENTRYPOINTS != ("transition",):
        problems.append("StateMachine 只能声明 transition 为公开写入口")
    public_callables = [
        name
        for name in dir(StateMachine)
        if not name.startswith("_") and callable(getattr(StateMachine, name, None))
    ]
    for name in public_callables:
        if name not in StateMachine.PUBLIC_WRITE_ENTRYPOINTS:
            problems.append(f"StateMachine 多出公开可调用入口：{name}")
    for cls in (TaskRepository, NodeRepository, EvidenceMetaRepository):
        for method in ("update", "set_state", "save", "delete"):
            if hasattr(cls, method):
                problems.append(f"{cls.__name__} 暴露了裸写方法 {method}")
    return problems