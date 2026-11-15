"""M13 · orchestration/scheduler/ready_queue.py — READY 判定与就绪队列（P7 伪代码）。
阶段：P7「调度与定向恢复」｜追踪：FR-011（Ready Scheduler；正式属 T1/G4）、05 §9.3 R07/R08、策划书 §8.5
依赖：M04 GraphContent（dependencies/拓扑序）、M02 StateMachine（**只经 transition()**）、M03 scheduler.yaml、M13 scoring
不变量：依赖未全部 VERIFIED 不得进入 READY；资源或权限任一拒绝不得出队；**出队前重验**（失效/资源可能已变）；
        队列只持有 READY 节点；同一链路上不被新候选插队（饥饿老化提升）
错误码：STATE_TRANSITION_DENIED（409；reason=DEPENDENCIES_UNSATISFIED / RESOURCE_NOT_AVAILABLE / NODE_NOT_READY /
        QUEUE_DUPLICATE_ENTRY / QUEUE_POLICY_INVALID）、CONFIG_*（队列策略配置，503）
写入者：无。本文件不写状态、不写证据、不写审计；状态迁移由 `dispatch` 调 StateMachine 发起
状态：伪代码；不执行、不建表、不派发

## READY 的三合取判定（本文件的核心）

  `READY(n) = 依赖满足(n) ∧ 资源允许(n) ∧ 权限通过(n)`

  三项各自独立求值，**任一项未知也按不满足处理**（fail-closed）：

  | 检查 | 通过条件 | 依据 |
  |---|---|---|
  | 依赖满足 | 全部 `depends_on` 的前驱状态 = `VERIFIED`；`input_refs` 可解析；节点图版本 = 任务图版本 | 05 §9.3 R07 |
  | 资源允许 | 有空闲并发槽；内存/磁盘水位未触发软/硬阈值；预算未耗尽；Governor 未暂停派发 | 05 §9.3 R08；NFR-06 |
  | 权限通过 | 模板已登记且 `node_type` 匹配；路径落在 allowlist；执行角色有权 | FR-004；errors.TOOL_NOT_ALLOWLISTED |

  三者是**合取**，不是打分：不允许「资源差一点但也还行」。分数只决定「都合格时先跑谁」。

## 为什么入队之后还要重验

  节点在 `PLANNED→READY` 时依赖满足，不代表出队时仍满足：上游可能在排队期间被
  `INVALIDATED`、磁盘可能在排队期间写满、Governor 可能已把并发降到 1。
  因此 `pop_best()` 在返回候选**之前**调用 `revalidate`，失败就**驱逐**该条目并继续看下一个，
  绝不把陈旧的就绪状态当成许可。这是「依赖未满足不得派发」的实际落点。

## 饥饿处理（两层，写清各自能证明什么）

  1. **软层**：`SchedScore` 的 Age 项（权重 0.20）。只能“提高概率”，不能作保证 ——
     关键路径长、风险高的节点可能长期压过它。
  2. **硬层**：`starvation_promotion_age_sec`。等待超过该阈值的条目在**可派发**时优先于任何更年轻的条目。
     可证明的保证是：「一旦资源允许，超龄条目先走」；不能证明的是「资源永远会允许」——
     那是 Governor/容量问题，调度器不能承诺。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Callable, Final, Mapping, Protocol, Sequence

from .scoring import (
    NodeScoreFacts,
    ResourceCaps,
    RiskPolicy,
    SchedScore,
    SchedScoreWeights,
    ScoringConfigInvalid,
    ScoringInputInvalid,
    compare_scores,
    compute_score,
)

__all__ = [
    "PROPOSED_STARVATION_PROMOTION_AGE_SEC",
    "QUEUE_INVARIANTS",
    "Eviction",
    "DependencyFactsPort",
    "PermissionFactsPort",
    "PopResult",
    "QueueEntry",
    "QueueInvariantViolated",
    "ReadyBlocker",
    "ReadyDecision",
    "ReadyQueue",
    "ResourceFactsPort",
    "ResourceOffer",
    "SelectionPolicy",
    "StarvationPolicy",
    "assert_queue_boundary",
    "assert_queue_invariants",
    "compare_entries",
    "evaluate_ready",
    "queue_policy_from_config",
]

# 老化提升阈值：`[P7 提议值 · 未校准]`。策划书 §8.5 只说「Age 防止饥饿」，没给阈值。
# 它不是契约、不是验收阈值；缺配置键时**不得**使用它（见 `queue_policy_from_config`）。
PROPOSED_STARVATION_PROMOTION_AGE_SEC: Final[float] = 120.0

QUEUE_INVARIANTS: Final[tuple[str, ...]] = (
    "队列条目必须来自 state=READY 的节点；PLANNED/INVALIDATED/FAILED 一律不得入队。",
    "同一 node_id 在队列中最多一条；重复入队是编程错误，不是幂等。",
    "出队前必须调用 revalidate；revalidate 不通过则驱逐，不得返回该候选。",
    "等待超过 starvation_promotion_age_sec 的条目在可派发时优先于任何更年轻条目。",
    "队列不持有时钟：`now_ticks` 由调用方传入，保证同一快照可用同一时钟重放。",
)


# ---------------------------------------------------------------------------
# 1. 选择策略
# ---------------------------------------------------------------------------
class SelectionPolicy(StrEnum):
    """就绪节点的选择策略。

    `TOPOLOGICAL_ONLY`：完全按 `topological_then_node_id`（M03 `scheduler.yaml: ready_order` 的现值）。
    `SCHED_SCORE`：按 §8.5 的 SchedScore 排序，拓扑序退化为并列裁决。

    **冲突登记（OQ-P7-01）**：M03 的 `ready_order` 是 `const "topological_then_node_id"`，
    并注明「T0 只允许该值；其他排序会破坏可重放性」。而 §8.5 明确要求 SchedScore。
    本文件两种都定义，是因为 M13 不能改 M03 schema；**在 OQ-P7-01 裁决前，
    T0 部署只能配 `TOPOLOGICAL_ONLY`**，否则属越权配置（`queue_policy_from_config` 不拦，
    但落地阶段必须由启动守卫拦，登记在 OQ 里）。
    """

    TOPOLOGICAL_ONLY = "TOPOLOGICAL_ONLY"
    SCHED_SCORE = "SCHED_SCORE"


class ReadyBlocker(StrEnum):
    """「不 READY」的结构化原因。同一节点可同时命中多条。"""

    # 依赖类
    DEPENDENCY_NOT_VERIFIED = "DEPENDENCY_NOT_VERIFIED"      # 前驱不是 VERIFIED
    DEPENDENCY_STATE_UNKNOWN = "DEPENDENCY_STATE_UNKNOWN"    # 查不到前驱状态（数据不一致）
    INPUT_UNRESOLVABLE = "INPUT_UNRESOLVABLE"                # input_refs 解析不到
    GRAPH_VERSION_STALE = "GRAPH_VERSION_STALE"              # 节点图版本 ≠ 任务图版本
    # 资源类
    NO_CONCURRENCY_SLOT = "NO_CONCURRENCY_SLOT"
    MEMORY_SOFT_LIMIT = "MEMORY_SOFT_LIMIT"
    MEMORY_HARD_LIMIT = "MEMORY_HARD_LIMIT"
    DISK_LOW = "DISK_LOW"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    GOVERNOR_PAUSED = "GOVERNOR_PAUSED"                      # Governor 直接暂停派发
    # 权限类
    TEMPLATE_NOT_ALLOWLISTED = "TEMPLATE_NOT_ALLOWLISTED"
    NODE_TYPE_NOT_ALLOWED = "NODE_TYPE_NOT_ALLOWED"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    # 状态/事实类
    NODE_NOT_READY = "NODE_NOT_READY"                        # 当前状态不是 READY
    FACTS_UNAVAILABLE = "FACTS_UNAVAILABLE"                  # 端口读取失败（fail-closed）


# 阻塞原因 → 对应注册表错误码（审计/API 映射用；本文件不抛这些码，只登记映射）
BLOCKER_ERROR_CODES: Final[Mapping[ReadyBlocker, str]] = MappingProxyType(
    {
        ReadyBlocker.DEPENDENCY_NOT_VERIFIED: "STATE_TRANSITION_DENIED",
        ReadyBlocker.DEPENDENCY_STATE_UNKNOWN: "STATE_TRANSITION_DENIED",
        ReadyBlocker.INPUT_UNRESOLVABLE: "STATE_TRANSITION_DENIED",
        ReadyBlocker.GRAPH_VERSION_STALE: "STATE_TRANSITION_DENIED",
        ReadyBlocker.NO_CONCURRENCY_SLOT: "RESOURCE_BUDGET_EXCEEDED",
        ReadyBlocker.MEMORY_SOFT_LIMIT: "RESOURCE_BUDGET_EXCEEDED",
        ReadyBlocker.MEMORY_HARD_LIMIT: "RESOURCE_BUDGET_EXCEEDED",
        ReadyBlocker.DISK_LOW: "RESOURCE_BUDGET_EXCEEDED",
        ReadyBlocker.BUDGET_EXHAUSTED: "RESOURCE_BUDGET_EXCEEDED",
        ReadyBlocker.GOVERNOR_PAUSED: "RESOURCE_BUDGET_EXCEEDED",
        ReadyBlocker.TEMPLATE_NOT_ALLOWLISTED: "TOOL_NOT_ALLOWLISTED",
        ReadyBlocker.NODE_TYPE_NOT_ALLOWED: "TOOL_NOT_ALLOWLISTED",
        ReadyBlocker.PATH_NOT_ALLOWED: "TOOL_NOT_ALLOWLISTED",
        ReadyBlocker.ROLE_NOT_ALLOWED: "TOOL_NOT_ALLOWLISTED",
        ReadyBlocker.NODE_NOT_READY: "STATE_TRANSITION_DENIED",
        ReadyBlocker.FACTS_UNAVAILABLE: "STATE_TRANSITION_DENIED",
    }
)


# ---------------------------------------------------------------------------
# 2. 事实端口（只读；本文件不持有任何仓储实现）
# ---------------------------------------------------------------------------
class FactsUnavailable(RuntimeError):
    """事实端口不可用。调度器必须把它转成 `FACTS_UNAVAILABLE` 阻塞，而不是“假设可用”。"""


class DependencyFactsPort(Protocol):
    """依赖事实的只读视图（M02 NodeRepository + M04 图）。"""

    def state_of(self, task_id: str, node_id: str) -> str:
        """返回节点当前状态；查不到时抛 `FactsUnavailable`（不得返回空串冒充状态）。"""
        ...

    def dependencies_of(self, task_id: str, node_id: str) -> tuple[str, ...]:
        ...

    def input_refs_resolvable(self, task_id: str, node_id: str) -> bool:
        ...

    def graph_version_of(self, task_id: str) -> int:
        ...

    def node_graph_version(self, task_id: str, node_id: str) -> int:
        ...


class ResourceFactsPort(Protocol):
    """资源水位（来自 Governor/limits；只读）。"""

    def offer(self, task_id: str) -> "ResourceOffer":
        ...


class PermissionFactsPort(Protocol):
    """模板/路径/角色白名单（来自 M05 registry 与 security.yaml）。"""

    def template_allowed(self, task_id: str, node_id: str) -> bool:
        ...

    def node_type_allowed(self, task_id: str, node_id: str) -> bool:
        ...

    def path_allowed(self, task_id: str, node_id: str) -> bool:
        ...

    def role_allowed(self, task_id: str, node_id: str, role: str) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class ResourceOffer:
    """某一时刻可用于派发的资源视图。

    `paused` 是 Governor 的硬暂停（硬阈值/磁盘写满）；`soft_pressure` 表示软阈值已触发，
    此时仍可派发**已在队列**的节点，但不再接受新的入队（由调用方执行，见 `enqueue`）。
    """

    free_slots: int
    memory_available_mb: float
    disk_free_mb: float
    budget_remaining: float
    paused: bool = False
    soft_pressure: bool = False

    def __post_init__(self) -> None:
        if self.free_slots < 0:
            raise ValueError("free_slots 不得为负")
        for name in ("memory_available_mb", "disk_free_mb", "budget_remaining"):
            value = float(getattr(self, name))
            if value != value or value < 0.0:
                raise ValueError(f"{name} 必须是有限非负数")


# ---------------------------------------------------------------------------
# 3. READY 判定
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReadyDecision:
    """一次 READY 判定的完整结果（三项检查各自留痕，便于解释“为什么还没轮到它”）。"""

    node_id: str
    ready: bool
    blockers: tuple[ReadyBlocker, ...]
    dependencies_ok: bool
    resources_ok: bool
    permission_ok: bool
    detail: str = ""

    def __post_init__(self) -> None:
        if self.ready != (not self.blockers):
            raise ValueError("ready 与 blockers 必须一致（ready ⇔ blockers 为空）")
        if self.ready and not (self.dependencies_ok and self.resources_ok and self.permission_ok):
            raise ValueError("ready=True 必须三项检查全过（合取，不得打折）")

    @property
    def primary_blocker(self) -> ReadyBlocker | None:
        """第一个阻塞原因（按 `blockers` 的确定性顺序，不按枚举定义序）。"""
        return self.blockers[0] if self.blockers else None

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "ready": self.ready,
                "blockers": [b.value for b in self.blockers],
                "dependencies_ok": self.dependencies_ok,
                "resources_ok": self.resources_ok,
                "permission_ok": self.permission_ok,
                "detail": self.detail,
            }
        )


def _dependency_blockers(
    task_id: str, node_id: str, deps: DependencyFactsPort
) -> tuple[ReadyBlocker, ...]:
    """依赖合取项：前驱全 VERIFIED + 输入可解析 + 图版本一致。

    顺序固定（先状态、再输入、最后图版本），保证同一输入得到同一 `blockers` 序列。
    """
    out: list[ReadyBlocker] = []
    try:
        # 步骤 1：图版本一致（图变了，旧的就绪判断作废）
        if deps.node_graph_version(task_id, node_id) != deps.graph_version_of(task_id):
            out.append(ReadyBlocker.GRAPH_VERSION_STALE)
        # 步骤 2：每个前驱都必须 VERIFIED；未知状态按阻塞处理
        for predecessor in deps.dependencies_of(task_id, node_id):
            try:
                state = deps.state_of(task_id, predecessor)
            except FactsUnavailable:
                out.append(ReadyBlocker.DEPENDENCY_STATE_UNKNOWN)
                continue
            if state != "VERIFIED":
                out.append(ReadyBlocker.DEPENDENCY_NOT_VERIFIED)
        # 步骤 3：输入引用可解析（产物存在且哈希可读由 M05/M07 保证；这里只问“能不能解析”）
        if not deps.input_refs_resolvable(task_id, node_id):
            out.append(ReadyBlocker.INPUT_UNRESOLVABLE)
    except FactsUnavailable:
        out.append(ReadyBlocker.FACTS_UNAVAILABLE)
    # 去重但保序（不得用 set 直接输出，否则日志顺序不稳定）
    return tuple(dict.fromkeys(out))


def _resource_blockers(
    task_id: str, node_id: str, resources: ResourceFactsPort, demand_mb: float
) -> tuple[ReadyBlocker, ...]:
    """资源合取项：槽位 + 内存/磁盘水位 + 预算 + Governor 暂停。"""
    out: list[ReadyBlocker] = []
    try:
        offer = resources.offer(task_id)
    except FactsUnavailable:
        return (ReadyBlocker.FACTS_UNAVAILABLE,)
    # 步骤 1：Governor 硬暂停优先（暂停期间任何新派发都不成立）
    if offer.paused:
        out.append(ReadyBlocker.GOVERNOR_PAUSED)
    # 步骤 2：并发槽（上限 2 是契约值，槽数由 Governor 给出，不得在此上调）
    if offer.free_slots <= 0:
        out.append(ReadyBlocker.NO_CONCURRENCY_SLOT)
    # 步骤 3：内存（`demand_mb` 是节点声明需求；需求超过当前可用即拦，软/硬只决定错误码形态）
    if demand_mb > offer.memory_available_mb:
        out.append(ReadyBlocker.MEMORY_HARD_LIMIT if offer.paused else ReadyBlocker.MEMORY_SOFT_LIMIT)
    # 步骤 4：磁盘（水位由 scheduler.yaml: disk_watermark_mb 决定，不在本文件取默认值）
    if offer.disk_free_mb <= 0.0:
        out.append(ReadyBlocker.DISK_LOW)
    # 步骤 5：预算（token/wall/attempts 合计余量；T0 无 LLM 时 token 恒 0）
    if offer.budget_remaining <= 0.0:
        out.append(ReadyBlocker.BUDGET_EXHAUSTED)
    return tuple(dict.fromkeys(out))


def _permission_blockers(
    task_id: str, node_id: str, permission: PermissionFactsPort, role: str
) -> tuple[ReadyBlocker, ...]:
    """权限合取项：模板登记、node_type 白名单、路径 allowlist、执行角色。

    这一项**不得**因为“反正是内置模板”而跳过：未登记模板在 M05 会被拒，
    提前在 READY 判定就拦住，避免派发后才失败（`TOOL_NOT_ALLOWLISTED` 必须在启动子进程前拒绝）。
    """
    out: list[ReadyBlocker] = []
    try:
        if not permission.template_allowed(task_id, node_id):
            out.append(ReadyBlocker.TEMPLATE_NOT_ALLOWLISTED)
        if not permission.node_type_allowed(task_id, node_id):
            out.append(ReadyBlocker.NODE_TYPE_NOT_ALLOWED)
        if not permission.path_allowed(task_id, node_id):
            out.append(ReadyBlocker.PATH_NOT_ALLOWED)
        if not permission.role_allowed(task_id, node_id, role):
            out.append(ReadyBlocker.ROLE_NOT_ALLOWED)
    except FactsUnavailable:
        out.append(ReadyBlocker.FACTS_UNAVAILABLE)
    return tuple(dict.fromkeys(out))


def evaluate_ready(
    *,
    task_id: str,
    node_id: str,
    deps: DependencyFactsPort,
    resources: ResourceFactsPort,
    permission: PermissionFactsPort,
    role: str,
    demand_mb: float = 0.0,
    current_state: str = "PLANNED",
) -> ReadyDecision:
    """判定一个节点是否满足进入 READY 的全部条件。

    步骤：
      1. 状态必须允许进入 READY（`PLANNED→READY` 或 `INVALIDATED→READY`）；
      2. 依赖合取项；
      3. 资源合取项；
      4. 权限合取项；
      5. 汇总：无阻塞才 ready；任一阻塞即不 ready（**不给部分通过**）。

    输入：任务/节点 ID、四个只读端口、执行角色、节点内存需求、当前状态。
    输出：`ReadyDecision`（含三项布尔与阻塞列表）。
    副作用：无（只读端口）。
    错误：不抛业务异常；端口故障转为 `FACTS_UNAVAILABLE` 阻塞（fail-closed）。
          `demand_mb` 为负属调用错误，抛 `ValueError`。
    """
    if demand_mb < 0.0 or demand_mb != demand_mb:
        raise ValueError("demand_mb 必须是有限非负数")
    # 步骤 1：状态门槛
    if current_state not in ("PLANNED", "INVALIDATED"):
        return ReadyDecision(
            node_id=node_id,
            ready=False,
            blockers=(ReadyBlocker.NODE_NOT_READY,),
            dependencies_ok=False,
            resources_ok=False,
            permission_ok=False,
            detail=f"当前状态 {current_state}：只有 PLANNED / INVALIDATED 可以申请进入 READY",
        )
    # 步骤 2–4：三项独立求值（互不短路：一次看全所有缺口）
    dep_blockers = _dependency_blockers(task_id, node_id, deps)
    res_blockers = _resource_blockers(task_id, node_id, resources, demand_mb)
    perm_blockers = _permission_blockers(task_id, node_id, permission, role)
    # 步骤 5：合取汇总（顺序：依赖 → 资源 → 权限，固定）
    blockers = tuple(dict.fromkeys((*dep_blockers, *res_blockers, *perm_blockers)))
    return ReadyDecision(
        node_id=node_id,
        ready=not blockers,
        blockers=blockers,
        dependencies_ok=not dep_blockers,
        resources_ok=not res_blockers,
        permission_ok=not perm_blockers,
        detail="全部检查通过" if not blockers else f"阻塞 {len(blockers)} 项",
    )


# ---------------------------------------------------------------------------
# 4. 队列结构
# ---------------------------------------------------------------------------
class QueueInvariantViolated(RuntimeError):
    """队列不变量被破坏（重复入队、非 READY 入队、缺拓扑名次）。

    这是**编程错误**，不是业务拒绝：不重试、不忽略，直接暴露给调用方。
    对外用 `STATE_TRANSITION_DENIED` + `reason=QUEUE_*`（不新增注册表码）。
    """

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 409

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{self.error_code}/{reason}：{detail}")


@dataclass(frozen=True, slots=True)
class QueueEntry:
    """队列中的一条就绪候选。

    `enqueued_at_ticks` 必须是**单调时钟**读数（`ClockPort.monotonic`），不是 wall clock：
    墙钟会被 NTP 调整，导致 Age 跳变甚至为负。
    """

    node_id: str
    topological_rank: int
    enqueued_at_ticks: float
    attempt_seq: int = 0
    user_priority: int = 0
    score: SchedScore | None = None

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("node_id 不得为空")
        if self.topological_rank < 0:
            raise ValueError("topological_rank 不得为负")
        if self.enqueued_at_ticks < 0.0:
            raise ValueError("单调时钟读数不得为负")
        if self.attempt_seq < 0:
            raise ValueError("attempt_seq 不得为负")

    def age_sec(self, now_ticks: float) -> float:
        """等待时长（秒）。时钟回退 → 抛错，不得返回负数把饥饿掩盖掉。"""
        if now_ticks < self.enqueued_at_ticks:
            raise ScoringInputInvalid(
                "now_ticks", f"单调时钟回退：{now_ticks} < {self.enqueued_at_ticks}"
            )
        return now_ticks - self.enqueued_at_ticks


@dataclass(frozen=True, slots=True)
class Eviction:
    """出队前重验失败的驱逐记录（必须进调度日志，不得静默丢弃）。"""

    node_id: str
    blocker: ReadyBlocker
    age_sec: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PopResult:
    """一次出队尝试的结果。"""

    entry: QueueEntry | None
    evicted: tuple[Eviction, ...]
    selection_reason: str
    evaluated: int

    @property
    def empty(self) -> bool:
        return self.entry is None


@dataclass(frozen=True, slots=True)
class StarvationPolicy:
    """饥饿策略的**全部**参数；三个都必须来自配置（缺键拒绝启动）。"""

    age_horizon_sec: float
    promotion_age_sec: float

    def __post_init__(self) -> None:
        for name in ("age_horizon_sec", "promotion_age_sec"):
            value = float(getattr(self, name))
            if value != value or value <= 0.0:
                raise ScoringConfigInvalid(
                    "CONFIG_VALUE_OUT_OF_RANGE",
                    f"scheduler.yaml: {name}",
                    f"必须 > 0，实际 {value!r}",
                )
        if self.promotion_age_sec < self.age_horizon_sec:
            # 老化提升必须在 Age 饱和之后才接管；否则 Age 项永远被硬提升遮蔽。
            raise ScoringConfigInvalid(
                "CONFIG_VALUE_OUT_OF_RANGE",
                "scheduler.yaml: starvation_promotion_age_sec",
                "老化提升阈值必须 ≥ age_horizon_sec（先软后硬）",
            )


def queue_policy_from_config(raw: Mapping[str, object]) -> "tuple[SelectionPolicy, StarvationPolicy]":
    """从 `scheduler.yaml` 的就绪队列段装载策略。

    必需键：`selection_policy` / `age_horizon_sec` / `starvation_promotion_age_sec`。
    缺键 → `CONFIG_MISSING_KEY`；未知键 → `CONFIG_UNKNOWN_KEY`；类型错 → `CONFIG_TYPE_INVALID`。
    **不读取也不改写** `ready_order`：该键属 M03 冻结面，与 §8.5 的口径冲突登记在 OQ-P7-01。
    """
    allowed = frozenset(("selection_policy", "age_horizon_sec", "starvation_promotion_age_sec"))
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ScoringConfigInvalid(
            "CONFIG_UNKNOWN_KEY", "scheduler.yaml: ready_queue", f"未声明的键 {unknown}"
        )
    for key in allowed:
        if key not in raw:
            raise ScoringConfigInvalid(
                "CONFIG_MISSING_KEY",
                f"scheduler.yaml: ready_queue.{key}",
                "配置没有隐式默认值，缺失必须拒绝启动",
            )
    text = raw["selection_policy"]
    if not isinstance(text, str) or text not in {p.value for p in SelectionPolicy}:
        raise ScoringConfigInvalid(
            "CONFIG_VALUE_OUT_OF_RANGE",
            "scheduler.yaml: ready_queue.selection_policy",
            f"只允许 {[p.value for p in SelectionPolicy]}",
        )
    numbers: dict[str, float] = {}
    for key in ("age_horizon_sec", "starvation_promotion_age_sec"):
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringConfigInvalid(
                "CONFIG_TYPE_INVALID", f"scheduler.yaml: ready_queue.{key}", "必须是数字"
            )
        numbers[key] = float(value)
    return (
        SelectionPolicy(text),
        StarvationPolicy(
            age_horizon_sec=numbers["age_horizon_sec"],
            promotion_age_sec=numbers["starvation_promotion_age_sec"],
        ),
    )


# ---------------------------------------------------------------------------
# 5. 就绪队列
# ---------------------------------------------------------------------------
class ReadyQueue:
    """READY 节点队列：确定性排序 + 出队前重验 + 饥饿老化提升。

    不持有仓储/时钟；所有事实通过构造参数与 `revalidate` 回调进入，便于测试与重放。
    """

    def __init__(
        self,
        *,
        policy: SelectionPolicy,
        starvation: StarvationPolicy,
        rank_of: Callable[[str], int],
    ) -> None:
        self._policy = policy
        self._starvation = starvation
        self._rank_of = rank_of
        self._entries: dict[str, QueueEntry] = {}
        self._evictions: list[Eviction] = []
        self._promotions = 0

    # -- 只读视图 ---------------------------------------------------------
    @property
    def policy(self) -> SelectionPolicy:
        return self._policy

    @property
    def evictions(self) -> tuple[Eviction, ...]:
        """历史驱逐记录（追加写；供调度日志与负例断言）。"""
        return tuple(self._evictions)

    @property
    def promotion_count(self) -> int:
        """因饥饿老化被提升的次数（用于证明饥饿处理真实发生）。"""
        return self._promotions

    def depth(self) -> int:
        return len(self._entries)

    def entries(self) -> tuple[QueueEntry, ...]:
        """确定性快照：按（拓扑名次, node_id）排序，与分数无关。"""
        return tuple(sorted(self._entries.values(), key=lambda e: (e.topological_rank, e.node_id)))

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._entries

    # -- 写入 -------------------------------------------------------------
    def enqueue(self, entry: QueueEntry, *, current_state: str) -> None:
        """入队。只接受 state=READY 的节点；重复入队是错误。

        输入：条目 + 节点当前状态（由调用方从 StateMachine 读，本类不读库）。
        副作用：修改内存队列。
        错误：非 READY → `QueueInvariantViolated(QUEUE_NODE_NOT_READY)`；
              重复 → `QueueInvariantViolated(QUEUE_DUPLICATE_ENTRY)`。
        """
        if current_state != "READY":
            raise QueueInvariantViolated(
                "QUEUE_NODE_NOT_READY", f"节点 {entry.node_id} 当前状态 {current_state}，不是 READY"
            )
        if entry.node_id in self._entries:
            raise QueueInvariantViolated(
                "QUEUE_DUPLICATE_ENTRY", f"节点 {entry.node_id} 已在队列中"
            )
        if entry.topological_rank != self._rank_of(entry.node_id):
            raise QueueInvariantViolated(
                "QUEUE_RANK_MISMATCH",
                f"节点 {entry.node_id} 的拓扑名次 {entry.topological_rank} 与图不一致",
            )
        self._entries[entry.node_id] = entry

    def remove(self, node_id: str) -> QueueEntry | None:
        """移除（节点已被外部迁移出 READY 时使用）；不存在返回 None。"""
        return self._entries.pop(node_id, None)

    # -- 出队 -------------------------------------------------------------
    def pop_best(
        self,
        *,
        now_ticks: float,
        revalidate: Callable[[str], ReadyDecision],
    ) -> PopResult:
        """选出下一个可派发节点。

        步骤：
          1. 取确定性快照；
          2. 计算每条目的等待时长（单调时钟）；
          3. **饥饿硬层**：存在超龄条目时，在超龄集合里取最老者（并列按拓扑名次、node_id）；
             否则按策略取最优（SchedScore 或拓扑序）；
          4. 对候选调用 `revalidate`；不 READY → 驱逐并回到步骤 2（最多 N 次，N = 队列长度）；
          5. 返回候选或空结果。

        输入：单调时钟读数、重验回调（由 dispatch 传入，内部会再查依赖/资源/权限）。
        输出：`PopResult`（候选 / 驱逐记录 / 选择原因 / 求值次数）。
        副作用：修改内存队列（移除出队条目与驱逐条目），追加驱逐记录。
        错误：`now_ticks` 回退 → `ScoringInputInvalid`；队列为空 → 返回空结果（不抛）。
        """
        evicted: list[Eviction] = []
        evaluated = 0
        while self._entries:
            # 步骤 1–2：快照 + 等待时长
            snapshot = self.entries()
            aged = [(entry, entry.age_sec(now_ticks)) for entry in snapshot]
            # 步骤 3：先硬层（老化），再软层（分数/拓扑）
            overdue = [(e, age) for e, age in aged if age >= self._starvation.promotion_age_sec]
            if overdue:
                # 最老者优先；并列按（拓扑名次, node_id），保证确定性
                entry, age = sorted(overdue, key=lambda pair: (-pair[1], pair[0].topological_rank,
                                                                pair[0].node_id))[0]
                reason = "AGE_PROMOTION"
            else:
                entry, age = self._best_by_policy(aged)
                reason = "SCHED_SCORE" if self._policy is SelectionPolicy.SCHED_SCORE else "TOPOLOGY"
            # 步骤 4：出队前重验（依赖未满足/资源变化/权限撤销都在这里挡住）
            evaluated += 1
            decision = revalidate(entry.node_id)
            if decision.ready:
                self._entries.pop(entry.node_id, None)
                if reason == "AGE_PROMOTION":
                    self._promotions += 1
                return PopResult(
                    entry=entry,
                    evicted=tuple(evicted),
                    selection_reason=reason,
                    evaluated=evaluated,
                )
            blocker = decision.primary_blocker or ReadyBlocker.FACTS_UNAVAILABLE
            eviction = Eviction(
                node_id=entry.node_id,
                blocker=blocker,
                age_sec=age,
                detail=decision.detail,
            )
            evicted.append(eviction)
            self._evictions.append(eviction)
            self._entries.pop(entry.node_id, None)
            # 回到步骤 2：继续看下一个候选（驱逐不能阻塞其他就绪节点）
        # 步骤 5：空队列
        return PopResult(entry=None, evicted=tuple(evicted), selection_reason="EMPTY", evaluated=evaluated)

    def _best_by_policy(
        self, aged: Sequence[tuple[QueueEntry, float]]
    ) -> tuple[QueueEntry, float]:
        """按当前策略选最优；返回（条目, 等待时长）。"""
        if not aged:
            raise QueueInvariantViolated("QUEUE_EMPTY", "队列为空时不应调用 _best_by_policy")
        if self._policy is SelectionPolicy.TOPOLOGICAL_ONLY:
            # 纯拓扑序：名次升序，再 node_id 升序（与 M03 ready_order 口径一致）
            return min(aged, key=lambda pair: (pair[0].topological_rank, pair[0].node_id))
        # SchedScore：没有分数的条目视为编程错误（不得“当作 0 分”）
        scored: list[tuple[QueueEntry, float]] = []
        for entry, age in aged:
            if entry.score is None:
                raise QueueInvariantViolated(
                    "QUEUE_MISSING_SCORE", f"节点 {entry.node_id} 没有分数却走 SCHED_SCORE 策略"
                )
            scored.append((entry, age))
        ranks = {entry.node_id: entry.topological_rank for entry, _ in scored}

        def _cmp(left: QueueEntry, right: QueueEntry) -> int:
            left_score, right_score = left.score, right.score
            if left_score is None or right_score is None:
                raise QueueInvariantViolated("QUEUE_MISSING_SCORE", "比较时出现无分数条目")
            return compare_scores(left_score, right_score, topological_rank=ranks)

        # 插入排序而非 sorted(key=...)：compare_scores 是三元比较，且要求全序键显式存在
        ordered = [entry for entry, _ in scored]
        for i in range(1, len(ordered)):
            current = ordered[i]
            j = i - 1
            while j >= 0 and _cmp(ordered[j], current) > 0:
                ordered[j + 1] = ordered[j]
                j -= 1
            ordered[j + 1] = current
        best = ordered[0]
        return best, dict((e.node_id, age) for e, age in scored)[best.node_id]

    # -- 饥饿观测 ---------------------------------------------------------
    def starvation_report(self, *, now_ticks: float) -> tuple[QueueEntry, ...]:
        """返回当前超过老化阈值的条目（正常情况下 `pop_best` 之后应为空）。

        这个函数是验收判据「无饥饿」的观测点：测试在 `pop_best` 之后断言它为空，
        证明超龄条目没有被更年轻的条目一直插队。
        """
        return tuple(
            entry
            for entry in self.entries()
            if entry.age_sec(now_ticks) >= self._starvation.promotion_age_sec
        )

    def build_entry(
        self,
        facts: NodeScoreFacts,
        *,
        weights: SchedScoreWeights,
        risk_policy: RiskPolicy,
        caps: ResourceCaps,
        now_ticks: float,
        current_state: str,
    ) -> QueueEntry:
        """装载一条候选：算分（仅 SCHED_SCORE 策略）并构造条目。

        输入：评分事实 + 权重/风险策略/维度上限 + 单调时钟 + 节点状态。
        输出：`QueueEntry`（`TOPOLOGICAL_ONLY` 下 `score=None`）。
        副作用：无（不入队；入队由调用方显式 `enqueue`）。
        错误：状态非 READY → `QueueInvariantViolated`；评分输入越域 → 透传 `ScoringInputInvalid`。
        """
        if current_state != "READY":
            raise QueueInvariantViolated(
                "QUEUE_NODE_NOT_READY", f"节点 {facts.node_id} 当前状态 {current_state}"
            )
        score = None
        if self._policy is SelectionPolicy.SCHED_SCORE:
            score = compute_score(
                facts,
                weights=weights,
                risk_policy=risk_policy,
                caps=caps,
                age_horizon_sec=self._starvation.age_horizon_sec,
            )
        return QueueEntry(
            node_id=facts.node_id,
            topological_rank=self._rank_of(facts.node_id),
            enqueued_at_ticks=now_ticks,
            user_priority=facts.user_priority,
            score=score,
        )


# ---------------------------------------------------------------------------
# 6. 确定性比较（条目级，供测试与日志排序）
# ---------------------------------------------------------------------------
def compare_entries(
    left: QueueEntry, right: QueueEntry, *, policy: SelectionPolicy
) -> int:
    """条目级确定性比较：-1/0/1。

    `TOPOLOGICAL_ONLY`：名次 → node_id；
    `SCHED_SCORE`：分数（含三项并列裁决）→ 名次 → node_id。
    副作用：无。
    """
    if policy is SelectionPolicy.TOPOLOGICAL_ONLY or left.score is None or right.score is None:
        if left.topological_rank != right.topological_rank:
            return -1 if left.topological_rank < right.topological_rank else 1
        if left.node_id == right.node_id:
            return 0
        return -1 if left.node_id < right.node_id else 1
    ranks = {left.node_id: left.topological_rank, right.node_id: right.topological_rank}
    return compare_scores(left.score, right.score, topological_rank=ranks)


# ---------------------------------------------------------------------------
# 7. 自检
# ---------------------------------------------------------------------------
def assert_queue_invariants(entries: Sequence[QueueEntry]) -> list[str]:
    """检查一份队列快照是否满足不变量（落地阶段在每次入队/出队后调用）。"""
    problems: list[str] = []
    ids = [e.node_id for e in entries]
    if len(set(ids)) != len(ids):
        problems.append("队列中存在重复 node_id")
    ranks = [e.topological_rank for e in entries]
    if len(set(ranks)) != len(ranks):
        problems.append("拓扑名次重复（图或名次表有误）")
    for entry in entries:
        if entry.score is not None and not (0.0 <= entry.score.total <= 1.0 + 1e-9):
            problems.append(f"节点 {entry.node_id} 的分数越界")
        if entry.enqueued_at_ticks < 0.0:
            problems.append(f"节点 {entry.node_id} 的单调时钟为负")
    return problems


def assert_queue_boundary() -> list[str]:
    """自检：本文件不得写状态、不得绕过 StateMachine、不得把未知事实当可用。

    检查项：
      1. 模块没有仓储/连接对象（`globals()` 里不得出现 `conn` / `repository` / `machine` / `session`）；
      2. `BLOCKER_ERROR_CODES` 覆盖 `ReadyBlocker` 全部成员（不缺映射）；
      3. 三个合取项函数与合取汇总函数都在模块面上（依赖/资源/权限 + `evaluate_ready`）；
      4. 老化提升**提议值**为正（“阈值 ≥ Age 视界”由 `StarvationPolicy.__post_init__` 在装载时校验，
         本函数不重复实现，只在此注明）。
    """
    problems: list[str] = []
    for forbidden in ("conn", "connection", "repository", "machine", "session"):
        if forbidden in globals():
            problems.append(f"队列模块不得持有 {forbidden}")
    missing = [b for b in ReadyBlocker if b not in BLOCKER_ERROR_CODES]
    if missing:
        problems.append(f"阻塞原因缺错误码映射：{[b.value for b in missing]}")
    for required in (
        "_dependency_blockers", "_resource_blockers", "_permission_blockers", "evaluate_ready",
    ):
        if required not in globals():
            problems.append(f"缺少合取项/汇总函数 {required}")
    if PROPOSED_STARVATION_PROMOTION_AGE_SEC <= 0:
        problems.append("老化提升提议值必须 > 0")
    return problems