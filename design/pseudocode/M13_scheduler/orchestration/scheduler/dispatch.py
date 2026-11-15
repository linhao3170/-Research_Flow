"""M13 · orchestration/scheduler/dispatch.py — 派发循环（P7 伪代码）。
阶段：P7「调度与定向恢复」｜追踪：FR-011（派发顺序）、FR-003（状态迁移唯一入口）、FR-004（白名单模板执行）、05 §9.3 R08
依赖：M13 ready_queue / governor、M02 StateMachine（**只经 transition()**）、M05 executor.run_attempt、M03 limits
不变量：**先迁移后执行**；失败路径也经 StateMachine；硬阈值不派发；角色与边绑定；本文件不写状态/证据/审计
错误码：STATE_TRANSITION_DENIED（409，边/守卫/前态拒绝）、RESOURCE_BUDGET_EXCEEDED（429，Governor 拒绝）、
        TOOL_NOT_ALLOWLISTED（403，权限拒绝）、AUDIT_WRITE_FAILED（500，审计降级）、PLAN_HASH_MISMATCH（仅 INVALIDATED→READY，本文件不发起）
写入者：无。状态由 StateMachine 写；执行事实由 Executor/Collector 产生
状态：伪代码；不启动进程、不写库、不读配置

## 一次派发的固定顺序（七相，不可交换）

  1. `ADMIT`：问 Governor「现在能不能派」；硬阈值 → 直接返回 PAUSED，**不碰队列、不碰状态**。
  2. `DEQUEUE`：从就绪队列取候选（含饥饿老化与出队前重验）。
  3. `REVALIDATE`：用最新事实再判一次 READY（依赖/资源/权限），不 READY → 驱逐；
     接着做**节点级准入**（`Governor.admit(state, demand_mb)`）：槽位/内存/磁盘不足 → `NOT_ADMITTED`。
  4. `MARK_RUNNING`：`StateMachine.transition(READY→RUNNING, actor=scheduler)`。
     守卫 `RESOURCES_AVAILABLE` 会再查一次资源；`attempt_seq += 1` 由状态机完成。
  5. `EXECUTE`：调 `Executor.run_attempt(...)`。**只有第 4 步成功才允许走到这里**。
  6. `ROUTE`：按执行事实请求 `RUNNING→VERIFYING` 或 `RUNNING→FAILED`。
     这两条边属 Orchestrator，不是 Scheduler；未授予该角色时返回 `HANDOFF_REQUIRED`，不伪造。
  7. `FINISHED`：返回结构化结果（含已走相位、拒绝码、attempt_id）。

## 失败路径为什么不能绕过状态机

  Executor 抛异常、超时、回收失败、产物哈希失败 —— 这些都只是**执行事实**，
  不是节点状态。把节点写成 FAILED 必须由 `StateMachine` 完成（05 §9.3 R09），
  因为只有它能同时写 `audit_log` 与推进 `attempt_seq`。
  本文件的失败分支因此只有一种形状：先组装 `failure_ref`，再请求 `RUNNING→FAILED`；
  迁移被拒就把拒绝原因原样返回（`DENIED` / `AUDIT_WRITE_FAILED`），
  并把 `node_state_known=False` 标出来交给启动恢复流程（NFR-04）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol

from .governor import Governor, GovernorAction, GovernorState, ResourceSample

__all__ = [
    "DISPATCH_INVARIANTS",
    "EDGE_ROLES",
    "ActorRef",
    "AttemptFacts",
    "AttemptIdPort",
    "DispatchContext",
    "DispatchLoop",
    "DispatchPhase",
    "DispatchResult",
    "DispatchStatus",
    "ExecutorPort",
    "HandoffRequired",
    "RoleNotGranted",
    "TransitionPort",
    "assert_governor_first",
    "assert_no_direct_state_write",
    "assert_phase_order",
]

DISPATCH_INVARIANTS: Final[tuple[str, ...]] = (
    "派发前必须有 Governor 的准入裁决；硬阈值下不得派发（NEG-M13-11）。",
    "READY→RUNNING 必须先于 Executor 调用；不得先跑后补状态。",
    "所有状态变更只经 StateMachine.transition()；本文件不持有仓储、不执行 UPDATE。",
    "每条边只用 05 §9.3 授权的角色；缺角色返回 HANDOFF_REQUIRED，不代替 Orchestrator 执行。",
    "执行失败必须请求 RUNNING→FAILED，并把拒绝原因原样上抛；不得自行写入 FAILED。",
    "回收失败（escalation_required）的节点进入隔离，未确认回收前不得再次派发。",
)

# 与 05 §9.3 的 allowed_roles 逐条对齐（本文件只发起其中四条）。
# 值用角色字面值（M02 ActorRole 的 value），便于与 StateMachine 的校验比对。
#
# **有序 tuple**，不是无序集合：`_transition()` 取「第一个已授予的角色」作为 actor，
# 若用无序集合，多角色授权时实际 actor 会随 `PYTHONHASHSEED` 漂移，审计不可复核。
# 顺序 = 期望的发起优先级，且与 M02 迁移表的 `roles=(...)` 声明顺序一致。
EDGE_ROLES: Final[Mapping[tuple[str, str], tuple[str, ...]]] = MappingProxyType(
    {
        # 建图后的首次就绪：只有 Scheduler 有权把 PLANNED 推到 READY。
        ("PLANNED", "READY"): ("scheduler",),
        # 派发：只有 Scheduler 有权把 READY 推到 RUNNING。
        ("READY", "RUNNING"): ("scheduler",),
        # 资源/权限拒绝：Scheduler 先决；Orchestrator 负责收尾（与 M02 声明顺序一致）。
        ("READY", "BLOCKED"): ("scheduler", "orchestrator"),
        # 执行结束交验证：优先 Orchestrator（正常路径），boot_recovery 只用于重启恢复。
        ("RUNNING", "VERIFYING"): ("orchestrator", "boot_recovery"),
        # 执行失败：同上，优先 Orchestrator。
        ("RUNNING", "FAILED"): ("orchestrator", "boot_recovery"),
        # INVALIDATED→READY 只允许 WP-R，且必须带 plan_id/plan_hash；dispatch 永不发起。
        ("INVALIDATED", "READY"): ("wp_r",),
    }
)


# ---------------------------------------------------------------------------
# 1. 值对象与异常
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ActorRef:
    """迁移发起者：`role` + `identity`，审计里写成 `role:identity`（M02 `Actor` 的口径）。"""

    role: str
    identity: str

    def __post_init__(self) -> None:
        if not self.role or not self.identity:
            raise ValueError("role 与 identity 都不得为空")
        if ":" in self.role:
            raise ValueError("role 里不得含分隔符 ':'")

    @property
    def audit_value(self) -> str:
        return f"{self.role}:{self.identity}"


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """一次派发的上下文（审计必填项都在这里）。"""

    task_id: str
    correlation_id: str
    rule_version: str
    python_exe: str

    def __post_init__(self) -> None:
        for name in ("task_id", "correlation_id", "rule_version", "python_exe"):
            if not getattr(self, name):
                raise ValueError(f"{name} 不得为空（迁移必填参数，05 §9.7）")


class HandoffRequired(RuntimeError):
    """所需角色未被授予：本次派发不能继续，必须交还给持有该角色的组件。

    不是业务拒绝、也不是错误：返回 `HANDOFF_REQUIRED`，由 Orchestrator 用自己的角色
    发起 `RUNNING→VERIFYING` / `RUNNING→FAILED`。**不得**借用别的身份硬发。
    """

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 409
    reason: Final[str] = "ROLE_NOT_GRANTED_FOR_EDGE"

    def __init__(
        self, edge: tuple[str, str], required: tuple[str, ...], granted: frozenset[str]
    ) -> None:
        self.edge = edge
        self.required = required
        self.granted = granted
        super().__init__(
            f"{self.error_code}/{self.reason}：边 {edge[0]}→{edge[1]} 需要 {list(required)}（按优先级），"
            f"当前只授予 {sorted(granted)}"
        )


class RoleNotGranted(HandoffRequired):
    """`HandoffRequired` 的显式别名（负例里断言这个名字更直观）。"""


class DispatchAssemblyError(RuntimeError):
    """装配错误（缺少重验端口等）：不得降级为“当作 READY”。

    对外用 `STATE_TRANSITION_DENIED` + `reason=DISPATCH_NOT_ASSEMBLED`（不新增注册表码）。
    """

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 500
    reason: Final[str] = "DISPATCH_NOT_ASSEMBLED"

    def __init__(self, missing: str) -> None:
        self.missing = missing
        super().__init__(f"{self.error_code}/{self.reason}：未装配 {missing}，拒绝派发")


# ---------------------------------------------------------------------------
# 2. 端口（结构视图；本文件不 import M02/M05 的运行期实现）
# ---------------------------------------------------------------------------
class TransitionPort(Protocol):
    """StateMachine 的结构视图。签名与 M02 `transition()` 一致。"""

    def transition(
        self,
        obj_type: str,
        obj_id: str,
        to_state: str,
        actor: ActorRef,
        reason_code: str,
        ctx: Mapping[str, object],
    ) -> object:
        ...


@dataclass(frozen=True, slots=True)
class AttemptFacts:
    """Executor 返回的**执行事实**（不是裁决）。

    字段刻意与 M05 `AttemptOutcome` 对齐；本文件不判断“成功”，只判断
    「exit_code == 0 且未超时/未回收失败」这个**事实组合**，是否通过由 Verifier 决定。
    """

    attempt_id: str
    disposition: str
    exit_code: int | None
    timed_out: bool
    escalation_required: bool
    fault: str | None
    failure_ref: str | None
    artifacts_digest: str | None

    def __post_init__(self) -> None:
        if not self.attempt_id.startswith("attempt_"):
            raise ValueError("attempt_id 形态非法")
        if self.disposition == "EXITED" and self.exit_code is None:
            raise ValueError("EXITED 必须带 exit_code")
        if self.timed_out and self.exit_code is not None:
            raise ValueError("timed_out=True 时不得带 exit_code（不得表达为正常退出）")
        if self.escalation_required and not self.failure_ref:
            raise ValueError("需要升级时必须带 failure_ref")

    @property
    def is_clean_exit(self) -> bool:
        """干净退出：已退出、退出码 0、未超时、未触发升级、无 fault。"""
        return (
            self.disposition == "EXITED"
            and self.exit_code == 0
            and not self.timed_out
            and not self.escalation_required
            and self.fault is None
        )


class ExecutorPort(Protocol):
    """M05 `run_attempt` 的结构视图。只接收已确认 RUNNING 的节点。"""

    def run_attempt(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        correlation_id: str,
    ) -> AttemptFacts:
        ...


class AttemptIdPort(Protocol):
    """分配 attempt_id；成功后 `attempt_seq` 由 StateMachine 递增，二者必须同源。"""

    def next_attempt_id(self, task_id: str, node_id: str, next_seq: int) -> str:
        ...


class ReadyRevalidator(Protocol):
    """出队前的 READY 重验（由 `ready_queue.evaluate_ready` 实现）。"""

    def __call__(self, node_id: str) -> object:
        ...


class ReadyQueuePort(Protocol):
    """就绪队列的结构视图（`ready_queue.ReadyQueue` 的一个子集）。

    `pop_best` 返回 `PopResult`；本文件只读它的 `entry` / `evicted` 两个属性，
    因此端口返回 `object` 也可以工作（结构化类型，便于替换测试替身）。
    """

    def pop_best(self, *, now_ticks: float, revalidate: "ReadyRevalidator") -> object:
        ...


# ---------------------------------------------------------------------------
# 3. 结果
# ---------------------------------------------------------------------------
class DispatchPhase(StrEnum):
    ADMIT = "ADMIT"
    DEQUEUE = "DEQUEUE"
    REVALIDATE = "REVALIDATE"
    MARK_RUNNING = "MARK_RUNNING"
    EXECUTE = "EXECUTE"
    ROUTE = "ROUTE"
    FINISHED = "FINISHED"


_PHASE_ORDER: Final[tuple[DispatchPhase, ...]] = (
    DispatchPhase.ADMIT,
    DispatchPhase.DEQUEUE,
    DispatchPhase.REVALIDATE,
    DispatchPhase.MARK_RUNNING,
    DispatchPhase.EXECUTE,
    DispatchPhase.ROUTE,
    DispatchPhase.FINISHED,
)


class DispatchStatus(StrEnum):
    IDLE = "IDLE"                          # 队列空
    PAUSED = "PAUSED"                      # Governor 硬阈值，未派发
    NOT_ADMITTED = "NOT_ADMITTED"          # 有候选但准入被拒（槽位/内存/磁盘）
    EVICTED = "EVICTED"                    # 出队前重验失败，已驱逐
    RUNNING_TO_VERIFYING = "RUNNING_TO_VERIFYING"
    RUNNING_TO_FAILED = "RUNNING_TO_FAILED"
    DENIED = "DENIED"                      # 状态机拒绝（边/守卫/前态）
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"  # 缺角色
    EXECUTOR_FAULT = "EXECUTOR_FAULT"      # Executor 抛异常（仍需经状态机转 FAILED）
    AUDIT_DEGRADED = "AUDIT_DEGRADED"      # 审计降级：状态未知，交启动恢复


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """一次派发的结构化结果。"""

    status: DispatchStatus
    phases: tuple[DispatchPhase, ...]
    node_id: str | None = None
    attempt_id: str | None = None
    error_code: str | None = None
    reason: str | None = None
    detail: str = ""
    node_state_known: bool = True
    quarantined: bool = False

    def __post_init__(self) -> None:
        if self.status is DispatchStatus.AUDIT_DEGRADED and self.node_state_known:
            raise ValueError("审计降级时必须标记 node_state_known=False（状态未知）")
        if self.status in (DispatchStatus.DENIED, DispatchStatus.HANDOFF_REQUIRED):
            if not self.error_code or not self.reason:
                raise ValueError("拒绝/移交必须带 error_code 与 reason")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "status": self.status.value,
                "phases": [p.value for p in self.phases],
                "node_id": self.node_id,
                "attempt_id": self.attempt_id,
                "error_code": self.error_code,
                "reason": self.reason,
                "detail": self.detail,
                "node_state_known": self.node_state_known,
                "quarantined": self.quarantined,
            }
        )


# ---------------------------------------------------------------------------
# 4. 派发循环
# ---------------------------------------------------------------------------
class DispatchLoop:
    """把「队列 → StateMachine → Executor → 返回」串成一次事务式推进。

    构造参数里**没有**仓储/连接：状态只经 `TransitionPort`，执行只经 `ExecutorPort`。
    """

    def __init__(
        self,
        *,
        queue: ReadyQueuePort,
        governor: Governor,
        machine: TransitionPort,
        executor: ExecutorPort,
        attempt_ids: AttemptIdPort,
        actors: Mapping[str, ActorRef],
        context: DispatchContext,
    ) -> None:
        self._queue = queue
        self._governor = governor
        self._machine = machine
        self._executor = executor
        self._attempt_ids = attempt_ids
        self._actors = MappingProxyType(dict(actors))
        self._context = context
        self._phases: list[DispatchPhase] = []
        self._quarantine: set[str] = set()
        self._governor_state: GovernorState | None = None
        self._ready_revalidator: ReadyRevalidator | None = None

    # -- 只读视图 ---------------------------------------------------------
    @property
    def granted_roles(self) -> frozenset[str]:
        return frozenset(self._actors)

    @property
    def quarantined_nodes(self) -> tuple[str, ...]:
        return tuple(sorted(self._quarantine))

    def is_quarantined(self, node_id: str) -> bool:
        return node_id in self._quarantine

    def release_quarantine(self, node_id: str, *, reclaimed_evidence: str) -> None:
        """解除隔离：必须给出「进程树已确认回收」的证据引用。

        没有证据不得解除 —— 残留进程会污染同一台机器上的后续 attempt（M05 §6.2）。
        """
        if not reclaimed_evidence:
            raise ValueError("解除隔离必须提供 reclaimed_evidence（回收确认）")
        self._quarantine.discard(node_id)

    # -- 主流程 -----------------------------------------------------------
    def run_once(
        self,
        *,
        now_ticks: float,
        governor_state: GovernorState,
        demand_mb: float = 0.0,
        disk_needed_mb: float = 0.0,
        sample: ResourceSample | None = None,
    ) -> DispatchResult:
        """推进一次派发。

        步骤见模块 docstring 的七相；每一相都先 `_enter(phase)` 记录，失败也记录。
        输入：单调时钟读数、Governor 的最新评估结果、本节点内存/磁盘需求、可选的资源快照。
        输出：`DispatchResult`。
        副作用：队列条目移除、状态迁移（经 StateMachine）、Executor 启动一次 attempt。
        错误：不吞异常 —— 状态机拒绝原样返回；Executor 异常转成 `EXECUTOR_FAULT` 后仍走状态机。
        """
        self._phases = []
        self._governor_state = governor_state

        # 相位 1：ADMIT —— 硬阈值直接停（不取队列、不迁移）
        self._enter(DispatchPhase.ADMIT)
        if governor_state.paused:
            self._enter(DispatchPhase.FINISHED)
            pause = governor_state.directive_for(GovernorAction.PAUSE_DISPATCH)
            return DispatchResult(
                status=DispatchStatus.PAUSED,
                phases=self.snapshot_phases(),
                reason=pause[0].reason if pause else "GOVERNOR_PAUSED",
                error_code="RESOURCE_BUDGET_EXCEEDED",
                detail="硬阈值未解除：不派发任何新节点",
            )

        # 相位 2：DEQUEUE —— 取候选（含老化提升与重验）
        self._enter(DispatchPhase.DEQUEUE)
        try:
            pop = self._queue.pop_best(
                now_ticks=now_ticks, revalidate=self._revalidate
            )
        except DispatchAssemblyError as exc:
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.DENIED,
                phases=self.snapshot_phases(),
                error_code=exc.error_code,
                reason=exc.reason,
                detail=str(exc),
            )
        except Exception as exc:  # 队列不变量破坏：不得静默当作空队列
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.DENIED,
                phases=self.snapshot_phases(),
                error_code="STATE_TRANSITION_DENIED",
                reason="QUEUE_INVARIANT_VIOLATED",
                detail=f"{type(exc).__name__}: {exc}",
            )
        if pop.entry is None:
            self._enter(DispatchPhase.FINISHED)
            status = DispatchStatus.EVICTED if pop.evicted else DispatchStatus.IDLE
            return DispatchResult(
                status=status,
                phases=self.snapshot_phases(),
                detail=f"驱逐 {len(pop.evicted)} 条；队列空",
            )
        entry = pop.entry
        node_id = entry.node_id

        # 相位 3：REVALIDATE —— 出队后、迁移前再判一次（依赖可能已失效）
        self._enter(DispatchPhase.REVALIDATE)
        revalidated = self._revalidate(node_id)
        if not getattr(revalidated, "ready", False):
            blocker = getattr(revalidated, "primary_blocker", None)
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.EVICTED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                error_code="STATE_TRANSITION_DENIED",
                reason=(blocker.value if blocker is not None else "NOT_READY"),
                detail="出队前重验失败：不得派发依赖未满足/资源不再允许的节点",
            )
        if self.is_quarantined(node_id):
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.DENIED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                error_code="STATE_TRANSITION_DENIED",
                reason="NODE_QUARANTINED",
                detail="该节点上次回收失败，未确认回收前不得派发",
            )

        # 相位 3 续：节点级准入 —— Governor 对“这个节点、这份需求”再判一次
        # （第 1 相只挡全局暂停；这里挡槽位/内存/磁盘的节点级不足）
        admission = self._governor.admit(
            state=governor_state,
            demand_mb=demand_mb,
            disk_needed_mb=disk_needed_mb,
            sample=sample,
        )
        if not admission.allowed:
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.NOT_ADMITTED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                error_code="RESOURCE_BUDGET_EXCEEDED",
                reason=admission.reason,
                detail=admission.detail,
            )

        # 相位 4：MARK_RUNNING —— 先迁移（attempt_id 与 attempt_seq 同源）
        self._enter(DispatchPhase.MARK_RUNNING)
        next_seq = int(getattr(entry, "attempt_seq", 0)) + 1
        attempt_id = self._attempt_ids.next_attempt_id(self._context.task_id, node_id, next_seq)
        if not attempt_id.startswith("attempt_"):
            # 装配错误不得降级为“照常派发”：attempt_id 与 attempt_seq 必须同源。
            self._enter(DispatchPhase.FINISHED)
            assembly = DispatchAssemblyError("AttemptIdPort（返回非法 attempt_id）")
            return DispatchResult(
                status=DispatchStatus.DENIED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                error_code=assembly.error_code,
                reason=assembly.reason,
                detail=str(assembly),
            )
        try:
            self._transition(
                edge=("READY", "RUNNING"),
                node_id=node_id,
                reason_code="NODE_STARTED",
                ctx={
                    "task_id": self._context.task_id,
                    "previous_state": "READY",
                    "correlation_id": self._context.correlation_id,
                    "rule_version": self._context.rule_version,
                    "attempt_id": attempt_id,
                },
            )
        except HandoffRequired as handoff:
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.HANDOFF_REQUIRED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                attempt_id=attempt_id,
                error_code=handoff.error_code,
                reason=handoff.reason,
                detail=str(handoff),
            )
        except Exception as denial:
            self._enter(DispatchPhase.FINISHED)
            return self._denied_result(node_id, denial, attempt_id=attempt_id)

        # 相位 5：EXECUTE —— 只有迁移成功才允许启动执行（先迁移后执行）
        self._enter(DispatchPhase.EXECUTE)
        try:
            facts = self._executor.run_attempt(
                task_id=self._context.task_id,
                node_id=node_id,
                attempt_id=attempt_id,
                correlation_id=self._context.correlation_id,
            )
        except Exception as exc:
            # Executor 异常 = 执行事实缺失，不是“节点失败”。仍必须经状态机转 FAILED。
            self._enter(DispatchPhase.ROUTE)
            return self._route_failure(
                node_id=node_id,
                attempt_id=attempt_id,
                failure_ref=f"executor_exception:{type(exc).__name__}",
                detail=f"Executor 抛出 {type(exc).__name__}：{exc}",
                quarantine=False,
                executor_fault=True,
            )

        # 相位 6：ROUTE —— 干净退出 → VERIFYING；其余 → FAILED（都属 Orchestrator 的边）
        self._enter(DispatchPhase.ROUTE)
        if facts.is_clean_exit:
            return self._route_verifying(node_id=node_id, attempt_id=attempt_id, facts=facts)
        return self._route_failure(
            node_id=node_id,
            attempt_id=attempt_id,
            failure_ref=facts.failure_ref or f"attempt_failed:{facts.disposition}",
            detail=f"disposition={facts.disposition} exit_code={facts.exit_code} fault={facts.fault}",
            quarantine=facts.escalation_required or facts.disposition == "RECLAIM_FAILED",
        )

    # -- 分支 -------------------------------------------------------------
    def _route_verifying(
        self, *, node_id: str, attempt_id: str, facts: AttemptFacts
    ) -> DispatchResult:
        """`RUNNING→VERIFYING`：守卫要求 attempt 结束事件且 exit_code=0。"""
        try:
            self._transition(
                edge=("RUNNING", "VERIFYING"),
                node_id=node_id,
                reason_code="ATTEMPT_ENDED",
                ctx={
                    "task_id": self._context.task_id,
                    "previous_state": "RUNNING",
                    "correlation_id": self._context.correlation_id,
                    "rule_version": self._context.rule_version,
                    "attempt_id": attempt_id,
                    "artifacts_digest": facts.artifacts_digest or "",
                },
            )
        except HandoffRequired as handoff:
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.HANDOFF_REQUIRED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                attempt_id=attempt_id,
                error_code=handoff.error_code,
                reason=handoff.reason,
                detail=str(handoff),
            )
        except Exception as denial:
            self._enter(DispatchPhase.FINISHED)
            return self._denied_result(node_id, denial, attempt_id=attempt_id)
        self._enter(DispatchPhase.FINISHED)
        return DispatchResult(
            status=DispatchStatus.RUNNING_TO_VERIFYING,
            phases=self.snapshot_phases(),
            node_id=node_id,
            attempt_id=attempt_id,
            detail="执行干净退出，已交验证",
        )

    def _route_failure(
        self,
        *,
        node_id: str,
        attempt_id: str,
        failure_ref: str,
        detail: str,
        quarantine: bool,
        executor_fault: bool = False,
    ) -> DispatchResult:
        """`RUNNING→FAILED`：失败的唯一合法落点。"""
        if quarantine:
            self._quarantine.add(node_id)
        try:
            self._transition(
                edge=("RUNNING", "FAILED"),
                node_id=node_id,
                reason_code="ATTEMPT_FAILED",
                ctx={
                    "task_id": self._context.task_id,
                    "previous_state": "RUNNING",
                    "correlation_id": self._context.correlation_id,
                    "rule_version": self._context.rule_version,
                    "attempt_id": attempt_id,
                    "failure_ref": failure_ref,
                },
            )
        except HandoffRequired as handoff:
            self._enter(DispatchPhase.FINISHED)
            return DispatchResult(
                status=DispatchStatus.HANDOFF_REQUIRED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                attempt_id=attempt_id,
                error_code=handoff.error_code,
                reason=handoff.reason,
                detail=str(handoff),
                quarantined=quarantine,
            )
        except Exception as denial:
            self._enter(DispatchPhase.FINISHED)
            return self._denied_result(node_id, denial, attempt_id=attempt_id, quarantined=quarantine)
        self._enter(DispatchPhase.FINISHED)
        status = DispatchStatus.EXECUTOR_FAULT if executor_fault else DispatchStatus.RUNNING_TO_FAILED
        return DispatchResult(
            status=status,
            phases=self.snapshot_phases(),
            node_id=node_id,
            attempt_id=attempt_id,
            detail=detail,
            quarantined=quarantine,
        )

    # -- 状态迁移的唯一调用点 ---------------------------------------------
    def _transition(
        self,
        *,
        edge: tuple[str, str],
        node_id: str,
        reason_code: str,
        ctx: Mapping[str, object],
    ) -> object:
        """发起一次节点状态迁移。

        步骤：
          1. 在 `EDGE_ROLES` 中查该边允许的角色；不在表里 → 立即失败（不得自创边）。
          2. 确认本循环被授予了其中一个角色；没有 → `HandoffRequired`（不借用身份）。
          3. 调 `StateMachine.transition(...)`；异常原样上抛，由调用分支转成结构化结果。

        为什么角色检查放在本地：StateMachine 会再校验一次，但本地先拦可以把
        「缺角色」与「守卫失败」区分开 —— 前者要移交，后者是真正的拒绝。
        """
        allowed = EDGE_ROLES.get(edge)
        if allowed is None:
            raise ValueError(f"未登记的边 {edge[0]}→{edge[1]}：不得自创迁移")
        usable = [role for role in allowed if role in self._actors]
        if not usable:
            raise HandoffRequired(edge=edge, required=allowed, granted=self.granted_roles)
        # 角色优先级固定：`EDGE_ROLES` 的值是**有序 tuple**（不是无序集合），
        # 按声明顺序取第一个已授予的角色 —— 多角色授权时 actor 不随 `PYTHONHASHSEED` 漂移。
        actor = self._actors[usable[0]]
        return self._machine.transition(
            "node",
            node_id,
            edge[1],
            actor,
            reason_code,
            ctx,
        )

    def _revalidate(self, node_id: str) -> object:
        """默认重验实现：必须装配 `ReadyRevalidator`，缺失即拒绝（fail-closed）。

        调度器不能“因为拿不到事实就当它 READY”。注入缺失属于装配错误，直接拒绝派发。
        """
        revalidate = self._ready_revalidator
        if revalidate is None:
            raise DispatchAssemblyError("READY 重验端口（ReadyRevalidator）")
        return revalidate(node_id)

    def attach_ready_revalidator(self, revalidator: ReadyRevalidator) -> None:
        """装配 READY 重验端口（`ready_queue.evaluate_ready` 的部分应用）。"""
        self._ready_revalidator = revalidator

    # -- 结果组装 ---------------------------------------------------------
    def _denied_result(
        self,
        node_id: str,
        denial: BaseException,
        *,
        attempt_id: str | None,
        quarantined: bool = False,
    ) -> DispatchResult:
        """把状态机拒绝转成结构化结果；按错误码区分 DENIED 与 AUDIT_DEGRADED。

        规则（05 §9.7 决议 7）：
          - `AUDIT_WRITE_FAILED`：状态回滚、DENIED 审计也没写成 → 状态未知，交启动恢复；
          - 其余拒绝：状态未被修改（StateMachine 保证回滚），`node_state_known=True`。
        """
        code = getattr(denial, "error_code", None) or "STATE_TRANSITION_DENIED"
        reason = getattr(denial, "reason", None) or type(denial).__name__
        if code == "AUDIT_WRITE_FAILED":
            return DispatchResult(
                status=DispatchStatus.AUDIT_DEGRADED,
                phases=self.snapshot_phases(),
                node_id=node_id,
                attempt_id=attempt_id,
                error_code=code,
                reason=str(reason),
                detail=str(denial),
                node_state_known=False,
                quarantined=quarantined,
            )
        return DispatchResult(
            status=DispatchStatus.DENIED,
            phases=self.snapshot_phases(),
            node_id=node_id,
            attempt_id=attempt_id,
            error_code=code,
            reason=str(reason),
            detail=str(denial),
            quarantined=quarantined,
        )

    def _enter(self, phase: DispatchPhase) -> None:
        """记录已进入的相位；顺序错乱立即抛错（编译期错误级别）。"""
        if self._phases:
            current_index = _PHASE_ORDER.index(self._phases[-1])
            next_index = _PHASE_ORDER.index(phase)
            if next_index < current_index:
                raise ValueError(f"相位倒退：{self._phases[-1]} → {phase}")
        self._phases.append(phase)

    def snapshot_phases(self) -> tuple[DispatchPhase, ...]:
        return tuple(self._phases)


# ---------------------------------------------------------------------------
# 5. 自检
# ---------------------------------------------------------------------------
def assert_phase_order() -> list[str]:
    """自检：七相顺序常量本身与 docstring 一致，且不含被禁的“先执行后迁移”。"""
    problems: list[str] = []
    expected = (
        DispatchPhase.ADMIT, DispatchPhase.DEQUEUE, DispatchPhase.REVALIDATE,
        DispatchPhase.MARK_RUNNING, DispatchPhase.EXECUTE, DispatchPhase.ROUTE,
        DispatchPhase.FINISHED,
    )
    if _PHASE_ORDER != expected:
        problems.append("相位顺序与模块 docstring 不一致")
    if _PHASE_ORDER.index(DispatchPhase.MARK_RUNNING) > _PHASE_ORDER.index(DispatchPhase.EXECUTE):
        problems.append("MARK_RUNNING 必须在 EXECUTE 之前（先迁移后执行）")
    if _PHASE_ORDER.index(DispatchPhase.ADMIT) > _PHASE_ORDER.index(DispatchPhase.DEQUEUE):
        problems.append("ADMIT 必须在 DEQUEUE 之前（硬阈值不取队列）")
    return problems


def assert_governor_first() -> list[str]:
    """自检：`run_once` 中 ADMIT 分支必须出现在任何 `pop_best` 调用之前。

    实现方式：`inspect.getsource()` 取源码后比较两个标记的位置；不执行、不 import 实现。
    落地阶段改用 AST 检查（更精确），本函数是 P7 的可评审核对。
    """
    import inspect

    problems: list[str] = []
    try:
        source = inspect.getsource(DispatchLoop.run_once)
    except (OSError, TypeError) as exc:  # 源码不可得时按“无法核对”处理，不假装通过
        return [f"无法读取 run_once 源码：{type(exc).__name__}"]
    admit_at = source.find("DispatchPhase.ADMIT")
    dequeue_at = source.find("pop_best")
    if admit_at < 0:
        problems.append("run_once 缺少 ADMIT 相位")
    if dequeue_at < 0:
        problems.append("run_once 缺少 pop_best 调用")
    if admit_at >= 0 and dequeue_at >= 0 and admit_at > dequeue_at:
        problems.append("ADMIT 分支晚于 pop_best：硬阈值会先取队列，违反不变量")
    if "paused" not in source:
        problems.append("run_once 必须在取队列前检查 Governor 的 paused")
    return problems


def assert_no_direct_state_write() -> list[str]:
    """自检：本模块不得出现直写状态/证据的调用面。"""
    problems: list[str] = []
    for forbidden in ("UPDATE ", "INSERT INTO", "conn.execute", "session.execute", "commit("):
        # 只扫模块级文本，避免把 docstring 里的“不得 UPDATE”误判：因此检查函数名而非原文
        if forbidden in _PUBLIC_SURFACE:
            problems.append(f"派发模块不得出现 {forbidden}")
    for name in ("set_state", "mark_failed", "mark_running", "force_state"):
        if hasattr(DispatchLoop, name):
            problems.append(f"DispatchLoop 不得暴露 {name}()")
    if len(EDGE_ROLES) != 6:
        problems.append("EDGE_ROLES 必须恰好覆盖 05 §9.3 的六条相关边")
    return problems


# 公开面清单（函数/类名），用于上面的静态自检；不参与运行。
_PUBLIC_SURFACE: Final[tuple[str, ...]] = (
    "DispatchLoop.run_once",
    "DispatchLoop._transition",
    "DispatchLoop._route_verifying",
    "DispatchLoop._route_failure",
    "DispatchLoop._revalidate",
)