"""M14 · orchestration/recovery/planner.py — 定向恢复计划生成（P7 伪代码）。
阶段：P7「调度与定向恢复」｜追踪：FR-010（T0 最小切片；T1 完整）、策划书 §8.4 / P0201–P0214、ADR-004
依赖：M14 `error_signature`、M04 `invalidation.descendants`（经 `OrderingPort`）、M14 `plan_freeze`（哈希与存储，不在此调用）
不变量：`affected = descendants(failed) ∪ {failed}`；拓扑序遍历；T0 **只有 REEXECUTE**；
        无 PROPOSED/APPROVED、无 Agent 提案、无人工审批；计划正文无时间戳/随机序/集合遍历序
错误码：STATE_TRANSITION_DENIED（409，`reason=AFFECTED_SET_INVALID / TOPOLOGY_ORDER_INVALID / SPA_FORBIDDEN_IN_T0`）
        —— 只用于**不变量被破坏**；正常业务拒绝返回 `RecoveryOutcome.escalation`，不抛异常
写入者：无。计划文件与冻结审计由 `plan_freeze` 负责；状态迁移由 StateMachine 负责
状态：伪代码；不读库、不写文件、不改状态、不读时钟

## §8.4 的逐分支落地（本文件的核心）

  ```
  affected = descendants(failed_node) ∪ {failed_node}
  for node in topological_order(affected):
      if node == failed_node or not retryable(node):   retry_or_escalate()   # ①
      elif has_side_effect(node):                      reexecute()          # ②
      elif not evidence_valid(node):                   reexecute()          # ③
      elif not predecessor_hashes_unchanged(node):     reexecute()          # ④
      elif not valid_DC(node, current_env):            reexecute()          # ⑤
      elif not disk_rehash_matches(node):              reexecute()          # ⑥
      elif not gate_passes_under_current_rules(node):  reexecute()          # ⑦
      else:                                            sign_SPA(node)       # ⑧ ← T0 禁止
  return immutable_plan
  ```

  **T0 的差别只有一处**：⑧ 这一支不存在。T2 之前 `valid_DC` 恒为 False，
  所以 ⑤ 永远先于 ⑥⑦ 命中 —— 这不是“提前实现了剪枝”，而是“把保守重跑写成默认”。
  ⑥⑦ 仍然求值并记入 `checks`（供诊断与 T2 复用），但它们**不可能**成为 T0 的决策理由。

  `not retryable(node)` 对**失败节点本身**的处理放在生成计划之前：不可重试 → 返回
  `escalation`，不生成计划。这样计划里的每个 decision 都是 REEXECUTE，没有第二种动作。

## 计划的 all-or-nothing 语义

  受影响集合里任一节点没有重试预算 → **不生成计划**。否则会出现“上游重跑了、下游跑不动”的
  半套状态，比不做更危险（与 M04 `apply_invalidations` 中途失败即整体报告同一口径）。
  计划**不改状态**：后代如何从 `VERIFIED`/`PLANNED` 走到可执行，由 M04 失效传播 +
  StateMachine 的 `INVALIDATED→READY` / `PLANNED→READY` 决定，本文件只说“都要重跑”。

## 为什么计划正文里没有 plan_id / 时间戳 / 集合

  - `plan_id` 由 `plan_hash` 派生（`plan_freeze.plan_id_for`）；写进正文会形成自指。
  - 时间戳只写 `audit_log` 的冻结记录（ADR-004 §3）；正文出现时间 → 同一输入两次哈希不同。
  - 集合（`set`/`frozenset`）不参与输出：迭代顺序不稳定；一律先转成按
    `topological_then_node_id` 排序的 `tuple` 再序列化。

## T0 不做的事（本文件用结构禁止，而不是靠注释提醒）

  - 不做 SPA：`RecoveryAction` 只有一个成员；⑧ 分支抛出 `SpaForbiddenInT0`。
  - 不做 DC 剪枝：`dc_available()` 在 T0 恒为 False，且计划 policy 里写死 `dc_used=False`。
  - 不做审批：模块里没有 `RecoveryState`、没有 `propose/approve` 函数；
    `PROPOSED`/`APPROVED` 只出现在 `assert_no_approval_states()` 的**禁名清单**里
    （用来检测越权改动），不是状态定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .error_signature import (
    CATEGORY_POLICY,
    ErrorCategory,
    ErrorSignature,
    Retryability,
    signature_from_failure,
    FailureInput,
)

__all__ = [
    "CheckName",
    "CheckOutcome",
    "EscalationReason",
    "GraphView",
    "OrderingPort",
    "PLAN_FORMAT_VERSION",
    "PlanRefused",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryEscalation",
    "RecoveryFactsPort",
    "RecoveryOutcome",
    "RecoveryPlan",
    "ReexecuteReason",
    "SpaForbiddenInT0",
    "T0_POLICY_FLAGS",
    "affected_nodes_expected",
    "assert_no_approval_states",
    "assert_plan_structure",
    "assert_t0_single_action",
    "assert_topological_subset",
    "plan_recovery",
]

PLAN_FORMAT_VERSION: Final[str] = "1.0"

T0_POLICY_FLAGS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "mode": "T0_CONSERVATIVE",
        "dc_used": False,
        "spa_used": False,
        "approval_required": False,   # 不是“已审批”，而是“T0 没有审批环节”（ADR-004 §2.5）
    }
)


# ---------------------------------------------------------------------------
# 1. 动作与原因
# ---------------------------------------------------------------------------
class RecoveryAction(StrEnum):
    """恢复动作。**T0 只有一个值**。

    加 `SKIP`/`SPA`/`DEFER` 属于 T2 能力，必须另立 ADR 并同时改本枚举、
    `assert_t0_single_action()` 与 NEGATIVE_TESTS；在那之前，任何第二值都是越权。
    """

    REEXECUTE = "REEXECUTE"


class ReexecuteReason(StrEnum):
    """为什么必须重跑。每个值对应 §8.4 的一条分支，顺序也按分支顺序。"""

    FAILED_NODE = "FAILED_NODE"                              # ① node == failed_node
    SIDE_EFFECT = "SIDE_EFFECT"                              # ② 有副作用
    NO_VALID_EVIDENCE = "NO_VALID_EVIDENCE"                  # ③ 证据无效/缺失/stale
    PREDECESSOR_HASH_CHANGED = "PREDECESSOR_HASH_CHANGED"    # ④ 前驱哈希变了
    NO_VALID_DC = "NO_VALID_DC"                              # ⑤ 无有效 DC（T0 恒真）
    DISK_REHASH_MISMATCH = "DISK_REHASH_MISMATCH"            # ⑥ 磁盘产物复算不符
    GATE_NOT_PASSING = "GATE_NOT_PASSING"                    # ⑦ 当前规则下 Gate 不过


class CheckName(StrEnum):
    """诊断检查名（固定顺序；全部求值，不只求值到第一个失败）。"""

    RETRYABLE = "RETRYABLE"
    SIDE_EFFECT = "SIDE_EFFECT"
    EVIDENCE_VALID = "EVIDENCE_VALID"
    PREDECESSOR_HASHES_UNCHANGED = "PREDECESSOR_HASHES_UNCHANGED"
    DC_AVAILABLE = "DC_AVAILABLE"
    DISK_REHASH_MATCHES = "DISK_REHASH_MATCHES"
    GATE_PASSES = "GATE_PASSES"


CHECK_ORDER: Final[tuple[CheckName, ...]] = (
    CheckName.RETRYABLE,
    CheckName.SIDE_EFFECT,
    CheckName.EVIDENCE_VALID,
    CheckName.PREDECESSOR_HASHES_UNCHANGED,
    CheckName.DC_AVAILABLE,
    CheckName.DISK_REHASH_MATCHES,
    CheckName.GATE_PASSES,
)


class EscalationReason(StrEnum):
    """不生成计划、改走升级的原因（正常业务结果，不抛异常）。"""

    STATE_MISMATCH = "STATE_MISMATCH"                                  # 节点不在 FAILED
    NO_RETRY_BUDGET = "NO_RETRY_BUDGET"                                # 重试次数耗尽
    CATEGORY_NOT_RECOVERABLE_IN_T0 = "CATEGORY_NOT_RECOVERABLE_IN_T0"  # 类别不可自动重跑
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"                                # 未知类别，保守升级


# ---------------------------------------------------------------------------
# 2. 异常（只用于不变量破坏）
# ---------------------------------------------------------------------------
class PlanRefused(RuntimeError):
    """计划不变量被破坏：**不得**产出半套计划。

    对外 `STATE_TRANSITION_DENIED`(409) + `reason`（与 M02 的守卫失败口径一致）。
    正常业务拒绝（类别不可恢复等）用 `RecoveryOutcome.escalation`，不走这里。
    """

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 409

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{self.error_code}/{reason}：{detail}")


class SpaForbiddenInT0(PlanRefused):
    """§8.4 的 ⑧ 分支（`sign_SPA`）在 T0 是**禁止**的。

    它在 T0 不可达（`dc_available` 恒 False），保留这个分支是为了防止
    “以后把 ⑤ 改成 True，⑧ 就悄悄生效”。一旦命中，说明有人提前实现了 T2 剪枝。
    """

    def __init__(self, node_id: str) -> None:
        super().__init__(
            "SPA_FORBIDDEN_IN_T0",
            f"节点 {node_id!r} 落到 §8.4 的 sign_SPA 分支；T0 无 DC/SPA 能力，必须重跑",
        )


# ---------------------------------------------------------------------------
# 3. 端口
# ---------------------------------------------------------------------------
class GraphView(Protocol):
    """图的只读结构视图（M04 `GraphContent` 的子集）。"""

    def node_ids(self) -> tuple[str, ...]:
        ...

    def dependencies(self) -> Mapping[str, tuple[str, ...]]:
        ...


class OrderingPort(Protocol):
    """受影响子图的确定性顺序。

    唯一实现应是 M04 `invalidation.descendants(graph, (failed,), include_seeds=True)`：
    返回 `topological_then_node_id` 排序的元组。本文件**不**自己算拓扑序，
    只校验传进来的顺序确实满足「拓扑 + 集合正确」——校验比重复实现更强。
    """

    def ordered_affected(self, failed_node: str) -> tuple[str, ...]:
        ...


class RecoveryFactsPort(Protocol):
    """§8.4 每条分支所需的只读事实。全部方法都不得写库、不得改状态。"""

    def state_of(self, node_id: str) -> str:
        ...

    def retry_budget_available(self, node_id: str) -> bool:
        """该节点是否还有重试预算（`attempt_seq < retry_policy.max_attempts`）。"""
        ...

    def side_effect_class(self, node_id: str) -> str:
        ...

    def evidence_valid(self, node_id: str) -> bool:
        """证据是否有效：非 stale、哈希可重算、在当前规则下仍成立。"""
        ...

    def predecessor_hashes_unchanged(self, node_id: str) -> bool:
        ...

    def dc_available(self, node_id: str) -> bool:
        """T0 恒返回 False（DC 属 T2）。返回 True 意味着越界实现了 T2 能力。"""
        ...

    def disk_rehash_matches(self, node_id: str) -> bool:
        ...

    def gate_passes_under_current_rules(self, node_id: str) -> bool:
        ...


# ---------------------------------------------------------------------------
# 4. 值对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """一条诊断检查的结果。"""

    name: CheckName
    passed: bool
    detail: str = ""

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType({"name": self.name.value, "passed": self.passed,
                                 "detail": self.detail})


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """一个受影响节点的决策。`action` 只有一个合法值。"""

    node_id: str
    action: RecoveryAction
    reason: ReexecuteReason
    is_failed_node: bool
    checks: tuple[CheckOutcome, ...]

    def __post_init__(self) -> None:
        if self.action is not RecoveryAction.REEXECUTE:
            raise ValueError("T0 只允许 REEXECUTE")
        if tuple(check.name for check in self.checks) != CHECK_ORDER:
            raise ValueError("检查集合必须按 CHECK_ORDER 全量出现（诊断要求全量求值）")
        if self.is_failed_node and self.reason is not ReexecuteReason.FAILED_NODE:
            raise ValueError("失败节点的决策理由必须是 FAILED_NODE")

    def as_body(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "action": self.action.value,
                "reason": self.reason.value,
                "is_failed_node": self.is_failed_node,
                "checks": [check.as_detail() for check in self.checks],
            }
        )


@dataclass(frozen=True, slots=True)
class RecoveryEscalation:
    """不生成计划时的结构化结果（交 Orchestrator 请求 `FAILED→BLOCKED`）。"""

    failed_node: str
    reason: EscalationReason
    category: ErrorCategory
    retryability: Retryability
    detail: str

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "failed_node": self.failed_node,
                "reason": self.reason.value,
                "category": self.category.value,
                "retryability": self.retryability.value,
                "detail": self.detail,
            }
        )


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """T0 内部不可变计划（ADR-004：不签名、不进七契约、不对外）。"""

    task_id: str
    graph_version: int
    graph_hash: str
    ruleset_hash: str
    failed_node: str
    signature: ErrorSignature
    decisions: tuple[RecoveryDecision, ...]

    def __post_init__(self) -> None:
        if not self.decisions:
            raise PlanRefused("EMPTY_PLAN", "计划必须至少包含失败节点本身")
        ids = [decision.node_id for decision in self.decisions]
        if len(set(ids)) != len(ids):
            raise PlanRefused("DUPLICATE_DECISION", "同一节点出现两条决策")
        if self.failed_node not in ids:
            raise PlanRefused("FAILED_NODE_MISSING", "失败节点必须在决策集合中")
        failed_decision = next(d for d in self.decisions if d.node_id == self.failed_node)
        if not failed_decision.is_failed_node:
            raise PlanRefused("FAILED_NODE_FLAG", "失败节点的 is_failed_node 必须为 True")

    def body(self) -> Mapping[str, object]:
        """计划正文（**唯一**进入 plan_hash 的内容）。

        键序固定；不含 plan_id、不含时间戳、不含集合；`decisions` 顺序 = 拓扑序。
        """
        return MappingProxyType(
            {
                "plan_format_version": PLAN_FORMAT_VERSION,
                "task_id": self.task_id,
                "graph_version": self.graph_version,
                "graph_hash": self.graph_hash,
                "ruleset_hash": self.ruleset_hash,
                "failed_node": self.failed_node,
                "error_signature": dict(self.signature.key_material()),
                "policy": dict(T0_POLICY_FLAGS),
                "decisions": [decision.as_body() for decision in self.decisions],
            }
        )

    @property
    def affected_nodes(self) -> tuple[str, ...]:
        return tuple(decision.node_id for decision in self.decisions)

    def assert_no_spa(self) -> None:
        """结构断言：计划里没有任何“跳过/复用旧结果”的动作。"""
        for decision in self.decisions:
            if decision.action is not RecoveryAction.REEXECUTE:
                raise SpaForbiddenInT0(decision.node_id)


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """`plan_recovery` 的返回：要么有计划，要么有升级原因，二者恰有其一。"""

    plan: RecoveryPlan | None
    escalation: RecoveryEscalation | None

    def __post_init__(self) -> None:
        if (self.plan is None) == (self.escalation is None):
            raise ValueError("必须恰有 plan 或 escalation 之一")

    @property
    def planned(self) -> bool:
        return self.plan is not None

    def as_detail(self) -> Mapping[str, object]:
        if self.plan is not None:
            return MappingProxyType(
                {
                    "planned": True,
                    "failed_node": self.plan.failed_node,
                    "affected": list(self.plan.affected_nodes),
                    "action": RecoveryAction.REEXECUTE.value,
                }
            )
        assert self.escalation is not None
        return MappingProxyType({"planned": False, "escalation": self.escalation.as_detail()})


# ---------------------------------------------------------------------------
# 5. 受影响集合（§8.4 第一行）
# ---------------------------------------------------------------------------
def affected_nodes_expected(graph: GraphView, failed_node: str) -> frozenset[str]:
    """`descendants(failed) ∪ {failed}` 的**集合**形态（顺序由 OrderingPort 提供）。

    实现：从失败节点沿出边做闭包（后继方向），最后并上失败节点本身。
    输入：只读图视图 + 失败节点。
    输出：`frozenset`（只用于比较；**不得**直接序列化，集合无序）。
    副作用：无。
    错误：失败节点不在图中 → `PlanRefused(FAILED_NODE_NOT_IN_GRAPH)`。
    """
    node_ids = graph.node_ids()
    if failed_node not in node_ids:
        raise PlanRefused("FAILED_NODE_NOT_IN_GRAPH", f"图中没有节点 {failed_node!r}")
    dependencies = graph.dependencies()
    successors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for node_id, preds in dependencies.items():
        for pred in preds:
            successors.setdefault(pred, []).append(node_id)
    reached: set[str] = set()
    stack = [failed_node]
    while stack:
        current = stack.pop()
        for successor in successors.get(current, ()):  # 顺序不影响集合
            if successor not in reached:
                reached.add(successor)
                stack.append(successor)
    reached.discard(failed_node)
    return frozenset(reached | {failed_node})


def assert_topological_subset(
    order: Sequence[str], graph: GraphView, subset: frozenset[str]
) -> None:
    """校验给定顺序是 `subset` 的一个拓扑序。

    规则：
      1. 元素唯一；
      2. 集合恰等于 `subset`；
      3. 对每个节点，它在 `subset` 内的全部前驱都必须排在它**之前**。

    不满足任一条 → `PlanRefused(TOPOLOGY_ORDER_INVALID)`。
    """
    if len(set(order)) != len(order):
        raise PlanRefused("TOPOLOGY_ORDER_INVALID", "受影响顺序含重复节点")
    if set(order) != set(subset):
        missing = sorted(set(subset) - set(order))
        extra = sorted(set(order) - set(subset))
        raise PlanRefused(
            "AFFECTED_SET_INVALID", f"受影响集合不符：缺 {missing}，多 {extra}"
        )
    position = {node_id: index for index, node_id in enumerate(order)}
    for node_id in order:
        for predecessor in graph.dependencies().get(node_id, ()):
            if predecessor in subset and position[predecessor] >= position[node_id]:
                raise PlanRefused(
                    "TOPOLOGY_ORDER_INVALID",
                    f"前驱 {predecessor!r} 未排在 {node_id!r} 之前",
                )


# ---------------------------------------------------------------------------
# 6. 主流程
# ---------------------------------------------------------------------------
def plan_recovery(
    *,
    task_id: str,
    graph: GraphView,
    failed_node: str,
    failure: FailureInput,
    facts: RecoveryFactsPort,
    ordering: OrderingPort,
    graph_version: int,
    graph_hash: str,
    ruleset_hash: str,
) -> RecoveryOutcome:
    """生成 T0 的定向恢复计划（或给出升级原因）。

    步骤：
      1. 失败节点必须处于 `FAILED`；否则升级 `STATE_MISMATCH`；
      2. 失败节点重试预算必须还有；否则升级 `NO_RETRY_BUDGET`；
      3. 错误分类 → 只允许 `RESOURCE` 类在 T0 自动重跑；否则升级；
      4. `affected = descendants(failed) ∪ {failed}`，校验 `ordering` 是它的拓扑序；
         再检查**全部**受影响节点的预算（all-or-nothing）；
      5. 逐节点按 §8.4 求值全部检查，决策理由 = **第一条**失败的分支；
      6. 构造不可变计划（正文无时间戳/无 plan_id/无集合）。

    输入：任务/图标识、失败节点、失败事实、只读事实端口、受影响顺序端口、三个哈希。
    输出：`RecoveryOutcome`（计划或升级）。
    副作用：无（只调用只读端口）。
    错误：不变量破坏 → `PlanRefused`；§8.4 ⑧ 命中 → `SpaForbiddenInT0`。
    """
    # 步骤 1：状态必须 FAILED（其它状态没有“恢复”语义）
    state = facts.state_of(failed_node)
    signature = signature_from_failure(failure)
    if state != "FAILED":
        return RecoveryOutcome(
            plan=None,
            escalation=RecoveryEscalation(
                failed_node=failed_node,
                reason=EscalationReason.STATE_MISMATCH,
                category=signature.category,
                retryability=signature.retryability,
                detail=f"节点状态为 {state}，恢复只处理 FAILED",
            ),
        )
    # 步骤 2：重试预算
    if not facts.retry_budget_available(failed_node):
        return RecoveryOutcome(
            plan=None,
            escalation=RecoveryEscalation(
                failed_node=failed_node,
                reason=EscalationReason.NO_RETRY_BUDGET,
                category=signature.category,
                retryability=signature.retryability,
                detail="retry_policy.max_attempts 已耗尽：按 05 §9.3 R11 走 BLOCKED",
            ),
        )
    # 步骤 3：类别是否允许在 T0 自动重跑
    policy = CATEGORY_POLICY[signature.category]
    if not policy.plan_eligible_in_t0:
        reason = (
            EscalationReason.UNKNOWN_FAILURE
            if signature.category is ErrorCategory.UNKNOWN
            else EscalationReason.CATEGORY_NOT_RECOVERABLE_IN_T0
        )
        return RecoveryOutcome(
            plan=None,
            escalation=RecoveryEscalation(
                failed_node=failed_node,
                reason=reason,
                category=signature.category,
                retryability=signature.retryability,
                detail=policy.rationale,
            ),
        )
    # 步骤 4：受影响集合与顺序（集合语义在 affected_nodes_expected，顺序来自 M04）
    subset = affected_nodes_expected(graph, failed_node)
    order = tuple(ordering.ordered_affected(failed_node))
    assert_topological_subset(order, graph, subset)
    # 步骤 4b：全有或全无 —— 任一受影响节点没有重试预算，整个计划都不执行
    exhausted = [node_id for node_id in order if not facts.retry_budget_available(node_id)]
    if exhausted:
        return RecoveryOutcome(
            plan=None,
            escalation=RecoveryEscalation(
                failed_node=exhausted[0],
                reason=EscalationReason.NO_RETRY_BUDGET,
                category=signature.category,
                retryability=signature.retryability,
                detail=(
                    f"受影响节点 {exhausted[0]!r} 的 retry_policy 预算已耗尽；"
                    "计划按 all-or-nothing 处理，不生成半套计划"
                ),
            ),
        )
    # 步骤 5：逐节点决策（顺序即拓扑序，稳定）
    decisions: list[RecoveryDecision] = []
    for node_id in order:
        decisions.append(
            _decide(
                node_id=node_id,
                failed_node=failed_node,
                facts=facts,
            )
        )
    # 步骤 6：不可变计划
    plan = RecoveryPlan(
        task_id=task_id,
        graph_version=graph_version,
        graph_hash=graph_hash,
        ruleset_hash=ruleset_hash,
        failed_node=failed_node,
        signature=signature,
        decisions=tuple(decisions),
    )
    plan.assert_no_spa()
    return RecoveryOutcome(plan=plan, escalation=None)


def _decide(*, node_id: str, failed_node: str, facts: RecoveryFactsPort) -> RecoveryDecision:
    """按 §8.4 的顺序对单个节点求值。

    全量求值（七项检查都跑）而不是短路：诊断需要知道“还有哪些条件也不满足”；
    但**决策理由**只取第一条失败的分支，与 §8.4 的 if/elif 语义一致。
    """
    checks: list[CheckOutcome] = [
        CheckOutcome(CheckName.RETRYABLE, facts.retry_budget_available(node_id)),
        CheckOutcome(CheckName.SIDE_EFFECT, facts.side_effect_class(node_id) != "SIDE_EFFECT"),
        CheckOutcome(CheckName.EVIDENCE_VALID, facts.evidence_valid(node_id)),
        CheckOutcome(
            CheckName.PREDECESSOR_HASHES_UNCHANGED, facts.predecessor_hashes_unchanged(node_id)
        ),
        CheckOutcome(CheckName.DC_AVAILABLE, facts.dc_available(node_id)),
        CheckOutcome(CheckName.DISK_REHASH_MATCHES, facts.disk_rehash_matches(node_id)),
        CheckOutcome(CheckName.GATE_PASSES, facts.gate_passes_under_current_rules(node_id)),
    ]
    # ① 失败节点本身：一律重跑（预算已在 plan_recovery 里检查过）
    if node_id == failed_node:
        return RecoveryDecision(
            node_id=node_id,
            action=RecoveryAction.REEXECUTE,
            reason=ReexecuteReason.FAILED_NODE,
            is_failed_node=True,
            checks=tuple(checks),
        )
    by_name = {check.name: check for check in checks}
    # ② 有副作用
    if not by_name[CheckName.SIDE_EFFECT].passed:
        return _decision(node_id, ReexecuteReason.SIDE_EFFECT, checks)
    # ③ 证据无效
    if not by_name[CheckName.EVIDENCE_VALID].passed:
        return _decision(node_id, ReexecuteReason.NO_VALID_EVIDENCE, checks)
    # ④ 前驱哈希变了
    if not by_name[CheckName.PREDECESSOR_HASHES_UNCHANGED].passed:
        return _decision(node_id, ReexecuteReason.PREDECESSOR_HASH_CHANGED, checks)
    # ⑤ 无有效 DC（T0 恒真；这一支就是“保守重跑”）
    if not by_name[CheckName.DC_AVAILABLE].passed:
        return _decision(node_id, ReexecuteReason.NO_VALID_DC, checks)
    # ⑥ 磁盘产物复算不符
    if not by_name[CheckName.DISK_REHASH_MATCHES].passed:
        return _decision(node_id, ReexecuteReason.DISK_REHASH_MISMATCH, checks)
    # ⑦ 当前规则下 Gate 不过
    if not by_name[CheckName.GATE_PASSES].passed:
        return _decision(node_id, ReexecuteReason.GATE_NOT_PASSING, checks)
    # ⑧ §8.4 的 sign_SPA 分支：T0 禁止
    raise SpaForbiddenInT0(node_id)


def _decision(
    node_id: str, reason: ReexecuteReason, checks: Sequence[CheckOutcome]
) -> RecoveryDecision:
    return RecoveryDecision(
        node_id=node_id,
        action=RecoveryAction.REEXECUTE,
        reason=reason,
        is_failed_node=False,
        checks=tuple(checks),
    )


# ---------------------------------------------------------------------------
# 7. 自检
# ---------------------------------------------------------------------------
def assert_t0_single_action() -> list[str]:
    """验收判据：`RecoveryAction` 在 T0 只有一个值，且没有 SKIP/SPA 类成员。"""
    problems: list[str] = []
    if len(RecoveryAction) != 1:
        problems.append(f"T0 动作必须恰好 1 个，实际 {[a.value for a in RecoveryAction]}")
    if next(iter(RecoveryAction)) is not RecoveryAction.REEXECUTE:
        problems.append("唯一动作必须是 REEXECUTE")
    for member in RecoveryAction:
        for forbidden in ("SKIP", "SPA", "REUSE", "DEFER", "RETRY_WITHOUT_STATE"):
            if forbidden in member.name:
                problems.append(f"动作 {member.name} 命中 T2 禁名 {forbidden}")
    if tuple(T0_POLICY_FLAGS) != ("mode", "dc_used", "spa_used", "approval_required"):
        problems.append("policy 键集合/顺序不稳定（会影响 plan_hash）")
    if T0_POLICY_FLAGS["spa_used"] is not False or T0_POLICY_FLAGS["dc_used"] is not False:
        problems.append("T0 的 dc_used/spa_used 必须为 False")
    return problems


def assert_no_approval_states() -> list[str]:
    """验收判据：T0 不得出现 PROPOSED/APPROVED/审批/T1 恢复状态。

    检查项：
      1. 模块 globals 里没有以 `RecoveryState` 命名的类型，也没有 PROPOSED/APPROVED 字面量；
      2. 公开面没有 `propose` / `approve` / `validate_plan` / `close_plan` 这类函数；
      3. `RecoveryPlan` 没有 `state` / `status` / `approval` 字段。
    """
    problems: list[str] = []
    forbidden_names = ("PROPOSED", "APPROVED", "EXECUTING", "RECHECKED", "CLOSED", "ESCALATED")
    for name, value in globals().items():
        if name.startswith("__"):
            continue
        if isinstance(value, str) and value in forbidden_names:
            problems.append(f"模块级常量 {name} 出现了 T1 恢复状态字面值 {value}")
        if name.lower() in {"recoverystate", "planstate", "approvalstate"}:
            problems.append(f"模块不得定义审批/恢复状态枚举 {name}")
    for forbidden_function in ("propose_plan", "approve_plan", "validate_plan", "close_plan"):
        if forbidden_function in globals():
            problems.append(f"模块不得提供 {forbidden_function}()")
    plan_fields = set(RecoveryPlan.__dataclass_fields__)
    for forbidden_field in ("state", "status", "approval", "approved_by", "proposed_at"):
        if forbidden_field in plan_fields:
            problems.append(f"RecoveryPlan 不得有字段 {forbidden_field}")
    if set(RecoveryAction) != {RecoveryAction.REEXECUTE}:
        problems.append("动作枚举被扩展（T0 只有 REEXECUTE）")
    return problems


def assert_plan_structure(plan: RecoveryPlan) -> list[str]:
    """自检：计划正文的键集合固定、无 plan_id、无集合、决策按拓扑序覆盖失败节点。

    时间/路径类易变值的检查由 `plan_freeze.assert_body_time_free()` 统一负责（单一实现）。
    """
    problems: list[str] = []
    body = plan.body()
    expected_keys = (
        "plan_format_version", "task_id", "graph_version", "graph_hash", "ruleset_hash",
        "failed_node", "error_signature", "policy", "decisions",
    )
    if tuple(body) != expected_keys:
        problems.append(f"正文键集合/顺序不符：{tuple(body)}")
    if "plan_id" in body:
        problems.append("正文不得含 plan_id（会形成自指）")
    for key, value in body.items():
        if isinstance(value, (set, frozenset)):
            problems.append(f"正文键 {key} 直接是集合（顺序不稳定）")
    if list(body["decisions"]) != [d.as_body() for d in plan.decisions]:
        problems.append("正文决策顺序与计划对象不一致")
    if body["policy"]["spa_used"] is not False:
        problems.append("policy.spa_used 必须为 False")
    if set(plan.affected_nodes) != set(affected_nodes_expected(
        _GraphFromPlan(plan), plan.failed_node
    )):
        problems.append("决策集合与 descendants∪{failed} 不一致")
    return problems


class _GraphFromPlan:
    """`assert_plan_structure` 专用的图替身：把计划里的决策当成线性链。

    只用于自检里“集合相等”这一条；真实校验发生在 `plan_recovery` 的步骤 4。
    """

    def __init__(self, plan: RecoveryPlan) -> None:
        self._nodes = tuple(decision.node_id for decision in plan.decisions)

    def node_ids(self) -> tuple[str, ...]:
        return self._nodes

    def dependencies(self) -> Mapping[str, tuple[str, ...]]:
        # 线性链：每个节点依赖前一个（第一个无前驱），保证闭包 = 全体
        parents: dict[str, tuple[str, ...]] = {}
        for index, node_id in enumerate(self._nodes):
            parents[node_id] = () if index == 0 else (self._nodes[index - 1],)
        return MappingProxyType(parents)