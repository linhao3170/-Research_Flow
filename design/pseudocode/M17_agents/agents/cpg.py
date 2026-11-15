"""MODULE：M17 · agents/cpg.py — 协作证据图（CPG）五项指标（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-012（role-off/CPG 对照）｜策划书 §10.3、§10.4
FR+依赖：FR-012；依赖 messages.py（九类消息）、contracts.py（RoleId）；只读 M07 证据索引（经端口取生产者角色）
不变量+错误码：五个指标都报“分子/分母/值”，分母固定且不可通过丢样本变小；无效引用进入引用有效率分母；
              CPG 只证信息流与协作结构，**不**进入 Gate/Verifier 判定，不作为“做没做”的完成证据。
              本文件不抛状态类错误；输入不完整抛 ValueError。
写入者：无。只读消息与证据索引，不写证据、不改状态、不给结论。
状态：伪代码；不聚合真实数据、不出报告。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Protocol, Sequence

from .contracts import RoleId
from .messages import (
    AgentMessage,
    Escalate,
    EvidenceRef,
    Finding,
    MessageType,
    PlanProposal,
    RecoveryProposal,
    VerifyRequest,
)

__all__ = [
    "CONTRIBUTION_MESSAGES",
    "CPG_IS_NOT_QUALITY",
    "CPGEdge",
    "CPGGraph",
    "CPGMetrics",
    "EvidenceProvenancePort",
    "Ratio",
    "RejectedReference",
    "RoleContribution",
    "build_cpg",
    "compute_metrics",
    "assert_denominators",
    "assert_invalid_refs_counted",
    "assert_not_quality_claim",
]

CPG_IS_NOT_QUALITY: Final[str] = (
    "CPG 只证明信息流与协作结构，不直接代表语义质量；"
    "必须结合任务成功率、错误放行、恢复成本等主指标解释（策划书 §10.3）。"
)

# 计入“角色产出”的消息类型：可被单独归因于某角色的一次实质产出。
# 不含 PROGRESS（仅展示）、EVIDENCE_REF（只是引用）、ESCALATE（可刷量）、TASK_ASSIGN/VERDICT（非角色产出）。
CONTRIBUTION_MESSAGES: Final[frozenset[MessageType]] = frozenset(
    {
        MessageType.FINDING,
        MessageType.PLAN_PROPOSAL,
        MessageType.RECOVERY_PROPOSAL,
        MessageType.VERIFY_REQUEST,
    }
)

# 固定分母：6 个角色两两有向 = 6 × 5 = 30。不得按“本任务参与角色数”缩小。
FIXED_PAIR_DENOMINATOR: Final[int] = 30
ROLE_COUNT: Final[int] = 6


# ---------------------------------------------------------------------------
# 0. 输入
# ---------------------------------------------------------------------------
class EvidenceProvenancePort(Protocol):
    """只读：一条证据由哪个角色产生（E0 claim 的 producer_role）。查不到返回 None。"""

    def role_of(self, evidence_id: str) -> RoleId | None: ...


@dataclass(frozen=True, slots=True)
class RejectedReference:
    """一条被拒绝的引用（来自 MessageValidator 的违规流）。必须计入有效性分母。"""

    sender_role: RoleId
    evidence_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.reason:
            raise ValueError("CPG-REJECT: evidence_id 与 reason 不得为空")


@dataclass(frozen=True, slots=True)
class CPGEdge:
    """CPG 的一条边：角色 A 引用角色 B 产生的证据。"""

    sender_role: RoleId
    producer_role: RoleId | None
    evidence_id: str
    message_type: MessageType
    valid: bool

    @property
    def cross_role(self) -> bool:
        """跨角色 = 有明确生产者且不是自己。无效边不算跨角色。"""
        return self.valid and self.producer_role is not None and self.producer_role is not self.sender_role


@dataclass(frozen=True, slots=True)
class RoleContribution:
    """一个角色的产出计数与占比；占比分母是全部角色的产出总数。"""

    role: RoleId
    outputs: int
    share: float

    def __post_init__(self) -> None:
        if self.outputs < 0:
            raise ValueError("CPG-ROLE: outputs 不得为负")
        if not 0.0 <= self.share <= 1.0:
            raise ValueError("CPG-ROLE: share 必须在 [0,1]")


@dataclass(frozen=True, slots=True)
class Ratio:
    """一个比例指标。分母为 0 时 `value` 为 None（不得报 0.0 冒充“0%”）。"""

    numerator: int
    denominator: int
    value: float | None

    def __post_init__(self) -> None:
        if self.denominator < 0:
            raise ValueError("CPG-RATIO: 分母不得为负")
        if self.numerator < 0:
            raise ValueError("CPG-RATIO: 分子不得为负")
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if expected is None and self.value is not None:
            raise ValueError("CPG-RATIO: 分母为 0 时 value 必须为 None")
        if expected is not None and (self.value is None or abs(expected - self.value) > 1e-12):
            raise ValueError("CPG-RATIO: value 与分子/分母不一致")

    def as_dict(self) -> dict[str, object]:
        return {"numerator": self.numerator, "denominator": self.denominator, "value": self.value}


@dataclass(frozen=True, slots=True)
class CPGGraph:
    """一次任务/批次的 CPG。只含边与拒绝记录，不含任务结果。"""

    task_id: str
    messages: tuple[AgentMessage, ...]
    edges: tuple[CPGEdge, ...]
    rejected: tuple[RejectedReference, ...]
    assigned_roles: frozenset[RoleId]

    def __post_init__(self) -> None:
        if not self.task_id.startswith("task_"):
            raise ValueError("CPG-GRAPH: task_id 形态非法")
        if not self.assigned_roles <= set(RoleId):
            raise ValueError("CPG-GRAPH: assigned_roles 含未注册角色")


# ---------------------------------------------------------------------------
# 1. 建图
# ---------------------------------------------------------------------------
def _refs_of(message: AgentMessage) -> tuple[str, ...]:
    """取一条消息引用的 evidence_id；只有三类消息带引用。"""
    payload = message.payload
    if isinstance(payload, EvidenceRef):
        return (payload.evidence_id,)
    if isinstance(payload, Finding):
        return payload.evidence_ids
    if isinstance(payload, Escalate):
        return payload.blocking_evidence_ids
    return ()


def build_cpg(
    *,
    task_id: str,
    messages: Sequence[AgentMessage],
    provenance: EvidenceProvenancePort,
    rejected: Sequence[RejectedReference] = (),
    assigned_roles: frozenset[RoleId] = frozenset(),
) -> CPGGraph:
    """从已通过校验的消息建图。

    规则：
      1. 只统计六角色发出的消息；非角色端点（Scheduler/Verifier）不进入 CPG；
      2. 每条引用都尝试取生产者角色；取不到即 `valid=False`（该边只进有效性分母）；
      3. 自引用合法但不算跨角色；
      4. 拒绝记录原样并入，**不得**在计算前过滤（否则有效率会被抬高）。
    """
    edges: list[CPGEdge] = []
    role_messages: list[AgentMessage] = []
    for message in messages:
        if message.meta.sender.value not in {role.value for role in RoleId}:
            continue
        role_messages.append(message)
        sender_role = RoleId(message.meta.sender.value)
        for evidence_id in _refs_of(message):
            producer = provenance.role_of(evidence_id)
            edges.append(
                CPGEdge(
                    sender_role=sender_role,
                    producer_role=producer,
                    evidence_id=evidence_id,
                    message_type=message.message_type,
                    valid=producer is not None,
                )
            )
    return CPGGraph(
        task_id=task_id,
        messages=tuple(role_messages),
        edges=tuple(edges),
        rejected=tuple(rejected),
        assigned_roles=frozenset(assigned_roles),
    )


# ---------------------------------------------------------------------------
# 2. 五项指标
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CPGMetrics:
    """CPG 的五个主指标 + 必要的原始计数。每个比例都带分子/分母。"""

    task_id: str
    cross_role_reference_rate: Ratio
    collaboration_density_fixed: Ratio
    collaboration_density_active: Ratio
    role_contribution_entropy_bits: float
    role_contribution_entropy_normalized: float
    silent_role_count: int
    idle_role_count: int
    silent_roles: tuple[RoleId, ...]
    reference_validity_rate: Ratio
    contributions: tuple[RoleContribution, ...]
    valid_reference_count: int
    rejected_reference_count: int
    cross_role_edge_count: int
    active_role_count: int

    def __post_init__(self) -> None:
        if not 0 <= self.silent_role_count <= ROLE_COUNT:
            raise ValueError("CPG-METRICS: silent_role_count 越界")
        if not 0.0 <= self.role_contribution_entropy_normalized <= 1.0:
            raise ValueError("CPG-METRICS: 归一化熵必须在 [0,1]")
        if abs(sum(item.share for item in self.contributions) - 1.0) > 1e-9 and any(
            item.outputs for item in self.contributions
        ):
            raise ValueError("CPG-METRICS: 角色占比之和必须为 1")

    def as_dict(self) -> dict[str, object]:
        """报告用结构；不含“通过/未通过”语义。"""
        return {
            "task_id": self.task_id,
            "cross_role_reference_rate": self.cross_role_reference_rate.as_dict(),
            "collaboration_density_fixed": self.collaboration_density_fixed.as_dict(),
            "collaboration_density_active": self.collaboration_density_active.as_dict(),
            "role_contribution_entropy_bits": self.role_contribution_entropy_bits,
            "role_contribution_entropy_normalized": self.role_contribution_entropy_normalized,
            "silent_role_count": self.silent_role_count,
            "idle_role_count": self.idle_role_count,
            "silent_roles": [role.value for role in self.silent_roles],
            "reference_validity_rate": self.reference_validity_rate.as_dict(),
            "valid_reference_count": self.valid_reference_count,
            "rejected_reference_count": self.rejected_reference_count,
            "cross_role_edge_count": self.cross_role_edge_count,
            "active_role_count": self.active_role_count,
            "caveat": CPG_IS_NOT_QUALITY,
        }


def _ratio(numerator: int, denominator: int) -> Ratio:
    return Ratio(numerator=numerator, denominator=denominator, value=None if denominator == 0 else numerator / denominator)


def compute_metrics(graph: CPGGraph) -> CPGMetrics:
    """按 §10.3 计算五个指标。

    定义（写死，测试按此断言）：
      - 跨角色引用率 = 有效跨角色边 / 有效边（自引用在内、无效边不在内）；
      - 协作密度（固定分母） = 出现有效边的有向角色对数 / 30；
      - 协作密度（活跃分母） = 出现有效边的有向角色对数 / k(k−1)，k = 有产出的角色数；
      - 角色贡献熵 = −Σ p_r log2 p_r（p_r = 该角色实质产出 / 全部实质产出），并除以 log2(6)；
      - 无产出角色数 = 被派发但实质产出为 0 的角色数（未被派发的另计 idle）；
      - 引用有效率 = 有效引用 / (有效引用 + 被拒引用)。
    """
    valid_edges = [edge for edge in graph.edges if edge.valid]
    cross_edges = [edge for edge in valid_edges if edge.cross_role]

    valid_pairs = {(edge.sender_role, edge.producer_role) for edge in cross_edges if edge.producer_role is not None}
    pair_count = len(valid_pairs)

    counts: dict[RoleId, int] = {role: 0 for role in RoleId}
    for message in graph.messages:
        if message.message_type in CONTRIBUTION_MESSAGES:
            counts[RoleId(message.meta.sender.value)] += 1
    total_outputs = sum(counts.values())
    active_roles = tuple(role for role in RoleId if counts[role] > 0 or role in graph.assigned_roles)
    k = len(active_roles)
    active_denominator = k * (k - 1) if k >= 2 else 0

    contributions = tuple(
        RoleContribution(
            role=role,
            outputs=counts[role],
            share=(counts[role] / total_outputs) if total_outputs else 0.0,
        )
        for role in RoleId
    )

    if total_outputs:
        entropy_bits = -sum(
            (counts[role] / total_outputs) * math.log2(counts[role] / total_outputs)
            for role in RoleId
            if counts[role] > 0
        )
        entropy_normalized = entropy_bits / math.log2(ROLE_COUNT)
    else:
        entropy_bits = 0.0
        entropy_normalized = 0.0

    silent_roles = tuple(role for role in RoleId if role in graph.assigned_roles and counts[role] == 0)
    idle_roles = tuple(role for role in RoleId if role not in graph.assigned_roles and counts[role] == 0)

    validity_denominator = len(graph.edges) + len(graph.rejected)
    return CPGMetrics(
        task_id=graph.task_id,
        cross_role_reference_rate=_ratio(len(cross_edges), len(valid_edges)),
        collaboration_density_fixed=_ratio(pair_count, FIXED_PAIR_DENOMINATOR),
        collaboration_density_active=_ratio(pair_count, active_denominator),
        role_contribution_entropy_bits=entropy_bits,
        role_contribution_entropy_normalized=entropy_normalized,
        silent_role_count=len(silent_roles),
        idle_role_count=len(idle_roles),
        silent_roles=silent_roles,
        reference_validity_rate=_ratio(len(valid_edges), validity_denominator),
        contributions=contributions,
        valid_reference_count=len(valid_edges),
        rejected_reference_count=len(graph.rejected),
        cross_role_edge_count=len(cross_edges),
        active_role_count=k,
    )


# ---------------------------------------------------------------------------
# 3. 静态守卫
# ---------------------------------------------------------------------------
def assert_denominators() -> tuple[str, ...]:
    """分母写死：固定 30、熵除 log2(6)、有效性分母含被拒引用。"""
    problems: list[str] = []
    if FIXED_PAIR_DENOMINATOR != ROLE_COUNT * (ROLE_COUNT - 1):
        problems.append("固定配对分母与 6×5 不一致")
    if abs(math.log2(ROLE_COUNT) - 2.584962500721156) > 1e-9:
        problems.append("log2(6) 常量异常")
    if not CONTRIBUTION_MESSAGES:
        problems.append("贡献消息集合为空")
    if MessageType.PROGRESS in CONTRIBUTION_MESSAGES:
        problems.append("PROGRESS 不得计入角色产出")
    if MessageType.ESCALATE in CONTRIBUTION_MESSAGES:
        problems.append("ESCALATE 不得计入角色产出（可被刷量）")
    return tuple(problems)


def assert_invalid_refs_counted() -> tuple[str, ...]:
    """被拒引用必须进入有效率分母；有效边不得被静默丢弃。"""
    problems: list[str] = []
    graph = CPGGraph(
        task_id="task_00000000-0000-0000-0000-000000000000",
        messages=(),
        edges=(),
        rejected=(
            RejectedReference(sender_role=RoleId.DATA, evidence_id="ev_bad", reason="EVIDENCE_ID_NOT_FOUND"),
        ),
        assigned_roles=frozenset({RoleId.DATA}),
    )
    metrics = compute_metrics(graph)
    if metrics.reference_validity_rate.denominator != 1:
        problems.append("被拒引用未进入有效性分母")
    if metrics.reference_validity_rate.value != 0.0:
        problems.append("全是无效引用时有效率应为 0.0")
    if metrics.silent_role_count != 1:
        problems.append("被派发但无产出应计为 silent=1")
    return tuple(problems)


def assert_not_quality_claim() -> tuple[str, ...]:
    """CPG 不得成为质量/完成度判定输入。"""
    problems: list[str] = []
    forbidden = ("pass", "verified", "verdict", "gate", "certificate")
    for name in __all__:
        lowered = name.lower()
        for token in forbidden:
            if token in lowered:
                problems.append(f"CPG 导出了判定相关符号 {name}")
    fields = getattr(CPGMetrics, "__dataclass_fields__", {})
    for token in forbidden:
        if token in fields:
            problems.append(f"CPGMetrics 含判定字段 {token}")
    if "语义质量" not in CPG_IS_NOT_QUALITY:
        problems.append("缺少“CPG 不代表语义质量”的边界声明")
    return tuple(problems)