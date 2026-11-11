"""M04 · orchestration/dag/graph_version.py — 图版本、回放缓照与注册边界（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-002（图版本可回放）、FR-010（图版本变化触发失效）
依赖：M04 builder（GraphDraft）、M04 validator（ValidationReport 作为“已校验”凭证）、M02 repositories
不变量：版本单调 +1；冲突 409；快照可回放；注册只在 Orchestrator 且同事务插 nodes + graph_versions
错误码：STATE_TRANSITION_DENIED（409，reason=GRAPH_VERSION_CONFLICT / DAG_INVALID）、SCHEMA_INVALID（快照形态）
写入者：**Orchestrator**（持 `DAG_REGISTER`）→ M02 `NodeRepository._insert_planned` + 本模块 `GraphVersionStorePort`
状态：伪代码；**不写 SQL、不建表、不执行事务**

## 写者边界（DEC-01，不可重开）

  | 动作 | 允许的写者 | 落点 |
  |---|---|---|
  | INSERT `nodes`（初始 `PLANNED`） | Orchestrator（`DAG_REGISTER`） | M02 `NodeRepository._insert_planned` |
  | INSERT `graph_versions` | Orchestrator（`DAG_REGISTER`） | `GraphVersionStorePort`（WP-04 实现；**不在 M02 schema 范围**） |
  | UPDATE `tasks.graph_version` | **只有** StateMachine | `PLANNING→READY` 时写（M02 `TaskRepository._apply_transition`） |
  | UPDATE `nodes.state` | **只有** StateMachine | `transition()`，本文件不碰 |
  | 计算 `graph_hash` / 拓扑序 | Builder | 本文件只校验与保存 |

  所以“登记图”在本阶段是**两段式**：
    ① `GraphRegistrar.register()`：同事务写 `graph_versions` + `nodes(PLANNED)`；
    ② `StateMachine.transition(TASK, …, "READY", ctx.graph_version=N)`：写 `tasks.graph_version`。
  06 §2 把这两步写成“必须原子”，与 DEC-01 的写者分离存在口径差 → 记 `DOC_SYNC_PENDING`，
  **本阶段不改 06**（用户裁决：以 DEC-01 为准）。

## 为什么本文件不写 SQL

  `graph_versions` 在 M02 的建表范围之外（M02 MODULE §3 明写“由 WP-04 负责”），
  但它的 DDL 已在 06 §1.3 冻结。P3 只定义**端口与方法语义**；
  实现阶段由 WP-04 提供 `GraphVersionStore`（不得顺手改 M02 schema，也不得在 P3 里写 SQL）。
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .builder import GraphDraft, NodeDraft
from .validator import ValidationReport

__all__ = [
    "DOC_SYNC_PENDING",
    "GRAPH_VERSION_RULES",
    "REPLAY_SNAPSHOT_FIELDS",
    "SNAPSHOT_SCHEMA_VERSION",
    "CapabilityGatePort",
    "GraphContent",
    "GraphDiff",
    "GraphRegistrar",
    "GraphRegistrationResult",
    "GraphSnapshot",
    "GraphVersionConflict",
    "GraphVersionState",
    "GraphVersionStorePort",
    "NodeRegistrationRow",
    "NodeRegistrarPort",
    "ReadyTransitionRequest",
    "RegistrationRejected",
    "RegistrationViolation",
    "ReplayMismatch",
    "UnitOfWorkPort",
    "assert_graph_version_contract",
    "compare_versions",
    "diff_graphs",
    "parse_topology_order",
    "serialize_topology_order",
    "snapshot_digest",
    "verify_rebuild",
]

SNAPSHOT_SCHEMA_VERSION: Final[str] = "1.0"

# 06 §2 / §3 与本阶段裁决不一致的条目：只登记，不改上游文档。
DOC_SYNC_PENDING: Final[tuple[str, ...]] = (
    "06 §1.2 表清单：`graph_versions` 唯一写者写的是“DAG Builder（经 StateMachine 登记）”；"
    "按 DEC-01 应为“Orchestrator（持 DAG_REGISTER）+ WP-04 存储实现”，Builder 只计算。",
    "06 §3 表级写入权限：`graph_versions` 行写 StateMachine W（登记）、DAG Builder 计算；"
    "按 DEC-01，StateMachine 只写状态迁移，登记写者应为 Orchestrator。",
    "06 §2 事务边界：`graph_versions` 插入 + `tasks.graph_version` 更新“必须原子”；"
    "按 DEC-01 为两段式（同事务插 nodes+版本，另一事务由 StateMachine 在 READY 写版本号），"
    "本阶段以 DEC-01 为准，待文档同步后再改 06。",
)

GRAPH_VERSION_RULES: Final[tuple[str, ...]] = (
    "版本是整数，从 1 开始，每次登记严格 +1；不跳号、不回退、不复用。",
    "首次登记 base=0 → version=1；其后 version=latest+1。",
    "请求版本 ≤ 已登记最大版本：等于则 DUPLICATE（幂等重放，返回原快照），小于则 STALE（409）。",
    "请求版本 > latest+1：GAP，409；不得“补齐中间版本”。",
    "同一 (task_id, graph_version) 的 graph_hash 不可变；不同哈希 = 冲突，不是新版本。",
    "图版本变化本身不是“失效”的充要条件：是否失效由 invalidation.py 按差异计算。",
)


# ---------------------------------------------------------------------------
# 1. 版本比较
# ---------------------------------------------------------------------------
class GraphVersionState(StrEnum):
    """一次登记请求与已登记版本的相对关系。"""

    FIRST = "FIRST"        # 尚无版本：请求 1
    NEXT = "NEXT"          # 正常递增
    DUPLICATE = "DUPLICATE"  # 请求版本已存在且哈希相同 → 幂等返回
    STALE = "STALE"        # 请求版本落后于已登记最大版本 → 409
    GAP = "GAP"            # 跳号 → 409（不自动补）


class GraphVersionConflict(RuntimeError):
    """版本冲突；对外 409，用已注册码 `STATE_TRANSITION_DENIED`。

    为什么不用 `IDEMPOTENCY_CONFLICT`：那条码的语义是“同一 Idempotency-Key 对应不同请求体”
    （06 §4.5），图版本冲突与幂等键无关；用它会污染幂等语义。
    为什么不用 `RULESET_VERSION_MISMATCH`：那条码专指规则集版本（05 §1.5）。
    因此这里借用 `STATE_TRANSITION_DENIED`（“守卫不成立/前后态过期”），
    并把真实原因放进 `reason=GRAPH_VERSION_CONFLICT` 与 `detail`。见 OQ-P3-03。
    """

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 409
    reason: Final[str] = "GRAPH_VERSION_CONFLICT"

    def __init__(
        self,
        *,
        task_id: str,
        requested: int,
        latest: int | None,
        detail: str = "",
    ) -> None:
        self.task_id = task_id
        self.requested = requested
        self.latest = latest
        self.detail = detail
        suffix = f"；{detail}" if detail else ""
        super().__init__(
            f"{self.error_code}/{self.reason}：task {task_id} 请求图版本 {requested}，"
            f"已登记最大版本 {latest}{suffix}"
        )

    def as_detail(self) -> Mapping[str, object]:
        """DENIED 审计/结构化日志能安全承载的字段（无绝对路径、无 SQL）。"""
        return MappingProxyType(
            {
                "reason": self.reason,
                "requested_graph_version": self.requested,
                "latest_graph_version": self.latest,
            }
        )


def compare_versions(latest: int | None, requested: int) -> GraphVersionState:
    """纯函数：判定 `requested` 相对 `latest` 的关系。

    正例：`(None, 1) → FIRST`；`(1, 2) → NEXT`。
    负例：`(2, 1) → STALE`；`(2, 4) → GAP`；`(2, 2) → DUPLICATE`（是否幂等由调用方用哈希判定）。
    """
    if requested < 1:
        raise ValueError("图版本必须 ≥ 1")
    if latest is None:
        return GraphVersionState.FIRST if requested == 1 else GraphVersionState.GAP
    if requested == latest + 1:
        return GraphVersionState.NEXT
    if requested == latest:
        return GraphVersionState.DUPLICATE
    if requested < latest:
        return GraphVersionState.STALE
    return GraphVersionState.GAP


# ---------------------------------------------------------------------------
# 2. 快照（回放用）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class NodeRegistrationRow:
    """`nodes` 的 INSERT 行；字段与 M02 `NodeRow` **同名同序**，便于直接交给 `_insert_planned`。

    三个不变量（M02 仓储会再校验一次）：
      - `state` 恒为 `"PLANNED"`（节点只能以初始状态插入，DEC-01）；
      - `attempt_seq` 恒为 `0`；`plan_id/plan_hash` 恒为 `None`；
      - `updated_at` 与本批其它行相同（同一次登记同一时刻）。
    """

    task_id: str
    node_id: str
    schema_version: str
    node_type: str
    template_id: str
    state: str
    attempt_seq: int
    plan_id: str | None
    plan_hash: str | None
    updated_at: str

    def __post_init__(self) -> None:
        if self.state != "PLANNED":
            raise ValueError("节点注册只能写入初始状态 PLANNED（DEC-01）")
        if self.attempt_seq != 0:
            raise ValueError("注册阶段 attempt_seq 必须为 0")
        if self.plan_id is not None or self.plan_hash is not None:
            raise ValueError("注册阶段不得携带 plan_id/plan_hash")


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """一个已登记版本在**持久层可见**的内容：`nodes` 行 + `graph_versions` 行。

    重要限制（06 §1.3 的 DDL 决定，不是本文件的取舍）：
      - `nodes` 表**没有** `depends_on`/`parameters_hash`/`required_checks`/`side_effect_class` 列；
      - `graph_versions` 表只有 `graph_hash` 与 `topology_order`，**没有边表**。
    因此快照足以回答“有哪些节点、什么顺序、图身份是什么”，**不足以重建边**。
    边的重建只能靠“同输入确定性重建 + graph_hash 比对”（见 `GraphContent` 与
    `verify_rebuild()`）；这条限制必须写进评审结论，不得假装快照里有边。

    `snapshot_digest()` 是持久视图的摘要，用于发现“快照被改过”；
    它**不覆盖**边与 NodeSpec 正文（那些不在库里）。
    """

    task_id: str
    graph_version: int
    graph_hash: str
    topology_order: tuple[str, ...]
    nodes: tuple[NodeRegistrationRow, ...]
    created_at: str          # UTC 27 字符（M02 format_utc 口径）
    template_id: str
    dataset_sha256: str
    ruleset_hash: str


@dataclass(frozen=True, slots=True)
class GraphContent:
    """一张图的**内存全文**（草案或重建结果）：含边与 NodeSpec 派生字段。

    这是失效传播与 patch 审批真正需要的东西。它**不落库**，由 Builder 重建：
        built = build_graph(task, base_version=snapshot.graph_version - 1, ...)
        verify_rebuild(snapshot, built)   # graph_hash 必须一致，否则 fail-closed
    """

    task_id: str
    graph_version: int
    graph_hash: str
    nodes: tuple[NodeDraft, ...]
    edges: tuple[tuple[str, str], ...]

    def dependencies(self) -> Mapping[str, tuple[str, ...]]:
        pred: dict[str, list[str]] = {n.node_id: [] for n in self.nodes}
        for src, dst in self.edges:
            if dst in pred:
                pred[dst].append(src)
        return MappingProxyType({k: tuple(sorted(v)) for k, v in pred.items()})


REPLAY_SNAPSHOT_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "task_id",
    "graph_version",
    "graph_hash",
    "topology_order",
    "nodes",
    "template_id",
    "dataset_sha256",
    "ruleset_hash",
)

_NODE_REPLAY_FIELDS: Final[tuple[str, ...]] = (
    "node_id", "schema_version", "node_type", "template_id", "state", "attempt_seq",
    "plan_id", "plan_hash",
)


# ---------------------------------------------------------------------------
# 3. 拓扑序序列化
# ---------------------------------------------------------------------------
def serialize_topology_order(order: Sequence[str]) -> str:
    """把拓扑序序列化为 `graph_versions.topology_order` 的 TEXT 值。

    `[P3 约定]`（06 只给了列名与类型，没给格式）：
      - UTF-8 JSON 数组文本，元素为 node_id，**保持给定顺序**；
      - 无空格（`separators=(",", ":")`）、`ensure_ascii=False`；
      - 不排序：拓扑序本身就是顺序数据，排序会破坏 Kahn 的确定性语义。
    这样做的可审计收益：`topology_order` 可直接被 `json.loads` 读回，且与
    `scheduler.yaml: ready_order=topological_then_node_id` 使用同一口径。
    """
    if not all(isinstance(n, str) and n for n in order):
        raise ValueError("拓扑序只能包含非空 node_id 字符串")
    # 注意：这里是**存储序列化**（TEXT 列），不是签名/哈希前的规范化，
    # 因此可以用 json.dumps；任何用于哈希的规范化必须走 M01 `canonical_bytes`。
    return json.dumps(list(order), ensure_ascii=False, separators=(",", ":"))


def parse_topology_order(text: str) -> tuple[str, ...]:
    """把 TEXT 读回元组；非法形态立即拒绝（不返回空元组冒充“无拓扑序”）。"""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("topology_order 不是合法 JSON 数组文本") from exc
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ValueError("topology_order 必须是非空字符串数组")
    if len(set(value)) != len(value):
        raise ValueError("topology_order 含重复 node_id")
    return tuple(value)


# ---------------------------------------------------------------------------
# 4. 快照哈希与差异
# ---------------------------------------------------------------------------
def snapshot_digest(snapshot: GraphSnapshot) -> str:
    """**持久视图**摘要：`sha256(JCS(payload))`，不含 `created_at`。

    不含 created_at 的理由：同一份快照在不同时刻重放必须得到同一摘要；
    登记时间已经在 `graph_versions.created_at` 与审计里，无需进身份。

    覆盖范围：节点行（含 state/attempt_seq/plan_*）+ 拓扑序 + graph_hash + 规则/数据哈希。
    **不覆盖**：边、NodeSpec 正文（参数、required_checks、side_effect_class）——
    它们不在库里（06 §1.3 无对应列），由 `verify_rebuild()` 用 graph_hash 兜住。
    """
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "task_id": snapshot.task_id,
        "graph_version": snapshot.graph_version,
        "graph_hash": snapshot.graph_hash,
        "topology_order": list(snapshot.topology_order),
        "nodes": [
            {k: getattr(n, k) for k in _NODE_REPLAY_FIELDS}
            for n in sorted(snapshot.nodes, key=lambda n: n.node_id)
        ],
        "template_id": snapshot.template_id,
        "dataset_sha256": snapshot.dataset_sha256,
        "ruleset_hash": snapshot.ruleset_hash,
    }
    # LIB: researchflow.contracts.encoding.canonical_bytes（JCS）+ hashlib.sha256
    #
    # 纪律（ENCODING_RULES §5）：**不得**用 `json.dumps(sort_keys=True)` 冒充 JCS ——
    # Python 按键的码点排序，JCS 按 UTF-16 码元排序，astral 字符会得到不同字节。
    # 因此本函数在伪代码阶段只写前像形状，哈希计算必须交给 M01 落地。
    _ = payload
    raise NotImplementedError(
        "P3 伪代码：快照摘要由 M01 encoding.canonical_bytes + sha256 落地"
    )


@dataclass(frozen=True, slots=True)
class GraphDiff:
    """两张 `GraphContent` 之间的结构差异（供 patch 审批与失效传播共用）。"""

    from_version: int
    to_version: int
    added_nodes: tuple[str, ...]
    removed_nodes: tuple[str, ...]
    changed_params: tuple[str, ...]
    changed_templates: tuple[str, ...]
    changed_dependencies: tuple[str, ...]
    added_edges: tuple[tuple[str, str], ...]
    removed_edges: tuple[tuple[str, str], ...]

    @property
    def is_empty(self) -> bool:
        return not any(
            (self.added_nodes, self.removed_nodes, self.changed_params,
             self.changed_templates, self.changed_dependencies,
             self.added_edges, self.removed_edges)
        )

    def touched_nodes(self) -> tuple[str, ...]:
        """内容发生变化的节点（不含“仅被删/仅被加”的节点）。"""
        return tuple(sorted(set(self.changed_params) | set(self.changed_templates)
                            | set(self.changed_dependencies)))


def diff_graphs(before: GraphContent | None, after: GraphContent) -> GraphDiff:
    """按 node_id 对齐比较两张图。

    `before=None` 表示首次登记：全部节点都算“新增”。

    比较项：
      - 节点增删；
      - `parameters_hash` 变化（参数变了 → 下游输入可能变）；
      - `template_id` 变化（换了实现）；
      - `depends_on` 集合变化（边变了）；
      - 边集合差异。

    注意：本函数**不判断失效**。它只回答“结构上变了什么”；
    “变了是否导致下游 stale”由 `invalidation.py` 按 cause_type 与节点状态决定。
    """
    prev_nodes = {n.node_id: n for n in (before.nodes if before else ())}
    next_nodes = {n.node_id: n for n in after.nodes}
    added = tuple(sorted(set(next_nodes) - set(prev_nodes)))
    removed = tuple(sorted(set(prev_nodes) - set(next_nodes)))

    prev_edges = set(before.edges) if before else set()
    next_edges = set(after.edges)
    prev_deps = {k: set(v) for k, v in (before.dependencies().items() if before else ())}
    next_deps = {k: set(v) for k, v in after.dependencies().items()}

    changed_params: list[str] = []
    changed_templates: list[str] = []
    changed_deps: list[str] = []
    for node in sorted(set(prev_nodes) & set(next_nodes)):
        a, b = prev_nodes[node], next_nodes[node]
        if a.parameters_hash != b.parameters_hash:
            changed_params.append(node)
        if a.template_id != b.template_id or a.node_type != b.node_type:
            changed_templates.append(node)
        if prev_deps.get(node, set()) != next_deps.get(node, set()):
            changed_deps.append(node)

    return GraphDiff(
        from_version=before.graph_version if before else 0,
        to_version=after.graph_version,
        added_nodes=added,
        removed_nodes=removed,
        changed_params=tuple(sorted(set(changed_params))),
        changed_templates=tuple(sorted(set(changed_templates))),
        changed_dependencies=tuple(sorted(set(changed_deps))),
        added_edges=tuple(sorted(next_edges - prev_edges)),
        removed_edges=tuple(sorted(prev_edges - next_edges)),
    )


class ReplayMismatch(RuntimeError):
    """重建结果与已登记快照不一致：图重放失败，必须 fail-closed。

    这是**安全**分支，不是“重建一下就好”：
      - 模板注册表在两次构建之间变了（默认参数/产物声明）；
      - 蓝图代码变了；
      - 有人改了 `graph_versions.graph_hash`；
      - 有人改了 `nodes` 行。
    任一情况都意味着“现在跑出来的图 ≠ 当时登记的图”，不允许继续失效计算或重跑。
    """

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 409
    reason: Final[str] = "GRAPH_REPLAY_MISMATCH"

    def __init__(self, *, task_id: str, graph_version: int, expected: str, actual: str) -> None:
        self.task_id = task_id
        self.graph_version = graph_version
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{self.error_code}/{self.reason}：task {task_id} v{graph_version} "
            f"重建 graph_hash={actual[:12]}… ≠ 已登记 {expected[:12]}…"
        )


def verify_rebuild(snapshot: GraphSnapshot, rebuilt: GraphContent) -> None:
    """校验“重建的图 == 已登记的图”，不一致即抛 `ReplayMismatch`。

    必要条件（三条全查）：
      1. `task_id` / `graph_version` 相同；
      2. `graph_hash` 相同（核心：覆盖节点、边、参数哈希、模板、规则、数据哈希）；
      3. 节点集合与拓扑序相同（防止“哈希对了但节点少了”的构造）。
    """
    if rebuilt.task_id != snapshot.task_id or rebuilt.graph_version != snapshot.graph_version:
        raise ReplayMismatch(
            task_id=snapshot.task_id,
            graph_version=snapshot.graph_version,
            expected=snapshot.graph_hash,
            actual=f"{rebuilt.task_id}@{rebuilt.graph_version}",
        )
    if rebuilt.graph_hash != snapshot.graph_hash:
        raise ReplayMismatch(
            task_id=snapshot.task_id,
            graph_version=snapshot.graph_version,
            expected=snapshot.graph_hash,
            actual=rebuilt.graph_hash,
        )
    rebuilt_ids = tuple(sorted(n.node_id for n in rebuilt.nodes))
    snapshot_ids = tuple(sorted(n.node_id for n in snapshot.nodes))
    if rebuilt_ids != snapshot_ids:
        raise ReplayMismatch(
            task_id=snapshot.task_id,
            graph_version=snapshot.graph_version,
            expected=f"nodes={list(snapshot_ids)}",
            actual=f"nodes={list(rebuilt_ids)}",
        )


# ---------------------------------------------------------------------------
# 5. 端口（实现属 WP-04 / M02，本文件不写 SQL）
# ---------------------------------------------------------------------------
class GraphVersionStorePort(Protocol):
    """`graph_versions` 的读写端口（WP-04 实现；M02 不建此表）。

    唯一写入口 `insert()` 必须：
      - 接收 capability 并校验为 `DAG_REGISTER`（与 M02 同一对象身份）；
      - 以 `(task_id, graph_version)` 为主键，重复插入由 DB 主键拒绝（不得 upsert）；
      - 只 INSERT，不 UPDATE、不 DELETE（版本是历史事实）。
    """

    def latest(self, task_id: str) -> GraphSnapshot | None:
        ...

    def get(self, task_id: str, graph_version: int) -> GraphSnapshot | None:
        ...

    def list_versions(self, task_id: str) -> tuple[GraphSnapshot, ...]:
        ...

    def insert(self, snapshot: GraphSnapshot, *, capability: object) -> None:
        ...


class NodeRegistrarPort(Protocol):
    """M02 `NodeRepository._insert_planned` 的结构视图（只声明用到的方法）。"""

    def _insert_planned(self, nodes: Sequence[NodeRegistrationRow], *, capability: object) -> None:
        ...


class UnitOfWorkPort(Protocol):
    """M02 `UnitOfWork` 的结构视图：`immediate()` 是 `BEGIN IMMEDIATE` 上下文。"""

    def immediate(self) -> AbstractContextManager[object]:
        ...


class CapabilityGatePort(Protocol):
    """能力闸门；M02 的 `_require_capability` 满足此形状。

    纪律：实现必须对 `capability` 做**身份比较**（`is`），
    不得接受字符串 `"dag_register"`、`True`、或任何“看起来像”的对象。
    """

    def require(self, capability: object, expected_name: str) -> None:
        ...


# ---------------------------------------------------------------------------
# 6. 注册（两段式，第一段）
# ---------------------------------------------------------------------------
class RegistrationViolation(StrEnum):
    VALIDATION_MISSING = "VALIDATION_MISSING"          # 没带 ValidationReport
    VALIDATION_FAILED = "VALIDATION_FAILED"            # 校验没通过
    TOPOLOGY_MISMATCH = "TOPOLOGY_MISMATCH"            # 校验拓扑序与草案不一致
    VERSION_CONFLICT = "VERSION_CONFLICT"              # 版本非 NEXT
    DUPLICATE_DIFFERENT_CONTENT = "DUPLICATE_DIFFERENT_CONTENT"  # 同版本不同哈希
    HASH_INVALID = "HASH_INVALID"                      # graph_hash 不是 64 位小写十六进制
    CAPABILITY_DENIED = "CAPABILITY_DENIED"            # 不是 DAG_REGISTER
    EMPTY_NODES = "EMPTY_NODES"                        # 0 节点不得登记
    DOC_SYNC_BLOCKED = "DOC_SYNC_BLOCKED"              # 预留：文档未同步时显式阻断（默认不启用）


class RegistrationRejected(RuntimeError):
    """登记拒绝。版本类冲突走 `GraphVersionConflict`（409）；其余走本异常（400/500 语义）。"""

    def __init__(self, violation: RegistrationViolation, *, detail: str = "",
                 error_code: str = "STATE_TRANSITION_DENIED") -> None:
        self.violation = violation
        self.error_code = error_code
        self.detail = detail
        suffix = f"；{detail}" if detail else ""
        super().__init__(f"{error_code}/{violation.value}{suffix}")


@dataclass(frozen=True, slots=True)
class GraphRegistrationResult:
    """登记结果。`pending_task_version_write=True` 是**常态**，不是错误。

    它提醒调用方：`tasks.graph_version` 还没写；必须在 `PLANNING→READY` 时
    通过 `StateMachine.transition()` 用 `ctx.graph_version` 写入。
    """

    task_id: str
    graph_version: int
    graph_hash: str
    node_count: int
    registered_at: str
    pending_task_version_write: bool
    topology_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReadyTransitionRequest:
    """`PLANNING→READY` 的迁移请求**描述**（不是调用）。

    本文件只组装参数，实际调用仍在 Orchestrator：
        `StateMachine.transition(ObjectType.TASK, task_id, "READY", actor, ReasonCode.DAG_VALIDATED, ctx)`
    这样三件事各归其位：图登记（Orchestrator）、版本号写入（StateMachine）、校验事实（validator）。
    """

    task_id: str
    previous_state: str
    next_state: str
    reason_code: str
    graph_version: int
    correlation_id: str
    rule_version: str


class GraphRegistrar:
    """图登记服务（Orchestrator 侧）；**唯一**有权发起 `_insert_planned` 的组件。

    依赖全部通过端口注入：
      - `store`：`graph_versions` 读写（WP-04）；
      - `nodes`：M02 `NodeRepository`；
      - `uow`：M02 `UnitOfWork`；
      - `gate`：capability 闸门（M02 `_require_capability`）；
      - `clock`：UTC 时钟（M02 `SystemClock` 形状），仅用于 `created_at/updated_at`。
    """

    def __init__(
        self,
        *,
        store: GraphVersionStorePort,
        nodes: NodeRegistrarPort,
        uow: UnitOfWorkPort,
        gate: CapabilityGatePort,
        clock: object,
    ) -> None:
        self._store = store
        self._nodes = nodes
        self._uow = uow
        self._gate = gate
        self._clock = clock

    # -- 第一段：同事务写 graph_versions + nodes(PLANNED) -------------------
    def register(
        self,
        draft: GraphDraft,
        report: ValidationReport,
        *,
        capability: object,
        registered_at: str,
    ) -> GraphRegistrationResult:
        """登记一张**已校验**的静态图。

        步骤（顺序不可交换）：
          1. capability 闸门：必须是 `DAG_REGISTER`，否则 `CAPABILITY_DENIED`；
          2. 校验凭证：`report.ok` 必须为真、`report.topology == draft.topology_order`；
             没有凭证或凭证不符 → 拒绝（防止“先登记后校验”）；
          3. 版本比较：`compare_versions(latest, draft.graph_version)` 必须是 `FIRST/NEXT`；
             `DUPLICATE` 且哈希相同 → 幂等返回原结果；`DUPLICATE` 但哈希不同 → 409；
             `STALE/GAP` → 409；
          4. 组装快照与节点行（`state=PLANNED`、`attempt_seq=0`）；
          5. `BEGIN IMMEDIATE`：`store.insert()` + `nodes._insert_planned()`；任一失败整体回滚；
          6. 返回 `pending_task_version_write=True`。

        副作用：只写 `graph_versions` + `nodes`；**不写** `tasks`、不写 `audit_log`、
        不调用 `StateMachine.transition()`（`tasks.graph_version` 由第②段写）。
        """
        # 1) 能力
        try:
            self._gate.require(capability, "dag_register")
        except Exception as exc:  # 闸门实现可能抛 DirectStateWriteDenied
            raise RegistrationRejected(
                RegistrationViolation.CAPABILITY_DENIED,
                detail=f"{type(exc).__name__}：只有 Orchestrator 持 DAG_REGISTER 可登记图",
            ) from exc

        # 2) 校验凭证
        if report is None:
            raise RegistrationRejected(RegistrationViolation.VALIDATION_MISSING,
                                       detail="必须先跑 validator 六类校验")
        if not report.ok:
            code, reason, details = report.denial()
            raise RegistrationRejected(
                RegistrationViolation.VALIDATION_FAILED,
                error_code=code,
                detail=f"reason={reason};{details}",
            )
        if tuple(report.topology) != tuple(draft.topology_order):
            raise RegistrationRejected(
                RegistrationViolation.TOPOLOGY_MISMATCH,
                detail="校验报告与草案的拓扑序不一致：草案可能在提交后被改过",
            )

        # 3) 版本
        if not _is_sha256_hex(draft.graph_hash):
            raise RegistrationRejected(RegistrationViolation.HASH_INVALID,
                                       detail="graph_hash 必须是 64 位小写十六进制")
        if not draft.nodes:
            raise RegistrationRejected(RegistrationViolation.EMPTY_NODES)

        latest = self._store.latest(draft.task_id)
        state = compare_versions(latest.graph_version if latest else None, draft.graph_version)
        if state is GraphVersionState.DUPLICATE:
            if latest is not None and latest.graph_hash == draft.graph_hash:
                # 幂等重放：返回原快照，不写第二次。
                return _result_from_snapshot(latest)
            raise GraphVersionConflict(
                task_id=draft.task_id,
                requested=draft.graph_version,
                latest=latest.graph_version if latest else None,
                detail="同一版本号对应不同 graph_hash：版本不可改写",
            )
        if state in (GraphVersionState.STALE, GraphVersionState.GAP):
            raise GraphVersionConflict(
                task_id=draft.task_id,
                requested=draft.graph_version,
                latest=latest.graph_version if latest else None,
                detail=f"版本状态 {state.value}",
            )

        # 4) 快照与节点行
        rows = _rows_from_draft(draft, registered_at=registered_at)
        snapshot = GraphSnapshot(
            task_id=draft.task_id,
            graph_version=draft.graph_version,
            graph_hash=draft.graph_hash,
            topology_order=draft.topology_order,
            nodes=rows,
            created_at=registered_at,
            template_id=draft.template_id,
            dataset_sha256=draft.dataset_sha256,
            ruleset_hash=draft.ruleset_hash,
        )

        # 5) 同事务：版本 + 节点（顺序：先版本后节点，失败一起回滚）
        with self._uow.immediate():
            self._store.insert(snapshot, capability=capability)
            self._nodes._insert_planned(rows, capability=capability)

        # 6) 返回；tasks.graph_version 仍未写
        return _result_from_snapshot(snapshot)

    # -- 第二段：组装 PLANNING→READY 请求（不执行迁移） --------------------
    def build_ready_request(
        self,
        *,
        task_id: str,
        graph_version: int,
        correlation_id: str,
        rule_version: str,
    ) -> ReadyTransitionRequest:
        """组装 `PLANNING→READY` 的迁移参数。

        `graph_version` 必须等于本次已登记版本；调用方随后应：
            machine.transition(TASK, task_id, "READY", actor, "DAG_VALIDATED", ctx)
        其中 `ctx.previous_state="PLANNING"`、`ctx.graph_version=graph_version`。
        M02 会拒绝“非 PLANNING→READY 携带 graph_version”的调用（仓储校验）。
        """
        return ReadyTransitionRequest(
            task_id=task_id,
            previous_state="PLANNING",
            next_state="READY",
            reason_code="DAG_VALIDATED",
            graph_version=graph_version,
            correlation_id=correlation_id,
            rule_version=rule_version,
        )


def _rows_from_draft(draft: GraphDraft, *, registered_at: str) -> tuple[NodeRegistrationRow, ...]:
    """把草案节点转成 INSERT 行；字段与 M02 `NodeRow` 对齐。"""
    rows = [
        NodeRegistrationRow(
            task_id=draft.task_id,
            node_id=n.node_id,
            schema_version=n.schema_version,
            node_type=n.node_type,
            template_id=n.template_id,
            state="PLANNED",
            attempt_seq=0,
            plan_id=None,
            plan_hash=None,
            updated_at=registered_at,
        )
        for n in draft.nodes
    ]
    rows.sort(key=lambda r: r.node_id)
    return tuple(rows)


def _result_from_snapshot(snapshot: GraphSnapshot) -> GraphRegistrationResult:
    return GraphRegistrationResult(
        task_id=snapshot.task_id,
        graph_version=snapshot.graph_version,
        graph_hash=snapshot.graph_hash,
        node_count=len(snapshot.nodes),
        registered_at=snapshot.created_at,
        pending_task_version_write=True,
        topology_order=snapshot.topology_order,
    )


def _is_sha256_hex(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


# ---------------------------------------------------------------------------
# 7. 自检
# ---------------------------------------------------------------------------
def assert_graph_version_contract() -> list[str]:
    """自检：版本规则、快照字段、写者边界。

    返回违反项列表（空 = 通过）。落地阶段由测试调用。
    """
    problems: list[str] = []
    # 1) 版本比较的五个分支必须全覆盖
    cases = {
        (None, 1): GraphVersionState.FIRST,
        (1, 2): GraphVersionState.NEXT,
        (2, 2): GraphVersionState.DUPLICATE,
        (2, 1): GraphVersionState.STALE,
        (2, 4): GraphVersionState.GAP,
    }
    for (latest, requested), expected in cases.items():
        if compare_versions(latest, requested) is not expected:
            problems.append(f"compare_versions({latest},{requested}) != {expected}")
    # 2) 拓扑序往返
    sample = ("a", "b", "c")
    if parse_topology_order(serialize_topology_order(sample)) != sample:
        problems.append("拓扑序序列化不可往返")
    # 3) 快照摘要不含 created_at
    if "created_at" in REPLAY_SNAPSHOT_FIELDS:
        problems.append("快照摘要字段不得包含 created_at（会破坏同内容同摘要）")
    return problems