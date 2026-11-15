"""MODULE：M17 · agents/messages.py — 9 类消息的 Schema、方向与证据引用校验（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-012（消息 Schema、角色冒用、消息重放）｜策划书 §6.3 TABLE 27、§10.2、附录 E.3/E.4
FR+依赖：FR-012；依赖 contracts.py（六角色规格/身份/证据可见级别）、M01 错误码、M07 只读证据查找端口
不变量+错误码：消息类型恰好 9 类；方向表逐条落地；EVIDENCE_REF / FINDING / ESCALATE 引用的 evidence_id 必须存在，
              否则拒绝并记协议违规；E0/E1 不能借消息变成 E2；Agent 永远发不出 VERDICT。
              SCHEMA_INVALID(422) / EVIDENCE_REFERENCE_NOT_FOUND(422) / AUDIT_WRITE_FAILED(503)
写入者：无。本文件只构造/校验消息；协议违规经 ViolationSinkPort 由 Collector/审计侧追加，本文件不落库。
状态：伪代码；不发送、不持久化、不触发状态迁移。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, fields
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, Mapping, Protocol

from .contracts import (
    AGENT_MESSAGE_NAMES,
    EVIDENCE_LEVELS,
    ROLE_CONTRACT_VERSION,
    ROLE_SPECS,
    RoleId,
)

__all__ = [
    "AGENT_ENDPOINTS",
    "DIRECTIONS",
    "EVIDENCE_KINDS",
    "AgentMessage",
    "Direction",
    "Endpoint",
    "Escalate",
    "EscalationNeed",
    "EscalationReason",
    "EvidenceLookupPort",
    "EvidenceRef",
    "ExpectedCost",
    "Finding",
    "FindingItem",
    "FindingSeverity",
    "GraphOp",
    "GraphPatch",
    "MessageMeta",
    "MessageRejected",
    "MessageType",
    "MessageValidator",
    "PatchOpKind",
    "PlanProposal",
    "Progress",
    "ProgressStage",
    "ProtocolViolation",
    "RecoveryPlanRef",
    "RecoveryProposal",
    "ReplayGuard",
    "ReplayVerdict",
    "TaskAssign",
    "ValidatedMessage",
    "Verdict",
    "VerifyRequest",
    "ViolationSinkPort",
    "assert_direction_table",
    "assert_exactly_nine",
    "assert_no_agent_verdict",
    "message_digest",
    "parse_message",
    "parse_payload",
    "payload_type",
    "to_mapping",
]

# 附录 E.3 冻结的 7 个 EvidenceRecord.kind（不得新增）。
EVIDENCE_KINDS: Final[tuple[str, ...]] = (
    "agent_claim",
    "tool_invocation",
    "harness_trace",
    "executor_launch",
    "executor_process_exit",
    "artifact_observed",
    "verifier_recheck",
)

EVIDENCE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^ev_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
REPORT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^report_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
NODE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
CHECK_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
HASH64_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# 0. 端点与消息类型
# ---------------------------------------------------------------------------
class Endpoint(StrEnum):
    """消息端点。角色端点与 RoleId 同值，便于反向解析；Scheduler/Verifier/StateMachine 不是 LLM 角色。"""

    SCHEDULER = "scheduler"
    VERIFIER = "verifier"
    STATE_MACHINE = "state_machine"
    PLANNER = "planner"
    DATA = "data"
    EXPERIMENT = "experiment"
    ANALYSIS = "analysis"
    RECOVERY = "recovery"
    VERIFICATION = "verification"


AGENT_ENDPOINTS: Final[frozenset[Endpoint]] = frozenset(
    {
        Endpoint.PLANNER,
        Endpoint.DATA,
        Endpoint.EXPERIMENT,
        Endpoint.ANALYSIS,
        Endpoint.RECOVERY,
        Endpoint.VERIFICATION,
    }
)


class MessageType(StrEnum):
    """策划书 §6.3 的九类消息。**恰好九个**，多一个少一个都失败。"""

    TASK_ASSIGN = "TASK_ASSIGN"
    PROGRESS = "PROGRESS"
    EVIDENCE_REF = "EVIDENCE_REF"
    FINDING = "FINDING"
    PLAN_PROPOSAL = "PLAN_PROPOSAL"
    RECOVERY_PROPOSAL = "RECOVERY_PROPOSAL"
    VERIFY_REQUEST = "VERIFY_REQUEST"
    VERDICT = "VERDICT"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True, slots=True)
class Direction:
    """一条方向约束：谁可发、谁可收、是否只是提案/请求。"""

    message_type: MessageType
    senders: frozenset[Endpoint]
    receivers: frozenset[Endpoint]
    proposal_only: bool
    literal: str  # §6.3 方向列的原文

    def __post_init__(self) -> None:
        if not self.senders or not self.receivers:
            raise ValueError(f"MSG-DIR-EMPTY: {self.message_type} 的发送方/接收方不得为空")
        if self.senders & self.receivers:
            raise ValueError(f"MSG-DIR-SELF: {self.message_type} 的发送方与接收方不得重叠")
        if not self.literal.strip():
            raise ValueError(f"MSG-DIR-LITERAL: {self.message_type} 必须保留 §6.3 方向原文")


DIRECTIONS: Final[Mapping[MessageType, Direction]] = MappingProxyType(
    {
        MessageType.TASK_ASSIGN: Direction(
            MessageType.TASK_ASSIGN, frozenset({Endpoint.SCHEDULER}), AGENT_ENDPOINTS, False, "Scheduler→Agent"
        ),
        MessageType.PROGRESS: Direction(
            MessageType.PROGRESS, AGENT_ENDPOINTS, frozenset({Endpoint.SCHEDULER}), False, "Agent→Scheduler"
        ),
        MessageType.EVIDENCE_REF: Direction(
            MessageType.EVIDENCE_REF, AGENT_ENDPOINTS, frozenset({Endpoint.SCHEDULER}), False, "Agent→Scheduler"
        ),
        MessageType.FINDING: Direction(
            MessageType.FINDING, AGENT_ENDPOINTS, frozenset({Endpoint.SCHEDULER}), False, "Agent→Scheduler"
        ),
        MessageType.PLAN_PROPOSAL: Direction(
            MessageType.PLAN_PROPOSAL, frozenset({Endpoint.PLANNER}), frozenset({Endpoint.SCHEDULER}), True, "Planner→Scheduler"
        ),
        MessageType.RECOVERY_PROPOSAL: Direction(
            MessageType.RECOVERY_PROPOSAL, frozenset({Endpoint.RECOVERY}), frozenset({Endpoint.SCHEDULER}), True, "Recovery→Scheduler"
        ),
        MessageType.VERIFY_REQUEST: Direction(
            MessageType.VERIFY_REQUEST, frozenset({Endpoint.VERIFICATION}), frozenset({Endpoint.VERIFIER}), True, "Verification Agent→Verifier"
        ),
        MessageType.VERDICT: Direction(
            MessageType.VERDICT, frozenset({Endpoint.VERIFIER}), frozenset({Endpoint.STATE_MACHINE}), False, "Verifier→StateMachine"
        ),
        MessageType.ESCALATE: Direction(
            MessageType.ESCALATE,
            AGENT_ENDPOINTS | frozenset({Endpoint.VERIFIER}),
            frozenset({Endpoint.SCHEDULER}),
            False,
            "任意角色→Scheduler",
        ),
    }
)


# ---------------------------------------------------------------------------
# 1. 信封：消息身份与可追溯元数据（非 §6.3 字段，P8 新增，见 OQ-P8-02）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MessageMeta:
    """消息信封。`task_id` 与部分 payload 字段重复，构造期必须相等（见 ValidatedMessage）。"""

    message_id: str
    task_id: str
    sender: Endpoint
    receiver: Endpoint
    sent_at: str          # UTC RFC 3339，`Z` 或 `+00:00`
    correlation_id: str
    contract_version: str

    def __post_init__(self) -> None:
        for name in ("message_id", "task_id", "correlation_id"):
            value = getattr(self, name)
            if not value or any(ch.isspace() for ch in value):
                raise ValueError(f"MSG-META: {name} 不得为空或含空白")
        if not self.task_id.startswith("task_"):
            raise ValueError("MSG-META: task_id 必须是 task_<uuid> 形态")
        if self.contract_version != ROLE_CONTRACT_VERSION:
            raise ValueError(
                f"MSG-META: 未知角色契约版本 {self.contract_version!r}；不得跨版本重放消息"
            )


# ---------------------------------------------------------------------------
# 2. 九类 payload（字段逐条对齐 §6.3「必填字段/规则」列）
# ---------------------------------------------------------------------------
class ProgressStage(StrEnum):
    """PROGRESS 的阶段；仅展示，不参与任何判定。"""

    RECEIVED = "RECEIVED"
    CONTEXT_ASSEMBLED = "CONTEXT_ASSEMBLED"
    MODEL_CALLED = "MODEL_CALLED"
    OUTPUT_VALIDATED = "OUTPUT_VALIDATED"
    PROPOSED = "PROPOSED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"


class FindingSeverity(StrEnum):
    """FINDING 的严重度；不映射到 Node 状态。"""

    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class PatchOpKind(StrEnum):
    """图补丁允许的四种操作。**没有** REMOVE_NODE：已执行节点不得静默删除。"""

    ADD_NODE = "ADD_NODE"
    ADD_EDGE = "ADD_EDGE"
    CHANGE_PARAMS = "CHANGE_PARAMS"
    REMOVE_EDGE = "REMOVE_EDGE"


class EscalationReason(StrEnum):
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    KNOWLEDGE_CONFLICT = "KNOWLEDGE_CONFLICT"
    STALE_KNOWLEDGE = "STALE_KNOWLEDGE"
    ROLE_DISABLED = "ROLE_DISABLED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    PROTOCOL_VIOLATION = "PROTOCOL_VIOLATION"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    HAZARD_SUSPECTED = "HAZARD_SUSPECTED"


class EscalationNeed(StrEnum):
    HUMAN_DECISION = "HUMAN_DECISION"
    MORE_EVIDENCE = "MORE_EVIDENCE"
    MORE_BUDGET = "MORE_BUDGET"
    APPROVED_KNOWLEDGE_VERSION = "APPROVED_KNOWLEDGE_VERSION"
    ROLE_REENABLE = "ROLE_REENABLE"
    CONTRACT_CLARIFICATION = "CONTRACT_CLARIFICATION"


def _require_text(value: str, field_path: str, *, min_len: int = 1) -> None:
    if not isinstance(value, str) or len(value.strip()) < min_len:
        raise ValueError(f"MSG-FIELD: {field_path} 必须是非空字符串（min_len={min_len}）")


@dataclass(frozen=True, slots=True)
class TaskAssign:
    """TASK_ASSIGN：调度器派活。`inputs` 只放引用，不放原始数据。"""

    task_id: str
    node_id: str
    contract_version: str
    inputs: tuple[str, ...]
    limits: Mapping[str, int]

    def __post_init__(self) -> None:
        _require_text(self.task_id, "TaskAssign.task_id")
        if not NODE_ID_PATTERN.fullmatch(self.node_id):
            raise ValueError("MSG-FIELD: TaskAssign.node_id 形态非法")
        if self.contract_version != ROLE_CONTRACT_VERSION:
            raise ValueError("MSG-FIELD: TaskAssign.contract_version 与当前角色契约不一致")
        if not self.inputs:
            raise ValueError("MSG-FIELD: TaskAssign.inputs 至少一项；空输入必须走 ESCALATE")
        for ref in self.inputs:
            if not (ref.startswith("artifact://") or ref.startswith("local://")):
                raise ValueError(f"MSG-FIELD: TaskAssign.inputs 引用形态非法 {ref!r}")
        expected = {"wall_time_sec", "max_workers", "max_memory_mb"}
        if set(self.limits) != expected:
            raise ValueError(f"MSG-FIELD: TaskAssign.limits 必须恰为 {sorted(expected)}")
        if self.limits["wall_time_sec"] <= 0 or self.limits["max_memory_mb"] <= 0:
            raise ValueError("MSG-FIELD: TaskAssign.limits 的时间/内存必须 > 0")
        if self.limits["max_workers"] not in (1, 2):
            raise ValueError("MSG-FIELD: TaskAssign.limits.max_workers 只允许 1 或 2")


@dataclass(frozen=True, slots=True)
class Progress:
    """PROGRESS：只展示。`AFFECTS_STATE=False` 是硬声明。"""

    AFFECTS_STATE: ClassVar[bool] = False

    node_id: str
    stage: ProgressStage
    percent: int

    def __post_init__(self) -> None:
        if not NODE_ID_PATTERN.fullmatch(self.node_id):
            raise ValueError("MSG-FIELD: Progress.node_id 形态非法")
        if not isinstance(self.percent, int) or isinstance(self.percent, bool):
            raise ValueError("MSG-FIELD: Progress.percent 必须是整数百分比")
        if not 0 <= self.percent <= 100:
            raise ValueError("MSG-FIELD: Progress.percent 必须在 [0,100]")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """EVIDENCE_REF：引用一条已存在证据。`kind` 必须与该记录一致。"""

    evidence_id: str
    kind: str

    def __post_init__(self) -> None:
        if not EVIDENCE_ID_PATTERN.fullmatch(self.evidence_id):
            raise ValueError("MSG-FIELD: EvidenceRef.evidence_id 形态非法")
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(f"MSG-FIELD: EvidenceRef.kind 不在冻结的 7 类内：{self.kind!r}")


@dataclass(frozen=True, slots=True)
class FindingItem:
    """一条机器可读发现。`code` 供统计，`statement` 供人读。"""

    code: str
    statement: str
    severity: FindingSeverity

    def __post_init__(self) -> None:
        if not CHECK_ID_PATTERN.fullmatch(self.code):
            raise ValueError("MSG-FIELD: FindingItem.code 必须是小写点分外的标识符")
        _require_text(self.statement, "FindingItem.statement")


@dataclass(frozen=True, slots=True)
class Finding:
    """FINDING：带证据的发现。**必须**至少引用一条已存在证据（DEC-M17-04）。"""

    node_id: str
    findings: tuple[FindingItem, ...]
    confidence: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not NODE_ID_PATTERN.fullmatch(self.node_id):
            raise ValueError("MSG-FIELD: Finding.node_id 形态非法")
        if not self.findings:
            raise ValueError("MSG-FIELD: Finding.findings 不得为空；没有发现就不要发消息")
        if len({item.code for item in self.findings}) != len(self.findings):
            raise ValueError("MSG-FIELD: Finding.findings 的 code 不得重复")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("MSG-FIELD: Finding.confidence 必须是数字")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("MSG-FIELD: Finding.confidence 必须在 [0,1]")
        if not self.evidence_ids:
            raise ValueError("MSG-FIELD: Finding.evidence_ids 至少一条；无证据的结论请走 ESCALATE")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("MSG-FIELD: Finding.evidence_ids 不得重复")
        for evidence_id in self.evidence_ids:
            if not EVIDENCE_ID_PATTERN.fullmatch(evidence_id):
                raise ValueError(f"MSG-FIELD: Finding.evidence_ids 形态非法 {evidence_id!r}")


@dataclass(frozen=True, slots=True)
class GraphOp:
    """图补丁的一步操作。只描述“想改成什么”，不执行。"""

    op: PatchOpKind
    node_id: str
    template_id: str | None = None
    params_hash: str | None = None
    edge_from: str | None = None
    edge_to: str | None = None

    def __post_init__(self) -> None:
        if not NODE_ID_PATTERN.fullmatch(self.node_id):
            raise ValueError("MSG-FIELD: GraphOp.node_id 形态非法")
        if self.op is PatchOpKind.ADD_NODE:
            if not self.template_id or not self.template_id.strip():
                raise ValueError("MSG-FIELD: ADD_NODE 必须给 template_id")
            if self.edge_from or self.edge_to:
                raise ValueError("MSG-FIELD: ADD_NODE 不得带边字段")
        elif self.op is PatchOpKind.ADD_EDGE:
            if not self.edge_from or not self.edge_to:
                raise ValueError("MSG-FIELD: ADD_EDGE 必须给 edge_from/edge_to")
            if self.template_id or self.params_hash:
                raise ValueError("MSG-FIELD: ADD_EDGE 不得带节点字段")
        elif self.op is PatchOpKind.CHANGE_PARAMS:
            if not self.params_hash or not HASH64_PATTERN.fullmatch(self.params_hash):
                raise ValueError("MSG-FIELD: CHANGE_PARAMS 必须给 64 位 params_hash")
            if self.template_id or self.edge_from or self.edge_to:
                raise ValueError("MSG-FIELD: CHANGE_PARAMS 不得带模板/边字段")
        elif self.op is PatchOpKind.REMOVE_EDGE:
            if not self.edge_from or not self.edge_to:
                raise ValueError("MSG-FIELD: REMOVE_EDGE 必须给 edge_from/edge_to")
            if self.template_id or self.params_hash:
                raise ValueError("MSG-FIELD: REMOVE_EDGE 不得带节点字段")


@dataclass(frozen=True, slots=True)
class GraphPatch:
    """一次图补丁提案。`base_graph_version` 防止把补丁打到旧图上。"""

    base_graph_version: int
    ops: tuple[GraphOp, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.base_graph_version, int) or self.base_graph_version < 1:
            raise ValueError("MSG-FIELD: GraphPatch.base_graph_version 必须 >= 1")
        if not self.ops:
            raise ValueError("MSG-FIELD: GraphPatch.ops 不得为空")
        if len(self.ops) > 32:
            raise ValueError("MSG-FIELD: GraphPatch.ops 超过 32 步；大改走人工")


@dataclass(frozen=True, slots=True)
class ExpectedCost:
    """提案的预期成本；只用于调度比较，不进入签名载荷。"""

    token_budget: int
    wall_time_sec: int
    node_count: int

    def __post_init__(self) -> None:
        for name in ("token_budget", "wall_time_sec", "node_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"MSG-FIELD: ExpectedCost.{name} 必须是整数")
        if self.token_budget < 0 or self.wall_time_sec <= 0 or self.node_count < 1:
            raise ValueError("MSG-FIELD: ExpectedCost 取值越界（token>=0、wall>0、node>=1）")


@dataclass(frozen=True, slots=True)
class PlanProposal:
    """PLAN_PROPOSAL：Planner 的计划提案。只提案，不落图。"""

    graph_patch: GraphPatch
    rationale: str
    expected_cost: ExpectedCost

    def __post_init__(self) -> None:
        _require_text(self.rationale, "PlanProposal.rationale", min_len=10)


@dataclass(frozen=True, slots=True)
class RecoveryPlanRef:
    """恢复计划的引用（只引用已冻结计划，不内联可执行步骤）。"""

    plan_hash: str
    plan_format_version: str
    step_count: int

    def __post_init__(self) -> None:
        if not HASH64_PATTERN.fullmatch(self.plan_hash):
            raise ValueError("MSG-FIELD: RecoveryPlanRef.plan_hash 必须是 64 位小写十六进制")
        if self.plan_format_version != "1.0":
            raise ValueError("MSG-FIELD: RecoveryPlanRef.plan_format_version 未知（T0/T1 只允许 1.0）")
        if self.step_count < 1:
            raise ValueError("MSG-FIELD: RecoveryPlanRef.step_count 必须 >= 1")


@dataclass(frozen=True, slots=True)
class RecoveryProposal:
    """RECOVERY_PROPOSAL：Recovery 的提案。T0/T1 `skip_candidates` 必须为空。"""

    failed_node: str
    affected_nodes: tuple[str, ...]
    plan: RecoveryPlanRef
    skip_candidates: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not NODE_ID_PATTERN.fullmatch(self.failed_node):
            raise ValueError("MSG-FIELD: RecoveryProposal.failed_node 形态非法")
        if not self.affected_nodes:
            raise ValueError("MSG-FIELD: RecoveryProposal.affected_nodes 不得为空")
        if self.failed_node not in self.affected_nodes:
            raise ValueError("MSG-FIELD: RecoveryProposal.affected_nodes 必须包含失败节点")
        if len(set(self.affected_nodes)) != len(self.affected_nodes):
            raise ValueError("MSG-FIELD: RecoveryProposal.affected_nodes 不得重复")
        if self.skip_candidates:
            raise ValueError(
                "MSG-FIELD: T0/T1 禁止 skip_candidates；无 DC 一律保守重跑（策划书 §8.4）"
            )
        _require_text(self.rationale, "RecoveryProposal.rationale", min_len=10)


@dataclass(frozen=True, slots=True)
class VerifyRequest:
    """VERIFY_REQUEST：只请求验证，不含裁决字段。"""

    report_id: str
    checks_requested: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not REPORT_ID_PATTERN.fullmatch(self.report_id):
            raise ValueError("MSG-FIELD: VerifyRequest.report_id 形态非法")
        if not self.checks_requested:
            raise ValueError("MSG-FIELD: VerifyRequest.checks_requested 不得为空")
        if len(set(self.checks_requested)) != len(self.checks_requested):
            raise ValueError("MSG-FIELD: VerifyRequest.checks_requested 不得重复")
        for check in self.checks_requested:
            if not CHECK_ID_PATTERN.fullmatch(check):
                raise ValueError(f"MSG-FIELD: checks_requested 标识符非法 {check!r}")
        _require_text(self.reason, "VerifyRequest.reason", min_len=3)


@dataclass(frozen=True, slots=True)
class Verdict:
    """VERDICT：Verifier → StateMachine。Agent 发不出这类消息（方向表拒绝）。"""

    report_id: str
    final_state: str
    l3_status: str
    gaps: tuple[str, ...]
    certificate_id: str | None = None

    def __post_init__(self) -> None:
        if not REPORT_ID_PATTERN.fullmatch(self.report_id):
            raise ValueError("MSG-FIELD: Verdict.report_id 形态非法")
        if self.final_state not in ("VERIFIED", "PARTIAL", "FAILED", "BLOCKED"):
            raise ValueError("MSG-FIELD: Verdict.final_state 不在冻结四态内")
        if self.l3_status not in ("PASS", "FAIL", "SKIP", "NOT_RUN"):
            raise ValueError("MSG-FIELD: Verdict.l3_status 不在冻结四态内")
        for gap in self.gaps:
            _require_text(gap, "Verdict.gaps[]")
        if self.certificate_id is not None:
            if self.final_state != "VERIFIED":
                raise ValueError("MSG-FIELD: 只有 VERIFIED 才允许带 certificate_id")
            if self.l3_status != "PASS":
                raise ValueError("MSG-FIELD: 带 certificate_id 时 l3_status 必须 PASS")
            if self.gaps:
                raise ValueError("MSG-FIELD: VERIFIED 且签发凭证时 gaps 必须为空")
            if not self.certificate_id.startswith("cert_"):
                raise ValueError("MSG-FIELD: certificate_id 必须是 cert_<uuid> 形态")

    @property
    def signs_certificate(self) -> bool:
        """是否指向一次凭证签发；True 时必须已满足上面的三条互斥约束。"""
        return self.certificate_id is not None


@dataclass(frozen=True, slots=True)
class Escalate:
    """ESCALATE：把“不能自行决定”的事交出去。引用必须存在，需求必须显式。"""

    reason: EscalationReason
    needs: tuple[EscalationNeed, ...]
    blocking_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.needs:
            raise ValueError("MSG-FIELD: Escalate.needs 不得为空；升级必须说清需要什么")
        if len(set(self.needs)) != len(self.needs):
            raise ValueError("MSG-FIELD: Escalate.needs 不得重复")
        for evidence_id in self.blocking_evidence_ids:
            if not EVIDENCE_ID_PATTERN.fullmatch(evidence_id):
                raise ValueError(f"MSG-FIELD: blocking_evidence_ids 形态非法 {evidence_id!r}")


PAYLOAD_TYPES: Final[Mapping[MessageType, type]] = MappingProxyType(
    {
        MessageType.TASK_ASSIGN: TaskAssign,
        MessageType.PROGRESS: Progress,
        MessageType.EVIDENCE_REF: EvidenceRef,
        MessageType.FINDING: Finding,
        MessageType.PLAN_PROPOSAL: PlanProposal,
        MessageType.RECOVERY_PROPOSAL: RecoveryProposal,
        MessageType.VERIFY_REQUEST: VerifyRequest,
        MessageType.VERDICT: Verdict,
        MessageType.ESCALATE: Escalate,
    }
)


def payload_type(message_type: MessageType) -> type:
    """取消息类型对应的 payload 类；不存在即抛。"""
    return PAYLOAD_TYPES[message_type]


def parse_payload(message_type: MessageType, raw: Mapping[str, object]) -> object:
    """公开的 payload 解析入口（gateway 用）；只做结构校验，不做方向/证据存在性检查。"""
    return _parse_payload(message_type, raw)


# ---------------------------------------------------------------------------
# 3. 封装：一条消息 = 信封 + payload
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AgentMessage:
    """一条完整消息。`message_type` 由 payload 类型推导，不接受调用方自报。"""

    meta: MessageMeta
    payload: object

    @property
    def message_type(self) -> MessageType:
        for message_type, payload_cls in PAYLOAD_TYPES.items():
            if isinstance(self.payload, payload_cls):
                return message_type
        raise ValueError("MSG-TYPE: payload 不是九类之一")

    def __post_init__(self) -> None:
        message_type = self.message_type  # 触发类型检查
        direction = DIRECTIONS[message_type]
        if self.meta.sender not in direction.senders:
            raise ValueError(f"MSG-DIR: {message_type} 不允许该发送方 {self.meta.sender}")
        if self.meta.receiver not in direction.receivers:
            raise ValueError(f"MSG-DIR: {message_type} 不允许该接收方 {self.meta.receiver}")
        # 信封与 payload 重复字段必须一致，防止“信封一套、正文一套”。
        payload = self.payload
        if isinstance(payload, TaskAssign) and payload.task_id != self.meta.task_id:
            raise ValueError("MSG-META: 信封 task_id 与 payload.task_id 不一致")


def message_digest(message: AgentMessage) -> str:
    """消息摘要（本地去重/审计用，不是签名载荷）。"""
    parts = [
        message.meta.message_id,
        message.meta.task_id,
        message.meta.sender.value,
        message.meta.receiver.value,
        message.meta.sent_at,
        message.meta.correlation_id,
        message.meta.contract_version,
        message.message_type.value,
        repr(payload_to_mapping(message.payload)),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()  # LIB: hashlib.sha256


def payload_to_mapping(payload: object) -> dict[str, object]:
    """payload → 可审计字典（仅字段名与值；不递归展开 Mapping 之外的对象）。"""
    result: dict[str, object] = {}
    for field in fields(payload):  # 只接受 dataclass payload
        value = getattr(payload, field.name)
        if isinstance(value, tuple):
            result[field.name] = [payload_to_mapping(v) if hasattr(v, "__dataclass_fields__") else v for v in value]
        elif hasattr(value, "__dataclass_fields__"):
            result[field.name] = payload_to_mapping(value)
        else:
            result[field.name] = value
    return result


def to_mapping(message: AgentMessage) -> dict[str, object]:
    """整条消息 → 字典（供审计/日志；不含 prompt、不含密钥）。"""
    meta = {
        "message_id": message.meta.message_id,
        "task_id": message.meta.task_id,
        "sender": message.meta.sender.value,
        "receiver": message.meta.receiver.value,
        "sent_at": message.meta.sent_at,
        "correlation_id": message.meta.correlation_id,
        "contract_version": message.meta.contract_version,
    }
    return {"type": message.message_type.value, "meta": meta, "payload": payload_to_mapping(message.payload)}


# ---------------------------------------------------------------------------
# 4. 严格解析：未知字段、缺字段、类型不符一律拒绝
# ---------------------------------------------------------------------------
_META_KEYS: Final[frozenset[str]] = frozenset(
    {"message_id", "task_id", "sender", "receiver", "sent_at", "correlation_id", "contract_version"}
)


def _strict_keys(raw: Mapping[str, object], cls: type, field_path: str) -> None:
    expected = {f.name for f in fields(cls)}
    if set(raw) != expected:
        raise ValueError(f"MSG-PARSE: {field_path} 键集合不符；未知/缺失字段一律拒绝")


def _texts(value: object, field_path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"MSG-PARSE: {field_path} 必须是字符串数组")
    return tuple(value)


def _ints(value: object, field_path: str) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"MSG-PARSE: {field_path} 必须是对象")
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"MSG-PARSE: {field_path}.{key} 必须是整数")
        result[key] = item
    return MappingProxyType(result)


def _parse_payload(message_type: MessageType, raw: Mapping[str, object]) -> object:
    """把 JSON 形态的 payload 还原成九类 dataclass；嵌套对象逐层严格解析。"""
    payload_cls = payload_type(message_type)
    _strict_keys(raw, payload_cls, f"payload[{message_type.value}]")

    if message_type is MessageType.TASK_ASSIGN:
        return TaskAssign(
            task_id=str(raw["task_id"]),
            node_id=str(raw["node_id"]),
            contract_version=str(raw["contract_version"]),
            inputs=_texts(raw["inputs"], "TaskAssign.inputs"),
            limits=_ints(raw["limits"], "TaskAssign.limits"),
        )
    if message_type is MessageType.PROGRESS:
        return Progress(
            node_id=str(raw["node_id"]),
            stage=ProgressStage(str(raw["stage"])),
            percent=raw["percent"],  # type: ignore[arg-type]
        )
    if message_type is MessageType.EVIDENCE_REF:
        return EvidenceRef(evidence_id=str(raw["evidence_id"]), kind=str(raw["kind"]))
    if message_type is MessageType.FINDING:
        findings_raw = raw["findings"]
        if not isinstance(findings_raw, (list, tuple)):
            raise ValueError("MSG-PARSE: Finding.findings 必须是数组")
        items: list[FindingItem] = []
        for index, item in enumerate(findings_raw):
            if not isinstance(item, Mapping):
                raise ValueError(f"MSG-PARSE: Finding.findings[{index}] 必须是对象")
            _strict_keys(item, FindingItem, f"Finding.findings[{index}]")
            items.append(
                FindingItem(
                    code=str(item["code"]),
                    statement=str(item["statement"]),
                    severity=FindingSeverity(str(item["severity"])),
                )
            )
        return Finding(
            node_id=str(raw["node_id"]),
            findings=tuple(items),
            confidence=raw["confidence"],  # type: ignore[arg-type]
            evidence_ids=_texts(raw["evidence_ids"], "Finding.evidence_ids"),
        )
    if message_type is MessageType.PLAN_PROPOSAL:
        patch_raw = raw["graph_patch"]
        if not isinstance(patch_raw, Mapping):
            raise ValueError("MSG-PARSE: PlanProposal.graph_patch 必须是对象")
        _strict_keys(patch_raw, GraphPatch, "GraphPatch")
        ops_raw = patch_raw["ops"]
        if not isinstance(ops_raw, (list, tuple)):
            raise ValueError("MSG-PARSE: GraphPatch.ops 必须是数组")
        ops: list[GraphOp] = []
        for index, item in enumerate(ops_raw):
            if not isinstance(item, Mapping):
                raise ValueError(f"MSG-PARSE: GraphPatch.ops[{index}] 必须是对象")
            _strict_keys(item, GraphOp, f"GraphPatch.ops[{index}]")
            ops.append(
                GraphOp(
                    op=PatchOpKind(str(item["op"])),
                    node_id=str(item["node_id"]),
                    template_id=None if item["template_id"] is None else str(item["template_id"]),
                    params_hash=None if item["params_hash"] is None else str(item["params_hash"]),
                    edge_from=None if item["edge_from"] is None else str(item["edge_from"]),
                    edge_to=None if item["edge_to"] is None else str(item["edge_to"]),
                )
            )
        cost_raw = raw["expected_cost"]
        if not isinstance(cost_raw, Mapping):
            raise ValueError("MSG-PARSE: PlanProposal.expected_cost 必须是对象")
        _strict_keys(cost_raw, ExpectedCost, "ExpectedCost")
        return PlanProposal(
            graph_patch=GraphPatch(base_graph_version=patch_raw["base_graph_version"], ops=tuple(ops)),  # type: ignore[arg-type]
            rationale=str(raw["rationale"]),
            expected_cost=ExpectedCost(
                token_budget=cost_raw["token_budget"],  # type: ignore[arg-type]
                wall_time_sec=cost_raw["wall_time_sec"],  # type: ignore[arg-type]
                node_count=cost_raw["node_count"],  # type: ignore[arg-type]
            ),
        )
    if message_type is MessageType.RECOVERY_PROPOSAL:
        plan_raw = raw["plan"]
        if not isinstance(plan_raw, Mapping):
            raise ValueError("MSG-PARSE: RecoveryProposal.plan 必须是对象")
        _strict_keys(plan_raw, RecoveryPlanRef, "RecoveryPlanRef")
        return RecoveryProposal(
            failed_node=str(raw["failed_node"]),
            affected_nodes=_texts(raw["affected_nodes"], "RecoveryProposal.affected_nodes"),
            plan=RecoveryPlanRef(
                plan_hash=str(plan_raw["plan_hash"]),
                plan_format_version=str(plan_raw["plan_format_version"]),
                step_count=plan_raw["step_count"],  # type: ignore[arg-type]
            ),
            skip_candidates=_texts(raw["skip_candidates"], "RecoveryProposal.skip_candidates"),
            rationale=str(raw["rationale"]),
        )
    if message_type is MessageType.VERIFY_REQUEST:
        return VerifyRequest(
            report_id=str(raw["report_id"]),
            checks_requested=_texts(raw["checks_requested"], "VerifyRequest.checks_requested"),
            reason=str(raw["reason"]),
        )
    if message_type is MessageType.VERDICT:
        certificate = raw["certificate_id"]
        return Verdict(
            report_id=str(raw["report_id"]),
            final_state=str(raw["final_state"]),
            l3_status=str(raw["l3_status"]),
            gaps=_texts(raw["gaps"], "Verdict.gaps"),
            certificate_id=None if certificate is None else str(certificate),
        )
    if message_type is MessageType.ESCALATE:
        needs_raw = raw["needs"]
        if not isinstance(needs_raw, (list, tuple)) or not all(isinstance(v, str) for v in needs_raw):
            raise ValueError("MSG-PARSE: Escalate.needs 必须是字符串数组")
        return Escalate(
            reason=EscalationReason(str(raw["reason"])),
            needs=tuple(EscalationNeed(v) for v in needs_raw),
            blocking_evidence_ids=_texts(raw["blocking_evidence_ids"], "Escalate.blocking_evidence_ids"),
        )
    raise ValueError(f"MSG-PARSE: 未处理的消息类型 {message_type}")


def parse_message(raw: Mapping[str, object]) -> AgentMessage:
    """从外部输入严格解析一条消息。

    拒绝条件（每条都必须可断言）：
      - 顶层键不是 {type, meta, payload}；
      - type 未知或不是九类之一；
      - meta/payload 含未知键或缺少必填键；
      - payload 类型与 type 不符、嵌套对象字段不合法。

    说明：本函数只做结构校验；方向、角色、证据存在性在 MessageValidator 中做。
    """
    if set(raw) != {"type", "meta", "payload"}:
        raise ValueError(f"MSG-PARSE: 顶层键必须恰为 type/meta/payload，实际 {sorted(raw)}")
    type_raw = raw["type"]
    if not isinstance(type_raw, str) or type_raw not in {t.value for t in MessageType}:
        raise ValueError(f"MSG-PARSE: 未知消息类型 {type_raw!r}")
    message_type = MessageType(type_raw)

    meta_raw = raw["meta"]
    if not isinstance(meta_raw, Mapping):
        raise ValueError("MSG-PARSE: meta 必须是对象")
    if set(meta_raw) != _META_KEYS:
        raise ValueError(f"MSG-PARSE: meta 键集合不符，实际 {sorted(meta_raw)}")
    meta = MessageMeta(
        message_id=str(meta_raw["message_id"]),
        task_id=str(meta_raw["task_id"]),
        sender=Endpoint(str(meta_raw["sender"])),
        receiver=Endpoint(str(meta_raw["receiver"])),
        sent_at=str(meta_raw["sent_at"]),
        correlation_id=str(meta_raw["correlation_id"]),
        contract_version=str(meta_raw["contract_version"]),
    )

    payload_raw = raw["payload"]
    if not isinstance(payload_raw, Mapping):
        raise ValueError("MSG-PARSE: payload 必须是对象")
    payload = _parse_payload(message_type, payload_raw)
    return AgentMessage(meta=meta, payload=payload)


# ---------------------------------------------------------------------------
# 5. 协议违规与证据查找端口
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProtocolViolation:
    """一条协议违规记录。只追加，不覆盖。"""

    task_id: str
    message_type: str
    sender: str
    reason: str
    offending: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.task_id, "ProtocolViolation.task_id")
        _require_text(self.reason, "ProtocolViolation.reason")


class EvidenceLookupPort(Protocol):
    """只读证据查找。由 M07/M02 实现；本模块不写证据。"""

    def exists(self, evidence_id: str) -> bool: ...

    def kind_of(self, evidence_id: str) -> str: ...

    def level_of(self, evidence_id: str) -> str: ...


class ViolationSinkPort(Protocol):
    """协议违规接收端。必须由 Collector/审计侧追加；返回 violation_id。"""

    def record(self, violation: ProtocolViolation) -> str: ...


class MessageRejected(RuntimeError):
    """消息被拒绝；`code`/`reason`/`field_path` 是断言对象。"""

    def __init__(self, code: str, reason: str, field_path: str, detail: Mapping[str, object] | None = None) -> None:
        self.code = code
        self.reason = reason
        self.field_path = field_path
        self.detail = dict(detail or {})
        super().__init__(f"[{code}] {field_path}: {reason}")


# ---------------------------------------------------------------------------
# 6. 重放防护：同一 task 内 message_id 不得重复
# ---------------------------------------------------------------------------
class ReplayVerdict(StrEnum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"


class ReplayGuard:
    """任务内消息去重。重复消息一律拒绝，不做“幂等返回”。"""

    MAX_PER_TASK: ClassVar[int] = 4096

    def __init__(self) -> None:
        self._seen: dict[str, set[str]] = {}

    def check_and_record(self, task_id: str, message_id: str) -> ReplayVerdict:
        """登记并返回判定；超上限时拒绝新消息（fail-closed），不淘汰旧记录。"""
        seen = self._seen.setdefault(task_id, set())
        if message_id in seen:
            return ReplayVerdict.DUPLICATE
        if len(seen) >= self.MAX_PER_TASK:
            raise MessageRejected(
                "RESOURCE_BUDGET_EXCEEDED", "MESSAGE_TRACKING_LIMIT", "meta.message_id",
                {"max_per_task": self.MAX_PER_TASK},
            )
        seen.add(message_id)
        return ReplayVerdict.NEW


# ---------------------------------------------------------------------------
# 7. 校验器：方向 → 角色 → 版本 → 证据存在性 → 重放
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ValidatedMessage:
    """通过校验的消息；携带统计用摘要与引用数量。"""

    message: AgentMessage
    digest: str
    evidence_ref_count: int
    sender_role: RoleId | None


def _evidence_refs(payload: object) -> tuple[tuple[str, str | None], ...]:
    """收集 payload 中的证据引用：返回 (evidence_id, expected_kind)。"""
    if isinstance(payload, EvidenceRef):
        return ((payload.evidence_id, payload.kind),)
    if isinstance(payload, Finding):
        return tuple((evidence_id, None) for evidence_id in payload.evidence_ids)
    if isinstance(payload, Escalate):
        return tuple((evidence_id, None) for evidence_id in payload.blocking_evidence_ids)
    return ()


class MessageValidator:
    """消息校验的唯一入口（tool_gateway 之外没有第二条消息通道）。"""

    def __init__(
        self,
        *,
        evidence: EvidenceLookupPort,
        sink: ViolationSinkPort,
        replay: ReplayGuard | None = None,
    ) -> None:
        self._evidence = evidence
        self._sink = sink
        self._replay = replay or ReplayGuard()

    def validate(self, message: AgentMessage) -> ValidatedMessage:
        """按七步校验；任一步失败都先记违规再抛，违规记录失败则升级为 AUDIT_WRITE_FAILED。"""
        message_type = message.message_type
        direction = DIRECTIONS[message_type]

        # 1. 方向
        if message.meta.sender not in direction.senders or message.meta.receiver not in direction.receivers:
            self._reject_and_record(
                message, "SCHEMA_INVALID", "MESSAGE_DIRECTION_DENIED",
                "meta.sender/meta.receiver", (message.meta.sender.value, message.meta.receiver.value),
            )

        # 2. 角色白名单（六角色各自能发哪些消息）
        sender_role: RoleId | None = None
        if message.meta.sender in AGENT_ENDPOINTS:
            sender_role = RoleId(message.meta.sender.value)
            allowed = ROLE_SPECS[sender_role].allowed_messages
            if message_type.value not in allowed:
                self._reject_and_record(
                    message, "SCHEMA_INVALID", "MESSAGE_NOT_ALLOWED_FOR_ROLE",
                    "meta.sender", (message_type.value,),
                )

        # 3. 角色契约版本：信封已校验；TASK_ASSIGN 的正文必须一致
        if isinstance(message.payload, TaskAssign) and message.payload.contract_version != message.meta.contract_version:
            self._reject_and_record(
                message, "SCHEMA_INVALID", "CONTRACT_VERSION_MISMATCH",
                "payload.contract_version", (message.payload.contract_version,),
            )

        # 4. 证据存在性 + 类型 + 可见级别
        refs = _evidence_refs(message.payload)
        for evidence_id, expected_kind in refs:
            if not self._evidence.exists(evidence_id):
                self._reject_and_record(
                    message, "EVIDENCE_REFERENCE_NOT_FOUND", "EVIDENCE_ID_NOT_FOUND",
                    "payload.evidence_id", (evidence_id,),
                )
            actual_kind = self._evidence.kind_of(evidence_id)
            if actual_kind not in EVIDENCE_KINDS:
                self._reject_and_record(
                    message, "SCHEMA_INVALID", "EVIDENCE_KIND_UNKNOWN",
                    "payload.evidence_id", (evidence_id,),
                )
            if expected_kind is not None and actual_kind != expected_kind:
                self._reject_and_record(
                    message, "SCHEMA_INVALID", "EVIDENCE_KIND_MISMATCH",
                    "payload.kind", (expected_kind, actual_kind),
                )
            level = self._evidence.level_of(evidence_id)
            if level not in EVIDENCE_LEVELS:
                self._reject_and_record(
                    message, "SCHEMA_INVALID", "EVIDENCE_LEVEL_UNKNOWN",
                    "payload.evidence_id", (evidence_id,),
                )
            if sender_role is not None and level not in ROLE_SPECS[sender_role].context_scope.evidence_levels:
                self._reject_and_record(
                    message, "SCHEMA_INVALID", "EVIDENCE_LEVEL_NOT_VISIBLE",
                    "payload.evidence_id", (evidence_id, level),
                )

        # 5. 重放
        if self._replay.check_and_record(message.meta.task_id, message.meta.message_id) is ReplayVerdict.DUPLICATE:
            self._reject_and_record(
                message, "SCHEMA_INVALID", "MESSAGE_REPLAY",
                "meta.message_id", (message.meta.message_id,),
            )

        # 6. VERDICT 的发送方必须不是 Agent（纵深防御，方向表已挡一次）
        if message_type is MessageType.VERDICT and message.meta.sender in AGENT_ENDPOINTS:
            self._reject_and_record(
                message, "SCHEMA_INVALID", "VERDICT_SENDER_NOT_VERIFIER",
                "meta.sender", (message.meta.sender.value,),
            )

        # 7. 通过
        return ValidatedMessage(
            message=message,
            digest=message_digest(message),
            evidence_ref_count=len(refs),
            sender_role=sender_role,
        )

    def _reject_and_record(
        self,
        message: AgentMessage,
        code: str,
        reason: str,
        field_path: str,
        offending: tuple[str, ...],
    ) -> None:
        """先记违规、再抛拒绝；记录失败则抛 AUDIT_WRITE_FAILED（不得静默丢失违规）。"""
        violation = ProtocolViolation(
            task_id=message.meta.task_id,
            message_type=message.message_type.value,
            sender=message.meta.sender.value,
            reason=reason,
            offending=offending,
        )
        try:
            violation_id = self._sink.record(violation)
        except Exception as exc:  # noqa: BLE001 - 违规记录失败必须兜底成审计失败
            raise MessageRejected(
                "AUDIT_WRITE_FAILED", "PROTOCOL_VIOLATION_NOT_RECORDED", field_path,
                {"original_reason": reason, "violation": violation.reason, "cause": type(exc).__name__},
            ) from exc
        raise MessageRejected(code, reason, field_path, {"violation_id": violation_id})


# ---------------------------------------------------------------------------
# 8. 静态守卫
# ---------------------------------------------------------------------------
def assert_exactly_nine() -> tuple[str, ...]:
    """验收判据 2：消息类型恰好 9 类，且与 contracts 的名称清单逐字一致。"""
    problems: list[str] = []
    names = tuple(t.value for t in MessageType)
    if len(names) != 9:
        problems.append(f"消息类型应为 9，实际 {len(names)}")
    if len(set(names)) != len(names):
        problems.append("消息类型重复")
    if tuple(sorted(names)) != tuple(sorted(AGENT_MESSAGE_NAMES)):
        problems.append("MessageType 与 contracts.AGENT_MESSAGE_NAMES 不一致")
    if set(PAYLOAD_TYPES) != set(MessageType):
        problems.append("PAYLOAD_TYPES 未覆盖全部消息类型")
    return tuple(problems)


def assert_direction_table() -> tuple[str, ...]:
    """方向表自洽：无自环、九类齐全、提案类标 proposal_only、VERDICT 只由 Verifier 发。"""
    problems: list[str] = []
    if set(DIRECTIONS) != set(MessageType):
        problems.append("方向表未覆盖全部消息类型")
    for message_type, direction in DIRECTIONS.items():
        if message_type is not direction.message_type:
            problems.append(f"{message_type} 的方向键不一致")
        if direction.senders & direction.receivers:
            problems.append(f"{message_type} 存在自环")
    for message_type in (MessageType.PLAN_PROPOSAL, MessageType.RECOVERY_PROPOSAL, MessageType.VERIFY_REQUEST):
        if not DIRECTIONS[message_type].proposal_only:
            problems.append(f"{message_type} 必须标记 proposal_only")
    verdict = DIRECTIONS[MessageType.VERDICT]
    if verdict.senders != frozenset({Endpoint.VERIFIER}) or verdict.receivers != frozenset({Endpoint.STATE_MACHINE}):
        problems.append("VERDICT 方向必须是 Verifier→StateMachine")
    if DIRECTIONS[MessageType.TASK_ASSIGN].senders != frozenset({Endpoint.SCHEDULER}):
        problems.append("TASK_ASSIGN 只能由 Scheduler 发出")
    return tuple(problems)


def assert_no_agent_verdict() -> tuple[str, ...]:
    """Agent 不可能出现在 VERDICT 的发送方集合里。"""
    problems: list[str] = []
    senders = DIRECTIONS[MessageType.VERDICT].senders
    if senders & AGENT_ENDPOINTS:
        problems.append("VERDICT 的发送方集合包含 Agent 端点")
    for role in RoleId:
        if "VERDICT" in ROLE_SPECS[role].allowed_messages:
            problems.append(f"{role} 被允许发送 VERDICT")
    return tuple(problems)