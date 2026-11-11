"""M04 · orchestration/dag/patch_approval.py — 图变更审批（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-002（图治理）、FR-010（改图 → 失效）；依据：策划书 §8.9
依赖：M04 builder/validator/graph_version、M01 errors（只引用）、M03 limits（预算口径）
不变量：六项校验全过才可能放行；影响已验证结果或扩大权限必须人工批准；已执行节点不可静默重写
错误码：STATE_TRANSITION_DENIED / TOOL_NOT_ALLOWLISTED / SCHEMA_INVALID / RESOURCE_BUDGET_EXCEEDED
写入者：**无**（只出决策；新图登记走 graph_version.GraphRegistrar，失效走 invalidation.py）
状态：伪代码；不执行、不写库、不写审计、不调 transition

## 策划书 §8.9 原文要求的六项校验（逐条对应到本文件）

  > Planner 只能提交 graph_patch。调度器检查无环、节点/边白名单、图规模/深度、预算、
  > 权限不扩大、已执行节点不可静默重写；影响已验证结果或扩大执行权限的变更须人工批准。

  | # | 检查 | 实现 |
  |---|---|---|
  | 1 | 无环 | `_check_acyclic`（复用 validator 的 `check_cycles`） |
  | 2 | 节点/边白名单 | `_check_whitelist`（模板已注册 + node_type 允许 + 边端点存在） |
  | 3 | 图规模/深度 | `_check_limits`（复用 validator 的 `check_graph_limits`） |
  | 4 | 预算 | `_check_budget`（模板资源上限 × 剩余预算） |
  | 5 | 权限不扩大 | `_check_permission`（side_effect 等级、模板集合、网络、写入面） |
  | 6 | 已执行节点不可静默重写 | `_check_executed_nodes`（state/attempt_seq/证据） |

  另外两条硬规则（不在六项里，但同样拒绝）：
  - T0 只在 `PLANNING` 阶段接受 patch；已 `READY` 之后改图必须走**新版本 + 失效传播**；
  - 任何“接受”都必须留下审计；审计通道不可用 → fail-closed（`AUDIT_UNAVAILABLE`）。

## 为什么“批准”不等于“执行”

  `evaluate_patch()` 只返回决策与理由。真正的落地顺序由 Orchestrator 编排：
    ① 批准（拿到 `ApprovalTicket`）→ ② `GraphRegistrar.register()`（新版本）
    → ③ `invalidation.py` 计算失效集合 → ④ StateMachine 迁移。
  任一步失败都不得“先改图再补批准”。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .builder import NodeDraft, NodeIdRule, RetryPolicy, TemplateCatalogPort
from .graph_version import GraphContent
from .validator import (
    DagLimits,
    DagViolation,
    check_cycles,
    check_graph_limits,
    check_node_types,
)

__all__ = [
    "APPROVAL_THRESHOLD_RULES",
    "PATCH_CHECKS",
    "PERMISSION_RANK",
    "PATCH_VIOLATION_SPECS",
    "ApprovalTicket",
    "BudgetEstimate",
    "BudgetPort",
    "GraphPatch",
    "PatchAuditPort",
    "PatchChannelPort",
    "PatchContext",
    "PatchDecision",
    "PatchDecisionReport",
    "PatchFinding",
    "PatchOp",
    "PatchOpKind",
    "PatchViolation",
    "PermissionEnvelope",
    "apply_patch",
    "assert_patch_approval_contract",
    "evaluate_patch",
    "patch_hash",
]


# ---------------------------------------------------------------------------
# 1. 变更操作
# ---------------------------------------------------------------------------
class PatchOpKind(StrEnum):
    """只允许这些操作。没有 `SET_GRAPH`、没有 `RUN`、没有 `EXEC`。"""

    ADD_NODE = "ADD_NODE"
    REMOVE_NODE = "REMOVE_NODE"
    ADD_EDGE = "ADD_EDGE"
    REMOVE_EDGE = "REMOVE_EDGE"
    CHANGE_PARAMS = "CHANGE_PARAMS"            # 只改 parameters（→ parameters_hash 变）
    CHANGE_TEMPLATE = "CHANGE_TEMPLATE"        # 换模板（可能换实现/换 side_effect）
    CHANGE_REQUIRED_CHECKS = "CHANGE_REQUIRED_CHECKS"
    CHANGE_RETRY = "CHANGE_RETRY"              # retry_policy 变化（不扩大预算则不触发批准）


@dataclass(frozen=True, slots=True)
class PatchOp:
    """一条变更。

    `payload` 的键按 `kind` 固定，**不做多态猜测**：
      - ADD_NODE → `{"template_id": ..., "parameters": {...}, "depends_on": [...]}`
      - REMOVE_NODE → `{}`（节点由 `node_id` 指定）
      - ADD_EDGE / REMOVE_EDGE → `{"src": node_id}`（`node_id` 是 dst）
      - CHANGE_PARAMS → `{"parameters": {...}}`
      - CHANGE_TEMPLATE → `{"template_id": ...}`
      - CHANGE_REQUIRED_CHECKS → `{"required_checks": [...]}`
      - CHANGE_RETRY → `{"max_attempts": int, "backoff_sec": number}`
    """

    kind: PatchOpKind
    node_id: str
    payload: Mapping[str, object] = MappingProxyType({})
    reason: str = ""


@dataclass(frozen=True, slots=True)
class GraphPatch:
    """一次图变更提案（Planner/T1 产生；T0 仅用于“配置变更导致重建图”的内部路径）。"""

    task_id: str
    base_graph_version: int
    ops: tuple[PatchOp, ...]
    proposed_by: str            # actor identity，形状同 M02 Actor.identity
    justification: str
    patch_hash: str             # 内容哈希，批准票绑定它


def patch_hash(task_id: str, base_graph_version: int, ops: Sequence[PatchOp]) -> str:
    """补丁内容哈希：`sha256(JCS({task_id, base_version, ops}))`。

    绑定 `patch_hash` 是批准票防掉包的唯一手段：批准的是**这一份**补丁，
    换一条 op 就必须重新批准。`proposed_by`/`justification` 不进哈希：
    它们不影响图的语义，且由审计单独记录。
    """
    payload = {
        "task_id": task_id,
        "base_graph_version": base_graph_version,
        "ops": [
            {"kind": op.kind.value, "node_id": op.node_id,
             "payload": _jsonable(op.payload), "reason": op.reason}
            for op in ops
        ],
    }
    # LIB: researchflow.contracts.encoding.canonical_bytes（JCS）+ sha256
    #
    # 纪律：不得用 `json.dumps(sort_keys=True)` 冒充 JCS（ENCODING_RULES §5）。
    # 伪代码阶段只固定前像字段与顺序语义，实际哈希由 M01 落地。
    _ = payload
    raise NotImplementedError("P3 伪代码：patch_hash 由 M01 encoding.canonical_bytes + sha256 落地")


def _jsonable(value: object) -> object:
    """把 payload 转成可 JSON 化的结构；不可序列化即判非法（不 str() 兜底）。"""
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"patch payload 含不可序列化类型 {type(value).__name__}")


# ---------------------------------------------------------------------------
# 2. 违规与决策
# ---------------------------------------------------------------------------
class PatchViolation(StrEnum):
    """图变更的拒绝/升级原因（原因码，不是新错误码）。"""

    BASE_VERSION_STALE = "BASE_VERSION_STALE"          # 补丁基于旧版本
    PLAN_NOT_ALLOWED = "PLAN_NOT_ALLOWED"              # 非 PLANNING 阶段不得改图
    UNSUPPORTED_OP = "UNSUPPORTED_OP"                  # 未知操作/载荷缺键
    NODE_NOT_IN_GRAPH = "NODE_NOT_IN_GRAPH"            # 操作指向不存在的节点
    DUPLICATE_NODE = "DUPLICATE_NODE"                  # ADD_NODE 撞名
    # 六项
    CYCLE_INTRODUCED = "CYCLE_INTRODUCED"
    WHITELIST_VIOLATION = "WHITELIST_VIOLATION"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PERMISSION_EXPANSION = "PERMISSION_EXPANSION"
    EXECUTED_NODE_REWRITE = "EXECUTED_NODE_REWRITE"
    # 批准与审计
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"            # 不是错误：需要人工批准
    BLOCKED_EVIDENCE_IMPACT = "BLOCKED_EVIDENCE_IMPACT"  # 影响已验证结果但通道不可用
    REQUIRED_CHECKS_REMOVED = "REQUIRED_CHECKS_REMOVED"  # 削弱必检项：必须批准，不得静默
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"            # 无审计写者 → fail-closed


@dataclass(frozen=True, slots=True)
class PatchViolationSpec:
    error_code: str
    http_status: int
    reason: str
    hard_reject: bool        # True = 直接拒绝；False = 可经人工批准
    approval_required: bool
    source: str


PATCH_VIOLATION_SPECS: Final[Mapping[PatchViolation, PatchViolationSpec]] = MappingProxyType(
    {
        PatchViolation.BASE_VERSION_STALE: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "GRAPH_VERSION_CONFLICT", True, False,
            "补丁必须基于当前已登记版本；旧补丁不得覆盖新图",
        ),
        PatchViolation.PLAN_NOT_ALLOWED: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "GRAPH_PATCH_NOT_ALLOWED", True, False,
            "T0 只在 PLANNING 接受 patch；READY 之后改图 = 新版本 + 失效传播",
        ),
        PatchViolation.UNSUPPORTED_OP: PatchViolationSpec(
            "SCHEMA_INVALID", 422, "PATCH_OP_INVALID", True, False,
            "未知操作或载荷缺必填键；不允许“尽力解析”",
        ),
        PatchViolation.NODE_NOT_IN_GRAPH: PatchViolationSpec(
            "SCHEMA_INVALID", 422, "PATCH_NODE_UNKNOWN", True, False,
            "操作指向不存在的节点（不能靠改图删掉误引用）",
        ),
        PatchViolation.DUPLICATE_NODE: PatchViolationSpec(
            "SCHEMA_INVALID", 422, "PATCH_NODE_DUPLICATE", True, False,
            "ADD_NODE 的 node_id 已存在；改内容请用 CHANGE_*",
        ),
        PatchViolation.CYCLE_INTRODUCED: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True, False,
            "六项之一：无环（05 §3.3）",
        ),
        PatchViolation.WHITELIST_VIOLATION: PatchViolationSpec(
            "TOOL_NOT_ALLOWLISTED", 403, "NODE_TYPE_NOT_ALLOWED", True, False,
            "六项之二：节点/边白名单（05 §3.1）",
        ),
        PatchViolation.LIMIT_EXCEEDED: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "DAG_INVALID", True, False,
            "六项之三：图规模/深度（策划书 §8.9）",
        ),
        PatchViolation.BUDGET_EXCEEDED: PatchViolationSpec(
            "RESOURCE_BUDGET_EXCEEDED", 429, "BUDGET_EXCEEDED", True, False,
            "六项之四：预算；detail.limit_kind 取 wall_clock/memory/disk/retry",
        ),
        PatchViolation.PERMISSION_EXPANSION: PatchViolationSpec(
            "TOOL_NOT_ALLOWLISTED", 403, "PERMISSION_EXPANSION", False, True,
            "六项之五：权限不扩大；扩大即必须人工批准（§8.9）",
        ),
        PatchViolation.EXECUTED_NODE_REWRITE: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "EXECUTED_NODE_REWRITE", True, False,
            "六项之六：已执行节点不可静默重写（只能新版本 + 失效 + 重跑）",
        ),
        PatchViolation.APPROVAL_REQUIRED: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "PATCH_APPROVAL_REQUIRED", False, True,
            "影响已验证结果或扩大权限：必须人工批准后才可登记",
        ),
        PatchViolation.BLOCKED_EVIDENCE_IMPACT: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "PATCH_BLOCKED_EVIDENCE_IMPACT", True, True,
            "影响已验证结果但批准通道不可用 → 拒绝（不得默认放行）",
        ),
        PatchViolation.REQUIRED_CHECKS_REMOVED: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "REQUIRED_CHECKS_REMOVED", False, True,
            "§8.9：不得静默取消必检项或 L3；删除必检项必须显式批准并留痕",
        ),
        PatchViolation.AUDIT_UNAVAILABLE: PatchViolationSpec(
            "STATE_TRANSITION_DENIED", 409, "PATCH_AUDIT_UNAVAILABLE", True, False,
            "审计写者不可用 → fail-closed（见 OQ-P3-05）",
        ),
    }
)


class PatchDecision(StrEnum):
    ACCEPT = "ACCEPT"                          # 可以直接登记
    ACCEPT_WITH_APPROVAL = "ACCEPT_WITH_APPROVAL"  # 需要并已拿到批准票
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"    # 需要但还没拿到（未执行，不是失败）
    REJECT = "REJECT"                          # 硬拒绝


@dataclass(frozen=True, slots=True)
class PatchFinding:
    violation: PatchViolation
    nodes: tuple[str, ...]
    detail: str

    @property
    def spec(self) -> PatchViolationSpec:
        return PATCH_VIOLATION_SPECS[self.violation]

    @property
    def error_code(self) -> str:
        return self.spec.error_code

    @property
    def hard_reject(self) -> bool:
        return self.spec.hard_reject


# ---------------------------------------------------------------------------
# 3. 权限包络与预算
# ---------------------------------------------------------------------------
PERMISSION_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {"PURE_FUNCTION": 0, "PURE_ARTIFACT": 1, "SIDE_EFFECT": 2}
)


@dataclass(frozen=True, slots=True)
class PermissionEnvelope:
    """一张图“能做什么”的摘要；用于判断补丁是否扩大权限。

    字段刻意选**可比较**的量：
      - `max_side_effect`: 0/1/2（见 PERMISSION_RANK）；
      - `templates`: 用到的模板集合（必须都在注册表内，白名单检查已保证）；
      - `network_allowed`: T0 恒 False；补丁把它变 True 就是扩大；
      - `write_outputs`: 声明的产物名集合（写面）；
      - `max_wall_time_sec` / `max_memory_mb` / `max_disk_mb`：资源上限的图内最大值。
    """

    max_side_effect: int
    templates: frozenset[str]
    network_allowed: bool
    write_outputs: frozenset[str]
    max_wall_time_sec: int
    max_memory_mb: int
    max_disk_mb: int


@dataclass(frozen=True, slots=True)
class BudgetEstimate:
    """执行预算估计（由模板资源上限累加，不是实测值）。"""

    wall_time_sec: int
    memory_mb: int
    disk_mb: int
    attempts: int


class BudgetPort(Protocol):
    """剩余预算来源（TaskSpec.limits + limits.yaml 装配结果；P7 提供）。"""

    def remaining(self, task_id: str) -> BudgetEstimate:
        ...


# ---------------------------------------------------------------------------
# 4. 上下文与通道
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PatchContext:
    """评估一次补丁所需的**只读事实**。全部由调用方收集，本文件不查库。"""

    task_id: str
    task_state: str                         # CREATED/PLANNING/READY/RUNNING/VERIFYING/...
    current_graph_version: int
    base: GraphContent
    node_states: Mapping[str, str]          # node_id → PLANNED/READY/RUNNING/VERIFYING/VERIFIED/...
    node_attempt_seq: Mapping[str, int]     # node_id → attempt_seq（>0 = 执行过）
    node_has_evidence: Mapping[str, bool]   # node_id → 是否已有任何证据
    verified_nodes: frozenset[str]          # 曾经 VERIFIED 的节点（含已 INVALIDATED）
    limits: DagLimits
    budget_remaining: BudgetEstimate
    catalog: TemplateCatalogPort
    node_id_rule: NodeIdRule
    approval: "ApprovalTicket | None" = None
    approval_channel_available: bool = False
    audit_available: bool = True


class PatchChannelPort(Protocol):
    """人工批准通道（T0 无用户体系 → 默认不可用，approval=False 时拒绝）。"""

    def submit(self, *, patch_hash: str, findings: Sequence[PatchFinding]) -> str | None:
        """提交审批；返回 `approved_by` 或 None（未批准/通道不可用）。"""
        ...


class PatchAuditPort(Protocol):
    """审计写者端口。

    **当前没有合法实现**：`audit_log` 的唯一写者是 StateMachine（06 §3），
    而图变更不是状态迁移。P3 因此把它做成显式端口并要求 fail-closed：
    端口缺失 → `AUDIT_UNAVAILABLE` → 拒绝。落地前必须先补 ADR（OQ-P3-05）。
    """

    def record_patch_decision(
        self,
        *,
        task_id: str,
        base_graph_version: int,
        patch_hash: str,
        decision: PatchDecision,
        proposed_by: str,
        findings: Sequence[PatchFinding],
    ) -> None:
        ...


@dataclass(frozen=True, slots=True)
class ApprovalTicket:
    """批准票：与 `patch_hash` 绑定，内容寻址，**不新造 ID 前缀**（ENCODING_RULES §1）。"""

    patch_hash: str
    approved_by: str
    approved_at: str            # UTC 27 字符
    scope: str                  # 批准范围说明（例如 “影响 2 个已验证节点的重跑”）

    def digest(self) -> str:
        payload = f"{self.patch_hash}|{self.approved_by}|{self.approved_at}|{self.scope}"
        return sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 5. 补丁应用（纯函数）
# ---------------------------------------------------------------------------
class _CandidateView:
    """`GraphView` 适配器：让 validator 的检查函数直接跑在候选图上。"""

    def __init__(self, content: GraphContent) -> None:
        self._content = content

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(n.node_id for n in self._content.nodes)

    @property
    def edge_pairs(self) -> tuple[tuple[str, str], ...]:
        return self._content.edges

    @property
    def dependencies(self) -> Mapping[str, Sequence[str]]:
        return self._content.dependencies()

    @property
    def node_types(self) -> Mapping[str, str]:
        return MappingProxyType({n.node_id: n.node_type for n in self._content.nodes})

    @property
    def template_ids(self) -> Mapping[str, str]:
        return MappingProxyType({n.node_id: n.template_id for n in self._content.nodes})

    @property
    def input_refs(self) -> Mapping[str, Sequence[str]]:
        return MappingProxyType({n.node_id: n.input_refs for n in self._content.nodes})


def apply_patch(base: GraphContent, ops: Sequence[PatchOp]) -> GraphContent:
    """把补丁应用到内存图，返回**候选图**（不校验、不登记、不改版本号）。

    错误（`PatchViolation`，由调用方转成 finding）：
      - 未知 `kind` / 载荷缺键 → `UNSUPPORTED_OP`；
      - 指向不存在节点（REMOVE/ADD_EDGE/CHANGE_*）→ `NODE_NOT_IN_GRAPH`；
      - ADD_NODE 撞名 → `DUPLICATE_NODE`；
      - ADD_EDGE 产生自环 → 交给六项校验的“无环”报（这里允许先构造出来）。

    注意：候选图的 `graph_version` 保持 base，`graph_hash` 置空字符串 ——
    新版本与新哈希由 Builder 重建后给出，本函数不伪造。
    """
    nodes: dict[str, NodeDraft] = {n.node_id: n for n in base.nodes}
    edges: set[tuple[str, str]] = set(base.edges)

    for op in ops:
        if op.kind is PatchOpKind.ADD_NODE:
            if op.node_id in nodes:
                raise _PatchError(PatchViolation.DUPLICATE_NODE, (op.node_id,), "节点已存在")
            nodes[op.node_id] = _node_from_payload(op)
        elif op.kind is PatchOpKind.REMOVE_NODE:
            if op.node_id not in nodes:
                raise _PatchError(PatchViolation.NODE_NOT_IN_GRAPH, (op.node_id,), "")
            nodes.pop(op.node_id)
            edges = {(s, d) for (s, d) in edges if op.node_id not in (s, d)}
        elif op.kind is PatchOpKind.ADD_EDGE:
            src = _require_key(op, "src")
            _require_node(nodes, op.node_id)
            _require_node(nodes, src)
            edges.add((src, op.node_id))
        elif op.kind is PatchOpKind.REMOVE_EDGE:
            src = _require_key(op, "src")
            if (src, op.node_id) not in edges:
                raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,),
                                  f"边 {src}→{op.node_id} 不存在")
            edges.discard((src, op.node_id))
        elif op.kind is PatchOpKind.CHANGE_PARAMS:
            node = _require_node(nodes, op.node_id)
            params = op.payload.get("parameters")
            if not isinstance(params, Mapping):
                raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,),
                                  "CHANGE_PARAMS 缺 parameters 对象")
            nodes[op.node_id] = _replace(node, parameters=params,
                                         parameters_hash=_hash_payload_or_raise(params))
        elif op.kind is PatchOpKind.CHANGE_TEMPLATE:
            node = _require_node(nodes, op.node_id)
            nodes[op.node_id] = _replace(node, template_id=_require_key(op, "template_id"))
        elif op.kind is PatchOpKind.CHANGE_REQUIRED_CHECKS:
            node = _require_node(nodes, op.node_id)
            checks = op.payload.get("required_checks")
            if not isinstance(checks, list) or not checks:
                raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,),
                                  "required_checks 必须是非空数组")
            nodes[op.node_id] = _replace(node, required_checks=tuple(str(c) for c in checks))
        elif op.kind is PatchOpKind.CHANGE_RETRY:
            node = _require_node(nodes, op.node_id)
            max_attempts = op.payload.get("max_attempts")
            backoff = op.payload.get("backoff_sec")
            if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
                raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,), "max_attempts 必须是整数")
            if not isinstance(backoff, (int, float)) or isinstance(backoff, bool):
                raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,), "backoff_sec 必须是数字")
            nodes[op.node_id] = _replace(
                node,
                retry_policy=type(node.retry_policy)(max_attempts=max_attempts,
                                                     backoff_sec=float(backoff)),
            )
        else:  # pragma: no cover - StrEnum 已穷举
            raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,), f"未知 kind {op.kind}")

    return GraphContent(
        task_id=base.task_id,
        graph_version=base.graph_version,
        graph_hash="",              # 由重建给出，不在此伪造
        nodes=tuple(sorted(nodes.values(), key=lambda n: n.node_id)),
        edges=tuple(sorted(edges)),
    )


class _PatchError(RuntimeError):
    def __init__(self, violation: PatchViolation, nodes: tuple[str, ...], detail: str) -> None:
        self.violation = violation
        self.nodes = nodes
        self.detail = detail
        super().__init__(f"{violation.value}: {detail}")


def _require_key(op: PatchOp, key: str) -> str:
    value = op.payload.get(key)
    if not isinstance(value, str) or not value:
        raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,), f"载荷缺 {key}")
    return value


def _require_node(nodes: Mapping[str, NodeDraft], node_id: str) -> NodeDraft:
    node = nodes.get(node_id)
    if node is None:
        raise _PatchError(PatchViolation.NODE_NOT_IN_GRAPH, (node_id,), "节点不在图中")
    return node


def _replace(node: NodeDraft, **changes: object) -> NodeDraft:
    data = {f: getattr(node, f) for f in node.__dataclass_fields__}
    data.update(changes)
    return NodeDraft(**data)  # type: ignore[arg-type]


def _node_from_payload(op: PatchOp) -> NodeDraft:
    params = op.payload.get("parameters")
    if not isinstance(params, Mapping):
        raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,), "ADD_NODE 缺 parameters")
    deps = op.payload.get("depends_on") or []
    if not isinstance(deps, (list, tuple)) or not all(isinstance(d, str) for d in deps):
        raise _PatchError(PatchViolation.UNSUPPORTED_OP, (op.node_id,), "depends_on 必须是字符串数组")
    template_id = _require_key(op, "template_id")
    # ADD_NODE 只带“结构占位”：node_type/side_effect/retry/required_checks 的权威值
    # 由 Builder 在重建新版本时补齐。占位 node_type 为空 → 白名单检查直接拒绝
    # （见 `_check_whitelist`），避免 patch 侧自己发明节点类型。
    return NodeDraft(
        node_id=op.node_id,
        node_type="",
        template_id=template_id,
        schema_version="1.0",
        depends_on=tuple(deps),
        input_refs=tuple(str(x) for x in (op.payload.get("input_refs") or [])),
        parameters_hash=_hash_payload_or_raise(params),
        side_effect_class="",
        retry_policy=RetryPolicy(max_attempts=1, backoff_sec=0.0),
        required_checks=tuple(str(c) for c in (op.payload.get("required_checks") or ("executor_observed",))),
        parameters=params,
    )


def _hash_payload_or_raise(params: Mapping[str, object]) -> str:
    """补丁里的参数哈希：**不在本文件重算**，调用 M01 `hash_payload`。

    伪代码阶段保留 NotImplementedError，落地时替换为：
        from researchflow.contracts.encoding import hash_payload
    """
    raise NotImplementedError("P3 伪代码：参数哈希由 M01 encoding.hash_payload 落地")


# ---------------------------------------------------------------------------
# 6. 六项校验
# ---------------------------------------------------------------------------
PATCH_CHECKS: Final[tuple[str, ...]] = (
    "无环", "白名单", "规模深度", "预算", "权限不扩大", "已执行节点不可静默重写",
)


def _check_acyclic(candidate: GraphContent) -> tuple[PatchFinding, ...]:
    view = _CandidateView(candidate)
    findings: list[PatchFinding] = []
    for finding in check_cycles(view):
        if finding.violation is DagViolation.SELF_LOOP:
            findings.append(PatchFinding(PatchViolation.CYCLE_INTRODUCED, finding.nodes,
                                         "补丁引入自环：" + finding.detail))
        else:
            findings.append(PatchFinding(PatchViolation.CYCLE_INTRODUCED, finding.nodes,
                                         "补丁引入环：" + finding.detail))
    return tuple(findings)


def _check_whitelist(candidate: GraphContent, ctx: PatchContext) -> tuple[PatchFinding, ...]:
    """白名单：模板已注册、node_type 允许、边端点存在、node_id 合法。"""
    view = _CandidateView(candidate)
    findings: list[PatchFinding] = []
    for finding in check_node_types(view, catalog=ctx.catalog, node_id_rule=ctx.node_id_rule):  # type: ignore[arg-type]
        findings.append(PatchFinding(PatchViolation.WHITELIST_VIOLATION, finding.nodes, finding.detail))
    known = set(view.node_ids)
    for src, dst in candidate.edges:
        if src not in known or dst not in known:
            findings.append(PatchFinding(PatchViolation.WHITELIST_VIOLATION, (dst, src),
                                         "边端点不在图中"))
    # 新增节点的模板必须已注册（ADD_NODE 占位 node_type 为空，不能靠占位过检查）
    for node in candidate.nodes:
        if not node.node_type:
            findings.append(PatchFinding(PatchViolation.WHITELIST_VIOLATION, (node.node_id,),
                                         "节点缺少 node_type（ADD_NODE 必须带模板，由重建补齐）"))
    return tuple(findings)


def _check_limits(candidate: GraphContent, ctx: PatchContext) -> tuple[PatchFinding, ...]:
    view = _CandidateView(candidate)
    return tuple(
        PatchFinding(PatchViolation.LIMIT_EXCEEDED, f.nodes, f.detail)
        for f in check_graph_limits(view, limits=ctx.limits)
    )


def _check_budget(candidate: GraphContent, ctx: PatchContext) -> tuple[PatchFinding, ...]:
    """预算：补丁引起的**增量**不得超过剩余预算。

    估算口径（保守，宁严不松）：
      - 每个节点的 wall/memory/disk 上限来自模板 `resource_caps`，缺省用任务级上限；
      - 增量 = 候选图合计 − 基线图合计；`attempts` 增量 = 新增节点的 `max_attempts` 之和。
    任何维度超限即一条 finding；`detail` 里带 `limit_kind`（wall_clock/memory/disk/retry），
    与 errors.py 的 `RESOURCE_BUDGET_EXCEEDED` + `detail.limit_kind` 口径一致。
    """
    base_est = _estimate(ctx.base, ctx)
    next_est = _estimate(candidate, ctx)
    remaining = ctx.budget_remaining
    findings: list[PatchFinding] = []
    for kind, base_v, next_v, remain_v, _unit in (
        ("wall_clock", base_est.wall_time_sec, next_est.wall_time_sec, remaining.wall_time_sec, "s"),
        ("memory", base_est.memory_mb, next_est.memory_mb, remaining.memory_mb, "MiB"),
        ("disk", base_est.disk_mb, next_est.disk_mb, remaining.disk_mb, "MiB"),
        ("retry", base_est.attempts, next_est.attempts, remaining.attempts, "attempts"),
    ):
        delta = next_v - base_v
        if delta > remain_v:
            findings.append(PatchFinding(
                PatchViolation.BUDGET_EXCEEDED, (),
                f"limit_kind={kind};delta={delta};remaining={remain_v}",
            ))
    return tuple(findings)


def _estimate(content: GraphContent, ctx: PatchContext) -> BudgetEstimate:
    """按模板上限累加估算（不看实测值：patch 发生在执行之前）。"""
    wall = memory = disk = attempts = 0
    for node in content.nodes:
        descriptor = ctx.catalog.node_template(node.template_id)
        caps = descriptor.resource_caps if descriptor else {}
        wall += int(caps.get("wall_time_sec", 0))
        memory += int(caps.get("memory_mb", 0))
        disk += int(caps.get("disk_mb", 0))
        attempts += node.retry_policy.max_attempts
    return BudgetEstimate(wall_time_sec=wall, memory_mb=memory, disk_mb=disk, attempts=attempts)


def _check_permission(
    base: PermissionEnvelope, candidate: PermissionEnvelope
) -> tuple[PatchFinding, ...]:
    """权限不扩大：四项全比，任一扩大即 finding（不自动批准，转人工）。"""
    findings: list[PatchFinding] = []
    if candidate.max_side_effect > base.max_side_effect:
        findings.append(PatchFinding(
            PatchViolation.PERMISSION_EXPANSION, (),
            f"side_effect 等级 {base.max_side_effect}→{candidate.max_side_effect}"
            "（PURE_FUNCTION<PURE_ARTIFACT<SIDE_EFFECT）",
        ))
    if candidate.network_allowed and not base.network_allowed:
        findings.append(PatchFinding(PatchViolation.PERMISSION_EXPANSION, (),
                                     "网络访问从禁止变为允许（T0 断网）"))
    new_templates = candidate.templates - base.templates
    if new_templates:
        findings.append(PatchFinding(
            PatchViolation.PERMISSION_EXPANSION, (),
            f"引入了基线未使用的新模板：{sorted(new_templates)}",
        ))
    if candidate.write_outputs - base.write_outputs:
        findings.append(PatchFinding(
            PatchViolation.PERMISSION_EXPANSION, (),
            f"写面扩大：新增产物 {sorted(candidate.write_outputs - base.write_outputs)}",
        ))
    for name, b, c in (
        ("wall_time_sec", base.max_wall_time_sec, candidate.max_wall_time_sec),
        ("max_memory_mb", base.max_memory_mb, candidate.max_memory_mb),
        ("max_disk_mb", base.max_disk_mb, candidate.max_disk_mb),
    ):
        if c > b:
            findings.append(PatchFinding(PatchViolation.PERMISSION_EXPANSION, (),
                                         f"{name} 上限提高 {b}→{c}"))
    return tuple(findings)


def _check_executed_nodes(
    base: GraphContent, candidate: GraphContent, ctx: PatchContext
) -> tuple[PatchFinding, ...]:
    """已执行节点不可静默重写。

    “已执行”的判定（任一成立即算）：
      - `attempt_seq > 0`；
      - 状态不在 `{PLANNED, READY}`（READY 尚未真正跑过，允许改，但会触发批准）；
      - 已有任何证据（`node_has_evidence`）。

    对已执行节点，禁止：改参数/模板/必检项/依赖、删除节点。
    允许：给它加**下游**新节点（不动它的输入与语义）。
    """
    findings: list[PatchFinding] = []
    base_nodes = {n.node_id: n for n in base.nodes}
    cand_nodes = {n.node_id: n for n in candidate.nodes}

    for node_id, node in base_nodes.items():
        executed = (
            ctx.node_attempt_seq.get(node_id, 0) > 0
            or ctx.node_has_evidence.get(node_id, False)
            or ctx.node_states.get(node_id, "PLANNED") not in ("PLANNED", "READY")
        )
        if not executed:
            continue
        if node_id not in cand_nodes:
            findings.append(PatchFinding(
                PatchViolation.EXECUTED_NODE_REWRITE, (node_id,), "已执行节点被删除"))
            continue
        new = cand_nodes[node_id]
        if new.parameters_hash != node.parameters_hash:
            findings.append(PatchFinding(
                PatchViolation.EXECUTED_NODE_REWRITE, (node_id,), "已执行节点参数被改写"))
        if new.template_id != node.template_id:
            findings.append(PatchFinding(
                PatchViolation.EXECUTED_NODE_REWRITE, (node_id,), "已执行节点模板被替换"))
        if tuple(new.required_checks) != tuple(node.required_checks):
            findings.append(PatchFinding(
                PatchViolation.EXECUTED_NODE_REWRITE, (node_id,), "已执行节点必检项被改写"))
        if set(new.depends_on) != set(node.depends_on):
            findings.append(PatchFinding(
                PatchViolation.EXECUTED_NODE_REWRITE, (node_id,), "已执行节点依赖被改写"))

    # 必检项被删除（即使节点未执行）也要显式批准，不得静默
    for node_id, node in cand_nodes.items():
        if node_id not in base_nodes:
            continue
        removed = set(base_nodes[node_id].required_checks) - set(node.required_checks)
        if removed:
            findings.append(PatchFinding(
                PatchViolation.REQUIRED_CHECKS_REMOVED, (node_id,),
                f"删除必检项 {sorted(removed)}（§8.9 不得静默取消）",
            ))
    return tuple(findings)


# ---------------------------------------------------------------------------
# 7. 权限包络计算
# ---------------------------------------------------------------------------
def _envelope(content: GraphContent, ctx: PatchContext) -> PermissionEnvelope:
    max_rank = 0
    templates: set[str] = set()
    outputs: set[str] = set()
    wall = memory = disk = 0
    for node in content.nodes:
        descriptor = ctx.catalog.node_template(node.template_id)
        templates.add(node.template_id)
        rank = PERMISSION_RANK.get(node.side_effect_class, PERMISSION_RANK["SIDE_EFFECT"])
        max_rank = max(max_rank, rank)
        outputs.update(ref[len("artifact://"):] for ref in node.input_refs)
        caps = descriptor.resource_caps if descriptor else {}
        wall = max(wall, int(caps.get("wall_time_sec", 0)))
        memory = max(memory, int(caps.get("memory_mb", 0)))
        disk = max(disk, int(caps.get("disk_mb", 0)))
    return PermissionEnvelope(
        max_side_effect=max_rank,
        templates=frozenset(templates),
        network_allowed=False,   # 模板未声明网络能力；T0 恒 False
        write_outputs=frozenset(outputs),
        max_wall_time_sec=wall,
        max_memory_mb=memory,
        max_disk_mb=disk,
    )


# ---------------------------------------------------------------------------
# 8. 决策
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PatchDecisionReport:
    """评估结果。

    `decision` 是四值枚举；`findings` 一定包含触发决策的原因（ACCEPT 时为空）。
    `requires_approval=True` 且 `decision=APPROVAL_REQUIRED` 时，调用方**不得**登记图。
    """

    decision: PatchDecision
    findings: tuple[PatchFinding, ...]
    candidate: GraphContent | None
    next_graph_version: int
    requires_approval: bool
    approval_ticket: ApprovalTicket | None
    audit_ok: bool

    def error_code(self) -> str | None:
        hard = [f for f in self.findings if f.hard_reject]
        return hard[0].error_code if hard else None


APPROVAL_THRESHOLD_RULES: Final[tuple[str, ...]] = (
    "影响已验证结果：补丁触及任何 VERIFIED/VERIFYING 节点，或其任一前驱/后继在 verified_nodes 中。",
    "扩大权限：side_effect 等级升高、启用网络、引入新模板、扩大写面、提高资源上限。",
    "删除必检项：任何 required_checks 被移除（§8.9 不得静默取消必检项或 L3）。",
    "T0 无批准通道时，以上三类一律 APPROVAL_REQUIRED（不登记、不失效、不重跑）。",
)


def evaluate_patch(patch: GraphPatch, *, ctx: PatchContext) -> PatchDecisionReport:
    """评估一次图变更，返回决策。

    步骤：
      1. 基础一致性：补丁基线版本 = 当前版本；任务必须处于 PLANNING；
      2. 应用补丁 → 候选图（纯函数）；
      3. 跑六项校验，收集 findings；
      4. 判断批准阈值（影响已验证结果 / 扩大权限 / 删除必检项）；
      5. 审计可用性：不可用即 REJECT（fail-closed）；
      6. 决策：有硬拒绝 → REJECT；需要批准且有票 → ACCEPT_WITH_APPROVAL；
         需要批准但无票 → APPROVAL_REQUIRED；否则 ACCEPT。

    副作用：**无**。本函数不登记图、不写审计（审计由调用方用返回的报告去写）。
    """
    findings: list[PatchFinding] = []

    # 1) 基础一致性
    if patch.base_graph_version != ctx.current_graph_version:
        findings.append(PatchFinding(
            PatchViolation.BASE_VERSION_STALE, (),
            f"patch.base={patch.base_graph_version} 当前={ctx.current_graph_version}",
        ))
    if ctx.task_state != "PLANNING":
        findings.append(PatchFinding(
            PatchViolation.PLAN_NOT_ALLOWED, (),
            f"任务状态 {ctx.task_state}：T0 只在 PLANNING 接受 patch",
        ))

    if any(f.hard_reject for f in findings):
        return _report(PatchDecision.REJECT, findings, None, ctx, requires_approval=False)

    # 2) 候选图
    try:
        candidate = apply_patch(ctx.base, patch.ops)
    except _PatchError as exc:
        findings.append(PatchFinding(exc.violation, exc.nodes, exc.detail))
        return _report(PatchDecision.REJECT, findings, None, ctx, requires_approval=False)

    # 3) 六项校验
    findings.extend(_check_acyclic(candidate))
    findings.extend(_check_whitelist(candidate, ctx))
    findings.extend(_check_limits(candidate, ctx))
    findings.extend(_check_budget(candidate, ctx))
    base_env = _envelope(ctx.base, ctx)
    cand_env = _envelope(candidate, ctx)
    findings.extend(_check_permission(base_env, cand_env))
    findings.extend(_check_executed_nodes(ctx.base, candidate, ctx))

    # 4) 批准阈值
    approval_findings = [f for f in findings
                         if f.violation in (PatchViolation.PERMISSION_EXPANSION,
                                            PatchViolation.REQUIRED_CHECKS_REMOVED)]
    if _affects_verified(patch, ctx):
        approval_findings.append(PatchFinding(
            PatchViolation.APPROVAL_REQUIRED, _touched(patch),
            "影响已验证结果：变更涉及已验证节点或其上下游",
        ))
    requires_approval = bool(approval_findings)
    findings.extend(f for f in approval_findings if f not in findings)

    # 5) 审计
    audit_ok = ctx.audit_available
    if not audit_ok:
        findings.append(PatchFinding(PatchViolation.AUDIT_UNAVAILABLE, (),
                                     "审计写者不可用 → 拒绝（不得无审计地改图）"))
        return _report(PatchDecision.REJECT, findings, candidate, ctx, requires_approval)

    # 6) 决策
    if any(f.hard_reject for f in findings):
        return _report(PatchDecision.REJECT, findings, candidate, ctx, requires_approval)

    if requires_approval:
        ticket = ctx.approval
        if ticket is None or ticket.patch_hash != patch.patch_hash:
            findings.append(PatchFinding(PatchViolation.APPROVAL_REQUIRED, _touched(patch),
                                         "需要人工批准，但未提供与 patch_hash 绑定的批准票"))
            return _report(PatchDecision.APPROVAL_REQUIRED, findings, candidate, ctx, True)
        return _report(PatchDecision.ACCEPT_WITH_APPROVAL, findings, candidate, ctx, True,
                       ticket=ticket)

    return _report(PatchDecision.ACCEPT, findings, candidate, ctx, requires_approval=False)


def _report(
    decision: PatchDecision,
    findings: Sequence[PatchFinding],
    candidate: GraphContent | None,
    ctx: PatchContext,
    requires_approval: bool,
    *,
    ticket: ApprovalTicket | None = None,
) -> PatchDecisionReport:
    return PatchDecisionReport(
        decision=decision,
        findings=tuple(findings),
        candidate=candidate,
        next_graph_version=ctx.current_graph_version + 1,
        requires_approval=requires_approval,
        approval_ticket=ticket,
        audit_ok=ctx.audit_available,
    )


def _touched(patch: GraphPatch) -> tuple[str, ...]:
    return tuple(dict.fromkeys(op.node_id for op in patch.ops))


def _affects_verified(patch: GraphPatch, ctx: PatchContext) -> bool:
    """补丁是否可能影响已验证结果。

    判据（保守，宁可多批准一次）：
      - 任一 op 的目标节点在 `verified_nodes` 中；
      - 任一目标节点的**任一前驱或后继**在 `verified_nodes` 中（改上游输入/改下游消费）。
    """
    if not ctx.verified_nodes:
        return False
    succ: dict[str, set[str]] = {n.node_id: set() for n in ctx.base.nodes}
    for src, dst in ctx.base.edges:
        succ.setdefault(src, set()).add(dst)
    for node in _touched(patch):
        if node in ctx.verified_nodes:
            return True
        if ctx.base.dependencies().get(node, ()) and set(ctx.base.dependencies()[node]) & ctx.verified_nodes:
            return True
        if succ.get(node, set()) & ctx.verified_nodes:
            return True
    return False


# ---------------------------------------------------------------------------
# 9. 自检
# ---------------------------------------------------------------------------
def assert_patch_approval_contract() -> list[str]:
    """自检：六项校验齐全；硬拒绝必须有错误码；需要批准时不得 ACCEPT。"""
    problems: list[str] = []
    if len(PATCH_CHECKS) != 6:
        problems.append(f"策划书 §8.9 要求六项校验，当前 {len(PATCH_CHECKS)} 项")
    allowed = {"STATE_TRANSITION_DENIED", "TOOL_NOT_ALLOWLISTED", "SCHEMA_INVALID",
               "RESOURCE_BUDGET_EXCEEDED"}
    for violation, spec in PATCH_VIOLATION_SPECS.items():
        if spec.error_code not in allowed:
            problems.append(f"{violation} 使用注册表外错误码 {spec.error_code}")
    for violation in (PatchViolation.PERMISSION_EXPANSION,
                      PatchViolation.REQUIRED_CHECKS_REMOVED):
        if not PATCH_VIOLATION_SPECS[violation].approval_required:
            problems.append(f"{violation} 必须要求人工批准")
        if PATCH_VIOLATION_SPECS[violation].hard_reject:
            problems.append(f"{violation} 不应硬拒绝（应转人工批准）")
    return problems