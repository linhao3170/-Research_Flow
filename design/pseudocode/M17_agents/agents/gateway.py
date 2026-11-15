"""MODULE：M17 · agents/gateway.py — 角色调度：装配上下文 → 调模型 → 校验输出 → 交提案（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-012（角色调度、上下文范围、提案不落库）｜策划书 §10.1/§10.2、§10.4、§6.3
FR+依赖：FR-012；依赖 contracts.py（身份/范围）、messages.py（九类消息/证据引用）、roles.py（六角色/role_off）、llm_client.py（预算/回退）、M03 feature_flags（agents）
不变量+错误码：只给角色可见的知识类型；模型输出必须过严格 Schema 与越权键扫描；通过后**只**交给 SchedulerPort（提案）；
              本文件没有状态机端口、没有证据写端口、没有签名端口。
              FEATURE_FLAG_NOT_PERMITTED(503) / SCHEMA_INVALID(422) / RESOURCE_BUDGET_EXCEEDED(429) / AUDIT_WRITE_FAILED(503)
写入者：无。审计经 AgentAuditPort；提案经 SchedulerPort；证据仍只由 Collector 写。
状态：伪代码；不联网、不落库、不调度。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Mapping, Protocol, Sequence

from .contracts import (
    ROLE_CONTRACT_VERSION,
    ROLE_SPECS,
    RoleId,
    RoleIdentity,
    identity_for,
)
from .llm_client import (
    FallbackReason,
    FinishReason,
    LLMBudgetExceeded,
    LLMClient,
    LLMRequest,
    LLMResponse,
    PromptKind,
    PromptSection,
    TrustLevel,
    estimate_tokens,
)
from .messages import (
    AGENT_ENDPOINTS,
    AgentMessage,
    Endpoint,
    Escalate,
    EscalationNeed,
    EscalationReason,
    EvidenceLookupPort,
    MessageMeta,
    MessageRejected,
    MessageType,
    MessageValidator,
    TaskAssign,
    ViolationSinkPort,
    parse_payload,
)
from .roles import (
    ROLE_OFF_CONTRACTS,
    RoleFallback,
    RoleOffContract,
    RoleOffRegistry,
    RoleValidationContext,
    role_class,
    validate_role_output,
)

# 单次输出上限与模型超时（P8 装配约定，OQ-P8-06；不是契约值）。
PROPOSED_MAX_TOKENS: Final[int] = 1024
PROPOSED_TIMEOUT_SEC: Final[int] = 60

__all__ = [
    "AgentAuditPort",
    "AgentAuditRecord",
    "AgentContext",
    "AgentGateway",
    "ContextAssembler",
    "ContextOverflow",
    "DispatchOutcome",
    "DispatchStatus",
    "EvidenceFacts",
    "EvidenceIndexPort",
    "KnowledgeConflict",
    "KnowledgeHit",
    "KnowledgePort",
    "KnowledgeQuery",
    "KnowledgeResult",
    "NodeFacts",
    "OutputInvalid",
    "OutputValidator",
    "SchedulerPort",
    "TaskFactsPort",
    "assert_context_scope_only",
    "assert_no_write_surface",
]

# 模型输出里一旦出现这些键，即判定为“试图越权”。递归扫描，大小写归一。
FORBIDDEN_OUTPUT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "state",
        "new_state",
        "final_state",
        "transition",
        "verdict",
        "signature",
        "private_key",
        "secret",
        "certificate",
        "certificate_id", "report", "task_state", "node_state",
        "write",
        "persist",
        "evidence_write",
        "append_evidence",
        "sql",
        "database",
        "audit_write",
    }
)


# ---------------------------------------------------------------------------
# 0. 只读端口（全部由外部装配；本文件不实现存储）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class NodeFacts:
    """一个节点的事实视图（来自 NodeSpec/图，不是证据）。"""

    node_id: str
    node_type: str
    template_id: str
    parameters_hash: str
    input_refs: tuple[str, ...]
    required_checks: tuple[str, ...]


class TaskFactsPort(Protocol):
    """任务/节点的只读事实。查不到必须抛，不得返回默认值。"""

    def goal(self, task_id: str) -> str: ...

    def node(self, task_id: str, node_id: str) -> NodeFacts: ...


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    """一次知识检索请求。ktypes 必须已按角色收敛。"""

    text: str
    ktypes: tuple[str, ...]
    scope_prefix: str
    limit: int
    allow_stale: bool

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("CTX-QUERY: 检索文本不得为空")
        if not self.ktypes:
            raise ValueError("CTX-QUERY: ktypes 不得为空；空白检索等于放开知识边界")
        if not 1 <= self.limit <= 20:
            raise ValueError("CTX-QUERY: limit 必须在 [1,20]")


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    """一条检索命中。`content_hash` 让调用方核对版本；`stale_kb` 必须透传。"""

    kid: str
    version: int
    content_hash: str
    source_url: str
    ktype: str
    scope: str
    status: str
    score: float
    stale_kb: bool
    injectable: bool
    match_reason: str

    def __post_init__(self) -> None:
        if self.status not in ("ACTIVE", "DEPRECATED", "CONFLICTED"):
            raise ValueError("CTX-HIT: 未知知识状态")
        if self.status == "CONFLICTED" and self.injectable:
            raise ValueError("CTX-HIT: 冲突知识不得标记为可注入")
        if len(self.content_hash) != 64:
            raise ValueError("CTX-HIT: content_hash 必须是 64 位十六进制")


@dataclass(frozen=True, slots=True)
class KnowledgeConflict:
    """冲突通知：只用于升级，不提供“选哪个版本”的接口。"""

    scope: str
    ktype: str
    contenders: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if len(self.contenders) < 2:
            raise ValueError("CTX-CONFLICT: 冲突至少两个候选版本")


@dataclass(frozen=True, slots=True)
class KnowledgeResult:
    """检索结果。`evidence_event_id` 是 Collector 写的 E1 事件 ID（不是本模块写的）。"""

    hits: tuple[KnowledgeHit, ...]
    conflicts: tuple[KnowledgeConflict, ...]
    evidence_event_id: str
    query_hash: str


class KnowledgePort(Protocol):
    """M18 retrieval 的结构视图。只在 Agent 侧使用；Gate/Verifier 不得接这个端口。"""

    def retrieve(self, query: KnowledgeQuery) -> KnowledgeResult: ...


@dataclass(frozen=True, slots=True)
class EvidenceFacts:
    """证据索引的一行；不含 payload，避免把原始内容塞进 prompt。"""

    evidence_id: str
    level: str
    kind: str
    producer: str
    producer_role: RoleId | None

    def __post_init__(self) -> None:
        if self.level not in ("E0", "E1", "E2", "E3"):
            raise ValueError("CTX-EV: 未知证据等级")


class EvidenceIndexPort(EvidenceLookupPort, Protocol):
    """只读证据索引；同时满足 messages.EvidenceLookupPort 的三个方法。"""

    def facts(self, evidence_id: str) -> EvidenceFacts: ...

    def list_for_task(self, task_id: str, *, levels: Sequence[str], limit: int) -> tuple[EvidenceFacts, ...]: ...


class SchedulerPort(Protocol):
    """提案接收端。只有 `submit`，**没有** `apply`/`transition`。"""

    def submit(self, message: AgentMessage) -> str: ...


@dataclass(frozen=True, slots=True)
class AgentAuditRecord:
    """一次 Agent 运行的审计。首次写入在提交提案之前；无审计不得提交。"""

    task_id: str
    node_id: str
    role: RoleId
    contract_version: str
    status: str
    message_types: tuple[str, ...]
    output_digest: str | None
    prompt_tokens: int
    completion_tokens: int
    cache_hit: bool
    fallback_reason: str | None
    violations: tuple[str, ...]
    correlation_id: str
    started_at: str

    def __post_init__(self) -> None:
        if self.contract_version != ROLE_CONTRACT_VERSION:
            raise ValueError("CTX-AUDIT: 审计必须绑定当前角色契约版本")
        if not self.task_id.startswith("task_") or not self.node_id:
            raise ValueError("CTX-AUDIT: task/node 不得为空")


class AgentAuditPort(Protocol):
    def record(self, record: AgentAuditRecord) -> str: ...


class ClockPort(Protocol):
    def utc_now_iso(self) -> str: ...


# ---------------------------------------------------------------------------
# 1. 上下文装配：只给该看的知识
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AgentContext:
    """装配后的上下文。`dropped_*` 让“截断”可观测，避免悄悄丢证据。"""

    identity: RoleIdentity
    goal: str
    node: NodeFacts
    knowledge: tuple[KnowledgeHit, ...]
    evidence: tuple[EvidenceFacts, ...]
    conflicts: tuple[KnowledgeConflict, ...]
    stale_kids: tuple[str, ...]
    estimated_tokens: int
    dropped_knowledge: int
    dropped_evidence: int

    def knowledge_kinds(self) -> frozenset[str]:
        return frozenset(hit.ktype for hit in self.knowledge)

    def evidence_levels(self) -> frozenset[str]:
        return frozenset(fact.level for fact in self.evidence)


class ContextOverflow(RuntimeError):
    """上下文超预算；调用方必须升级，不得截断系统策略或任务事实。"""

    def __init__(self, reason: str, detail: str) -> None:
        self.error_code = "RESOURCE_BUDGET_EXCEEDED"
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{self.error_code}] {reason}（{detail}）")


class ContextAssembler:
    """按角色范围装配上下文。

    四条硬规则：
      1. 知识 ktype ⊆ 角色范围；检索请求里就收敛，不做“先取全量再过滤”；
      2. CONFLICTED 命中不进 prompt，只产出冲突通知；
      3. stale 命中保留，但打 `stale_kb` 标记，不得当成默认值来源；
      4. 超预算先丢知识、再丢证据索引；系统策略与任务事实永不丢。
    """

    def __init__(
        self, *, task_facts: TaskFactsPort, knowledge: KnowledgePort, evidence: EvidenceIndexPort
    ) -> None:
        self._task_facts = task_facts
        self._knowledge = knowledge
        self._evidence = evidence

    def assemble(self, identity: RoleIdentity, assign: TaskAssign) -> AgentContext:
        """装配一次上下文；范围越界或超预算即抛。"""
        spec = ROLE_SPECS[identity.role]
        node = self._task_facts.node(assign.task_id, assign.node_id)
        goal = self._task_facts.goal(assign.task_id)

        query = KnowledgeQuery(
            text=f"{goal} {node.node_type} {node.template_id}",
            ktypes=tuple(sorted(spec.context_scope.knowledge_kinds)),
            scope_prefix="",
            limit=5,
            allow_stale=True,
        )
        result = self._knowledge.retrieve(query)

        # 2. 冲突：不注入，只上报
        conflicts = result.conflicts
        injectable_hits = tuple(
            hit for hit in result.hits if hit.injectable and hit.status != "CONFLICTED"
        )
        # 3. stale 标记
        stale_kids = tuple(sorted(hit.kid for hit in injectable_hits if hit.stale_kb))

        # 4. 证据索引：等级按角色范围收敛，只取元数据
        evidence = tuple(
            fact
            for fact in self._task_facts_evidence(assign.task_id, spec.context_scope.evidence_levels)
        )

        # 5. token 预算：先丢知识，再丢证据
        policy_section = PromptSection(
            PromptKind.SYSTEM_POLICY, TrustLevel.TRUSTED, spec.system_policy, "system_policy"
        )
        task_text = f"goal={goal}\nnode={node.node_id}\ntype={node.node_type}\ntemplate={node.template_id}"
        base_tokens = estimate_tokens(policy_section.text) + estimate_tokens(task_text)
        if base_tokens > spec.context_scope.max_context_tokens:
            raise ContextOverflow("CONTEXT_OVERFLOW_POLICY", f"{base_tokens}>{spec.context_scope.max_context_tokens}")

        knowledge = list(injectable_hits)
        evidence_list = list(evidence)
        dropped_knowledge = 0
        dropped_evidence = 0

        def total() -> int:
            tokens = base_tokens
            for hit in knowledge:
                tokens += estimate_tokens(hit.match_reason) + 16  # 16 ≈ 元数据开销
            for fact in evidence_list:
                tokens += 24
            return tokens

        while total() > spec.context_scope.max_context_tokens and knowledge:
            knowledge.pop()
            dropped_knowledge += 1
        while total() > spec.context_scope.max_context_tokens and evidence_list:
            evidence_list.pop()
            dropped_evidence += 1
        if total() > spec.context_scope.max_context_tokens:
            raise ContextOverflow("CONTEXT_OVERFLOW_HARD", f"{total()}>{spec.context_scope.max_context_tokens}")

        return AgentContext(
            identity=identity,
            goal=goal,
            node=node,
            knowledge=tuple(knowledge),
            evidence=tuple(evidence_list),
            conflicts=conflicts,
            stale_kids=stale_kids,
            estimated_tokens=total(),
            dropped_knowledge=dropped_knowledge,
            dropped_evidence=dropped_evidence,
        )

    def _task_facts_evidence(self, task_id: str, levels: frozenset[str]) -> tuple[EvidenceFacts, ...]:
        """证据索引由端口提供；本方法只做等级收敛，端口缺失即空（不伪造）。"""
        return tuple(self._evidence.list_for_task(task_id, levels=tuple(sorted(levels)), limit=20))


# ---------------------------------------------------------------------------
# 2. 输出校验：严格 JSON + 越权键扫描 + 角色语义
# ---------------------------------------------------------------------------
class OutputInvalid(RuntimeError):
    """模型输出不合法；`reason` 与 `field_path` 必须可断言。"""

    def __init__(self, reason: str, field_path: str, detail: str) -> None:
        self.error_code = "SCHEMA_INVALID"
        self.reason = reason
        self.field_path = field_path
        self.detail = detail
        super().__init__(f"[{self.error_code}] {field_path}: {reason}（{detail}）")


def _no_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise OutputInvalid("DUPLICATE_KEY", f"output.{key}", "JSON 重复键")
        result[key] = value
    return result


def _reject_constant(name: str) -> object:
    raise OutputInvalid("NON_FINITE_NUMBER", "output", name)


def loads_strict(text: str) -> object:
    """严格 JSON 解析：拒绝重复键与 NaN/Infinity（与 M01 解析层同口径）。"""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except OutputInvalid:
        raise
    except json.JSONDecodeError as exc:
        raise OutputInvalid("INVALID_JSON", "output", f"{exc.msg}@{exc.pos}") from exc


def _scan_forbidden_keys(node: object, path: str = "output") -> tuple[str, ...]:
    """递归扫描越权键；数组按下标继续。"""
    problems: list[str] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str):
                problems.append(f"{path}:NON_STRING_KEY")
                continue
            if key.strip().lower() in FORBIDDEN_OUTPUT_KEYS:
                problems.append(f"{path}.{key}:FORBIDDEN_KEY")
            problems.extend(_scan_forbidden_keys(value, f"{path}.{key}"))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            problems.extend(_scan_forbidden_keys(value, f"{path}[{index}]"))
    return tuple(problems)


@dataclass(frozen=True, slots=True)
class ParsedOutput:
    """通过校验的模型输出：一条待提交消息 + 原因说明。"""

    message: AgentMessage
    rationale: str


class OutputValidator:
    """模型输出 → 消息。只接受 `{proposal_type, rationale, payload}` 三键。"""

    def __init__(self, *, validator: MessageValidator, clock: ClockPort) -> None:
        self._validator = validator
        self._clock = clock
        self._sequence = 0

    def validate(self, response: LLMResponse, context: AgentContext, assign: TaskAssign) -> ParsedOutput:
        """六步校验；任何一步失败都抛 OutputInvalid（调用方记违规）。"""
        if response.finish_reason is not FinishReason.STOP:
            raise OutputInvalid("OUTPUT_NOT_COMPLETE", "finish_reason", response.finish_reason.value)
        parsed = loads_strict(response.text)
        if not isinstance(parsed, Mapping):
            raise OutputInvalid("OUTPUT_NOT_OBJECT", "output", type(parsed).__name__)
        if set(parsed) != {"proposal_type", "rationale", "payload"}:
            raise OutputInvalid("OUTPUT_KEYS_MISMATCH", "output", str(sorted(parsed)))

        forbidden = _scan_forbidden_keys(parsed)
        if forbidden:
            raise OutputInvalid("OUTPUT_ATTEMPTS_WRITE", forbidden[0].split(":")[-1], forbidden[0])

        proposal_raw = parsed["proposal_type"]
        if not isinstance(proposal_raw, str):
            raise OutputInvalid("PROPOSAL_TYPE_NOT_STRING", "proposal_type", type(proposal_raw).__name__)
        if proposal_raw not in {t.value for t in MessageType}:
            raise OutputInvalid("UNKNOWN_PROPOSAL_TYPE", "proposal_type", proposal_raw)
        message_type = MessageType(proposal_raw)
        if message_type is MessageType.PROGRESS:
            raise OutputInvalid("PROGRESS_IS_GATEWAY_ONLY", "proposal_type", "PROGRESS 由 gateway 生成")
        if message_type is MessageType.TASK_ASSIGN:
            raise OutputInvalid("AGENT_CANNOT_ASSIGN_TASK", "proposal_type", "TASK_ASSIGN 只能由 Scheduler 发")
        if message_type is MessageType.VERDICT:
            raise OutputInvalid("AGENT_CANNOT_VERDICT", "proposal_type", "VERDICT 只能由 Verifier 发")

        rationale = parsed["rationale"]
        if not isinstance(rationale, str) or len(rationale.strip()) < 10:
            raise OutputInvalid("RATIONALE_TOO_SHORT", "rationale", "需要 >=10 字符的理由")

        payload_raw = parsed["payload"]
        if not isinstance(payload_raw, Mapping):
            raise OutputInvalid("PAYLOAD_NOT_OBJECT", "payload", type(payload_raw).__name__)
        payload = parse_payload(message_type, payload_raw)

        # 角色语义
        validation_context = RoleValidationContext(
            allowed_templates=frozenset({context.node.template_id}),
            graph_version=None,
            allowed_checks=frozenset(context.node.required_checks),
        )
        problems = validate_role_output(context.identity.role, message_type, payload, validation_context)
        if problems:
            raise OutputInvalid("ROLE_OUTPUT_VIOLATION", "payload", ";".join(problems))

        # 方向 + 证据存在性 + 重放
        message = AgentMessage(
            meta=self._meta(assign, context.identity.role, message_type),
            payload=payload,
        )
        self._validator.validate(message)
        return ParsedOutput(message=message, rationale=rationale)

    def _meta(self, assign: TaskAssign, role: RoleId, message_type: MessageType) -> MessageMeta:
        """生成信封。message_id 由确定性输入 + 序号构成，重放防护在 validator。"""
        self._sequence += 1
        sent_at = self._clock.utc_now_iso()
        raw = f"{assign.task_id}|{assign.node_id}|{role.value}|{message_type.value}|{self._sequence}|{sent_at}"
        message_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]  # LIB: hashlib.sha256
        receiver = Endpoint.VERIFIER if message_type is MessageType.VERIFY_REQUEST else Endpoint.SCHEDULER
        return MessageMeta(
            message_id=message_id,
            task_id=assign.task_id,
            sender=Endpoint(role.value),
            receiver=receiver,
            sent_at=sent_at,
            correlation_id=f"{assign.task_id}:{assign.node_id}:{role.value}",
            contract_version=ROLE_CONTRACT_VERSION,
        )


# ---------------------------------------------------------------------------
# 3. 调度结果
# ---------------------------------------------------------------------------
class DispatchStatus(StrEnum):
    PROPOSED = "PROPOSED"
    FALLBACK = "FALLBACK"
    ROLE_DISABLED = "ROLE_DISABLED"
    REFUSED = "REFUSED"
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
    OUTPUT_REJECTED = "OUTPUT_REJECTED"
    AUDIT_DEGRADED = "AUDIT_DEGRADED"
    SUBMIT_FAILED = "SUBMIT_FAILED"


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    """一次角色调度的终态。`messages` 是提案，不是已生效的变更。"""

    status: DispatchStatus
    role: RoleId
    messages: tuple[AgentMessage, ...]
    error_code: str | None
    reason: str | None
    fallback: RoleFallback | None
    off_contract: RoleOffContract | None
    prompt_tokens: int
    completion_tokens: int
    cache_hit: bool
    audit_id: str | None
    detail: str

    def __post_init__(self) -> None:
        if self.status is DispatchStatus.PROPOSED and (self.error_code or not self.messages):
            raise ValueError("GW-OUT: PROPOSED 必须至少一条消息且无错误码")
        if self.status is not DispatchStatus.PROPOSED and not self.reason:
            raise ValueError("GW-OUT: 非 PROPOSED 必须给 reason")
        if self.status is DispatchStatus.ROLE_DISABLED and self.off_contract is None:
            raise ValueError("GW-OUT: ROLE_DISABLED 必须带 role_off 契约")

    def as_log_fields(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "role": self.role.value,
            "message_types": [m.message_type.value for m in self.messages],
            "error_code": self.error_code,
            "reason": self.reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cache_hit": self.cache_hit,
            "audit_id": self.audit_id,
        }


# ---------------------------------------------------------------------------
# 4. Gateway 主体
# ---------------------------------------------------------------------------
class AgentGateway:
    """角色调度器。九步，任何一步失败都返回结构化终态。

      1. feature gate：`agents=false` → REFUSED（T0 只有接口，没有行为）；
      2. role_off：关闭的角色 → ROLE_DISABLED + 显式回退，不转给别的角色；
      3. 身份：版本/策略哈希与角色规格核对；
      4. 上下文：只给角色范围，冲突不注入，超预算升级；
      5. 调模型：统一客户端（预算/缓存/超时/回退）；
      6. fallback：模型不可用 → 角色确定性回退，不伪造内容；
      7. 输出校验：严格 JSON + 越权键 + 角色语义 + 消息方向；
      8. 审计：提交提案前先写审计，失败不提交；
      9. 提交：只调用 SchedulerPort.submit（提案），不落库、不改状态。
    """

    def __init__(
        self,
        *,
        flags: Mapping[str, bool],
        assembler: ContextAssembler,
        client: LLMClient,
        output_validator: OutputValidator,
        roles: RoleOffRegistry,
        scheduler: SchedulerPort | None,
        audit: AgentAuditPort | None,
        violation_sink: ViolationSinkPort,
        clock: ClockPort,
    ) -> None:
        self._flags = dict(flags)
        self._assembler = assembler
        self._client = client
        self._validator = output_validator
        self._roles = roles
        self._scheduler = scheduler
        self._audit = audit
        self._violation_sink = violation_sink
        self._clock = clock

    # -- 公共入口 ---------------------------------------------------------
    def dispatch(self, message: AgentMessage) -> DispatchOutcome:
        """执行一次角色调度。入参必须是 Scheduler 发来的 TASK_ASSIGN。"""
        if not isinstance(message.payload, TaskAssign):
            return self._refuse(message, DispatchStatus.REFUSED, "SCHEMA_INVALID", "DISPATCH_EXPECTS_TASK_ASSIGN")
        assign = message.payload
        if message.meta.sender is not Endpoint.SCHEDULER:
            return self._refuse(message, DispatchStatus.REFUSED, "SCHEMA_INVALID", "TASK_ASSIGN_NOT_FROM_SCHEDULER")
        if message.meta.receiver not in AGENT_ENDPOINTS:
            return self._refuse(message, DispatchStatus.REFUSED, "SCHEMA_INVALID", "TASK_ASSIGN_RECEIVER_NOT_AGENT")
        if message.meta.task_id != assign.task_id:
            return self._refuse(message, DispatchStatus.REFUSED, "SCHEMA_INVALID", "META_PAYLOAD_TASK_MISMATCH")
        role = RoleId(message.meta.receiver.value)

        # 1. feature gate
        if not self._flags.get("agents", False):
            return self._refuse(
                message, DispatchStatus.REFUSED, "FEATURE_FLAG_NOT_PERMITTED",
                "AGENTS_DISABLED_IN_THIS_TIER",
            )

        # 2. role_off
        try:
            self._roles.require_active(role)
        except Exception as exc:  # noqa: BLE001 - 关闭是显式终态
            off = ROLE_OFF_CONTRACTS[role]
            fallback = role_class(role)().fallback()
            messages: tuple[AgentMessage, ...] = ()
            if fallback.emits_messages:
                messages = (self._escalate(assign, role, EscalationReason.ROLE_DISABLED,
                                           (EscalationNeed.HUMAN_DECISION,), ()),)
            return DispatchOutcome(
                status=DispatchStatus.ROLE_DISABLED, role=role, messages=messages,
                error_code="FEATURE_FLAG_NOT_PERMITTED", reason="ROLE_DISABLED",
                fallback=fallback, off_contract=off, prompt_tokens=0, completion_tokens=0,
                cache_hit=False, audit_id=None, detail=type(exc).__name__,
            )

        # 3. 身份
        identity = identity_for(role)
        if assign.contract_version != identity.contract_version:
            return self._refuse(
                message, DispatchStatus.REFUSED, "SCHEMA_INVALID", "ROLE_CONTRACT_VERSION_MISMATCH"
            )

        # 4. 上下文
        try:
            context = self._assembler.assemble(identity, assign)
        except ContextOverflow as exc:
            return DispatchOutcome(
                status=DispatchStatus.CONTEXT_INSUFFICIENT, role=role,
                messages=(self._escalate(assign, role, EscalationReason.INSUFFICIENT_CONTEXT,
                                          (EscalationNeed.HUMAN_DECISION,), ()),),
                error_code=exc.error_code, reason=exc.reason,
                fallback=None, off_contract=None, prompt_tokens=0, completion_tokens=0,
                cache_hit=False, audit_id=None, detail=exc.detail,
            )
        except Exception as exc:  # noqa: BLE001 - 端口故障不得冒泡到调度器
            return self._refuse(message, DispatchStatus.REFUSED, "AUDIT_WRITE_FAILED", f"CONTEXT_ASSEMBLY_FAILED:{type(exc).__name__}")

        # 4b. 冲突知识：不注入、由人裁决；模型不得自选版本
        if context.conflicts:
            return DispatchOutcome(
                status=DispatchStatus.CONTEXT_INSUFFICIENT, role=role,
                messages=(self._escalate(
                    assign, role, EscalationReason.KNOWLEDGE_CONFLICT,
                    (EscalationNeed.APPROVED_KNOWLEDGE_VERSION, EscalationNeed.HUMAN_DECISION), (),
                ),),
                error_code="STATE_TRANSITION_DENIED", reason="KNOWLEDGE_CONFLICT_REQUIRES_HUMAN",
                fallback=None, off_contract=None, prompt_tokens=0, completion_tokens=0,
                cache_hit=False, audit_id=None,
                detail=";".join(f"{c.ktype}:{c.scope}" for c in context.conflicts),
            )

        # 5. 调模型
        try:
            request = self._build_request(assign, context)
            response = self._client.complete(request)
        except LLMBudgetExceeded as exc:
            return DispatchOutcome(
                status=DispatchStatus.REFUSED, role=role,
                messages=(self._escalate(assign, role, EscalationReason.BUDGET_EXHAUSTED,
                                          (EscalationNeed.MORE_BUDGET,), ()),),
                error_code=exc.error_code, reason=exc.reason,
                fallback=None, off_contract=None, prompt_tokens=0, completion_tokens=0,
                cache_hit=False, audit_id=None, detail=exc.detail,
            )
        except Exception as exc:  # noqa: BLE001 - 请求装配/渲染失败必须结构化
            return self._refuse(message, DispatchStatus.REFUSED, "SCHEMA_INVALID", f"AGENT_REQUEST_INVALID:{type(exc).__name__}")

        # 6. fallback
        if response.finish_reason is FinishReason.FALLBACK:
            fallback = role_class(role)().fallback()
            messages = ()
            if fallback.emits_messages:
                messages = (self._escalate(assign, role, EscalationReason.MODEL_UNAVAILABLE,
                                            (EscalationNeed.HUMAN_DECISION,), ()),)
            audit_id = self._record_audit(assign, role, DispatchStatus.FALLBACK, messages, None, response, ())
            return DispatchOutcome(
                status=DispatchStatus.FALLBACK, role=role, messages=messages,
                error_code=None, reason=f"MODEL_FALLBACK:{response.fallback_reason.value if response.fallback_reason else 'UNKNOWN'}",
                fallback=fallback, off_contract=None,
                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
                cache_hit=response.cache_hit, audit_id=audit_id, detail=fallback.behavior,
            )

        # 7. 输出校验
        try:
            parsed = self._validator.validate(response, context, assign)
        except (OutputInvalid, MessageRejected, ValueError) as exc:
            reasons = (getattr(exc, "reason", None) or type(exc).__name__,)
            violation = self._record_violation(assign, role, reasons[0])
            self._record_audit(assign, role, DispatchStatus.OUTPUT_REJECTED, (), None, response, reasons)
            return DispatchOutcome(
                status=DispatchStatus.OUTPUT_REJECTED, role=role, messages=(),
                error_code=getattr(exc, "error_code", "SCHEMA_INVALID"),
                reason=reasons[0],
                fallback=None, off_contract=None,
                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
                cache_hit=response.cache_hit, audit_id=None,
                detail=f"{exc}; violation_id={violation or 'NOT_RECORDED'}",
            )

        messages = (parsed.message,)

        # 8. 审计（提交前）
        audit_id = self._record_audit(assign, role, DispatchStatus.PROPOSED, messages, parsed.rationale, response, ())
        if audit_id is None:
            return DispatchOutcome(
                status=DispatchStatus.AUDIT_DEGRADED, role=role, messages=(),
                error_code="AUDIT_WRITE_FAILED", reason="AGENT_AUDIT_UNAVAILABLE",
                fallback=None, off_contract=None,
                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
                cache_hit=response.cache_hit, audit_id=None, detail="proposal withheld",
            )

        # 9. 提交提案
        if self._scheduler is None:
            return DispatchOutcome(
                status=DispatchStatus.SUBMIT_FAILED, role=role, messages=(),
                error_code="AUDIT_WRITE_FAILED", reason="SCHEDULER_PORT_UNAVAILABLE",
                fallback=None, off_contract=None,
                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
                cache_hit=response.cache_hit, audit_id=audit_id, detail="proposal withheld",
            )
        try:
            self._scheduler.submit(parsed.message)
        except Exception as exc:  # noqa: BLE001 - 提交失败不得重试成“已提交”
            return DispatchOutcome(
                status=DispatchStatus.SUBMIT_FAILED, role=role, messages=(),
                error_code="AUDIT_WRITE_FAILED", reason="SCHEDULER_SUBMIT_FAILED",
                fallback=None, off_contract=None,
                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
                cache_hit=response.cache_hit, audit_id=audit_id, detail=type(exc).__name__,
            )

        return DispatchOutcome(
            status=DispatchStatus.PROPOSED, role=role, messages=messages,
            error_code=None, reason=None, fallback=None, off_contract=None,
            prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
            cache_hit=response.cache_hit, audit_id=audit_id, detail=parsed.rationale,
        )

    # -- 内部 -------------------------------------------------------------
    def _refuse(self, message: AgentMessage, status: DispatchStatus, code: str, reason: str) -> DispatchOutcome:
        """在调用模型之前拒绝；角色从信封接收方取，取不到按 planner 记录（不冒充已调度）。"""
        role = RoleId.PLANNER
        try:
            if message.meta.receiver in AGENT_ENDPOINTS:
                role = RoleId(message.meta.receiver.value)
        except ValueError:
            role = RoleId.PLANNER
        return DispatchOutcome(
            status=status, role=role, messages=(), error_code=code, reason=reason,
            fallback=None, off_contract=None, prompt_tokens=0, completion_tokens=0,
            cache_hit=False, audit_id=None, detail="refused before model call",
        )

    def _build_request(self, assign: TaskAssign, context: AgentContext) -> LLMRequest:
        """装配 PromptSection：系统策略可信，知识与证据索引均为资料。"""
        spec = ROLE_SPECS[context.identity.role]
        sections: list[PromptSection] = [
            PromptSection(PromptKind.SYSTEM_POLICY, TrustLevel.TRUSTED, spec.system_policy, "system_policy"),
            PromptSection(
                PromptKind.TASK_FACT,
                TrustLevel.TRUSTED,
                f"goal={context.goal}\nnode={context.node.node_id}\ntype={context.node.node_type}\n"
                f"template={context.node.template_id}\nrequired_checks={','.join(context.node.required_checks)}",
                "task_fact",
            ),
        ]
        for hit in context.knowledge:
            sections.append(
                PromptSection(
                    PromptKind.KNOWLEDGE,
                    TrustLevel.UNTRUSTED,
                    f"[{hit.ktype}] {hit.match_reason}\nstale={hit.stale_kb}\nscope={hit.scope}",
                    f"{hit.kid}@{hit.version}#{hit.content_hash[:12]}",
                )
            )
        if context.evidence:
            index_text = "\n".join(
                f"{fact.evidence_id} {fact.level} {fact.kind} producer={fact.producer}" for fact in context.evidence
            )
            sections.append(PromptSection(PromptKind.EVIDENCE_INDEX, TrustLevel.TRUSTED, index_text, "evidence_index"))
        return LLMRequest(
            role=context.identity.role,
            task_id=assign.task_id,
            node_id=assign.node_id,
            sections=tuple(sections),
            max_tokens=PROPOSED_MAX_TOKENS,
            timeout_sec=PROPOSED_TIMEOUT_SEC,
            max_context_tokens=spec.context_scope.max_context_tokens,
            request_id=f"{assign.task_id}:{assign.node_id}:{context.identity.role.value}",
        )

    def _escalate(
        self,
        assign: TaskAssign,
        role: RoleId,
        reason: EscalationReason,
        needs: tuple[EscalationNeed, ...],
        evidence_ids: tuple[str, ...],
    ) -> AgentMessage:
        """Gateway 自身生成的 ESCALATE（不冒用模型输出）。"""
        self._seq = getattr(self, "_seq", 0) + 1
        sent_at = self._clock.utc_now_iso()
        raw = f"{assign.task_id}|{assign.node_id}|{role.value}|ESCALATE|{self._seq}|{sent_at}"
        meta = MessageMeta(
            message_id=hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32],  # LIB: hashlib.sha256
            task_id=assign.task_id,
            sender=Endpoint(role.value),
            receiver=Endpoint.SCHEDULER,
            sent_at=sent_at,
            correlation_id=f"{assign.task_id}:{assign.node_id}:{role.value}",
            contract_version=ROLE_CONTRACT_VERSION,
        )
        return AgentMessage(meta=meta, payload=Escalate(reason=reason, needs=needs, blocking_evidence_ids=evidence_ids))

    def _record_audit(
        self,
        assign: TaskAssign,
        role: RoleId,
        status: DispatchStatus,
        messages: tuple[AgentMessage, ...],
        rationale: str | None,
        response: LLMResponse,
        violations: tuple[str, ...],
    ) -> str | None:
        """写运行审计；返回 audit_id，失败返回 None（调用方据此拒绝提交）。"""
        if self._audit is None:
            return None
        digest = None
        if messages:
            digest = hashlib.sha256(  # LIB: hashlib.sha256
                "|".join(m.meta.message_id for m in messages).encode("utf-8")
            ).hexdigest()
        record = AgentAuditRecord(
            task_id=assign.task_id,
            node_id=assign.node_id,
            role=role,
            contract_version=ROLE_CONTRACT_VERSION,
            status=status.value,
            message_types=tuple(m.message_type.value for m in messages),
            output_digest=digest,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            cache_hit=response.cache_hit,
            fallback_reason=None if response.fallback_reason is None else response.fallback_reason.value,
            violations=violations,
            correlation_id=f"{assign.task_id}:{assign.node_id}:{role.value}",
            started_at=self._clock.utc_now_iso(),
        )
        try:
            return self._audit.record(record)
        except Exception:  # noqa: BLE001 - 审计失败必须让调用方拒交提案
            return None

    def _record_violation(self, assign: TaskAssign, role: RoleId, reason: str) -> str:
        """把输出违规写入协议违规流；写失败也不得静默，但返回值仅作审计提示。"""
        try:
            return self._violation_sink.record(
                _violation(assign.task_id, role, reason)
            )
        except Exception:  # noqa: BLE001
            return ""


def _violation(task_id: str, role: RoleId, reason: str):  # noqa: ANN201 - ProtocolViolation
    from .messages import ProtocolViolation

    return ProtocolViolation(
        task_id=task_id,
        message_type="OUTPUT_VALIDATION",
        sender=role.value,
        reason=reason,
        offending=(reason,),
    )


# ---------------------------------------------------------------------------
# 5. 静态守卫
# ---------------------------------------------------------------------------
def assert_context_scope_only(context: AgentContext) -> tuple[str, ...]:
    """上下文中所有知识与证据都必须在角色范围内；冲突知识不得出现。"""
    problems: list[str] = []
    spec = ROLE_SPECS[context.identity.role]
    extra = context.knowledge_kinds() - spec.context_scope.knowledge_kinds
    if extra:
        problems.append(f"KNOWLEDGE_OUT_OF_SCOPE:{sorted(extra)[0]}")
    levels = context.evidence_levels() - spec.context_scope.evidence_levels
    if levels:
        problems.append(f"EVIDENCE_LEVEL_OUT_OF_SCOPE:{sorted(levels)[0]}")
    if any(hit.status == "CONFLICTED" for hit in context.knowledge):
        problems.append("CONFLICTED_KNOWLEDGE_INJECTED")
    if context.estimated_tokens > spec.context_scope.max_context_tokens:
        problems.append("CONTEXT_OVER_BUDGET")
    return tuple(problems)


def assert_no_write_surface() -> tuple[str, ...]:
    """AgentGateway 不得有状态/证据/签名写入口。"""
    problems: list[str] = []
    forbidden = ("transition", "write_state", "append_evidence", "write_evidence", "sign", "issue_certificate", "persist")
    for name in dir(AgentGateway):
        if name.startswith("_"):
            continue
        if any(fragment in name for fragment in forbidden):
            problems.append(f"AgentGateway 暴露了 {name}")
    if not hasattr(SchedulerPort, "submit"):
        problems.append("SchedulerPort 缺少 submit（提案入口）")
    if hasattr(SchedulerPort, "apply") or hasattr(SchedulerPort, "transition"):
        problems.append("SchedulerPort 不得提供 apply/transition")
    return tuple(problems)