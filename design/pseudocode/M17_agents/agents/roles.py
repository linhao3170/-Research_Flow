"""MODULE：M17 · agents/roles.py — 六个角色的职责、输出校验与 role_off 行为（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-012（role-off 对照可测）｜策划书 §10.1 TABLE 40、§10.4、§6.3
FR+依赖：FR-012；依赖 contracts.py（RoleSpec/身份/禁止项）、messages.py（九类 payload）、M03 feature_flags（agents/role_off）
不变量+错误码：六角色各一个类；每个角色都能被显式关闭，关闭后行为有定义且**不得**退化成“单 Agent 全包”；
              FEATURE_FLAG_NOT_PERMITTED(503) / AUDIT_WRITE_FAILED(503) / STATE_TRANSITION_DENIED(409)
写入者：无。角色只产出“消息/提案/回退说明”，不写状态、不写证据、不签任何东西。
状态：伪代码；不调用模型、不调度、不关闭任何真实开关。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Final, Mapping, Protocol

from .contracts import (
    PROHIBITION_ENFORCEMENT,
    ROLE_CONTRACT_VERSION,
    ROLE_SPECS,
    RoleId,
    RoleIdentity,
    identity_for,
)
from .messages import (
    Escalate,
    Finding,
    FindingItem,
    MessageType,
    PlanProposal,
    RecoveryProposal,
    VerifyRequest,
)

__all__ = [
    "AgentRole",
    "AnalysisRole",
    "DataRole",
    "ExperimentRole",
    "PlannerRole",
    "RecoveryRole",
    "ReplacementKind",
    "RoleDisabled",
    "RoleFallback",
    "RoleOffAuditPort",
    "RoleOffContract",
    "RoleOffEvent",
    "RoleOffRegistry",
    "RoleRegistryRefused",
    "RoleStatus",
    "RoleValidationContext",
    "SystemMode",
    "VerificationRole",
    "assert_no_silent_collapse",
    "assert_role_off_defined",
    "role_class",
    "role_classes",
    "validate_role_output",
]

# 策划书 §6.3 的“专属消息”：只有指定角色能发。role_off 时也不得转给别的角色。
EXCLUSIVE_MESSAGES: Final[Mapping[MessageType, RoleId]] = {
    MessageType.PLAN_PROPOSAL: RoleId.PLANNER,
    MessageType.RECOVERY_PROPOSAL: RoleId.RECOVERY,
    MessageType.VERIFY_REQUEST: RoleId.VERIFICATION,
}


# ---------------------------------------------------------------------------
# 0. 关闭语义：显式枚举，**没有** SINGLE_AGENT
# ---------------------------------------------------------------------------
class RoleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class SystemMode(StrEnum):
    """系统级模式。`NO_AGENTS` 是“全关”，不是“一个 Agent 全包”。"""

    AGENTS_ACTIVE = "AGENTS_ACTIVE"
    PARTIAL_ROLE_OFF = "PARTIAL_ROLE_OFF"
    NO_AGENTS = "NO_AGENTS"


class ReplacementKind(StrEnum):
    """角色关闭后“谁来补位”。**没有** OTHER_AGENT / ALL_ROLES。"""

    NONE = "NONE"                          # 不补位：缺什么就报什么
    HUMAN_FORM = "HUMAN_FORM"              # 离线表单/人工选择模板（§10.4）
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"    # 确定性规则/工具
    DETERMINISTIC_TEMPLATE = "DETERMINISTIC_TEMPLATE"  # 模板默认值
    MANDATORY_VERIFIER_ONLY = "MANDATORY_VERIFIER_ONLY"  # 只保留 Verifier 必检


@dataclass(frozen=True, slots=True)
class RoleOffContract:
    """一个角色关闭后的完整行为契约。每个字段都必须可观测。"""

    role: RoleId
    replacement: ReplacementKind
    replacement_ref: str
    observable_effect: str
    forbidden_substitution: frozenset[RoleId]
    mandatory_preserved: bool
    requires_human: bool
    note: str

    def __post_init__(self) -> None:
        if not self.replacement_ref.strip() or not self.observable_effect.strip():
            raise ValueError(f"ROLE-OFF: {self.role} 的补位/观测效果不得为空")
        others = frozenset(r for r in RoleId if r is not self.role)
        if self.forbidden_substitution != others:
            raise ValueError(f"ROLE-OFF: {self.role} 必须禁止其余五个角色补位")
        if not self.mandatory_preserved:
            raise ValueError(f"ROLE-OFF: {self.role} 不得牺牲必检项/L3")
        if self.replacement is ReplacementKind.NONE and not self.requires_human:
            raise ValueError(
                f"ROLE-OFF: {self.role} 选 NONE 时必须 requires_human=True（否则等于静默失去能力）"
            )


def _others(role: RoleId) -> frozenset[RoleId]:
    return frozenset(r for r in RoleId if r is not role)


# 策划书 §10.4：分别关闭六个角色，比较完成率/协议违规/画像覆盖/复核请求/恢复成功率/L3 覆盖/成本/CPG。
ROLE_OFF_CONTRACTS: Final[Mapping[RoleId, RoleOffContract]] = {
    RoleId.PLANNER: RoleOffContract(
        role=RoleId.PLANNER,
        replacement=ReplacementKind.HUMAN_FORM,
        replacement_ref="task.form.template_selection",
        observable_effect="plan_proposals=0；完成率取决于表单是否选模板；协议违规不因关闭而下降",
        forbidden_substitution=_others(RoleId.PLANNER),
        mandatory_preserved=True,
        requires_human=True,
        note="无表单且无预置 template_id → ESCALATE(HUMAN_DECISION)，任务保持 BLOCKED，不得由别的角色代写 DAG",
    ),
    RoleId.DATA: RoleOffContract(
        role=RoleId.DATA,
        replacement=ReplacementKind.DETERMINISTIC_RULE,
        replacement_ref="dataset.profile + 质量阈值规则",
        observable_effect="data_profile_coverage 仍可测；异常解释与 FINDING 数为 0",
        forbidden_substitution=_others(RoleId.DATA),
        mandatory_preserved=True,
        requires_human=False,
        note="画像由工具执行；不得把画像结果写成 E2，也不得由 Analysis 代替解释",
    ),
    RoleId.EXPERIMENT: RoleOffContract(
        role=RoleId.EXPERIMENT,
        replacement=ReplacementKind.DETERMINISTIC_TEMPLATE,
        replacement_ref="template.parameterize + SPEC 默认值",
        observable_effect="default_value_correctness 可测；参数化 FINDING 数为 0",
        forbidden_substitution=_others(RoleId.EXPERIMENT),
        mandatory_preserved=True,
        requires_human=False,
        note="必填参数无默认值 → ESCALATE(MORE_EVIDENCE)；不得猜参数，不得让 Planner 代填",
    ),
    RoleId.ANALYSIS: RoleOffContract(
        role=RoleId.ANALYSIS,
        replacement=ReplacementKind.NONE,
        replacement_ref="—",
        observable_effect="analysis_findings=0；L2 指标重算不受影响；报告无解释性叙述",
        forbidden_substitution=_others(RoleId.ANALYSIS),
        mandatory_preserved=True,
        requires_human=True,
        note="没有解释就诚实空着；不得让 Verifier 代写叙述，也不得降低必检",
    ),
    RoleId.RECOVERY: RoleOffContract(
        role=RoleId.RECOVERY,
        replacement=ReplacementKind.NONE,
        replacement_ref="—",
        observable_effect="recovery_proposals=0；失败直接升级；恢复成功率记 0 并如实报告",
        forbidden_substitution=_others(RoleId.RECOVERY),
        mandatory_preserved=True,
        requires_human=True,
        note="无提案就升级；不得让 Planner 改图“顺手恢复”，不得签 SPA",
    ),
    RoleId.VERIFICATION: RoleOffContract(
        role=RoleId.VERIFICATION,
        replacement=ReplacementKind.MANDATORY_VERIFIER_ONLY,
        replacement_ref="M08 ruleset + M09/M10 必检 L1/L2/L3",
        observable_effect="verify_requests=0；必检覆盖不变；缺口解释减少",
        forbidden_substitution=_others(RoleId.VERIFICATION),
        mandatory_preserved=True,
        requires_human=False,
        note="Verification Agent 只提请求；关掉它不得减少任何必检项或 L3",
    ),
}


# ---------------------------------------------------------------------------
# 1. 输出校验上下文与结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RoleValidationContext:
    """角色输出校验所需的只读事实；缺省即不校验对应项（fail-open 只在“未提供”时发生）。"""

    allowed_templates: frozenset[str] = frozenset()
    graph_version: int | None = None
    allowed_checks: frozenset[str] = frozenset()
    issued_report_ids: frozenset[str] = frozenset()
    affected_nodes: frozenset[str] = frozenset()
    known_plan_hashes: frozenset[str] = frozenset()
    max_nodes: int = 16
    max_plan_steps: int = 32


@dataclass(frozen=True, slots=True)
class RoleFallback:
    """模型不可用时的确定性回退说明。不得包含伪造的模型文本。"""

    role: RoleId
    kind: ReplacementKind
    behavior: str
    requires_human: bool
    emits_messages: bool

    def __post_init__(self) -> None:
        if not self.behavior.strip():
            raise ValueError("ROLE-FALLBACK: 回退行为必须写清")
        if self.kind is ReplacementKind.NONE and not self.requires_human:
            raise ValueError("ROLE-FALLBACK: NONE 回退必须要求人工")


# ---------------------------------------------------------------------------
# 2. 角色基类与六个角色
# ---------------------------------------------------------------------------
class AgentRole:
    """角色基类：只读规格 + 输出校验 + 回退说明。没有任何写入口。"""

    role: ClassVar[RoleId]
    off: ClassVar[RoleOffContract]

    @property
    def spec(self):  # noqa: ANN201 - 返回 contracts.RoleSpec，避免循环标注
        return ROLE_SPECS[self.role]

    def identity(self) -> RoleIdentity:
        """装配身份（白名单来自规格，不接受调用方覆盖）。"""
        return identity_for(self.role)

    def allowed_messages(self) -> tuple[str, ...]:
        return self.spec.allowed_messages

    def allowed_tools(self) -> tuple[str, ...]:
        return self.spec.allowed_tools

    def knowledge_kinds(self) -> frozenset[str]:
        return self.spec.context_scope.knowledge_kinds

    def off_contract(self) -> RoleOffContract:
        return self.off

    def validate_output(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        """校验一个输出是否越权/越界；返回违规原因列表，空 = 通过。"""
        problems: list[str] = []
        if message_type.value not in self.spec.allowed_messages:
            problems.append(f"ROLE_OUTPUT_NOT_ALLOWED:{self.role.value}:{message_type.value}")
        if message_type in EXCLUSIVE_MESSAGES and EXCLUSIVE_MESSAGES[message_type] is not self.role:
            problems.append(f"ROLE_EXCLUSIVE_OUTPUT_VIOLATION:{message_type.value}")
        problems.extend(self._validate_payload(message_type, payload, context))
        return tuple(problems)

    def _validate_payload(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        """子类覆写；基类不做类型判断（子类必须显式检查）。"""
        return ()

    def fallback(self, *, template_id: str | None = None, has_human_form: bool = False) -> RoleFallback:
        """模型不可用时的确定性行为。未覆写即“什么都不产出并升级”。"""
        return RoleFallback(
            role=self.role,
            kind=ReplacementKind.NONE,
            behavior="不产出任何模型内容；升级人工，不使用猜测内容",
            requires_human=True,
            emits_messages=False,
        )

    def assert_prohibitions_honored(self) -> tuple[str, ...]:
        """每个禁止项都要有拒绝分支（由 contracts.PROHIBITION_ENFORCEMENT 覆盖）。"""
        problems: list[str] = []
        for prohibition in self.spec.prohibitions:
            if prohibition not in PROHIBITION_ENFORCEMENT:
                problems.append(f"{self.role.value}:{prohibition.value}")
        return tuple(problems)


class PlannerRole(AgentRole):
    role = RoleId.PLANNER
    off = ROLE_OFF_CONTRACTS[RoleId.PLANNER]

    def _validate_payload(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        if message_type is not MessageType.PLAN_PROPOSAL:
            return ()
        if not isinstance(payload, PlanProposal):
            return ("ROLE_OUTPUT_TYPE_MISMATCH:PLAN_PROPOSAL",)
        problems: list[str] = []
        patch = payload.graph_patch
        if context.graph_version is not None and patch.base_graph_version != context.graph_version:
            problems.append("GRAPH_VERSION_STALE")
        if len(patch.ops) > context.max_nodes:
            problems.append("PLAN_TOO_LARGE")
        for op in patch.ops:
            if op.template_id is not None and context.allowed_templates:
                if op.template_id not in context.allowed_templates:
                    problems.append(f"TEMPLATE_NOT_ALLOWED:{op.template_id}")
        if payload.expected_cost.node_count > context.max_nodes:
            problems.append("PLAN_NODE_COUNT_EXCEEDS_LIMIT")
        return tuple(problems)

    def fallback(self, *, template_id: str | None = None, has_human_form: bool = False) -> RoleFallback:
        if has_human_form or template_id:
            return RoleFallback(
                role=self.role,
                kind=ReplacementKind.HUMAN_FORM,
                behavior="由表单/预置 template_id 决定模板，Builder 直接生成图；Planner 不产出 PLAN_PROPOSAL",
                requires_human=not template_id,
                emits_messages=False,
            )
        return RoleFallback(
            role=self.role,
            kind=ReplacementKind.NONE,
            behavior="无模板可选：ESCALATE(ROLE_DISABLED, HUMAN_DECISION)，任务保持 BLOCKED",
            requires_human=True,
            emits_messages=True,
        )


class DataRole(AgentRole):
    role = RoleId.DATA
    off = ROLE_OFF_CONTRACTS[RoleId.DATA]

    _CODE_PREFIXES: ClassVar[tuple[str, ...]] = ("dataset_", "schema_", "quality_", "profile_")

    def _validate_payload(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        if message_type is not MessageType.FINDING:
            return ()
        if not isinstance(payload, Finding):
            return ("ROLE_OUTPUT_TYPE_MISMATCH:FINDING",)
        problems: list[str] = []
        for item in payload.findings:
            if not item.code.startswith(self._CODE_PREFIXES):
                problems.append(f"DATASET_FINDING_CODE_OUT_OF_SCOPE:{item.code}")
        return tuple(problems)

    def fallback(self, *, template_id: str | None = None, has_human_form: bool = False) -> RoleFallback:
        return RoleFallback(
            role=self.role,
            kind=ReplacementKind.DETERMINISTIC_RULE,
            behavior="只跑 dataset.profile 与质量阈值规则；不产出异常解释 FINDING",
            requires_human=False,
            emits_messages=False,
        )


class ExperimentRole(AgentRole):
    role = RoleId.EXPERIMENT
    off = ROLE_OFF_CONTRACTS[RoleId.EXPERIMENT]

    _CODE_PREFIXES: ClassVar[tuple[str, ...]] = ("params_", "template_", "config_")
    _CODE_TOKENS: ClassVar[tuple[str, ...]] = ("import ", "eval(", "exec(", "subprocess", "os.system", "__import__", "pickle.loads")

    def _validate_payload(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        if message_type is not MessageType.FINDING:
            return ()
        if not isinstance(payload, Finding):
            return ("ROLE_OUTPUT_TYPE_MISMATCH:FINDING",)
        problems: list[str] = []
        for item in payload.findings:
            if not item.code.startswith(self._CODE_PREFIXES):
                problems.append(f"EXPERIMENT_FINDING_CODE_OUT_OF_SCOPE:{item.code}")
            lowered = item.statement.lower()
            if any(token in lowered for token in self._CODE_TOKENS):
                problems.append("ARBITRARY_CODE_IN_PARAMS")
        return tuple(problems)

    def fallback(self, *, template_id: str | None = None, has_human_form: bool = False) -> RoleFallback:
        return RoleFallback(
            role=self.role,
            kind=ReplacementKind.DETERMINISTIC_TEMPLATE,
            behavior="用 SPEC 默认值做参数映射；缺失必填参数 → ESCALATE，不猜值",
            requires_human=False,
            emits_messages=False,
        )


class AnalysisRole(AgentRole):
    role = RoleId.ANALYSIS
    off = ROLE_OFF_CONTRACTS[RoleId.ANALYSIS]

    _CODE_PREFIXES: ClassVar[tuple[str, ...]] = ("metric_", "analysis_", "recompute_", "gap_")
    _FORBIDDEN_CODES: ClassVar[tuple[str, ...]] = ("verdict", "verified", "certificate", "signed")

    def _validate_payload(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        if message_type is not MessageType.FINDING:
            return ()
        if not isinstance(payload, Finding):
            return ("ROLE_OUTPUT_TYPE_MISMATCH:FINDING",)
        problems: list[str] = []
        for item in payload.findings:
            if not item.code.startswith(self._CODE_PREFIXES):
                problems.append(f"ANALYSIS_FINDING_CODE_OUT_OF_SCOPE:{item.code}")
            if any(token in item.code for token in self._FORBIDDEN_CODES):
                problems.append("ANALYSIS_ATTEMPTS_VERDICT")
        return tuple(problems)

    def fallback(self, *, template_id: str | None = None, has_human_form: bool = False) -> RoleFallback:
        return RoleFallback(
            role=self.role,
            kind=ReplacementKind.NONE,
            behavior="不解释指标；指标仍由 L2 重算；报告不含叙述，不得声称 VERIFIED",
            requires_human=True,
            emits_messages=False,
        )


class RecoveryRole(AgentRole):
    role = RoleId.RECOVERY
    off = ROLE_OFF_CONTRACTS[RoleId.RECOVERY]

    def _validate_payload(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        if message_type is not MessageType.RECOVERY_PROPOSAL:
            return ()
        if not isinstance(payload, RecoveryProposal):
            return ("ROLE_OUTPUT_TYPE_MISMATCH:RECOVERY_PROPOSAL",)
        problems: list[str] = []
        if context.affected_nodes and frozenset(payload.affected_nodes) != context.affected_nodes:
            problems.append("RECOVERY_AFFECTED_SET_MISMATCH")
        if context.known_plan_hashes and payload.plan.plan_hash not in context.known_plan_hashes:
            problems.append("RECOVERY_PLAN_NOT_FROZEN")
        if payload.plan.step_count > context.max_plan_steps:
            problems.append("RECOVERY_PLAN_TOO_LARGE")
        return tuple(problems)

    def fallback(self, *, template_id: str | None = None, has_human_form: bool = False) -> RoleFallback:
        return RoleFallback(
            role=self.role,
            kind=ReplacementKind.NONE,
            behavior="不产出恢复提案；失败经 M14 的 RESOURCE 规则或直接 ESCALATE，不签 SPA",
            requires_human=True,
            emits_messages=True,
        )


class VerificationRole(AgentRole):
    role = RoleId.VERIFICATION
    off = ROLE_OFF_CONTRACTS[RoleId.VERIFICATION]

    def _validate_payload(self, message_type: MessageType, payload: object, context: RoleValidationContext) -> tuple[str, ...]:
        if message_type is not MessageType.VERIFY_REQUEST:
            return ()
        if not isinstance(payload, VerifyRequest):
            return ("ROLE_OUTPUT_TYPE_MISMATCH:VERIFY_REQUEST",)
        problems: list[str] = []
        if context.allowed_checks:
            extra = set(payload.checks_requested) - context.allowed_checks
            if extra:
                problems.append(f"CHECK_NOT_IN_RULESET:{sorted(extra)[0]}")
        if payload.report_id in context.issued_report_ids:
            problems.append("REPORT_ID_ALREADY_ISSUED")
        return tuple(problems)

    def fallback(self, *, template_id: str | None = None, has_human_form: bool = False) -> RoleFallback:
        return RoleFallback(
            role=self.role,
            kind=ReplacementKind.MANDATORY_VERIFIER_ONLY,
            behavior="不提交验证计划；Verifier 必检 L1/L2/L3 照常执行，覆盖不得下降",
            requires_human=False,
            emits_messages=False,
        )


_ROLE_CLASSES: Final[Mapping[RoleId, type[AgentRole]]] = {
    RoleId.PLANNER: PlannerRole,
    RoleId.DATA: DataRole,
    RoleId.EXPERIMENT: ExperimentRole,
    RoleId.ANALYSIS: AnalysisRole,
    RoleId.RECOVERY: RecoveryRole,
    RoleId.VERIFICATION: VerificationRole,
}


def role_class(role: RoleId) -> type[AgentRole]:
    """按 RoleId 取角色类；未知即抛。"""
    return _ROLE_CLASSES[role]


def role_classes() -> tuple[type[AgentRole], ...]:
    """六个角色类（顺序固定）。"""
    return tuple(_ROLE_CLASSES[role] for role in RoleId)


def validate_role_output(
    role: RoleId, message_type: MessageType, payload: object, context: RoleValidationContext
) -> tuple[str, ...]:
    """模块级入口：装配一个角色实例并校验输出。"""
    return role_class(role)().validate_output(message_type, payload, context)


# ---------------------------------------------------------------------------
# 3. role_off 注册表：关闭必须留痕，且不得静默退化
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RoleOffEvent:
    """一次关闭/恢复事件；审计必须追加。"""

    role: RoleId
    action: str  # DISABLED / REENABLED
    reason: str
    approved_by: str
    at: str
    contract_version: str

    def __post_init__(self) -> None:
        if self.action not in ("DISABLED", "REENABLED"):
            raise ValueError("ROLE-OFF-EVENT: action 只能是 DISABLED/REENABLED")
        if not (self.reason.strip() and self.approved_by.strip() and self.at.strip()):
            raise ValueError("ROLE-OFF-EVENT: reason/approved_by/at 不得为空")


class RoleOffAuditPort(Protocol):
    def record(self, event: RoleOffEvent) -> str: ...


class RoleRegistryRefused(RuntimeError):
    """关闭请求被拒；`code`/`reason` 是断言对象。"""

    def __init__(self, code: str, reason: str, detail: str) -> None:
        self.code = code
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{code}] {reason}（{detail}）")


class RoleDisabled(RuntimeError):
    """角色已关闭：派发必须显式失败，不得转给其他角色。"""

    def __init__(self, role: RoleId, off: RoleOffContract) -> None:
        self.role = role
        self.off = off
        self.error_code = "FEATURE_FLAG_NOT_PERMITTED"
        self.reason = "ROLE_DISABLED"
        super().__init__(f"[{self.error_code}] {self.reason}: {role.value} → {off.replacement.value}")


class RoleOffRegistry:
    """六角色的开关。三个硬约束：

      1. `agents=false` 或 `role_off=false` 时不允许关闭任何角色；
      2. 关闭必须写审计（失败则拒绝关闭，避免“悄悄消失”）；
      3. 关闭后派发只返回 `RoleDisabled`，**不**把活转给别的角色。
    """

    def __init__(self, *, flags: Mapping[str, bool], audit: RoleOffAuditPort) -> None:
        self._flags = dict(flags)
        self._audit = audit
        self._status: dict[RoleId, RoleStatus] = {role: RoleStatus.ACTIVE for role in RoleId}

    def status(self, role: RoleId) -> RoleStatus:
        return self._status[role]

    def disabled_roles(self) -> tuple[RoleId, ...]:
        return tuple(role for role in RoleId if self._status[role] is RoleStatus.DISABLED)

    def mode(self) -> SystemMode:
        disabled = len(self.disabled_roles())
        if disabled == 0:
            return SystemMode.AGENTS_ACTIVE
        if disabled == len(RoleId):
            return SystemMode.NO_AGENTS
        return SystemMode.PARTIAL_ROLE_OFF

    def disable(self, role: RoleId, *, reason: str, approved_by: str, at: str) -> None:
        """关闭一个角色。前置：agents=true 且 role_off=true；必须审计成功。"""
        if not self._flags.get("agents", False):
            raise RoleRegistryRefused(
                "FEATURE_FLAG_NOT_PERMITTED", "ROLE_OFF_REQUIRES_AGENTS",
                "agents=false 时没有可关闭的角色；T0 强制 agents=false",
            )
        if not self._flags.get("role_off", False):
            raise RoleRegistryRefused(
                "FEATURE_FLAG_NOT_PERMITTED", "ROLE_OFF_FLAG_DISABLED",
                "role_off=false 时禁止关闭角色；不得绕过 feature flag",
            )
        if self._status[role] is RoleStatus.DISABLED:
            raise RoleRegistryRefused("FEATURE_FLAG_NOT_PERMITTED", "ROLE_ALREADY_DISABLED", role.value)
        if not reason.strip() or not approved_by.strip() or not at.strip():
            raise RoleRegistryRefused("SCHEMA_INVALID", "ROLE_OFF_EVENT_INCOMPLETE", role.value)
        event = RoleOffEvent(
            role=role, action="DISABLED", reason=reason, approved_by=approved_by, at=at,
            contract_version=ROLE_CONTRACT_VERSION,
        )
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001 - 无审计不得关闭
            raise RoleRegistryRefused("AUDIT_WRITE_FAILED", "ROLE_OFF_AUDIT_UNAVAILABLE", type(exc).__name__) from exc
        self._status[role] = RoleStatus.DISABLED

    def reenable(self, role: RoleId, *, reason: str, approved_by: str, at: str) -> None:
        """恢复角色；同样必须留痕。"""
        if self._status[role] is RoleStatus.ACTIVE:
            raise RoleRegistryRefused("FEATURE_FLAG_NOT_PERMITTED", "ROLE_ALREADY_ACTIVE", role.value)
        if not reason.strip() or not approved_by.strip() or not at.strip():
            raise RoleRegistryRefused("SCHEMA_INVALID", "ROLE_OFF_EVENT_INCOMPLETE", role.value)
        event = RoleOffEvent(
            role=role, action="REENABLED", reason=reason, approved_by=approved_by, at=at,
            contract_version=ROLE_CONTRACT_VERSION,
        )
        try:
            self._audit.record(event)
        except Exception as exc:  # noqa: BLE001
            raise RoleRegistryRefused("AUDIT_WRITE_FAILED", "ROLE_OFF_AUDIT_UNAVAILABLE", type(exc).__name__) from exc
        self._status[role] = RoleStatus.ACTIVE

    def require_active(self, role: RoleId) -> None:
        """派发前守卫：关闭的角色直接抛，调用方不得换角色重试。"""
        if self._status[role] is RoleStatus.DISABLED:
            raise RoleDisabled(role, ROLE_OFF_CONTRACTS[role])

    def assert_no_silent_collapse(self) -> tuple[str, ...]:
        """验收判据 3：关闭后的行为已定义，且不存在“某个角色全包”的路径。"""
        return _collapse_problems()


def _collapse_problems() -> tuple[str, ...]:
    """“单 Agent 全包”的静态检查；Registry 与模块级守卫共用同一实现。"""
    problems: list[str] = []
    for role in RoleId:
        off = ROLE_OFF_CONTRACTS[role]
        if off.forbidden_substitution != _others(role):
            problems.append(f"{role.value} 的禁止补位集合不完整")
        if off.mandatory_preserved is not True:
            problems.append(f"{role.value} 关闭后必检被牺牲")
    # 专属消息不得被别的角色持有
    for message_type, owner in EXCLUSIVE_MESSAGES.items():
        for role in RoleId:
            if role is owner:
                continue
            if message_type.value in ROLE_SPECS[role].allowed_messages:
                problems.append(f"{role.value} 持有专属消息 {message_type.value}")
    # 全关时必须是 NO_AGENTS
    if SystemMode.NO_AGENTS.value != "NO_AGENTS":
        problems.append("SystemMode 缺少 NO_AGENTS")
    if "SINGLE_AGENT" in {m.value for m in SystemMode}:
        problems.append("SystemMode 不得包含 SINGLE_AGENT")
    return tuple(problems)


# ---------------------------------------------------------------------------
# 4. 静态守卫
# ---------------------------------------------------------------------------
def assert_role_off_defined() -> tuple[str, ...]:
    """每个角色都有：补位方式、观测效果、禁止补位、必检保留、人工要求。"""
    problems: list[str] = []
    for role in RoleId:
        off = ROLE_OFF_CONTRACTS.get(role)
        if off is None:
            problems.append(f"{role.value} 没有 role_off 契约")
            continue
        if off.replacement is ReplacementKind.NONE and not off.requires_human:
            problems.append(f"{role.value} 的 NONE 补位未要求人工")
        if not off.observable_effect:
            problems.append(f"{role.value} 没有可观测效果")
        if role_class(role).off is not off:
            problems.append(f"{role.value} 的类属性 off 与注册表不一致")
    if len(ROLE_OFF_CONTRACTS) != 6:
        problems.append("role_off 契约数不是 6")
    return tuple(problems)


def assert_no_silent_collapse() -> tuple[str, ...]:
    """静态版：不构造 Registry 也能检查“单 Agent 全包”不存在。"""
    return _collapse_problems()