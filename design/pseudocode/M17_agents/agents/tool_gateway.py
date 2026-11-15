"""MODULE：M17 · agents/tool_gateway.py — Agent 工具调用的唯一出口（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-012（越权工具调用、未注册工具）｜策划书 §10.2 TABLE 41、§5.7 工具契约、附录 E.3 TOOL_NOT_ALLOWLISTED
FR+依赖：FR-012；依赖 contracts.py（角色身份/工具目录/禁用能力）、M05 registry（参数 Schema 同源）、M03 limits、M07 Collector（E1 写入）
不变量+错误码：所有 Agent 工具调用只经本文件；未注册/非白名单/禁用能力一律 403；参数 Schema 不符、超时、预算、审计、证据记录各有显式分支；
              TOOL_NOT_ALLOWLISTED(403) / SCHEMA_INVALID(422) / RESOURCE_BUDGET_EXCEEDED(429) / AUDIT_WRITE_FAILED(503)
写入者：无直接写入。审计经 ToolAuditPort（持久化仍由 StateMachine/审计表承担）；
        E1 由 Collector 经 EvidenceEventPort 追加；本文件不写状态、不写证据库、不读密钥。
状态：伪代码；不执行真实工具、不启动子进程。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol

from .contracts import (
    AGENT_TOOL_CATALOG,
    AgentToolSpec,
    Axis,
    RoleId,
    RoleIdentity,
    ToolAccess,
    authorize_agent,
    is_forbidden_tool,
)

__all__ = [
    "MAX_TOOL_TIMEOUT_SEC",
    "PROPOSED_TOOL_BUDGET",
    "ParamKind",
    "ParamSpec",
    "RegisteredTool",
    "RunnerOutcome",
    "RunnerStatus",
    "ToolArgsInvalid",
    "ToolAuditOutcome",
    "ToolAuditPort",
    "ToolAuditRecord",
    "ToolBudget",
    "ToolBudgetTracker",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolCallStatus",
    "ToolEvidenceEvent",
    "ToolEvidencePort",
    "ToolGateway",
    "ToolRegistry",
    "ToolRunnerPort",
    "ToolTimeout",
    "assert_no_write_tools",
    "assert_single_egress",
    "assert_timeout_bounds",
    "build_default_registry",
]

# 工具超时上限：任何工具都不得超过（与 M05 进程回收预算对齐）。
MAX_TOOL_TIMEOUT_SEC: Final[int] = 30

# 预算常量是 P8 装配约定（OQ-P8-06），不是 G0 契约值。
PROPOSED_TOOL_BUDGET: Final[Mapping[str, int]] = MappingProxyType(
    {"max_calls_per_node": 8, "max_calls_per_task": 64, "max_consecutive_failures": 3}
)


# ---------------------------------------------------------------------------
# 0. 参数 Schema：与 M05 registry 同源（未知键拒绝，不做类型强转）
# ---------------------------------------------------------------------------
class ParamKind(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    ARRAY_STRING = "ARRAY_STRING"


class ToolArgsInvalid(RuntimeError):
    """工具参数不合法；`field_path` 必须精确到参数名。"""

    def __init__(self, reason: str, field_path: str, detail: str) -> None:
        self.reason = reason
        self.field_path = field_path
        self.detail = detail
        super().__init__(f"[TOOL_ARGS_INVALID] {field_path}: {reason}（{detail}）")


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """一个工具参数的约束。没有默认值：缺省即缺失，由 required 决定是否拒绝。"""

    name: str
    kind: ParamKind
    required: bool
    min_value: float | None = None
    max_value: float | None = None
    max_length: int | None = None
    pattern: str | None = None
    min_items: int | None = None
    max_items: int | None = None
    enum_values: tuple[str, ...] = ()

    def validate(self, value: object) -> None:
        """校验单个参数值；失败抛 ToolArgsInvalid（带字段路径）。"""
        path = f"args.{self.name}"
        if self.kind is ParamKind.STRING or self.kind is ParamKind.ARRAY_STRING:
            if self.kind is ParamKind.STRING:
                if not isinstance(value, str):
                    raise ToolArgsInvalid("TYPE_MISMATCH", path, f"应为字符串，实际 {type(value).__name__}")
                if self.max_length is not None and len(value) > self.max_length:
                    raise ToolArgsInvalid("VALUE_OUT_OF_RANGE", path, f"长度超过 {self.max_length}")
                if self.pattern is not None:
                    import re  # LIB: re（仅编译，不访问外部资源）

                    if re.fullmatch(self.pattern, value) is None:
                        raise ToolArgsInvalid("VALUE_NOT_IN_PATTERN", path, f"不匹配 {self.pattern}")
            else:
                if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
                    raise ToolArgsInvalid("TYPE_MISMATCH", path, "应为字符串数组")
                if self.min_items is not None and len(value) < self.min_items:
                    raise ToolArgsInvalid("VALUE_OUT_OF_RANGE", path, f"元素少于 {self.min_items}")
                if self.max_items is not None and len(value) > self.max_items:
                    raise ToolArgsInvalid("VALUE_OUT_OF_RANGE", path, f"元素多于 {self.max_items}")
            if self.enum_values and self.kind is ParamKind.STRING and value not in self.enum_values:
                raise ToolArgsInvalid("VALUE_NOT_IN_ENUM", path, f"允许值 {self.enum_values}")
            return
        if self.kind is ParamKind.BOOLEAN:
            if not isinstance(value, bool):
                raise ToolArgsInvalid("TYPE_MISMATCH", path, "应为布尔")
            return
        if self.kind in (ParamKind.INTEGER, ParamKind.NUMBER):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ToolArgsInvalid("TYPE_MISMATCH", path, "应为数字")
            if self.kind is ParamKind.INTEGER and not isinstance(value, int):
                raise ToolArgsInvalid("TYPE_MISMATCH", path, "应为整数")
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                raise ToolArgsInvalid("TYPE_MISMATCH", path, "不允许 NaN/Infinity")
            if self.min_value is not None and number < self.min_value:
                raise ToolArgsInvalid("VALUE_OUT_OF_RANGE", path, f"小于 {self.min_value}")
            if self.max_value is not None and number > self.max_value:
                raise ToolArgsInvalid("VALUE_OUT_OF_RANGE", path, f"大于 {self.max_value}")
            return
        raise ToolArgsInvalid("TYPE_UNSUPPORTED", path, f"未实现的参数类型 {self.kind}")


@dataclass(frozen=True, slots=True)
class ToolArgsSchema:
    """一个工具的参数 Schema。`additionalProperties=False` 的等价物：未知键拒绝。"""

    tool_name: str
    schema_id: str
    params: tuple[ParamSpec, ...]

    def __post_init__(self) -> None:
        if not self.tool_name or not self.schema_id:
            raise ValueError("TOOL-SCHEMA: tool_name/schema_id 不得为空")
        if len({p.name for p in self.params}) != len(self.params):
            raise ValueError(f"TOOL-SCHEMA: {self.tool_name} 的参数名重复")

    def validate(self, args: Mapping[str, object]) -> None:
        """按 Schema 校验整组参数：先拒未知键，再拒缺失，再逐项校验。"""
        declared = {p.name for p in self.params}
        unknown = set(args) - declared
        if unknown:
            raise ToolArgsInvalid("UNKNOWN_PARAM", f"args.{sorted(unknown)[0]}", "未知参数一律拒绝")
        for spec in self.params:
            if spec.name not in args:
                if spec.required:
                    raise ToolArgsInvalid("MISSING_PARAM", f"args.{spec.name}", "缺少必填参数")
                continue
            spec.validate(args[spec.name])


# ---------------------------------------------------------------------------
# 1. 注册表：登记即校验，禁用能力永远进不来
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """一个已注册工具。`access` 只能取 Agent 目录里的三类。"""

    spec: AgentToolSpec
    schema: ToolArgsSchema
    description: str

    def __post_init__(self) -> None:
        if self.spec.name != self.schema.tool_name:
            raise ValueError("TOOL-REG: spec.name 与 schema.tool_name 不一致")
        if self.spec.access not in (ToolAccess.READ_ONLY, ToolAccess.PURE_COMPUTE, ToolAccess.DRAFT_ONLY):
            raise ValueError("TOOL-REG: Agent 工具不得有副作用访问类别")
        if not 0 < self.spec.timeout_sec <= MAX_TOOL_TIMEOUT_SEC:
            raise ValueError("TOOL-REG: 超时必须落在 (0, 30]")
        if is_forbidden_tool(self.spec.name):
            raise ValueError(f"TOOL-REG: {self.spec.name} 命中禁用能力")


class ToolRegistry:
    """工具注册表。`register` 是唯一入口；重复注册、禁用名、越界超时都拒绝。"""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"TOOL-REG-DUP: {name} 已注册；版本升级必须换名或显式迁移")
        if tool.spec.name not in AGENT_TOOL_CATALOG:
            raise ValueError(f"TOOL-REG-CATALOG: {name} 不在 contracts.AGENT_TOOL_CATALOG")
        catalog_spec = AGENT_TOOL_CATALOG[name]
        if tool.spec != catalog_spec:
            raise ValueError(f"TOOL-REG-CATALOG: {name} 的 spec 与目录不一致（不得就地改超时/类别）")
        self._tools[name] = tool

    def resolve(self, name: str) -> RegisteredTool:
        """取工具；不存在即抛（调用方必须转 403，不得“降级到默认工具”）。"""
        if name not in self._tools:
            raise KeyError(f"TOOL-REG-MISS: {name} 未注册")
        return self._tools[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


def _p(name: str, kind: ParamKind, required: bool, **kwargs: object) -> ParamSpec:
    return ParamSpec(name=name, kind=kind, required=required, **kwargs)  # type: ignore[arg-type]


_DEFAULT_SCHEMAS: Final[Mapping[str, ToolArgsSchema]] = MappingProxyType(
    {
        "knowledge.search": ToolArgsSchema(
            "knowledge.search", "knowledge.search/1.0",
            (
                _p("query", ParamKind.STRING, True, max_length=512),
                _p("ktypes", ParamKind.ARRAY_STRING, True, min_items=1, max_items=5),
                _p("scope_prefix", ParamKind.STRING, False, max_length=200),
                _p("limit", ParamKind.INTEGER, True, min_value=1, max_value=20),
            ),
        ),
        "template.list": ToolArgsSchema("template.list", "template.list/1.0", ()),
        "template.parameterize": ToolArgsSchema(
            "template.parameterize", "template.parameterize/1.0",
            (
                _p("template_id", ParamKind.STRING, True, max_length=120),
                _p("values_json", ParamKind.STRING, True, max_length=16384),
            ),
        ),
        "dataset.schema.read": ToolArgsSchema(
            "dataset.schema.read", "dataset.schema.read/1.0",
            (_p("uri", ParamKind.STRING, True, max_length=512),),
        ),
        "dataset.profile": ToolArgsSchema(
            "dataset.profile", "dataset.profile/1.0",
            (
                _p("uri", ParamKind.STRING, True, max_length=512),
                _p("max_rows", ParamKind.INTEGER, False, min_value=1, max_value=1_000_000),
            ),
        ),
        "metrics.read": ToolArgsSchema(
            "metrics.read", "metrics.read/1.0", (_p("artifact_ref", ParamKind.STRING, True, max_length=512),)
        ),
        "predictions.summary.read": ToolArgsSchema(
            "predictions.summary.read", "predictions.summary.read/1.0",
            (_p("artifact_ref", ParamKind.STRING, True, max_length=512),),
        ),
        "error.signature.read": ToolArgsSchema(
            "error.signature.read", "error.signature.read/1.0",
            (_p("node_id", ParamKind.STRING, True, max_length=120),),
        ),
        "recovery.plan.validate": ToolArgsSchema(
            "recovery.plan.validate", "recovery.plan.validate/1.0",
            (_p("plan_hash", ParamKind.STRING, True, pattern=r"[0-9a-f]{64}"),),
        ),
        "evidence.index.read": ToolArgsSchema(
            "evidence.index.read", "evidence.index.read/1.0",
            (
                _p("task_id", ParamKind.STRING, True, max_length=120),
                _p("node_id", ParamKind.STRING, False, max_length=120),
                _p("limit", ParamKind.INTEGER, True, min_value=1, max_value=200),
            ),
        ),
        "ruleset.read": ToolArgsSchema(
            "ruleset.read", "ruleset.read/1.0",
            (_p("ruleset_hash", ParamKind.STRING, True, pattern=r"[0-9a-f]{64}"),),
        ),
        "verification.plan.draft": ToolArgsSchema(
            "verification.plan.draft", "verification.plan.draft/1.0",
            (_p("node_ids", ParamKind.ARRAY_STRING, True, min_items=1, max_items=64),),
        ),
    }
)


def build_default_registry() -> ToolRegistry:
    """按 contracts 目录装配注册表；目录缺 Schema 即失败（不允许先跑起来）。"""
    registry = ToolRegistry()
    for name, spec in AGENT_TOOL_CATALOG.items():
        schema = _DEFAULT_SCHEMAS.get(name)
        if schema is None:
            raise ValueError(f"TOOL-REG-SCHEMA: {name} 没有参数 Schema，拒绝启动")
        registry.register(RegisteredTool(spec=spec, schema=schema, description=name))
    return registry


# ---------------------------------------------------------------------------
# 2. 端口：审计、执行、E1 事件、时钟
# ---------------------------------------------------------------------------
class ToolAuditPort(Protocol):
    """工具调用审计。`begin` 返回 audit_id；`finish` 必须写完成态。"""

    def begin(self, record: "ToolAuditRecord") -> str: ...

    def finish(self, audit_id: str, outcome: "ToolAuditOutcome") -> None: ...


class ClockPort(Protocol):
    """单调时钟 + UTC 墙钟；超时只用单调时钟。"""

    def monotonic(self) -> float: ...

    def utc_now_iso(self) -> str: ...


class RunnerStatus(StrEnum):
    EXITED = "EXITED"
    TIMEOUT = "TIMEOUT"
    KILLED = "KILLED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class RunnerOutcome:
    """执行端返回的事实（不是裁决）。`child_tree_reclaimed` 决定是否需要升级。"""

    status: RunnerStatus
    exit_code: int | None
    value: object
    error_text: str
    child_tree_reclaimed: bool

    def __post_init__(self) -> None:
        if self.status is RunnerStatus.EXITED and self.exit_code is None:
            raise ValueError("TOOL-RUN: EXITED 必须带 exit_code")
        if self.status is RunnerStatus.TIMEOUT and not self.error_text:
            raise ValueError("TOOL-RUN: TIMEOUT 必须给原因")


class ToolRunnerPort(Protocol):
    """唯一执行端口。实现方（M05 进程层）必须按 timeout 杀进程树。"""

    def run(self, *, tool: RegisteredTool, args: Mapping[str, object], timeout_sec: int) -> RunnerOutcome: ...


@dataclass(frozen=True, slots=True)
class ToolEvidenceEvent:
    """提交给 Collector 的 E1 观测（level/kind 固定，producer 由 Collector 填）。"""

    task_id: str
    node_id: str
    attempt_id: str
    tool_name: str
    role: RoleId
    args_hash: str
    result_hash: str
    status: str
    elapsed_ms: int
    correlation_id: str
    level: str = "E1"
    kind: str = "tool_invocation"

    def __post_init__(self) -> None:
        if self.level != "E1":
            raise ValueError("TOOL-EV: Agent 工具观测只能是 E1")
        if self.kind != "tool_invocation":
            raise ValueError("TOOL-EV: Agent 工具观测的 kind 只能是 tool_invocation")


class ToolEvidencePort(Protocol):
    """把工具调用观测交给 Collector（本文件不写证据库）。返回事件 ID。"""

    def submit(self, event: ToolEvidenceEvent) -> str: ...


@dataclass(frozen=True, slots=True)
class ToolAuditRecord:
    """审计开始记录。**不含参数值**，只存哈希与键名（数据最小化）。"""

    task_id: str
    node_id: str
    attempt_id: str
    role: RoleId
    tool_name: str
    args_hash: str
    arg_keys: tuple[str, ...]
    correlation_id: str
    started_at: str

    def __post_init__(self) -> None:
        if len(self.args_hash) != 64:
            raise ValueError("TOOL-AUDIT: args_hash 必须是 64 位十六进制")
        if len(set(self.arg_keys)) != len(self.arg_keys):
            raise ValueError("TOOL-AUDIT: arg_keys 不得重复")


@dataclass(frozen=True, slots=True)
class ToolAuditOutcome:
    """审计完成记录。失败原因也要写，不允许只写成功。"""

    status: str
    elapsed_ms: int
    error_code: str | None
    reason: str | None
    evidence_event_id: str | None

    def __post_init__(self) -> None:
        if self.status == "OK" and (self.error_code or self.reason):
            raise ValueError("TOOL-AUDIT: 成功态不得携带失败原因")
        if self.status != "OK" and not (self.error_code and self.reason):
            raise ValueError("TOOL-AUDIT: 失败态必须带 error_code 与 reason")


# ---------------------------------------------------------------------------
# 3. 预算
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ToolBudget:
    """按节点/任务的调用预算。缺省值来自 PROPOSED_TOOL_BUDGET（非契约）。"""

    max_calls_per_node: int = PROPOSED_TOOL_BUDGET["max_calls_per_node"]
    max_calls_per_task: int = PROPOSED_TOOL_BUDGET["max_calls_per_task"]

    def __post_init__(self) -> None:
        if self.max_calls_per_node < 1 or self.max_calls_per_task < self.max_calls_per_node:
            raise ValueError("TOOL-BUDGET: 预算是正数，且任务上限不得低于节点上限")


class ToolBudgetTracker:
    """调用计数。超限抛 ToolTimeout 之外的 429 语义（由 gateway 转 ToolCallResult）。"""

    def __init__(self, budget: ToolBudget) -> None:
        self._budget = budget
        self._by_node: dict[tuple[str, str], int] = {}
        self._by_task: dict[str, int] = {}

    def consume(self, task_id: str, node_id: str) -> None:
        node_calls = self._by_node.get((task_id, node_id), 0) + 1
        task_calls = self._by_task.get(task_id, 0) + 1
        if node_calls > self._budget.max_calls_per_node:
            raise ToolTimeout("RESOURCE_BUDGET_EXCEEDED", "TOOL_CALL_LIMIT_PER_NODE", "node_id", str(node_calls))
        if task_calls > self._budget.max_calls_per_task:
            raise ToolTimeout("RESOURCE_BUDGET_EXCEEDED", "TOOL_CALL_LIMIT_PER_TASK", "task_id", str(task_calls))
        self._by_node[(task_id, node_id)] = node_calls
        self._by_task[task_id] = task_calls

    def snapshot(self) -> Mapping[str, int]:
        return MappingProxyType(
            {"nodes": len(self._by_node), "calls": sum(self._by_task.values())}
        )


class ToolTimeout(RuntimeError):
    """超时/预算类拒绝（不是执行失败）。"""

    def __init__(self, code: str, reason: str, field_path: str, detail: str) -> None:
        self.code = code
        self.reason = reason
        self.field_path = field_path
        self.detail = detail
        super().__init__(f"[{code}] {field_path}: {reason}（{detail}）")


# ---------------------------------------------------------------------------
# 4. 请求/结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """一次工具调用申请。`identity` 由 gateway 装配，不接受调用方自报白名单。"""

    identity: RoleIdentity
    tool_name: str
    args: Mapping[str, object]
    task_id: str
    node_id: str
    attempt_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        if not self.identity.role:
            raise ValueError("TOOL-REQ: 缺少角色身份")
        if not self.task_id.startswith("task_"):
            raise ValueError("TOOL-REQ: task_id 形态非法")
        if not self.node_id or not self.attempt_id or not self.correlation_id:
            raise ValueError("TOOL-REQ: node/attempt/correlation 不得为空")
        if not isinstance(self.args, Mapping):
            raise ValueError("TOOL-REQ: args 必须是对象")


class ToolCallStatus(StrEnum):
    OK = "OK"
    DENIED = "DENIED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    AUDIT_DEGRADED = "AUDIT_DEGRADED"


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """工具调用结果。`value_withheld=True` 时调用方不得使用 value。"""

    status: ToolCallStatus
    value: object
    error_code: str | None
    reason: str | None
    field_path: str | None
    elapsed_ms: int
    audit_id: str | None
    evidence_event_id: str | None
    value_withheld: bool

    def __post_init__(self) -> None:
        if self.status is ToolCallStatus.OK and (self.error_code or self.value_withheld):
            raise ValueError("TOOL-RES: OK 不得带错误码或扣留 value")
        if self.status is not ToolCallStatus.OK and not self.reason:
            raise ValueError("TOOL-RES: 非 OK 必须给 reason")
        if self.value_withheld and self.value is not None:
            raise ValueError("TOOL-RES: 扣留 value 时 value 必须为 None")

    def as_detail(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "error_code": self.error_code,
            "reason": self.reason,
            "field_path": self.field_path,
            "elapsed_ms": self.elapsed_ms,
            "audit_id": self.audit_id,
            "evidence_event_id": self.evidence_event_id,
            "value_withheld": self.value_withheld,
        }


# ---------------------------------------------------------------------------
# 5. Gateway：唯一出口，十步
# ---------------------------------------------------------------------------
class ToolGateway:
    """所有 Agent 工具调用的唯一出口。

    十步（任一步失败都返回结构化拒绝，不抛到模型层）：
      1. 装配检查：审计/执行/证据/时钟端口必须齐全，缺一即拒（fail-closed）；
      2. 身份授权：contracts.authorize_agent(TOOL_REQUEST)；
      3. 注册表解析：未注册 → 403 TOOL_NOT_REGISTERED；
      4. 参数 Schema：未知/缺失/类型/范围 → 403 TOOL_ARGS_SCHEMA_INVALID（E.3 把“参数 Schema 不匹配”归入 TOOL_NOT_ALLOWLISTED）；
      5. 预算：节点/任务调用上限 → 429；
      6. 审计开始：失败则**不执行**；
      7. 执行：唯一 ToolRunnerPort 调用点，超时由 runner 杀进程树；
      8. 超时/失败：结构化返回，必要时 escalation_required；
      9. E1 事件：提交 Collector；失败 → EVIDENCE_UNAVAILABLE 且扣留 value；
     10. 审计完成：失败 → AUDIT_DEGRADED 且扣留 value。
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        runner: ToolRunnerPort | None,
        audit: ToolAuditPort | None,
        evidence: ToolEvidencePort | None,
        clock: ClockPort | None,
        budget: ToolBudget | None = None,
    ) -> None:
        self._registry = registry
        self._runner = runner
        self._audit = audit
        self._evidence = evidence
        self._clock = clock
        self._budget = ToolBudgetTracker(budget or ToolBudget())
        self._assembly_errors: list[str] = []
        for name, value in (("runner", runner), ("audit", audit), ("evidence", evidence), ("clock", clock)):
            if value is None:
                self._assembly_errors.append(name)

    def invoke(self, request: ToolCallRequest) -> ToolCallResult:
        """执行一次调用。返回结果即终态；调用方不得重试未授权的工具。"""
        started = self._now()

        # 1. 装配
        if self._assembly_errors:
            return self._deny(
                ToolCallStatus.DENIED, "AUDIT_WRITE_FAILED", "TOOL_GATEWAY_NOT_ASSEMBLED",
                "gateway", 0, None, None, detail=",".join(self._assembly_errors),
            )

        # 2. 身份授权
        decision = authorize_agent(request.identity, Axis.TOOL_REQUEST, tool_name=request.tool_name)
        if not decision.allowed:
            return self._deny(
                ToolCallStatus.DENIED, decision.error_code or "TOOL_NOT_ALLOWLISTED",
                decision.reason or "TOOL_DENIED", "tool_name", self._elapsed(started), None, None,
                detail=request.tool_name,
            )

        # 3. 注册表
        try:
            tool = self._registry.resolve(request.tool_name)
        except KeyError:
            return self._deny(
                ToolCallStatus.DENIED, "TOOL_NOT_ALLOWLISTED", "TOOL_NOT_REGISTERED",
                "tool_name", self._elapsed(started), None, None, detail=request.tool_name,
            )

        # 4. 参数 Schema
        try:
            tool.schema.validate(request.args)
        except ToolArgsInvalid as exc:
            return self._deny(
                ToolCallStatus.DENIED, "TOOL_NOT_ALLOWLISTED", "TOOL_ARGS_SCHEMA_INVALID",
                exc.field_path, self._elapsed(started), None, None,
                detail=f"{exc.reason}:{exc.detail}",
            )

        # 5. 预算
        try:
            self._budget.consume(request.task_id, request.node_id)
        except ToolTimeout as exc:
            return self._deny(
                ToolCallStatus.DENIED, exc.code, exc.reason, exc.field_path,
                self._elapsed(started), None, None, detail=exc.detail,
            )

        # 6. 审计开始（失败不执行）
        args_hash = self._hash_args(request.args)
        try:
            audit_id = self._audit.begin(  # type: ignore[union-attr]
                ToolAuditRecord(
                    task_id=request.task_id,
                    node_id=request.node_id,
                    attempt_id=request.attempt_id,
                    role=request.identity.role,
                    tool_name=tool.spec.name,
                    args_hash=args_hash,
                    arg_keys=tuple(sorted(request.args)),
                    correlation_id=request.correlation_id,
                    started_at=self._clock.utc_now_iso(),  # type: ignore[union-attr]
                )
            )
        except Exception:  # noqa: BLE001 - 审计不可用必须拒绝对外调用
            return self._deny(
                ToolCallStatus.DENIED, "AUDIT_WRITE_FAILED", "TOOL_AUDIT_UNAVAILABLE",
                "audit", self._elapsed(started), None, None, detail="begin failed",
            )

        # 7. 执行
        timeout_sec = min(tool.spec.timeout_sec, MAX_TOOL_TIMEOUT_SEC)
        try:
            outcome = self._runner.run(tool=tool, args=request.args, timeout_sec=timeout_sec)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - 执行端异常必须结构化
            result = self._deny(
                ToolCallStatus.FAILED, "AUDIT_WRITE_FAILED", "TOOL_RUNNER_FAULT",
                "runner", self._elapsed(started), audit_id, None, detail=type(exc).__name__,
            )
            self._finish_audit(audit_id, result)
            return result

        # 8. 超时/失败
        if outcome.status is RunnerStatus.TIMEOUT:
            result = self._deny(
                ToolCallStatus.TIMEOUT, "RESOURCE_BUDGET_EXCEEDED", "TOOL_TIMEOUT",
                "timeout_sec", self._elapsed(started), audit_id, None,
                detail=f"reclaimed={outcome.child_tree_reclaimed}",
            )
            self._finish_audit(audit_id, result)
            return result
        if outcome.status is not RunnerStatus.EXITED or outcome.exit_code not in (0, None):
            result = self._deny(
                ToolCallStatus.FAILED, "TOOL_NOT_ALLOWLISTED", "TOOL_EXIT_NONZERO",
                "exit_code", self._elapsed(started), audit_id, None,
                detail=f"{outcome.exit_code}:{outcome.error_text}",
            )
            self._finish_audit(audit_id, result)
            return result

        # 9. E1 事件（Collector 写；失败即扣留 value）
        result_hash = hashlib.sha256(  # LIB: hashlib.sha256
            json.dumps({"value": repr(outcome.value)}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        try:
            event_id = self._evidence.submit(  # type: ignore[union-attr]
                ToolEvidenceEvent(
                    task_id=request.task_id,
                    node_id=request.node_id,
                    attempt_id=request.attempt_id,
                    tool_name=tool.spec.name,
                    role=request.identity.role,
                    args_hash=args_hash,
                    result_hash=result_hash,
                    status="EXITED",
                    elapsed_ms=self._elapsed(started),
                    correlation_id=request.correlation_id,
                )
            )
        except Exception:  # noqa: BLE001 - E1 记录失败 → 结果不可用
            result = self._deny(
                ToolCallStatus.EVIDENCE_UNAVAILABLE, "AUDIT_WRITE_FAILED", "TOOL_EVIDENCE_NOT_RECORDED",
                "evidence", self._elapsed(started), audit_id, None, detail="collector unavailable",
            )
            self._finish_audit(audit_id, result)
            return result

        result = ToolCallResult(
            status=ToolCallStatus.OK,
            value=outcome.value,
            error_code=None,
            reason=None,
            field_path=None,
            elapsed_ms=self._elapsed(started),
            audit_id=audit_id,
            evidence_event_id=event_id,
            value_withheld=False,
        )

        # 10. 审计完成
        if not self._finish_audit(audit_id, result):
            return ToolCallResult(
                status=ToolCallStatus.AUDIT_DEGRADED,
                value=None,
                error_code="AUDIT_WRITE_FAILED",
                reason="TOOL_AUDIT_FINISH_FAILED",
                field_path="audit",
                elapsed_ms=self._elapsed(started),
                audit_id=audit_id,
                evidence_event_id=event_id,
                value_withheld=True,
            )
        return result

    # -- 内部工具 ---------------------------------------------------------
    def _now(self) -> float:
        return self._clock.monotonic() if self._clock is not None else 0.0  # type: ignore[union-attr]

    def _elapsed(self, started: float) -> int:
        if self._clock is None:
            return 0
        return max(0, int((self._clock.monotonic() - started) * 1000))

    @staticmethod
    def _hash_args(args: Mapping[str, object]) -> str:
        payload = json.dumps(dict(args), ensure_ascii=False, sort_keys=True, default=repr)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()  # LIB: hashlib.sha256

    def _finish_audit(self, audit_id: str, result: ToolCallResult) -> bool:
        if self._audit is None:
            return False
        try:
            self._audit.finish(
                audit_id,
                ToolAuditOutcome(
                    status=result.status.value,
                    elapsed_ms=result.elapsed_ms,
                    error_code=result.error_code,
                    reason=result.reason,
                    evidence_event_id=result.evidence_event_id,
                ),
            )
            return True
        except Exception:  # noqa: BLE001 - 审计降级必须显式
            return False

    def _deny(
        self,
        status: ToolCallStatus,
        code: str,
        reason: str,
        field_path: str,
        elapsed_ms: int,
        audit_id: str | None,
        evidence_event_id: str | None,
        *,
        detail: str,
    ) -> ToolCallResult:
        """统一拒绝结果；`detail` 只进日志，不返回给模型。"""
        return ToolCallResult(
            status=status,
            value=None,
            error_code=code,
            reason=reason,
            field_path=field_path,
            elapsed_ms=elapsed_ms,
            audit_id=audit_id,
            evidence_event_id=evidence_event_id,
            value_withheld=True,
        )


# ---------------------------------------------------------------------------
# 6. 静态守卫
# ---------------------------------------------------------------------------
def assert_no_write_tools() -> tuple[str, ...]:
    """目录与注册表都不得出现写状态/证据/签名/密钥类工具。"""
    problems: list[str] = []
    for name in AGENT_TOOL_CATALOG:
        if is_forbidden_tool(name):
            problems.append(f"{name} 命中禁用能力")
    for name in _DEFAULT_SCHEMAS:
        if name not in AGENT_TOOL_CATALOG:
            problems.append(f"{name} 有 Schema 但不在目录")
    if any(spec.access not in (ToolAccess.READ_ONLY, ToolAccess.PURE_COMPUTE, ToolAccess.DRAFT_ONLY)
           for spec in AGENT_TOOL_CATALOG.values()):
        problems.append("目录里存在副作用工具")
    return tuple(problems)


def assert_timeout_bounds() -> tuple[str, ...]:
    """所有工具超时都在 (0, MAX_TOOL_TIMEOUT_SEC]，且 Schema 与名字同源。"""
    problems: list[str] = []
    for name, spec in AGENT_TOOL_CATALOG.items():
        if not 0 < spec.timeout_sec <= MAX_TOOL_TIMEOUT_SEC:
            problems.append(f"{name} 超时越界")
        schema = _DEFAULT_SCHEMAS.get(name)
        if schema is None:
            problems.append(f"{name} 缺 Schema")
            continue
        if schema.tool_name != name or not schema.schema_id.startswith(name + "/"):
            problems.append(f"{name} 的 Schema 与工具名不同源")
    return tuple(problems)


def assert_single_egress() -> tuple[str, ...]:
    """本模块只暴露 ToolGateway 一个执行入口，不导出自由函数 `run_tool`。"""
    problems: list[str] = []
    if "ToolGateway" not in __all__:
        problems.append("未导出 ToolGateway")
    for name in __all__:
        if name.lower() in {"run_tool", "invoke_tool", "execute_tool", "exec_tool"}:
            problems.append(f"导出了第二个执行入口 {name}")
    if "ToolRunnerPort" not in __all__:
        problems.append("未导出 ToolRunnerPort（调用方无法正确注入执行端）")
    return tuple(problems)