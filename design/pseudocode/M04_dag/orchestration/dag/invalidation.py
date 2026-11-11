"""M04 · orchestration/dag/invalidation.py — 失效传播（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-010（失效传播）、ADR-001（INVALIDATED）
依赖：M04 graph_version（GraphContent/GraphDiff）、M02 StateMachine（**只经 transition()**）
不变量：失效只写 `evidence_invalidations` + `audit_log`；不删除/不修改 evidence；不占 E0–E3
错误码：STATE_TRANSITION_DENIED（409，reason=STALE_CAUSE_DETECTED 的拒绝/守卫失败）、
        PLAN_HASH_MISMATCH（仅 `INVALIDATED→READY`，属 M02 守卫，不在本文件）
写入者：**StateMachine**（本文件只发起迁移请求；`evidence_invalidations` 由它在同事务追加）
状态：伪代码；不执行、不写库、不写证据、不跑重试

## 本文件回答三件事

  1. `descendants()`：给定若干节点，谁在它们下游？（确定性顺序）
  2. 失效集合怎么算？四类原因各从哪些种子出发、哪些节点要迁移、哪些跳过？
  3. 失效在哪里落库？——**只在 StateMachine 的 `VERIFIED→INVALIDATED` 事务里**落
     `evidence_invalidations` + `audit_log`（M02 `_apply_success` 的既有行为）。

## 三条硬边界（与 DEC-03 一致）

  | 东西 | 本文件是否碰 | 说明 |
  |---|---|---|
  | `evidence_invalidations` | 不直接写 | 由 StateMachine 在 `_append_invalidations` 同事务追加 |
  | `audit_log` | 不直接写 | 同上；审计写者只有 StateMachine（06 §3） |
  | `evidence` 行 | **绝不** | 不 UPDATE、不 DELETE、不“标记 stale 列”；`APPENDED` = 行存在 |
  | E0–E3 事件 | **绝不** | 失效是控制事件，不占用证据等级（I-11） |
  | 节点 `state` | 不直接写 | 只经 `transition()`；本文件不持有仓储 |
  | `evidence_rejections` | 不建、不写 | 属 WP-07/P4（DEC-03），P3 不涉及 |

## 为什么必须经 StateMachine

  `VERIFIED→INVALIDATED` 是唯一能同时做到“状态 + 失效记录 + 审计”原子的路径（06 §2）。
  任何绕过它的写法（直接 UPDATE、直接 INSERT invalidations）都会破坏 I-14 与审计可追溯性。
  本文件因此只依赖一个端口：`TransitionPort.transition(...)`。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .graph_version import GraphContent, GraphDiff, diff_graphs

__all__ = [
    "CAUSE_TYPES",
    "INVALIDATION_BOUNDARY",
    "OQ_CT_12_NOTE",
    "CauseType",
    "ChangeSignal",
    "EvidenceIndexPort",
    "InvalidationAborted",
    "InvalidationIncomplete",
    "InvalidationSet",
    "InvalidationSkipReason",
    "InvalidationTarget",
    "NodeStatePort",
    "SkippedNode",
    "StateTransitionDeniedLike",
    "StaleEvidence",
    "TransitionPort",
    "apply_invalidations",
    "assert_invalidation_boundary",
    "build_invalidation_set",
    "descendants",
]

# 与 06 §1.3 `evidence_invalidations.cause_type` 的 CHECK 完全一致（四值，不得增删）。
CAUSE_TYPES: Final[tuple[str, ...]] = (
    "INPUT_CHANGE",
    "PREDECESSOR_CHANGE",
    "GRAPH_VERSION_CHANGE",
    "RULESET_CHANGE",
)


class CauseType(StrEnum):
    """失效原因；字面值必须等于 `CAUSE_TYPES`（DB CHECK 会拒绝其它值）。"""

    INPUT_CHANGE = "INPUT_CHANGE"
    PREDECESSOR_CHANGE = "PREDECESSOR_CHANGE"
    GRAPH_VERSION_CHANGE = "GRAPH_VERSION_CHANGE"
    RULESET_CHANGE = "RULESET_CHANGE"


INVALIDATION_BOUNDARY: Final[tuple[str, ...]] = (
    "失效只写 evidence_invalidations + audit_log（均经 StateMachine 同事务）。",
    "不 UPDATE/DELETE evidence；不新增 stale 列；不改写历史证据。",
    "失效事件不占 E0–E3：不调用 Collector，不产生 EvidenceRecord。",
    "状态变更只经 StateMachine.transition()；本文件不持有任何仓储。",
    "任一必要事实缺失（证据读不到、节点状态不明）→ fail-closed，不猜。",
)

OQ_CT_12_NOTE: Final[str] = (
    "OQ-CT-12 未决：节点已 INVALIDATED 时的重复失效是否幂等。"
    "P3 的处理：不重复迁移（没有合法边），把该节点列入 `deferred_reinvalidation` 并告警；"
    "这不等于“已幂等”，需要 StateMachine 提供受审计的追加入口后才能实现。"
)


# ---------------------------------------------------------------------------
# 1. 端口
# ---------------------------------------------------------------------------
class StateTransitionDeniedLike(Exception):
    """M02 `StateTransitionDenied` 的结构替身（本文件不 import M02 运行期实现）。"""

    error_code: str
    reason: str
    previous_state: str | None
    next_state: str | None


class TransitionPort(Protocol):
    """StateMachine 的结构视图：**唯一**可用的状态写入口。

    签名与 M02 `StateMachine.transition(obj_type, obj_id, to_state, actor, reason_code, ctx)`
    一致；`ctx` 需要 `previous_state="VERIFIED"`、`cause_type`、`cause_ref`、
    `evidence_ids`、`correlation_id`、`rule_version`、`task_id`。
    """

    def transition(
        self,
        obj_type: object,
        obj_id: str,
        to_state: str,
        actor: object,
        reason_code: object,
        ctx: object,
    ) -> object:
        ...


class NodeStatePort(Protocol):
    """只读节点状态（M02 `NodeRepository.get_state` / `list_by_task`）。"""

    def state_of(self, task_id: str, node_id: str) -> str:
        ...


class EvidenceIndexPort(Protocol):
    """只读证据索引：给出某节点全部证据 id（按 event_seq 升序）。

    只读！本端口**没有** append/update/delete 方法；实现方不得在这里开写口。
    """

    def evidence_ids_of(self, task_id: str, node_id: str) -> tuple[str, ...]:
        ...


# ---------------------------------------------------------------------------
# 2. 变更信号
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChangeSignal:
    """触发失效的一次变化。

    四类原因各自的字段用法：
      - `INPUT_CHANGE`：`cause_ref` = 新 dataset sha256；`seed_nodes` 可空（默认取根节点）；
      - `PREDECESSOR_CHANGE`：`seed_nodes` = 内容已变的节点（其下游要失效）；
      - `GRAPH_VERSION_CHANGE`：`graph_diff` = 新旧图差异（`diff_graphs`）；
      - `RULESET_CHANGE`：`cause_ref` = 新 ruleset_hash；`seed_nodes` 可空（默认全图）。
    """

    cause_type: CauseType
    cause_ref: str
    graph_version: int
    seed_nodes: tuple[str, ...] = ()
    graph_diff: GraphDiff | None = None
    note: str = ""


# ---------------------------------------------------------------------------
# 3. 结果值对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StaleEvidence:
    evidence_id: str
    node_id: str


@dataclass(frozen=True, slots=True)
class InvalidationTarget:
    """一个要执行 `VERIFIED→INVALIDATED` 的节点。

    `evidence_ids` 必须非空：M02 `_append_invalidations` 明确拒绝空集合
    （“失效迁移必须至少引用一条 stale 证据”）。空集合说明数据不一致 → fail-closed。
    """

    node_id: str
    evidence_ids: tuple[str, ...]
    cause_type: CauseType
    cause_ref: str
    current_state: str = "VERIFIED"


class InvalidationSkipReason(StrEnum):
    NOT_VERIFIED = "NOT_VERIFIED"              # 状态不是 VERIFIED：无需失效迁移
    ALREADY_INVALIDATED = "ALREADY_INVALIDATED"  # 已 INVALIDATED：OQ-CT-12 未决
    REMOVED_FROM_GRAPH = "REMOVED_FROM_GRAPH"  # 新图已删除该节点
    NO_EVIDENCE = "NO_EVIDENCE"                # VERIFIED 但无证据 → 数据不一致（见 fail_closed）


@dataclass(frozen=True, slots=True)
class SkippedNode:
    node_id: str
    reason: InvalidationSkipReason
    detail: str = ""


@dataclass(frozen=True, slots=True)
class InvalidationSet:
    """一次失效传播的完整计划（**不是**恢复计划，不落库、不签名）。"""

    task_id: str
    cause_type: CauseType
    cause_ref: str
    graph_version: int
    targets: tuple[InvalidationTarget, ...]        # 按 topological_then_node_id 排序
    skipped: tuple[SkippedNode, ...]
    affected_nodes: tuple[str, ...]                # 全部受影响（含跳过）
    stale_evidence: tuple[StaleEvidence, ...]
    deferred_reinvalidation: tuple[str, ...]       # 已 INVALIDATED 的节点（OQ-CT-12）

    @property
    def is_empty(self) -> bool:
        return not self.targets

    def total_evidence(self) -> int:
        return sum(len(t.evidence_ids) for t in self.targets)


class InvalidationIncomplete(RuntimeError):
    """必要事实缺失/不一致：拒绝生成失效集合（fail-closed），不返回“部分结果”。"""

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 409

    def __init__(self, *, node_id: str, reason: str) -> None:
        self.node_id = node_id
        self.reason = reason
        super().__init__(f"{self.error_code}：节点 {node_id!r} 的失效集合不完整（{reason}）")


class InvalidationAborted(RuntimeError):
    """迁移中途被拒绝：已成功的部分必须被完整报告，不得“吞掉一半”。"""

    error_code: Final[str] = "STATE_TRANSITION_DENIED"

    def __init__(
        self,
        *,
        node_id: str,
        denial: BaseException,
        applied: Sequence[str],
        remaining: Sequence[str],
    ) -> None:
        self.node_id = node_id
        self.denial = denial
        self.applied = tuple(applied)
        self.remaining = tuple(remaining)
        super().__init__(
            f"{self.error_code}：失效在节点 {node_id!r} 被拒绝"
            f"（{type(denial).__name__}）；已失效 {list(self.applied)}，未处理 {list(self.remaining)}"
        )


# ---------------------------------------------------------------------------
# 4. descendants()
# ---------------------------------------------------------------------------
def descendants(
    graph: GraphContent,
    seeds: Sequence[str],
    *,
    include_seeds: bool = False,
) -> tuple[str, ...]:
    """返回 `seeds` 的全部传递后继，按 `topological_then_node_id` 排序。

    输入：
      - `graph`：内存全文（含边），必须已通过 `verify_rebuild()`；
      - `seeds`：种子节点；不在图中的种子被忽略（由调用方先行校验）；
      - `include_seeds=False`：默认不包含种子自身。

    输出：确定性元组。排序规则与 M03 `scheduler.yaml: ready_order=topological_then_node_id`
    一致：拓扑层序优先，同层按 node_id 字典序。**不返回集合**，避免调用方拿到无序结果。

    副作用：无。

    错误：无（纯函数）。种子不在图中不是异常，而是“该节点已被新图删除”，
    由 `build_invalidation_set()` 记 `REMOVED_FROM_GRAPH`。
    """
    pred = graph.dependencies()
    succ: dict[str, list[str]] = {n.node_id: [] for n in graph.nodes}
    for node_id, parents in pred.items():
        for p in parents:
            succ.setdefault(p, []).append(node_id)

    reached: set[str] = set()
    stack = [s for s in seeds if s in succ]
    while stack:
        cur = stack.pop()
        for nxt in succ.get(cur, ()):
            if nxt not in reached:
                reached.add(nxt)
                stack.append(nxt)
    if include_seeds:
        reached |= {s for s in seeds if s in succ}
    else:
        reached -= {s for s in seeds}
    if not reached:
        return ()
    order = _topological_subset(graph, reached)
    return order


def _topological_subset(graph: GraphContent, subset: set[str]) -> tuple[str, ...]:
    """子图的确定性拓扑序（Kahn + 按 node_id 的最小堆）。"""
    import heapq

    pred = graph.dependencies()
    indeg = {n: sum(1 for p in pred.get(n, ()) if p in subset) for n in subset}
    succ: dict[str, list[str]] = {n: [] for n in subset}
    for node in subset:
        for p in pred.get(node, ()):
            if p in subset:
                succ.setdefault(p, []).append(node)
    heap = [n for n, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    out: list[str] = []
    while heap:
        cur = heapq.heappop(heap)
        out.append(cur)
        for nxt in sorted(succ.get(cur, ())):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, nxt)
    if len(out) != len(subset):  # 子图成环：说明图本身没通过校验，拒绝静默截断
        raise InvalidationIncomplete(node_id="*", reason="子图成环，无法给出确定顺序")
    return tuple(out)


# ---------------------------------------------------------------------------
# 5. 失效集合
# ---------------------------------------------------------------------------
def build_invalidation_set(
    *,
    task_id: str,
    signal: ChangeSignal,
    graph: GraphContent,
    states: NodeStatePort,
    evidence: EvidenceIndexPort,
) -> InvalidationSet:
    """计算一次失效传播的目标集合。

    种子规则（按原因）：

      | 原因 | 种子 | 说明 |
      |---|---|---|
      | `INPUT_CHANGE` | 无依赖的根节点（可被 `seed_nodes` 覆盖） | 数据集变了，根节点输入变 |
      | `PREDECESSOR_CHANGE` | `signal.seed_nodes` | 上游节点内容变了，其下游失效 |
      | `GRAPH_VERSION_CHANGE` | `graph_diff` 的变动/删除节点 + 其下游 | 图结构或参数变化 |
      | `RULESET_CHANGE` | 全部节点 | 规则版本变，所有已验证结论都要重判 |

    受影响集合 = 种子 ∪ `descendants(种子)`，再按 `topological_then_node_id` 排序。

    每个受影响节点按状态分流：
      - `VERIFIED` → `targets`（要迁移）；证据为空 → `InvalidationIncomplete`（fail-closed）；
      - `INVALIDATED` → `deferred_reinvalidation`（OQ-CT-12；不重复迁移、不静默吞）；
      - 其它状态 → `skipped(NOT_VERIFIED)`（它们本来就要重算，无需失效迁移）；
      - 不在图中 → `skipped(REMOVED_FROM_GRAPH)`。

    副作用：只读。**不**写库、**不**调用 transition（调用在 `apply_invalidations`）。
    """
    _require_cause(signal.cause_type)
    seeds = _seeds_for(signal, graph)
    known = {n.node_id for n in graph.nodes}

    affected: list[str] = []
    for seed in seeds:
        if seed not in known:
            continue
        affected.append(seed)
        affected.extend(descendants(graph, (seed,)))
    affected_set = set(affected)
    removed = {s for s in seeds if s not in known}
    ordered = _topological_subset(graph, affected_set) if affected_set else ()

    targets: list[InvalidationTarget] = []
    skipped: list[SkippedNode] = [
        SkippedNode(node_id=n, reason=InvalidationSkipReason.REMOVED_FROM_GRAPH,
                    detail="新版本已删除该节点")
        for n in sorted(removed)
    ]
    deferred: list[str] = []
    stale: list[StaleEvidence] = []

    for node_id in ordered:
        state = states.state_of(task_id, node_id)
        if state == "VERIFIED":
            ids = tuple(evidence.evidence_ids_of(task_id, node_id))
            if not ids:
                # 不可能同时成立：VERIFIED 必须有 E2/E3 证据。数据不一致时不得“跳过”。
                raise InvalidationIncomplete(
                    node_id=node_id,
                    reason="状态为 VERIFIED 但证据索引为空（证据链/索引不一致）",
                )
            targets.append(InvalidationTarget(
                node_id=node_id,
                evidence_ids=ids,
                cause_type=signal.cause_type,
                cause_ref=signal.cause_ref,
            ))
            stale.extend(StaleEvidence(evidence_id=e, node_id=node_id) for e in ids)
        elif state == "INVALIDATED":
            deferred.append(node_id)
            skipped.append(SkippedNode(
                node_id=node_id,
                reason=InvalidationSkipReason.ALREADY_INVALIDATED,
                detail="OQ-CT-12 未决：不重复迁移；见 deferred_reinvalidation",
            ))
        else:
            skipped.append(SkippedNode(
                node_id=node_id,
                reason=InvalidationSkipReason.NOT_VERIFIED,
                detail=f"当前状态 {state}：无需失效迁移",
            ))

    return InvalidationSet(
        task_id=task_id,
        cause_type=signal.cause_type,
        cause_ref=signal.cause_ref,
        graph_version=graph.graph_version,
        targets=tuple(targets),
        skipped=tuple(skipped),
        affected_nodes=tuple(ordered),
        stale_evidence=tuple(stale),
        deferred_reinvalidation=tuple(sorted(deferred)),
    )


def _require_cause(cause: CauseType) -> None:
    if cause.value not in CAUSE_TYPES:
        raise ValueError(f"未注册的失效原因 {cause!r}（只允许 {CAUSE_TYPES}）")


def _seeds_for(signal: ChangeSignal, graph: GraphContent) -> tuple[str, ...]:
    """按原因给种子；不给就退回保守默认，**不返回空集合当“无需失效”**。"""
    if signal.seed_nodes:
        return tuple(dict.fromkeys(signal.seed_nodes))
    if signal.cause_type is CauseType.INPUT_CHANGE:
        # 数据集变化 → 所有根节点（无前驱）的输入都变
        return tuple(n.node_id for n in graph.nodes if not graph.dependencies().get(n.node_id))
    if signal.cause_type is CauseType.GRAPH_VERSION_CHANGE:
        if signal.graph_diff is None:
            raise InvalidationIncomplete(
                node_id="*", reason="GRAPH_VERSION_CHANGE 必须带 graph_diff；否则无法确定影响面",
            )
        diff = signal.graph_diff
        return tuple(dict.fromkeys((*diff.touched_nodes(), *diff.added_nodes, *diff.removed_nodes)))
    if signal.cause_type is CauseType.RULESET_CHANGE:
        # 规则版本变化：全图重判（T0 只有一套规则，但语义上不允许“抽样子集”）
        return tuple(n.node_id for n in graph.nodes)
    # PREDECESSOR_CHANGE 未给种子：无法确定影响面 → fail-closed
    raise InvalidationIncomplete(
        node_id="*", reason="PREDECESSOR_CHANGE 必须显式给 seed_nodes",
    )


# ---------------------------------------------------------------------------
# 6. 调用点：写 evidence_invalidations 的唯一合法路径
# ---------------------------------------------------------------------------
def apply_invalidations(
    plan: InvalidationSet,
    *,
    machine: TransitionPort,
    actor: object,
    correlation_id: str,
    rule_version: str,
    reason_code: str = "STALE_CAUSE_DETECTED",
    on_applied: object | None = None,
) -> tuple[object, ...]:
    """逐节点调用 `StateMachine.transition(NODE, node, "INVALIDATED", ...)`。

    每个成功调用的**同事务**结果（由 StateMachine 保证）：
      - `evidence_invalidations` 追加 N 行（N = 该节点的 stale evidence 数）；
      - `audit_log(result=OK)` 一条；
      - `nodes.state = INVALIDATED`。
    本函数自己**不写**这三样东西，只提供参数。

    失败处理（不吞异常）：
      - 任一节点被拒 → 立即停止，抛 `InvalidationAborted`，带上已应用列表与未处理列表；
      - 不重试、不跳过、不“继续把剩下的失效掉”——半套失效比不做更危险
        （Gate 会看到部分 stale、部分非 stale，结论不可解释）。

    幂等：`plan.targets` 已按前态 `VERIFIED` 过滤；重复调用会因 `STALE_PREVIOUS_STATE`
    被 StateMachine 拒绝（M02 `NEG-M02-34`），本函数不会把它当成成功。

    返回：`TransitionResult` 元组（M02 的结构，本文件不解读其内容）。
    """
    applied: list[str] = []
    results: list[object] = []
    targets = plan.targets
    for idx, target in enumerate(targets):
        ctx = _transition_context(
            task_id=plan.task_id,
            target=target,
            correlation_id=correlation_id,
            rule_version=rule_version,
        )
        try:
            result = machine.transition(
                "node",                 # ObjectType.NODE 的字面值；由 M02 校验
                target.node_id,
                "INVALIDATED",
                actor,
                reason_code,
                ctx,
            )
        except BaseException as exc:  # 包含 StateTransitionDenied / AuditWriteFailed
            remaining = [t.node_id for t in targets[idx + 1:]]
            raise InvalidationAborted(
                node_id=target.node_id, denial=exc, applied=applied, remaining=remaining,
            ) from exc
        applied.append(target.node_id)
        results.append(result)
        if on_applied is not None:
            on_applied(target)   # 只允许“观测/记录”，不得借此写库（见 assert_invalidation_boundary）
    return tuple(results)


def _transition_context(
    *, task_id: str, target: InvalidationTarget, correlation_id: str, rule_version: str
) -> object:
    """组装 M02 `TransitionContext`。

    字段逐项对应 05 §9.7 与 M02 的定义：
      - `previous_state="VERIFIED"`（乐观并发的期望前态，不得省略）；
      - `cause_type` / `cause_ref`：四类之一 + 引用（新哈希/节点/图版本）；
      - `evidence_ids`：本节点的 stale 证据（非空，M02 会再校验一次）；
      - `correlation_id` / `rule_version`：审计必填。
    实现阶段用 M02 的 dataclass 构造；这里返回同构 mapping，便于评审对照字段。
    """
    return MappingProxyType(
        {
            "task_id": task_id,
            "previous_state": target.current_state,
            "cause_type": target.cause_type.value,
            "cause_ref": target.cause_ref,
            "evidence_ids": target.evidence_ids,
            "correlation_id": correlation_id,
            "rule_version": rule_version,
        }
    )


# ---------------------------------------------------------------------------
# 7. 便捷封装：从“图版本变化”一路到“失效集合”
# ---------------------------------------------------------------------------
def invalidation_for_graph_change(
    *,
    task_id: str,
    before: GraphContent,
    after: GraphContent,
    states: NodeStatePort,
    evidence: EvidenceIndexPort,
) -> InvalidationSet:
    """图版本变化的便捷入口：`diff_graphs` → `ChangeSignal` → `build_invalidation_set`。

    只在“新版本已登记、旧版本仍可重建”的前提下调用；`cause_ref` 用新图哈希
    （`GRAPH_VERSION_CHANGE` 的引用取 `graph_hash`，便于审计追到具体版本内容）。

    若差异为空：返回空 `InvalidationSet`（`targets=()`），**不报错**——
    版本号上升但内容相同是合法情况（例如一次被拒绝后又重新登记同一内容）。
    """
    diff = diff_graphs(before, after)
    signal = ChangeSignal(
        cause_type=CauseType.GRAPH_VERSION_CHANGE,
        cause_ref=after.graph_hash,
        graph_version=after.graph_version,
        graph_diff=diff,
        note="graph version change",
    )
    return build_invalidation_set(
        task_id=task_id, signal=signal, graph=after, states=states, evidence=evidence,
    )


# ---------------------------------------------------------------------------
# 8. 自检
# ---------------------------------------------------------------------------
def assert_invalidation_boundary() -> list[str]:
    """自检：本模块不得出现证据写入/状态直写/E0–E3 痕迹。

    检查项（落地阶段由测试静态扫描本文件）：
      1. 不出现 `_insert` / `_append_invalidations` / `_apply_transition`（仓储私有写口）；
      2. 不出现 `"E0"`/`"E1"`/`"E2"`/`"E3"` 作为失效等级（失效不占证据等级）；
      3. 不出现 `UPDATE evidence` / `DELETE FROM evidence`；
      4. 只通过 `machine.transition(...)` 发起状态变更。
    返回违反项列表（空 = 通过）。
    """
    problems: list[str] = []
    forbidden_calls = ("_insert", "_append_invalidations", "_apply_transition", "_insert_planned")
    for name in forbidden_calls:
        if name in globals():
            problems.append(f"失效模块不得直接调用仓储写口 {name}")
    if len(CAUSE_TYPES) != 4:
        problems.append("cause_type 必须恰好四类（06 §1.3 CHECK）")
    if not INVALIDATION_BOUNDARY:
        problems.append("边界声明不得为空")
    return problems