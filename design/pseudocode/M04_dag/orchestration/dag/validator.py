"""M04 · orchestration/dag/validator.py — 六类图校验（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-002（DAG 编排）、FR-010（失效传播的正确性前提）
依赖：M04 builder（`GraphView` 结构、NodeIdRule、TemplateCatalogPort）、M01 errors（只引用，不新增码）
不变量：六类校验各自独立可调用；拒绝必须给「错误码 + 违规码 + 涉及节点」；校验器不写库、不改图
错误码：TOOL_NOT_ALLOWLISTED / SCHEMA_INVALID / STATE_TRANSITION_DENIED（三选一，见 VIOLATION_SPECS）
写入者：**无**（纯只读校验；不 import 仓储、不持 DAG_REGISTER、不调用 transition）
状态：伪代码；不执行、不建库、不跑测试

六类校验（每一类都可单独调用，也可由 `validate_graph` 一次跑完）：

  | # | CheckClass | 验什么 | 典型负例 |
  |---|---|---|---|
  | 1 | CYCLE_SELF_LOOP | 环、自环 | A→B→C→A；A→A |
  | 2 | ORPHAN | 孤立节点、到不了汇点的节点 | 图里有个谁都不连的节点 |
  | 3 | DUPLICATE_EDGE | 重复边、重复节点、悬空依赖 | depends_on 里出现两次同一节点 |
  | 4 | NODE_TYPE | 节点类型白名单、模板已注册、node_id 形态 | 域包未声明的 node_type |
  | 5 | GRAPH_LIMIT | 规模、深度、扇入/扇出 | 200 个节点；深度 40 |
  | 6 | INPUT_REF | 输入引用完整性（`artifact://<name>`） | 引用了没有生产者的产物 |

**为什么“错误码”只有三个**：M01 注册表固定 27 条，本阶段不得新增码。
所以每个违规给两层信息：
  - `violation`（本文件的原因码，写 `detail.reason`、日志、测试断言）；
  - `error_code`（来自已注册表，决定 HTTP 语义）。
“环”与“孤立”不是 HTTP 请求体错误，而是“这张图不能进入 READY”的守卫失败，
故映射到 `STATE_TRANSITION_DENIED`(409) + `reason=DAG_INVALID`，与 M02
`NEG-M02-16`（Task `PLANNING→READY` 时 `dag_valid=False` → `reason=DAG_INVALID`）对齐。
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .builder import (
    RESERVED_NODE_NAMES,
    NodeIdRule,
    TemplateCatalogPort,
)

__all__ = [
    "ALLOWED_ERROR_CODES",
    "CHECK_CLASSES",
    "CHECK_MATRIX",
    "CHECK_ORDER",
    "DEFAULT_DAG_LIMITS",
    "VIOLATION_SPECS",
    "ArtifactProducerMap",
    "CheckClass",
    "CheckVector",
    "DagLimits",
    "DagViolation",
    "GraphView",
    "ValidationFinding",
    "ValidationReport",
    "ViolationSpec",
    "assert_validator_contract",
    "check_cycles",
    "check_duplicate_edges",
    "check_graph_limits",
    "check_input_refs",
    "check_node_types",
    "check_orphans",
    "validate_graph",
]


# ---------------------------------------------------------------------------
# 1. 六类校验与违规码
# ---------------------------------------------------------------------------
class CheckClass(StrEnum):
    """六类校验的稳定标识；顺序即 `CHECK_ORDER`（报告排序与评审矩阵共用）。"""

    CYCLE_SELF_LOOP = "CYCLE_SELF_LOOP"
    ORPHAN = "ORPHAN"
    DUPLICATE_EDGE = "DUPLICATE_EDGE"
    NODE_TYPE = "NODE_TYPE"
    GRAPH_LIMIT = "GRAPH_LIMIT"
    INPUT_REF = "INPUT_REF"


CHECK_ORDER: Final[tuple[CheckClass, ...]] = (
    CheckClass.CYCLE_SELF_LOOP,
    CheckClass.ORPHAN,
    CheckClass.DUPLICATE_EDGE,
    CheckClass.NODE_TYPE,
    CheckClass.GRAPH_LIMIT,
    CheckClass.INPUT_REF,
)
CHECK_CLASSES: Final[tuple[CheckClass, ...]] = CHECK_ORDER


class DagViolation(StrEnum):
    """图校验的具体拒绝原因（原因码，**不是**新错误码）。"""

    # 1. 环 / 自环
    SELF_LOOP = "SELF_LOOP"
    CYCLE = "CYCLE"
    # 2. 孤立
    ORPHAN_NODE = "ORPHAN_NODE"
    DEAD_END_NODE = "DEAD_END_NODE"
    # 3. 重复 / 悬空
    DUPLICATE_EDGE = "DUPLICATE_EDGE"
    DUPLICATE_NODE_ID = "DUPLICATE_NODE_ID"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"
    EMPTY_GRAPH = "EMPTY_GRAPH"
    # 4. 类型白名单
    NODE_TYPE_NOT_ALLOWED = "NODE_TYPE_NOT_ALLOWED"
    TEMPLATE_NOT_REGISTERED = "TEMPLATE_NOT_REGISTERED"
    NODE_ID_INVALID = "NODE_ID_INVALID"
    NODE_ID_RESERVED = "NODE_ID_RESERVED"
    # 5. 规模 / 深度
    GRAPH_TOO_LARGE = "GRAPH_TOO_LARGE"
    GRAPH_TOO_DEEP = "GRAPH_TOO_DEEP"
    GRAPH_FAN_LIMIT = "GRAPH_FAN_LIMIT"
    # 6. 输入引用
    INPUT_REF_UNRESOLVED = "INPUT_REF_UNRESOLVED"
    INPUT_REF_NOT_UPSTREAM = "INPUT_REF_NOT_UPSTREAM"
    INPUT_REF_FORMAT_INVALID = "INPUT_REF_FORMAT_INVALID"
    ARTIFACT_DUPLICATE_PRODUCER = "ARTIFACT_DUPLICATE_PRODUCER"


@dataclass(frozen=True, slots=True)
class ViolationSpec:
    check: CheckClass
    error_code: str
    http_status: int
    reason: str
    fail_closed: bool
    note: str


# 允许出现在本模块的错误码集合。任何新增码都会让 `assert_validator_contract()` 失败。
ALLOWED_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"TOOL_NOT_ALLOWLISTED", "SCHEMA_INVALID", "STATE_TRANSITION_DENIED"}
)

VIOLATION_SPECS: Final[Mapping[DagViolation, ViolationSpec]] = MappingProxyType(
    {
        # --- 1. 环 / 自环 -------------------------------------------------
        DagViolation.SELF_LOOP: ViolationSpec(
            CheckClass.CYCLE_SELF_LOOP, "SCHEMA_INVALID", 422, "SELF_LOOP", True,
            "05 §3.3：depends_on 自引用拒绝（SEM-NS-01）；属单节点字段语义，故 422",
        ),
        DagViolation.CYCLE: ViolationSpec(
            CheckClass.CYCLE_SELF_LOOP, "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True,
            "05 §3.3「节点构成环 → 拒绝并指出环路径」；图级问题，走 409 + reason=DAG_INVALID",
        ),
        # --- 2. 孤立 ------------------------------------------------------
        DagViolation.ORPHAN_NODE: ViolationSpec(
            CheckClass.ORPHAN, "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True,
            "孤立节点不得当作正常节点：无前驱且无后继（多节点图）或从根不可达",
        ),
        DagViolation.DEAD_END_NODE: ViolationSpec(
            CheckClass.ORPHAN, "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True,
            "从该节点出发到不了任何汇点（含指向环），会产生永远无法收敛的分支",
        ),
        # --- 3. 重复 / 悬空 -----------------------------------------------
        DagViolation.DUPLICATE_EDGE: ViolationSpec(
            CheckClass.DUPLICATE_EDGE, "SCHEMA_INVALID", 422, "DUPLICATE_EDGE", True,
            "同一 (src,dst) 出现多次；`策划书 §6.1` 要求图校验覆盖重复边",
        ),
        DagViolation.DUPLICATE_NODE_ID: ViolationSpec(
            CheckClass.DUPLICATE_EDGE, "SCHEMA_INVALID", 422, "DUPLICATE_NODE_ID", True,
            "05 §3.3：node_id 重复拒绝",
        ),
        DagViolation.UNKNOWN_DEPENDENCY: ViolationSpec(
            CheckClass.DUPLICATE_EDGE, "SCHEMA_INVALID", 422, "UNKNOWN_DEPENDENCY", True,
            "05 §3.3：depends_on 含不存在节点 → 拒绝",
        ),
        DagViolation.EMPTY_GRAPH: ViolationSpec(
            CheckClass.DUPLICATE_EDGE, "SCHEMA_INVALID", 422, "EMPTY_GRAPH", True,
            "0 节点的图不是合法图；Builder 已拦一次，这里再拦（纵深防御）",
        ),
        # --- 4. 类型白名单 -------------------------------------------------
        DagViolation.NODE_TYPE_NOT_ALLOWED: ViolationSpec(
            CheckClass.NODE_TYPE, "TOOL_NOT_ALLOWLISTED", 403, "NODE_TYPE_NOT_ALLOWED", True,
            "05 §3.1「必须在域包允许类型内」；errors.py 的 TOOL_NOT_ALLOWLISTED 覆盖场景",
        ),
        DagViolation.TEMPLATE_NOT_REGISTERED: ViolationSpec(
            CheckClass.NODE_TYPE, "TOOL_NOT_ALLOWLISTED", 403, "TEMPLATE_NOT_REGISTERED", True,
            "05 §3.1 template_id「已注册」；未注册模板一律拒绝",
        ),
        DagViolation.NODE_ID_INVALID: ViolationSpec(
            CheckClass.NODE_TYPE, "SCHEMA_INVALID", 422, "NODE_ID_INVALID", True,
            "ENCODING_RULES §1：Node 无前缀、字符集 [A-Za-z0-9_.-]、不得含路径分隔符",
        ),
        DagViolation.NODE_ID_RESERVED: ViolationSpec(
            CheckClass.NODE_TYPE, "SCHEMA_INVALID", 422, "NODE_ID_RESERVED", True,
            "node_id 会成为 attempt 目录名；Windows 保留设备名一律拒绝（见 workspace.py）",
        ),
        # --- 5. 规模 / 深度 -----------------------------------------------
        DagViolation.GRAPH_TOO_LARGE: ViolationSpec(
            CheckClass.GRAPH_LIMIT, "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True,
            "策划书 §6.1/§8.9 要求校验图规模；无专用错误码，归入 DAG_INVALID（见 OQ-P3-02）",
        ),
        DagViolation.GRAPH_TOO_DEEP: ViolationSpec(
            CheckClass.GRAPH_LIMIT, "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True,
            "深度过大使重跑/失效传播代价失控；同上，不新增码",
        ),
        DagViolation.GRAPH_FAN_LIMIT: ViolationSpec(
            CheckClass.GRAPH_LIMIT, "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True,
            "扇入/扇出上限；并发上限仍是 2（05 §2.1），但图结构不受并发限制",
        ),
        # --- 6. 输入引用 ---------------------------------------------------
        DagViolation.INPUT_REF_UNRESOLVED: ViolationSpec(
            CheckClass.INPUT_REF, "SCHEMA_INVALID", 422, "INPUT_REF_UNRESOLVED", True,
            "05 §3.1 input_refs「必须可解析到已有产物引用」；无生产者即拒绝",
        ),
        DagViolation.INPUT_REF_NOT_UPSTREAM: ViolationSpec(
            CheckClass.INPUT_REF, "SCHEMA_INVALID", 422, "INPUT_REF_NOT_UPSTREAM", True,
            "引用了非上游产物 → 会读到未来/无关产物；拒绝",
        ),
        DagViolation.INPUT_REF_FORMAT_INVALID: ViolationSpec(
            CheckClass.INPUT_REF, "SCHEMA_INVALID", 422, "INPUT_REF_FORMAT_INVALID", True,
            "只接受 `artifact://<name>`；拒绝绝对路径、URL、`..`、盘符、UNC",
        ),
        DagViolation.ARTIFACT_DUPLICATE_PRODUCER: ViolationSpec(
            CheckClass.INPUT_REF, "SCHEMA_INVALID", 422, "ARTIFACT_DUPLICATE_PRODUCER", True,
            "同一产物名被两个节点声明 → 引用二义；拒绝（不改名、不猜）",
        ),
    }
)


# ---------------------------------------------------------------------------
# 2. 规模上限（P3 建议值，非契约）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DagLimits:
    """图规模上限。**没有**对应配置键（M03 的十个 yaml 都未定义图上限）→ 见 OQ-P3-01。

    取值依据：策划书 §14.2 主线 DAG 为 8 个逻辑阶段、fan-out 3 个模型，典型 10 节点/9 边/深度 7。
    上限留 3 倍余量，避免“正常图被误拒”，同时挡住“把图当数据库用”。
    """

    max_nodes: int
    max_edges: int
    max_depth: int
    max_fan_in: int
    max_fan_out: int

    def __post_init__(self) -> None:
        for name in ("max_nodes", "max_edges", "max_depth", "max_fan_in", "max_fan_out"):
            if getattr(self, name) < 1:
                raise ValueError(f"DagLimits.{name} 必须 ≥ 1")


DEFAULT_DAG_LIMITS: Final[DagLimits] = DagLimits(
    max_nodes=32, max_edges=160, max_depth=16, max_fan_in=16, max_fan_out=8
)


# ---------------------------------------------------------------------------
# 3. 图视图与报告
# ---------------------------------------------------------------------------
class GraphView(Protocol):
    """校验所需的最小只读视图（`GraphDraft` 与 patch 预览都结构上满足）。

    刻意不接收 `GraphDraft` 具体类：patch_approval 要在“未登记的新图”上跑同样的六类校验，
    而那个图不是 Builder 的产物。校验器只认形状，不认来源。
    """

    @property
    def node_ids(self) -> Sequence[str]:
        ...

    @property
    def edge_pairs(self) -> Sequence[tuple[str, str]]:
        ...

    @property
    def dependencies(self) -> Mapping[str, Sequence[str]]:
        ...

    @property
    def node_types(self) -> Mapping[str, str]:
        ...

    @property
    def template_ids(self) -> Mapping[str, str]:
        ...

    @property
    def input_refs(self) -> Mapping[str, Sequence[str]]:
        ...


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """一条拒绝。

    `nodes` 是“涉及节点”，默认必须非空；唯一允许为空的是 `EMPTY_GRAPH`
    （此时没有节点可列，`field_path="nodes"`）。负例断言应同时检查 violation 与 nodes。
    """

    violation: DagViolation
    nodes: tuple[str, ...]
    field_path: str
    detail: str

    @property
    def spec(self) -> ViolationSpec:
        return VIOLATION_SPECS[self.violation]

    @property
    def check(self) -> CheckClass:
        return self.spec.check

    @property
    def error_code(self) -> str:
        return self.spec.error_code

    @property
    def http_status(self) -> int:
        return self.spec.http_status

    @property
    def reason(self) -> str:
        return self.spec.reason

    def sort_key(self) -> tuple[int, str, str]:
        return (CHECK_ORDER.index(self.check), self.nodes[0] if self.nodes else "", self.violation.value)


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """一次完整校验的结果。

    `ok=True` 时 `findings` 必为空且 `topology` 非空；
    `ok=False` 时 `topology` 为 `()`（**不返回残缺拓扑序**，避免调用方拿半张图去登记）。
    """

    ok: bool
    findings: tuple[ValidationFinding, ...]
    checks_run: tuple[CheckClass, ...]
    topology: tuple[str, ...]
    node_count: int
    edge_count: int
    depth: int
    stats: Mapping[str, int] = field(default_factory=dict)

    # -- 给 StateMachine / API 的两个出口 ---------------------------------
    def primary(self) -> ValidationFinding | None:
        """第一条（按 CHECK_ORDER 排序）；多违规时用于对外主错误码。"""
        return self.findings[0] if self.findings else None

    def denial(self) -> tuple[str, str, str]:
        """返回 `(error_code, reason, details)`，可直接填进 DENIED 审计的对应字段。

        多违规时：`error_code` 取第一条的码，`details` 列出全部违规码与节点，
        便于一条审计覆盖整次拒绝（不写第二条冗余审计）。
        """
        first = self.primary()
        if first is None:
            raise ValueError("校验通过时不应调用 denial()")
        codes = ",".join(dict.fromkeys(f.violation.value for f in self.findings))
        nodes = ",".join(dict.fromkeys(n for f in self.findings for n in f.nodes))
        return (first.error_code, first.reason, f"violations={codes};nodes={nodes}")


class ArtifactProducerMap(Protocol):
    """产物名 → 生产节点的只读查询（由 Builder 蓝图 + 模板 outputs 构造）。

    两个方法都要有：`producer_of` 用于解析引用；`producers_of` 用于发现“同一产物名
    被两个节点声明”的二义（`ARTIFACT_DUPLICATE_PRODUCER`）。只实现前者也可以运行，
    但二义检查会被跳过——**不得**因此把二义当成通过（见 NEGATIVE_TESTS 的 M04-13）。
    """

    def producer_of(self, artifact_name: str) -> str | None:
        ...

    def producers_of(self, artifact_name: str) -> tuple[str, ...]:
        ...


# ---------------------------------------------------------------------------
# 4. 工具：邻接、深度、拓扑、传递闭包
# ---------------------------------------------------------------------------
def _adjacency(view: GraphView) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """返回 `(后继表, 前驱表)`；端点不在 node_ids 的边不在此处报错（由重复/悬空检查负责）。"""
    known = set(view.node_ids)
    succ: dict[str, list[str]] = {n: [] for n in known}
    pred: dict[str, list[str]] = {n: [] for n in known}
    for src, dst in view.edge_pairs:
        if src in known and dst in known:
            succ[src].append(dst)
            pred[dst].append(src)
    for table in (succ, pred):
        for key in table:
            table[key].sort()
    return succ, pred


def _depths(view: GraphView) -> tuple[dict[str, int], bool]:
    """最长路径深度；返回 `(depth, has_cycle)`。有环时 depth 仅对已出队节点有效。"""
    succ, pred = _adjacency(view)
    indeg = {n: len(pred[n]) for n in succ}
    depth = {n: 0 for n in succ}
    heap = [n for n, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    seen = 0
    while heap:
        cur = heapq.heappop(heap)
        seen += 1
        for nxt in succ[cur]:
            depth[nxt] = max(depth[nxt], depth[cur] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, nxt)
    return depth, seen != len(succ)


def _topology(view: GraphView) -> tuple[str, ...]:
    """`topological_then_node_id`：Kahn + 最小堆（键 node_id）。

    与 Builder / M03 `scheduler.ready_order` 同一口径；有环时返回 `()`。
    """
    succ, pred = _adjacency(view)
    indeg = {n: len(pred[n]) for n in succ}
    heap = [n for n, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        cur = heapq.heappop(heap)
        order.append(cur)
        for nxt in succ[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, nxt)
    return tuple(order) if len(order) == len(succ) else ()


def _ancestors(view: GraphView) -> dict[str, frozenset[str]]:
    """每个节点的传递前驱集合（用拓扑序 DP；有环时按可达集合近似并交由 CYCLE 拒绝）。"""
    succ, pred = _adjacency(view)
    order = _topology(view)
    if not order:  # 有环：退化为逐点 DFS，只用于给出“非上游”判定
        result: dict[str, frozenset[str]] = {}
        for start in succ:
            seen: set[str] = set()
            stack = list(pred[start])
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                stack.extend(pred[cur])
            result[start] = frozenset(seen)
        return result
    result = {}
    for node in order:
        acc: set[str] = set()
        for p in pred[node]:
            acc.add(p)
            acc |= result.get(p, frozenset())
        result[node] = frozenset(acc)
    return result


# ---------------------------------------------------------------------------
# 5. 六类校验
# ---------------------------------------------------------------------------
def check_cycles(view: GraphView) -> tuple[ValidationFinding, ...]:
    """检查 1：自环与有向环。

    正例：`dataset_profile → split`（无环）→ 无 finding。
    负例：`a→a` → `SELF_LOOP`（422）；`a→b→c→a` → `CYCLE`（409，`detail` 含环路径）。

    实现：迭代 DFS + 三色标记；发现回边时沿 parent 还原**一条**环路径。
    每个环只报一次（以环上最小 node_id 去重），避免同一环按入口重复刷屏。
    """
    findings: list[ValidationFinding] = []
    node_ids = tuple(dict.fromkeys(view.node_ids))
    succ, _ = _adjacency(view)

    # 1) 自环单独报：它是 422（字段级），与环（409）的 HTTP 语义不同。
    for n in node_ids:
        if n in succ.get(n, ()):
            findings.append(ValidationFinding(
                DagViolation.SELF_LOOP, (n,), f"nodes.{n}.depends_on",
                f"{n} 依赖自身（SEM-NS-01）",
            ))

    # 2) 有向环：三色 DFS
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in node_ids}
    parent: dict[str, str | None] = {n: None for n in node_ids}
    reported: set[frozenset[str]] = set()

    for root in node_ids:
        if color[root] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        color[root] = GRAY
        while stack:
            cur, idx = stack[-1]
            children = succ.get(cur, [])
            if idx < len(children):
                stack[-1] = (cur, idx + 1)
                nxt = children[idx]
                if nxt not in color:  # 悬空端点：交给 UNKNOWN_DEPENDENCY
                    continue
                if color[nxt] == WHITE:
                    parent[nxt] = cur
                    color[nxt] = GRAY
                    stack.append((nxt, 0))
                elif color[nxt] == GRAY:
                    # 还原环：nxt … cur → nxt
                    path = [nxt]
                    walker: str | None = cur
                    while walker is not None and walker != nxt:
                        path.append(walker)
                        walker = parent[walker]
                    path.append(nxt)
                    path.reverse()
                    key = frozenset(path)
                    if key not in reported:
                        reported.add(key)
                        findings.append(ValidationFinding(
                            DagViolation.CYCLE, tuple(path), f"nodes.{path[0]}.depends_on",
                            "环路径：" + " → ".join(path),
                        ))
            else:
                color[cur] = BLACK
                stack.pop()

    findings.sort(key=lambda f: f.sort_key())
    return tuple(findings)


def check_orphans(view: GraphView) -> tuple[ValidationFinding, ...]:
    """检查 2：孤立节点与死端。

    定义（三条，全部拒绝）：
      1. **孤立**：多节点图中，既无前驱也无后继；
      2. **不可达**：从任一“根”（无前驱节点）出发沿边不可达；
      3. **死端**：从该节点出发沿边到不了任何“汇点”（无后继节点）。

    正例：单节点图（既是根也是汇）→ 通过；链 `a→b→c` → 通过。
    负例：`a→b` 加一个游离 `z` → `ORPHAN_NODE(z)`；
          `a→b`、`b→c`、`c→b`（b、c 互指）→ 由 CYCLE 报；`d` 无后继也无前驱 → 孤立。
    环上节点不重复报 ORPHAN/DEAD_END（已由 CYCLE 覆盖）。
    """
    node_ids = tuple(dict.fromkeys(view.node_ids))
    if not node_ids:
        return (ValidationFinding(DagViolation.EMPTY_GRAPH, (), "nodes", "图为空"),)

    succ, pred = _adjacency(view)
    cycle_nodes = {n for f in check_cycles(view) for n in f.nodes}

    findings: list[ValidationFinding] = []

    # 1) 多节点图中的完全孤立节点
    if len(node_ids) > 1:
        for n in node_ids:
            if n in cycle_nodes:
                continue
            if not succ.get(n) and not pred.get(n):
                findings.append(ValidationFinding(
                    DagViolation.ORPHAN_NODE, (n,), f"nodes.{n}.depends_on",
                    "既无前驱也无后继：孤立节点不得当作正常节点",
                ))

    # 2) 从根可达
    roots = [n for n in node_ids if not pred.get(n)]
    reachable: set[str] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        stack.extend(succ.get(cur, []))
    for n in node_ids:
        if n in reachable or n in cycle_nodes:
            continue
        findings.append(ValidationFinding(
            DagViolation.ORPHAN_NODE, (n,), f"nodes.{n}.depends_on",
            "从任何根节点都不可达",
        ))

    # 3) 能到汇点
    sinks = [n for n in node_ids if not succ.get(n)]
    co_reach: set[str] = set()
    stack = list(sinks)
    while stack:
        cur = stack.pop()
        if cur in co_reach:
            continue
        co_reach.add(cur)
        stack.extend(pred.get(cur, []))
    for n in node_ids:
        if n in co_reach or n in cycle_nodes:
            continue
        findings.append(ValidationFinding(
            DagViolation.DEAD_END_NODE, (n,), f"nodes.{n}.depends_on",
            "从该节点到不了任何汇点（分支永远不会收敛）",
        ))

    findings.sort(key=lambda f: f.sort_key())
    return tuple(findings)


def check_duplicate_edges(view: GraphView) -> tuple[ValidationFinding, ...]:
    """检查 3：重复边、重复节点、悬空依赖。

    正例：`a→b, a→c` → 通过。
    负例：
      - `depends_on: [a, a]` → `DUPLICATE_EDGE(b, a)`；
      - `node_ids: [a, a]` → `DUPLICATE_NODE_ID(a)`；
      - `b.depends_on: [ghost]` → `UNKNOWN_DEPENDENCY(b, ghost)`。
    """
    findings: list[ValidationFinding] = []
    seen_nodes: dict[str, int] = {}
    for n in view.node_ids:
        seen_nodes[n] = seen_nodes.get(n, 0) + 1
    for n, count in seen_nodes.items():
        if count > 1:
            findings.append(ValidationFinding(
                DagViolation.DUPLICATE_NODE_ID, (n,), f"nodes.{n}",
                f"node_id 出现 {count} 次（05 §3.3 重复拒绝）",
            ))

    known = set(view.node_ids)
    seen_edges: dict[tuple[str, str], int] = {}
    for src, dst in view.edge_pairs:
        seen_edges[(src, dst)] = seen_edges.get((src, dst), 0) + 1
    for (src, dst), count in seen_edges.items():
        if count > 1:
            findings.append(ValidationFinding(
                DagViolation.DUPLICATE_EDGE, (dst, src), f"nodes.{dst}.depends_on",
                f"边 {src}→{dst} 重复 {count} 次",
            ))
        if src not in known:
            findings.append(ValidationFinding(
                DagViolation.UNKNOWN_DEPENDENCY, (dst, src), f"nodes.{dst}.depends_on",
                f"依赖的前驱 {src!r} 不在图中",
            ))
        if dst not in known:
            findings.append(ValidationFinding(
                DagViolation.UNKNOWN_DEPENDENCY, (dst,), f"nodes.{dst}.depends_on",
                f"边的后继 {dst!r} 不在图中（内部不一致）",
            ))

    # 与 `dependencies` 交叉核对：防止调用方只改一份数据造成“两套真相”。
    for node, deps in view.dependencies.items():
        edge_deps = {src for src, dst in view.edge_pairs if dst == node}
        if set(deps) != edge_deps:
            findings.append(ValidationFinding(
                DagViolation.UNKNOWN_DEPENDENCY, (node,), f"nodes.{node}.depends_on",
                "dependencies 与 edge_pairs 不一致（视图自身矛盾）",
            ))

    findings.sort(key=lambda f: f.sort_key())
    return tuple(findings)


def check_node_types(
    view: GraphView,
    *,
    catalog: TemplateCatalogPort,
    node_id_rule: NodeIdRule,
) -> tuple[ValidationFinding, ...]:
    """检查 4：节点类型白名单、模板已注册、node_id 形态。

    正例：`node_type="ml.train.classifier"` 在白名单、模板已注册、node_id 合法 → 通过。
    负例：
      - `node_type="os.shell"` → `NODE_TYPE_NOT_ALLOWED`（403 TOOL_NOT_ALLOWLISTED）；
      - `template_id="ghost@9.9.9"` → `TEMPLATE_NOT_REGISTERED`（403）；
      - `node_id="../../etc/passwd"` → `NODE_ID_INVALID`（422）；
      - `node_id="con"` → `NODE_ID_RESERVED`（422）。
    """
    findings: list[ValidationFinding] = []
    for node in dict.fromkeys(view.node_ids):
        node_type = view.node_types.get(node)
        if node_type is None:
            findings.append(ValidationFinding(
                DagViolation.NODE_TYPE_NOT_ALLOWED, (node,), f"nodes.{node}.node_type",
                "缺少 node_type",
            ))
        elif not catalog.node_type_allowed(node_type):
            findings.append(ValidationFinding(
                DagViolation.NODE_TYPE_NOT_ALLOWED, (node,), f"nodes.{node}.node_type",
                f"{node_type!r} 不在域包允许类型内",
            ))

        template_id = view.template_ids.get(node)
        if not template_id or catalog.node_template(template_id) is None:
            findings.append(ValidationFinding(
                DagViolation.TEMPLATE_NOT_REGISTERED, (node,), f"nodes.{node}.template_id",
                f"{template_id!r} 未注册（不做 latest 回退）",
            ))

        if not isinstance(node, str) or not node:
            findings.append(ValidationFinding(
                DagViolation.NODE_ID_INVALID, (str(node),), f"nodes.{node}",
                "node_id 必须是非空字符串",
            ))
            continue
        if len(node) > 128 or "/" in node or "\\" in node or node.endswith((".", " ")):
            findings.append(ValidationFinding(
                DagViolation.NODE_ID_INVALID, (node,), f"nodes.{node}",
                "长度/路径分隔符/结尾句点空格不合规",
            ))
        elif node.lower() in RESERVED_NODE_NAMES:
            findings.append(ValidationFinding(
                DagViolation.NODE_ID_RESERVED, (node,), f"nodes.{node}",
                "Windows 保留设备名不能用作目录名",
            ))
        elif not node_id_rule.is_valid(node):
            findings.append(ValidationFinding(
                DagViolation.NODE_ID_INVALID, (node,), f"nodes.{node}",
                "不匹配 NODE_ID_PATTERN",
            ))

    findings.sort(key=lambda f: f.sort_key())
    return tuple(findings)


def check_graph_limits(
    view: GraphView, *, limits: DagLimits
) -> tuple[ValidationFinding, ...]:
    """检查 5：规模、深度、扇入/扇出。

    正例：10 节点/9 边/深度 7，`DEFAULT_DAG_LIMITS` 下通过。
    负例：
      - 33 节点 → `GRAPH_TOO_LARGE`（`detail` 含实际数与上限）；
      - 深度 17 → `GRAPH_TOO_DEEP`；
      - 一个节点 9 个直接后继 → `GRAPH_FAN_LIMIT`。
    """
    findings: list[ValidationFinding] = []
    node_ids = tuple(dict.fromkeys(view.node_ids))
    edge_count = len(view.edge_pairs)

    # 涉及节点：规模类违规的“涉及集合”就是整张图（全量列出，便于一条审计定位）。
    if len(node_ids) > limits.max_nodes:
        findings.append(ValidationFinding(
            DagViolation.GRAPH_TOO_LARGE, tuple(sorted(node_ids)), "graph.nodes",
            f"节点数 {len(node_ids)} > 上限 {limits.max_nodes}",
        ))
    if edge_count > limits.max_edges:
        endpoints = tuple(sorted({n for pair in view.edge_pairs for n in pair}))
        findings.append(ValidationFinding(
            DagViolation.GRAPH_TOO_LARGE, endpoints, "graph.edges",
            f"边数 {edge_count} > 上限 {limits.max_edges}",
        ))

    depth, has_cycle = _depths(view)
    if not has_cycle:
        deepest = max(depth.values(), default=0)
        if deepest > limits.max_depth:
            worst = sorted(n for n, d in depth.items() if d == deepest)[0]
            findings.append(ValidationFinding(
                DagViolation.GRAPH_TOO_DEEP, (worst,), f"nodes.{worst}",
                f"图深度 {deepest} > 上限 {limits.max_depth}",
            ))

    succ, pred = _adjacency(view)
    for node in sorted(succ):
        if len(succ[node]) > limits.max_fan_out:
            findings.append(ValidationFinding(
                DagViolation.GRAPH_FAN_LIMIT, (node,), f"nodes.{node}",
                f"扇出 {len(succ[node])} > 上限 {limits.max_fan_out}",
            ))
        if len(pred[node]) > limits.max_fan_in:
            findings.append(ValidationFinding(
                DagViolation.GRAPH_FAN_LIMIT, (node,), f"nodes.{node}.depends_on",
                f"扇入 {len(pred[node])} > 上限 {limits.max_fan_in}",
            ))

    findings.sort(key=lambda f: f.sort_key())
    return tuple(findings)


def check_input_refs(
    view: GraphView, *, producers: ArtifactProducerMap | Mapping[str, str]
) -> tuple[ValidationFinding, ...]:
    """检查 6：输入引用完整性。

    形态：`artifact://<name>`（05 §3.2 示例即 `artifact://split_manifest`）。
    拒绝：
      - 非 `artifact://` 形态、空名、含 `/`、`..`、`\\`、盘符/UNC → `INPUT_REF_FORMAT_INVALID`；
      - 无生产者 → `INPUT_REF_UNRESOLVED`；
      - 生产者不是本节点的传递前驱（或就是自己）→ `INPUT_REF_NOT_UPSTREAM`；
      - 两个节点声明同一产物名 → `ARTIFACT_DUPLICATE_PRODUCER`。

    正例：`preprocess.input_refs=["artifact://split_manifest"]`，split 是它的前驱 → 通过。
    负例：`predict.input_refs=["artifact://future_metrics"]`，生产者在它下游 → NOT_UPSTREAM。
    """
    findings: list[ValidationFinding] = []
    producer_of, producers_of = _producer_lookup(producers)
    ancestors = _ancestors(view)
    known = set(view.node_ids)

    for node in dict.fromkeys(view.node_ids):
        for idx, ref in enumerate(view.input_refs.get(node, ())):
            field_path = f"nodes.{node}.input_refs[{idx}]"
            name = _parse_artifact_ref(ref)
            if name is None:
                findings.append(ValidationFinding(
                    DagViolation.INPUT_REF_FORMAT_INVALID, (node,), field_path,
                    f"{ref!r} 不是 artifact://<name> 形态",
                ))
                continue
            if producers_of is not None:
                owners = tuple(producers_of(name))
                if len(owners) > 1:
                    findings.append(ValidationFinding(
                        DagViolation.ARTIFACT_DUPLICATE_PRODUCER, (node, *owners), field_path,
                        f"产物 {name!r} 有多个生产者：{list(owners)}",
                    ))
                    continue
            producer = producer_of(name)
            if producer is None or producer not in known:
                findings.append(ValidationFinding(
                    DagViolation.INPUT_REF_UNRESOLVED, (node,), field_path,
                    f"产物 {name!r} 没有已知生产者",
                ))
                continue
            if producer == node:
                findings.append(ValidationFinding(
                    DagViolation.INPUT_REF_NOT_UPSTREAM, (node,), field_path,
                    "节点不得消费自己的产物",
                ))
                continue
            if producer not in ancestors.get(node, frozenset()):
                findings.append(ValidationFinding(
                    DagViolation.INPUT_REF_NOT_UPSTREAM, (node, producer), field_path,
                    f"产物 {name!r} 的生产者 {producer!r} 不是本节点的前驱",
                ))

    findings.sort(key=lambda f: f.sort_key())
    return tuple(findings)


def _producer_lookup(
    producers: "ArtifactProducerMap | Mapping[str, str]",
) -> tuple[object, object]:
    """把 Mapping 或端口统一成 `(producer_of, producers_of|None)`。

    Mapping 形式没有 `producers_of`（键唯一，结构上不可能二义），
    此时二义检查返回 `None` 并跳过；端口形式必须实现两个方法。
    """
    if isinstance(producers, Mapping):
        mapping = producers

        def producer_of(name: str) -> str | None:
            return mapping.get(name)

        return producer_of, None
    producer_of = getattr(producers, "producer_of")
    producers_of = getattr(producers, "producers_of", None)
    return producer_of, producers_of


def _parse_artifact_ref(ref: str) -> str | None:
    """解析 `artifact://<name>`；非法返回 None（不抛，便于一次收集多条 findings）。

    拒绝：非 `artifact://`、空名、超长、路径分隔符、盘符/ADS（`:`）、`..`、
    首尾句点、空白/控制字符、Windows 保留设备名（产物名会成为文件名）。
    """
    prefix = "artifact://"
    if not isinstance(ref, str) or not ref.startswith(prefix):
        return None
    name = ref[len(prefix):]
    if not name or len(name) > 128:
        return None
    if "/" in name or "\\" in name or ":" in name:
        return None
    if ".." in name or name.startswith(".") or name.endswith("."):
        return None
    if any(ch.isspace() or not ch.isprintable() for ch in name):
        return None
    if name.lower() in RESERVED_NODE_NAMES:
        return None
    return name


# ---------------------------------------------------------------------------
# 6. 汇总校验
# ---------------------------------------------------------------------------
def validate_graph(
    view: GraphView,
    *,
    limits: DagLimits = DEFAULT_DAG_LIMITS,
    catalog: TemplateCatalogPort,
    producers: ArtifactProducerMap | Mapping[str, str],
    node_id_rule: NodeIdRule,
    checks: Sequence[CheckClass] = CHECK_ORDER,
) -> ValidationReport:
    """跑指定校验集合（默认六类全跑），一次收集全部 findings。

    设计取舍：**不 fail-fast**。理由：一次拒绝就把图的所有问题摊开，评审与修复成本最低；
    对外仍只回一个主错误码（`report.primary()`），细节进 `detail`/日志。

    参数：
      - `checks`：可只跑某几类（patch_approval 复用时会分开跑并保留分类结果）；
      - `producers`：产物名 → 生产者；可由 `Mapping` 或带 `producer_of()` 的端口提供。

    返回：`ValidationReport`。**不抛异常表示通过** —— 通过与否只看 `report.ok`，
    避免“异常被上层 catch 后当成通过”的老问题。
    """
    unknown = [c for c in checks if c not in CHECK_ORDER]
    if unknown:
        raise ValueError(f"未知校验类别：{unknown}")

    findings: list[ValidationFinding] = []
    ran: list[CheckClass] = []

    if CheckClass.CYCLE_SELF_LOOP in checks:
        findings.extend(check_cycles(view))
        ran.append(CheckClass.CYCLE_SELF_LOOP)
    if CheckClass.ORPHAN in checks:
        findings.extend(check_orphans(view))
        ran.append(CheckClass.ORPHAN)
    if CheckClass.DUPLICATE_EDGE in checks:
        findings.extend(check_duplicate_edges(view))
        ran.append(CheckClass.DUPLICATE_EDGE)
    if CheckClass.NODE_TYPE in checks:
        findings.extend(check_node_types(view, catalog=catalog, node_id_rule=node_id_rule))
        ran.append(CheckClass.NODE_TYPE)
    if CheckClass.GRAPH_LIMIT in checks:
        findings.extend(check_graph_limits(view, limits=limits))
        ran.append(CheckClass.GRAPH_LIMIT)
    if CheckClass.INPUT_REF in checks:
        findings.extend(check_input_refs(view, producers=producers))
        ran.append(CheckClass.INPUT_REF)

    findings.sort(key=lambda f: f.sort_key())
    topology = _topology(view) if not findings else ()
    depth, _ = _depths(view)
    stats = {
        "nodes": len(tuple(dict.fromkeys(view.node_ids))),
        "edges": len(view.edge_pairs),
        "max_depth": max(depth.values(), default=0),
        "findings": len(findings),
    }
    return ValidationReport(
        ok=not findings,
        findings=tuple(findings),
        checks_run=tuple(ran),
        topology=topology,
        node_count=stats["nodes"],
        edge_count=stats["edges"],
        depth=stats["max_depth"],
        stats=MappingProxyType(stats),
    )


# ---------------------------------------------------------------------------
# 7. 正负例矩阵（评审用；每条对应 NEGATIVE_TESTS.md 的一行）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CheckVector:
    vector_id: str
    check: CheckClass
    positive: bool
    graph_summary: str
    expected_ok: bool
    expected_violation: DagViolation | None
    expected_error_code: str | None
    expected_nodes: tuple[str, ...] = ()


# 六类 × 正负例 = 12 条。`expected_error_code=None` 表示应通过。
CHECK_MATRIX: Final[tuple[CheckVector, ...]] = (
    CheckVector("V-CYCLE-P", CheckClass.CYCLE_SELF_LOOP, True,
                "dataset_profile→split→preprocess", True, None, None),
    CheckVector("V-CYCLE-N", CheckClass.CYCLE_SELF_LOOP, False,
                "a→b→c→a", False, DagViolation.CYCLE, "STATE_TRANSITION_DENIED",
                ("a", "b", "c", "a")),
    CheckVector("V-SELF-N", CheckClass.CYCLE_SELF_LOOP, False,
                "a→a", False, DagViolation.SELF_LOOP, "SCHEMA_INVALID", ("a",)),
    CheckVector("V-ORPHAN-P", CheckClass.ORPHAN, True,
                "单节点图 / 链 a→b→c", True, None, None),
    CheckVector("V-ORPHAN-N", CheckClass.ORPHAN, False,
                "a→b 外挂孤立 z", False, DagViolation.ORPHAN_NODE,
                "STATE_TRANSITION_DENIED", ("z",)),
    CheckVector("V-DUP-P", CheckClass.DUPLICATE_EDGE, True,
                "a→b, a→c", True, None, None),
    CheckVector("V-DUP-N", CheckClass.DUPLICATE_EDGE, False,
                "b.depends_on=[a,a]", False, DagViolation.DUPLICATE_EDGE,
                "SCHEMA_INVALID", ("b", "a")),
    CheckVector("V-TYPE-P", CheckClass.NODE_TYPE, True,
                "node_type=ml.train.classifier + 已注册模板", True, None, None),
    CheckVector("V-TYPE-N", CheckClass.NODE_TYPE, False,
                "node_type=os.shell", False, DagViolation.NODE_TYPE_NOT_ALLOWED,
                "TOOL_NOT_ALLOWLISTED", ("x",)),
    CheckVector("V-LIMIT-P", CheckClass.GRAPH_LIMIT, True,
                "10 节点/9 边/深度 7", True, None, None),
    CheckVector("V-LIMIT-N", CheckClass.GRAPH_LIMIT, False,
                "33 节点（max_nodes=32）", False, DagViolation.GRAPH_TOO_LARGE,
                "STATE_TRANSITION_DENIED"),
    CheckVector("V-REF-P", CheckClass.INPUT_REF, True,
                "preprocess 引 artifact://split_manifest，split 是前驱", True, None, None),
    CheckVector("V-REF-N", CheckClass.INPUT_REF, False,
                "predict 引 artifact://future_metrics，生产者在它下游",
                False, DagViolation.INPUT_REF_NOT_UPSTREAM, "SCHEMA_INVALID",
                ("predict", "report")),
)


# ---------------------------------------------------------------------------
# 8. 自检
# ---------------------------------------------------------------------------
def assert_validator_contract() -> list[str]:
    """自检：六类校验齐全、违规映射完整、未引入注册表外的错误码。

    落地阶段由测试调用；返回违反项列表（空 = 通过）。
    """
    problems: list[str] = []
    mapped = {spec.check for spec in VIOLATION_SPECS.values()}
    for cls in CHECK_ORDER:
        if cls not in mapped:
            problems.append(f"校验类别 {cls} 没有任何违规码映射")
    for violation, spec in VIOLATION_SPECS.items():
        if spec.error_code not in ALLOWED_ERROR_CODES:
            problems.append(f"{violation} 使用了注册表外的错误码 {spec.error_code}")
        if not spec.fail_closed:
            problems.append(f"{violation} 必须 fail-closed")
    for vector in CHECK_MATRIX:
        if vector.positive and vector.expected_error_code is not None:
            problems.append(f"{vector.vector_id} 是正例却期待错误码")
        if not vector.positive and vector.expected_violation is None:
            problems.append(f"{vector.vector_id} 是负例却没写期望违规码")
    return problems