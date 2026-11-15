"""MODULE：M18 · knowledge/binding.py — 五种绑定：工具/模板/数据集/Agent/基准任务（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-013、策划书 §11.3 TABLE 43、§11.4
FR+依赖：FR-013；依赖 unit.py（五类）、retrieval.py（RetrievalHit）、M05/M06 的显式契约（只读）
不变量+错误码：知识只提供“怎么做”的建议，永远不覆盖显式规格/契约（explicit wins）；
              知识不得改必检项、ruleset_hash、limits、side_effect_class；过期知识注入必须人工确认；
              Agent 绑定不得跨角色 ktype。
              SCHEMA_INVALID(422) / STATE_TRANSITION_DENIED(409)
写入者：无。绑定只返回注入建议；不写任务、不写证据、不改配置。
状态：伪代码；不建索引、不执行工具、不跑基准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Mapping, Protocol, Sequence

from .retrieval import HitReason, RetrievalHit

__all__ = [
    "IMMUTABLE_KNOWLEDGE_TARGETS",
    "AgentBinding",
    "BenchmarkBinding",
    "BenchmarkScore",
    "BindingKind",
    "ConfirmationPort",
    "DatasetBinding",
    "Injection",
    "InjectionItem",
    "Metric",
    "Override",
    "TemplateBinding",
    "ToolBinding",
    "assert_explicit_wins",
    "assert_five_bindings",
    "assert_no_decision_binding",
    "assert_stale_requires_confirmation",
    "benchmark_metrics",
    "dataset_metrics",
    "agent_metrics",
    "template_metrics",
    "tool_metrics",
]

# 知识**永不**可写/可改的目标：出现即拒绝（知识不参与必检判定与权限）。
IMMUTABLE_KNOWLEDGE_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "required_checks",
        "ruleset_hash",
        "limits",
        "side_effect_class",
        "state",
        "task_state",
        "node_state",
        "evidence",
        "evidence_id",
        "report",
        "certificate",
        "signature",
        "key_id",
        "private_key",
    }
)

# 五类知识字面值（与 unit.KType 一致；本模块只做注入，不 import unit 以避免循环）。
KNOWLEDGE_KTYPES: Final[tuple[str, ...]] = ("SPEC", "TOOL", "DATASET", "FAULT_CASE", "PAPER_DOC")


class BindingKind(StrEnum):
    """§11.3 的五种绑定。**恰好五个**。"""

    TOOL = "TOOL"
    TEMPLATE = "TEMPLATE"
    DATASET = "DATASET"
    AGENT = "AGENT"
    BENCHMARK_TASK = "BENCHMARK_TASK"


class BindingRefused(RuntimeError):
    """绑定被拒；`reason`/`detail` 是断言对象。"""

    def __init__(self, code: str, reason: str, detail: str) -> None:
        self.error_code = code
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{code}] {reason}（{detail}）")


@dataclass(frozen=True, slots=True)
class Metric:
    """一个可测指标。分母为 0 时 value=None（不把“没有样本”写成 0%）。"""

    name: str
    numerator: int
    denominator: int
    value: float | None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise BindingRefused("SCHEMA_INVALID", "METRIC_NAME_EMPTY", "")
        if self.numerator < 0 or self.denominator < 0 or self.numerator > max(self.denominator, 0):
            raise BindingRefused("SCHEMA_INVALID", "METRIC_COUNT_INVALID", f"{self.numerator}/{self.denominator}")
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if expected is None and self.value is not None:
            raise BindingRefused("SCHEMA_INVALID", "METRIC_VALUE_INVALID", "分母为 0 时必须为 None")
        if expected is not None and (self.value is None or abs(expected - self.value) > 1e-12):
            raise BindingRefused("SCHEMA_INVALID", "METRIC_VALUE_INVALID", f"{self.value}!={expected}")

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "numerator": self.numerator, "denominator": self.denominator, "value": self.value}


def _metric(name: str, numerator: int, denominator: int) -> Metric:
    return Metric(name=name, numerator=numerator, denominator=denominator,
                  value=None if denominator == 0 else numerator / denominator)


@dataclass(frozen=True, slots=True)
class InjectionItem:
    """一条注入项。`authoritative` 恒 False：知识永远不是判据。"""

    kid: str
    version: int
    content_hash: str
    ktype: str
    reason: str
    stale_kb: bool
    structured: Mapping[str, object] = field(default_factory=dict)
    authoritative: bool = False

    def __post_init__(self) -> None:
        if self.authoritative:
            raise BindingRefused(
                "STATE_TRANSITION_DENIED", "KNOWLEDGE_CANNOT_BE_AUTHORITATIVE",
                "知识只能回答“怎么做”，不得成为判据",
            )
        if len(self.content_hash) != 64:
            raise BindingRefused("SCHEMA_INVALID", "INJECTION_HASH_INVALID", self.content_hash)
        if not self.kid or self.version < 1:
            raise BindingRefused("SCHEMA_INVALID", "INJECTION_ID_INVALID", f"{self.kid}@{self.version}")


@dataclass(frozen=True, slots=True)
class Override:
    """一次“知识 vs 显式值”的冲突。winner 恒为显式值。"""

    field_path: str
    explicit_value: object
    knowledge_value: object
    winner: str = "EXPLICIT_CONTRACT_OR_SPEC"

    def __post_init__(self) -> None:
        if self.winner != "EXPLICIT_CONTRACT_OR_SPEC":
            raise BindingRefused("STATE_TRANSITION_DENIED", "KNOWLEDGE_OVERRIDES_SPEC", self.field_path)


@dataclass(frozen=True, slots=True)
class Injection:
    """一次绑定的结果：注入了什么、跳过了什么、覆盖了什么。"""

    kind: BindingKind
    target: str
    items: tuple[InjectionItem, ...]
    injected: bool
    skipped_reason: str | None
    overrides: tuple[Override, ...] = ()
    requires_confirmation: bool = False
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.injected and not self.items:
            raise BindingRefused("SCHEMA_INVALID", "INJECTION_EMPTY", self.target)
        if not self.injected and not self.skipped_reason:
            raise BindingRefused("SCHEMA_INVALID", "INJECTION_SKIP_REASON_MISSING", self.target)
        for item in self.items:
            if item.ktype not in KNOWLEDGE_KTYPES:
                raise BindingRefused("SCHEMA_INVALID", "INJECTION_KTYPE_INVALID", item.ktype)
        extra = set(self.payload) & IMMUTABLE_KNOWLEDGE_TARGETS
        if extra:
            raise BindingRefused(
                "STATE_TRANSITION_DENIED", "KNOWLEDGE_BINDS_IMMUTABLE_TARGET", sorted(extra)[0]
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "target": self.target,
            "injected": self.injected,
            "skipped_reason": self.skipped_reason,
            "requires_confirmation": self.requires_confirmation,
            "payload_keys": sorted(self.payload),
            "items": [
                {"kid": i.kid, "version": i.version, "hash": i.content_hash[:12], "ktype": i.ktype,
                 "stale": i.stale_kb, "reason": i.reason}
                for i in self.items
            ],
            "overrides": [
                {"field_path": o.field_path, "explicit": o.explicit_value, "knowledge": o.knowledge_value,
                 "winner": o.winner}
                for o in self.overrides
            ],
        }


class ConfirmationPort(Protocol):
    """过期知识的使用确认（人工/工作台）。返回 False 即不使用该条知识。"""

    def confirm(self, *, kid: str, version: int, target: str, reason: str) -> bool: ...


def _to_item(hit: RetrievalHit, reason: str) -> InjectionItem:
    return InjectionItem(
        kid=hit.kid,
        version=hit.version,
        content_hash=hit.content_hash,
        ktype=hit.ktype,
        reason=reason,
        stale_kb=hit.stale_kb,
        structured=dict(hit.structured),
    )


def _is_stale_confirmed(hit: RetrievalHit, *, target: str, confirmation: ConfirmationPort | None) -> bool:
    """过期知识：没有确认端口或确认失败，一律不使用。"""
    if not hit.stale_kb:
        return True
    if confirmation is None:
        return False
    try:
        return bool(confirmation.confirm(kid=hit.kid, version=hit.version, target=target, reason="STALE_KB"))
    except Exception:  # noqa: BLE001 - 确认失败按未确认处理
        return False


# ---------------------------------------------------------------------------
# 1. 工具绑定：调用前注入参数约束与已知错误
# ---------------------------------------------------------------------------
class ToolBinding:
    """§11.3 工具行：注入参数约束/已知错误；与工具注册表冲突时注册表赢。"""

    kind = BindingKind.TOOL

    def bind(
        self,
        *,
        tool_name: str,
        hits: Sequence[RetrievalHit],
        registry_timeout_sec: int | None = None,
        confirmation: ConfirmationPort | None = None,
    ) -> Injection:
        """只接受 TOOL 类且 `structured.tool_name` 匹配的命中；其余不进注入。"""
        if not tool_name.strip():
            raise BindingRefused("SCHEMA_INVALID", "TOOL_NAME_REQUIRED", "")
        items: list[InjectionItem] = []
        overrides: list[Override] = []
        skipped: list[str] = []
        advisory: dict[str, object] = {}
        for hit in hits:
            if hit.ktype != "TOOL":
                skipped.append("KTYPE_MISMATCH")
                continue
            if str(hit.structured.get("tool_name", "")) != tool_name:
                skipped.append("TOOL_NAME_MISMATCH")
                continue
            if not _is_stale_confirmed(hit, target=tool_name, confirmation=confirmation):
                skipped.append("STALE_NOT_CONFIRMED")
                continue
            items.append(_to_item(hit, "参数约束/已知错误注入"))
            for key in ("params_schema", "known_errors"):
                if key in hit.structured:
                    advisory[key] = hit.structured[key]
            kb_timeout = hit.structured.get("timeout_sec")
            if registry_timeout_sec is not None and isinstance(kb_timeout, int) and kb_timeout != registry_timeout_sec:
                overrides.append(
                    Override(
                        field_path="timeout_sec",
                        explicit_value=registry_timeout_sec,
                        knowledge_value=kb_timeout,
                    )
                )
        if not items:
            return Injection(
                kind=self.kind, target=tool_name, items=(), injected=False,
                skipped_reason=skipped[0] if skipped else "NO_TOOL_KNOWLEDGE",
            )
        return Injection(
            kind=self.kind, target=tool_name, items=tuple(items), injected=True,
            skipped_reason=None, overrides=tuple(overrides),
            requires_confirmation=any(item.stale_kb for item in items),
            payload=advisory,
        )


# ---------------------------------------------------------------------------
# 2. 模板绑定：DAG 构建时注入默认种子/指标/划分
# ---------------------------------------------------------------------------
class TemplateBinding:
    """§11.3 模板行：只补缺省值；显式值优先；不得改必检/规则/限额。"""

    kind = BindingKind.TEMPLATE
    _DEFAULT_KEYS: Final[tuple[str, ...]] = ("seed", "test_ratio", "metric_defs")

    def bind(
        self,
        *,
        template_id: str,
        explicit: Mapping[str, object],
        hits: Sequence[RetrievalHit],
        confirmation: ConfirmationPort | None = None,
    ) -> Injection:
        """从 SPEC 记录取默认值；显式键存在时一律不覆盖，并记录 override。"""
        if not template_id.strip():
            raise BindingRefused("SCHEMA_INVALID", "TEMPLATE_ID_REQUIRED", "")
        items: list[InjectionItem] = []
        overrides: list[Override] = []
        skipped: list[str] = []
        defaults: dict[str, object] = {}

        for hit in hits:
            if hit.ktype != "SPEC":
                skipped.append("KTYPE_MISMATCH")
                continue
            if not (hit.scope == f"template:{template_id}" or hit.scope.startswith(f"template:{template_id}@")):
                skipped.append("SCOPE_MISMATCH")
                continue
            if not _is_stale_confirmed(hit, target=template_id, confirmation=confirmation):
                skipped.append("STALE_NOT_CONFIRMED")
                continue
            items.append(_to_item(hit, "默认种子/指标/划分"))
            for key in self._DEFAULT_KEYS:
                if key not in hit.structured:
                    continue
                value = hit.structured[key]
                if key in explicit:
                    if explicit[key] != value:
                        overrides.append(
                            Override(field_path=key, explicit_value=explicit[key], knowledge_value=value)
                        )
                    continue
                defaults.setdefault(key, value)

        if not items:
            return Injection(
                kind=self.kind, target=template_id, items=(), injected=False,
                skipped_reason=skipped[0] if skipped else "NO_TEMPLATE_SPEC",
            )
        # 只在“没有显式值”时补默认值；本对象不改任何 TaskSpec/NodeSpec。
        return Injection(
            kind=self.kind, target=template_id, items=tuple(items), injected=True,
            skipped_reason=None, overrides=tuple(overrides),
            requires_confirmation=any(item.stale_kb for item in items),
            payload=defaults,
        )


# ---------------------------------------------------------------------------
# 3. 数据集绑定：画像前注入字段解释与质量规则
# ---------------------------------------------------------------------------
class DatasetBinding:
    """§11.3 数据集行：注入字段解释/质量规则；不改数据；许可不一致即拒。"""

    kind = BindingKind.DATASET

    def bind(
        self,
        *,
        dataset_hash: str,
        dataset_license: str,
        hits: Sequence[RetrievalHit],
        confirmation: ConfirmationPort | None = None,
    ) -> Injection:
        """只接受 hash 匹配的 DATASET 记录；许可冲突直接拒绝注入。"""
        if len(dataset_hash) != 64:
            raise BindingRefused("SCHEMA_INVALID", "DATASET_HASH_INVALID", dataset_hash)
        items: list[InjectionItem] = []
        skipped: list[str] = []
        advisory: dict[str, object] = {}
        for hit in hits:
            if hit.ktype != "DATASET":
                skipped.append("KTYPE_MISMATCH")
                continue
            if str(hit.structured.get("dataset_hash", "")) != dataset_hash:
                skipped.append("DATASET_HASH_MISMATCH")
                continue
            kb_license = str(hit.structured.get("license", ""))
            if kb_license and kb_license != dataset_license:
                raise BindingRefused(
                    "STATE_TRANSITION_DENIED", "DATASET_LICENSE_CONFLICT",
                    f"kb={kb_license} task={dataset_license}",
                )
            if not _is_stale_confirmed(hit, target=dataset_hash, confirmation=confirmation):
                skipped.append("STALE_NOT_CONFIRMED")
                continue
            items.append(_to_item(hit, "字段解释/质量规则"))
            for key in ("target", "dtypes"):
                if key in hit.structured:
                    advisory[key] = hit.structured[key]
        if not items:
            return Injection(
                kind=self.kind, target=dataset_hash, items=(), injected=False,
                skipped_reason=skipped[0] if skipped else "NO_DATASET_KNOWLEDGE",
            )
        return Injection(
            kind=self.kind, target=dataset_hash, items=tuple(items), injected=True,
            skipped_reason=None, requires_confirmation=any(item.stale_kb for item in items),
            payload=advisory,
        )


# ---------------------------------------------------------------------------
# 4. Agent 绑定：按角色限制可见知识类型
# ---------------------------------------------------------------------------
class AgentBinding:
    """§11.3 Agent 行：越界 ktype 一律剔除；无关知识比例必须为 0。"""

    kind = BindingKind.AGENT

    def bind(
        self,
        *,
        role_name: str,
        allowed_ktypes: frozenset[str],
        hits: Sequence[RetrievalHit],
    ) -> Injection:
        """按角色允许的 ktype 过滤；被剔除数量进入观测，不进入上下文。"""
        if not role_name.strip() or not allowed_ktypes:
            raise BindingRefused("SCHEMA_INVALID", "AGENT_BINDING_SCOPE_EMPTY", role_name)
        items: list[InjectionItem] = []
        dropped = 0
        for hit in hits:
            if hit.ktype not in allowed_ktypes:
                dropped += 1
                continue
            items.append(_to_item(hit, f"{role_name} 角色可见知识"))
        if not items:
            return Injection(
                kind=self.kind, target=role_name, items=(), injected=False,
                skipped_reason=f"NO_ALLOWED_KNOWLEDGE(dropped={dropped})",
            )
        return Injection(
            kind=self.kind, target=role_name, items=tuple(items), injected=True,
            skipped_reason=None, requires_confirmation=any(item.stale_kb for item in items),
            payload={"allowed_ktypes": sorted(allowed_ktypes), "dropped": dropped},
        )


# ---------------------------------------------------------------------------
# 5. 基准任务绑定：expected_kb_hit 检查
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BenchmarkScore:
    """基准任务的知识命中评分。分母都必须报出。"""

    recall_at_k: Metric
    mrr: Metric
    version_hit_rate: Metric
    k: int

    def __post_init__(self) -> None:
        if self.k < 1:
            raise BindingRefused("SCHEMA_INVALID", "BENCHMARK_K_INVALID", str(self.k))

    def as_dict(self) -> dict[str, object]:
        return {
            "k": self.k,
            "recall_at_k": self.recall_at_k.as_dict(),
            "mrr": self.mrr.as_dict(),
            "version_hit_rate": self.version_hit_rate.as_dict(),
        }


class BenchmarkBinding:
    """§11.3 基准任务行：比较 expected_kb_hit 与真实命中。"""

    kind = BindingKind.BENCHMARK_TASK

    def score(
        self,
        *,
        expected: Sequence[str],
        actual: Sequence[RetrievalHit],
        k: int = 5,
    ) -> BenchmarkScore:
        """expected 写 `kid@version`；命中需版本一致才算 version hit。"""
        if not expected:
            raise BindingRefused("SCHEMA_INVALID", "EXPECTED_KB_HIT_EMPTY", "基准任务必须声明 expected_kb_hit")
        if k < 1 or k > MAX_K:
            raise BindingRefused("SCHEMA_INVALID", "BENCHMARK_K_INVALID", str(k))
        top = list(actual)[:k]
        actual_keys = [f"{hit.kid}@{hit.version}" for hit in top]
        matched_any = [key for key in expected if key in actual_keys]
        exact = [key for key in expected if key in actual_keys]

        ranks: list[int] = []
        for key in expected:
            if key in actual_keys:
                ranks.append(actual_keys.index(key) + 1)
        reciprocal = sum(1.0 / rank for rank in ranks)

        return BenchmarkScore(
            recall_at_k=_metric("recall_at_k", len(matched_any), len(expected)),
            mrr=Metric(
                "mrr",
                numerator=int(round(reciprocal * 1_000_000)),
                denominator=len(expected) * 1_000_000,
                value=int(round(reciprocal * 1_000_000)) / (len(expected) * 1_000_000),
            ),
            version_hit_rate=_metric("version_hit_rate", len(exact), len(expected)),
            k=k,
        )


MAX_K: Final[int] = 20


# ---------------------------------------------------------------------------
# 6. 可测指标（§11.3「可测指标」列）
# ---------------------------------------------------------------------------
def tool_metrics(*, calls: int, calls_with_injection: int, invalid_param_calls: int) -> tuple[Metric, Metric]:
    """知识命中率、违规参数率。分母都是工具调用次数。"""
    if min(calls, calls_with_injection, invalid_param_calls) < 0:
        raise BindingRefused("SCHEMA_INVALID", "METRIC_NEGATIVE", "计数不得为负")
    return (
        _metric("knowledge_hit_rate", calls_with_injection, calls),
        _metric("invalid_param_rate", invalid_param_calls, calls),
    )


def template_metrics(
    *, builds: int, spec_missing: int, defaults_applied: int, defaults_correct: int
) -> tuple[Metric, Metric]:
    """规范缺失率、默认值正确率。默认值正确性必须有对照标准（SPEC/人工复核）。"""
    return (
        _metric("spec_missing_rate", spec_missing, builds),
        _metric("default_value_correctness", defaults_correct, defaults_applied),
    )


def dataset_metrics(
    *, declared_fields: int, recognized_fields: int, total_columns: int, profiled_columns: int
) -> tuple[Metric, Metric]:
    """字段识别准确率、画像覆盖率。"""
    return (
        _metric("field_recognition_accuracy", recognized_fields, declared_fields),
        _metric("profile_coverage", profiled_columns, total_columns),
    )


def agent_metrics(*, injected_units: int, irrelevant_units: int, context_tokens: int) -> tuple[Metric, int]:
    """无关知识比例（目标 0）、上下文 token 成本（**计数**，不是比率）。"""
    if irrelevant_units > injected_units:
        raise BindingRefused("SCHEMA_INVALID", "IRRELEVANT_EXCEEDS_INJECTED", f"{irrelevant_units}/{injected_units}")
    if context_tokens < 0:
        raise BindingRefused("SCHEMA_INVALID", "CONTEXT_TOKENS_NEGATIVE", str(context_tokens))
    return (
        _metric("irrelevant_knowledge_ratio", irrelevant_units, injected_units),
        context_tokens,
    )


def benchmark_metrics(score: BenchmarkScore) -> tuple[Metric, Metric, Metric]:
    """基准任务三指标：Recall@k、MRR、版本命中率。"""
    return (score.recall_at_k, score.mrr, score.version_hit_rate)


# ---------------------------------------------------------------------------
# 7. 静态守卫
# ---------------------------------------------------------------------------
def assert_five_bindings() -> tuple[str, ...]:
    """绑定恰好五种，且各自有实现类。"""
    problems: list[str] = []
    if len(BindingKind) != 5:
        problems.append(f"绑定种类应为 5，实际 {len(BindingKind)}")
    for kind, cls in (
        (BindingKind.TOOL, ToolBinding),
        (BindingKind.TEMPLATE, TemplateBinding),
        (BindingKind.DATASET, DatasetBinding),
        (BindingKind.AGENT, AgentBinding),
        (BindingKind.BENCHMARK_TASK, BenchmarkBinding),
    ):
        if getattr(cls, "kind", None) is not kind:
            problems.append(f"{cls.__name__} 未绑定到 {kind.value}")
    return tuple(problems)


def assert_explicit_wins() -> tuple[str, ...]:
    """显式值永远压过知识：构造一个冲突，必须产生 override 且 winner 固定。"""
    problems: list[str] = []
    override = Override(field_path="seed", explicit_value=42, knowledge_value=7)
    if override.winner != "EXPLICIT_CONTRACT_OR_SPEC":
        problems.append("Override 的 winner 不是显式值")
    try:
        Override(field_path="seed", explicit_value=42, knowledge_value=7, winner="KNOWLEDGE")
    except BindingRefused:
        pass
    else:
        problems.append("放行了“知识覆盖显式值”的 Override")
    if "required_checks" not in IMMUTABLE_KNOWLEDGE_TARGETS:
        problems.append("必检项不在不可变目标里")
    return tuple(problems)


def assert_no_decision_binding() -> tuple[str, ...]:
    """知识不得绑定到判定字段；五类绑定都不返回 Task/Node 状态或证据。"""
    problems: list[str] = []
    for forbidden in ("required_checks", "ruleset_hash", "limits", "side_effect_class"):
        if forbidden not in IMMUTABLE_KNOWLEDGE_TARGETS:
            problems.append(f"{forbidden} 未被声明为不可变目标")
    for cls in (ToolBinding, TemplateBinding, DatasetBinding, AgentBinding, BenchmarkBinding):
        for name in dir(cls):
            if name.startswith("_"):
                continue
            if any(token in name for token in ("set_state", "write_evidence", "decide", "judge", "issue")):
                problems.append(f"{cls.__name__} 暴露判定入口 {name}")
    return tuple(problems)


def assert_stale_requires_confirmation() -> tuple[str, ...]:
    """过期知识在无确认端口时不得注入。"""
    problems: list[str] = []
    stale_hit = RetrievalHit(
        kid="kb_spec", version=1, content_hash="0" * 64, source_url="local://spec", ktype="SPEC",
        scope="template:t@1.0", status="ACTIVE", text="spec", score=1.0, stale_kb=True,
        requires_confirmation=True,
        hit_reason=HitReason(("spec",), ("ktypes=SPEC",), -1.0, 1, True),
        structured={"seed": 7},
    )
    injection = TemplateBinding().bind(template_id="t", explicit={}, hits=(stale_hit,), confirmation=None)
    if injection.injected:
        problems.append("无确认端口时仍注入了过期知识")
    return tuple(problems)