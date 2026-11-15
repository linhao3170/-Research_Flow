"""M15 · orchestration/determinism/dc_eligibility.py — DC 六类条件资格判定（P9 伪代码）。
MODULE: M15 DC/SPA ｜ 阶段：P9「DC/SPA 与 VAS」
追踪：FR-015（DC 资格与 SPA 证明；T2 / G4）、策划书 §8.2 TABLE 34、附录 D.5
FR+依赖：M04 节点元数据（node_type / 副作用类别）、M03 `env_fingerprint` 七组成项、
        M05 探针运行事实、M08 `ruleset_hash`；**不**依赖 M11 签名（签名只在 dc_issuer）
不变量：六条件全量求值（诊断需要），任一非 PASS 即 `eligible=False`；随机性是一票否决；
        本文件不签发、不签名、不写证据、不读时钟（`now` 由调用方传入）；T0/T1 直接拒绝
错误码：FEATURE_FLAG_NOT_PERMITTED（tier≠T2 / dc_spa=false，403）、
        SCHEMA_INVALID（事实对象自相矛盾，422）、ENV_FINGERPRINT_INCOMPLETE（409）、
        RULESET_VERSION_MISMATCH（409）、DC_INPUT_EVIDENCE_MISSING（422）
写入者：无。纯函数 + 冻结值对象
状态：伪代码；不执行、不签发、不剪枝

## 本文件回答四个问题

  1. §8.2 的六条件各看什么字段？缺字段算通过还是算不通过？（缺就是缺，不推断）
  2. 为什么随机性必须先于其他条件否决？（§8.2 关键修正：不签 DC、不剪枝）
  3. k 次 bit-exact 证明了什么、没证明什么？（经验性资格，不是数学确定性证明）
  4. 资格判定与签发为什么必须分开？（本文件没有 signature 槽位，签发在 dc_issuer）

## 三条写死的判定纪律

  | 纪律 | 实现方式 |
  |---|---|
  | 六条件全量求值，不只求值到第一个失败 | `evaluate_dc_eligibility()` 逐个调用六个 `_*_result`，全部产出 `ConditionResult` |
  | 否决优先，避免同一事实得到两种结论 | `EVALUATION_ORDER` 把 `RANDOMNESS` 放第一位；`VETO_CONDITIONS` 只有它 |
  | 缺证据不等于通过 | 每个 `_*_result` 对「未提供」返回 `MISSING_EVIDENCE`；`ConditionResult` 的 PASS 必须带证据 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

__all__ = [
    "CONDITION_LITERALS",
    "CONDITION_ORDER",
    "DC_SCOPE_STATEMENT",
    "DEFAULT_DC_POLICY",
    "EVALUATION_ORDER",
    "KEY_CORRECTION",
    "REQUIRED_ENV_COMPONENTS",
    "VETO_CONDITIONS",
    "Condition",
    "ConditionResult",
    "ConditionStatus",
    "DcBinding",
    "DcCandidate",
    "DcEligibilityError",
    "DcNotEnabled",
    "DcPolicy",
    "DcReason",
    "EligibilityVerdict",
    "EnvComparisonView",
    "PurityClass",
    "RunComparison",
    "RunProbe",
    "assert_condition_math",
    "assert_conservative_defaults",
    "assert_randomness_is_veto",
    "assert_scope_statement",
    "compare_runs",
    "evaluate_dc_eligibility",
    "required_k",
]

STAGE: Final[str] = "P9"
DC_POLICY_VERSION: Final[str] = "dc-policy/1.0-proposed"


# ---------------------------------------------------------------------------
# 1. §8.2 原文（逐字；改这些字符串等于改验收口径）
# ---------------------------------------------------------------------------
class Condition(StrEnum):
    """§8.2 TABLE 34 的六行，顺序即表格顺序（报告顺序）。"""

    NODE_PURITY = "NODE_PURITY"
    INPUT_FIXED = "INPUT_FIXED"
    ENV_FINGERPRINT = "ENV_FINGERPRINT"
    REPEATED_RUNS = "REPEATED_RUNS"
    RANDOMNESS = "RANDOMNESS"
    VALIDITY = "VALIDITY"


CONDITION_ORDER: Final[tuple[Condition, ...]] = (
    Condition.NODE_PURITY,
    Condition.INPUT_FIXED,
    Condition.ENV_FINGERPRINT,
    Condition.REPEATED_RUNS,
    Condition.RANDOMNESS,
    Condition.VALIDITY,
)

#: 唯一的一票否决条件。§8.2 关键修正：「随机性或有副作用节点不签 DC、不剪枝」。
VETO_CONDITIONS: Final[tuple[Condition, ...]] = (Condition.RANDOMNESS,)

#: 求值顺序：否决项先行，其余按表格顺序。报告顺序仍是 `CONDITION_ORDER`。
EVALUATION_ORDER: Final[tuple[Condition, ...]] = (
    Condition.RANDOMNESS,
    Condition.NODE_PURITY,
    Condition.INPUT_FIXED,
    Condition.ENV_FINGERPRINT,
    Condition.REPEATED_RUNS,
    Condition.VALIDITY,
)

#: §8.2 TABLE 34 的「要求 / 不满足时」两列，逐字。
CONDITION_LITERALS: Final[Mapping[Condition, tuple[str, str]]] = MappingProxyType(
    {
        Condition.NODE_PURITY: (
            "无数据库写入、网络请求、全局状态修改、当前时间/随机外部源依赖。",
            "永不签 DC。",
        ),
        Condition.INPUT_FIXED: (
            "数据、配置、代码、模板、依赖与上游哈希一致。",
            "DC 失效。",
        ),
        Condition.ENV_FINGERPRINT: (
            "OS/架构/CPU、Python、依赖锁、关键库、线程变量、locale/timezone、种子策略。",
            "环境变化即失效。",
        ),
        Condition.REPEATED_RUNS: (
            "默认 k=3 独立进程/目录；敏感因素增加探针。",
            "任一产物/指标不 bit-exact，不签 DC。",
        ),
        Condition.RANDOMNESS: (
            "预期具有随机波动的训练/采样节点不签 DC。",
            "用多种子/TOST 评估，不允许 DC 剪枝。",
        ),
        Condition.VALIDITY: (
            "DC 带 expires_at、ruleset_hash、code_hash、input_schema_hash。",
            "到期/规则变更后重新评估。",
        ),
    }
)

#: §8.2 表后的「关键修正」，逐字。它是本模块的边界声明。
KEY_CORRECTION: Final[str] = (
    "k 次运行相同只能形成限定环境下的经验性资格，不证明未来所有执行都确定。"
    "随机性或有副作用节点不签 DC、不剪枝。"
)

#: AGENTS §4.13 的限定语；任何「DC 已证明确定性」的表述都与本句冲突。
DC_SCOPE_STATEMENT: Final[str] = (
    "DC 是对某节点类型、固定输入结构、代码版本、依赖锁、环境指纹与规则版本，"
    "在 k 次跨进程、跨目录受控执行中观察到 bit-exact 一致的**经验性资格**；"
    "它不是数学意义上的普遍确定性证明，也不覆盖未来环境变化后的执行。"
)

#: M03 `env_fingerprint` 的七组成项（缺一项即 `ENV_FINGERPRINT_INCOMPLETE`）。
REQUIRED_ENV_COMPONENTS: Final[tuple[str, ...]] = (
    "os_arch_cpu",
    "python",
    "dependency_lock",
    "key_libraries",
    "thread_env",
    "locale_timezone",
    "seed_policy",
)


# ---------------------------------------------------------------------------
# 2. 错误与状态枚举
# ---------------------------------------------------------------------------
class DcReason(StrEnum):
    """不通过原因。每条对应一个可断言的判断点。"""

    RANDOM_NODE = "RANDOM_NODE"
    SIDE_EFFECT_NODE = "SIDE_EFFECT_NODE"
    NODE_NOT_PURE = "NODE_NOT_PURE"
    PURITY_UNKNOWN = "PURITY_UNKNOWN"
    INPUT_NOT_FIXED = "INPUT_NOT_FIXED"
    INPUT_HASH_MISSING = "INPUT_HASH_MISSING"
    ENV_CHANGED = "ENV_CHANGED"
    ENV_INCOMPLETE = "ENV_INCOMPLETE"
    K_RUNS_INSUFFICIENT = "K_RUNS_INSUFFICIENT"
    PROCESS_REUSED = "PROCESS_REUSED"
    DIRECTORY_REUSED = "DIRECTORY_REUSED"
    RUN_FINGERPRINT_REUSED = "RUN_FINGERPRINT_REUSED"
    RUN_ID_DUPLICATE = "RUN_ID_DUPLICATE"
    OUTPUT_DIVERGED = "OUTPUT_DIVERGED"
    METRIC_DIVERGED = "METRIC_DIVERGED"
    EXIT_CODE_NONZERO = "EXIT_CODE_NONZERO"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EXPIRES_AT_MISSING = "EXPIRES_AT_MISSING"
    EXPIRY_PASSED = "EXPIRY_PASSED"
    TTL_TOO_LONG = "TTL_TOO_LONG"
    RULESET_UNBOUND = "RULESET_UNBOUND"
    CODE_UNBOUND = "CODE_UNBOUND"
    INPUT_SCHEMA_UNBOUND = "INPUT_SCHEMA_UNBOUND"


class ConditionStatus(StrEnum):
    """条件结论。`MISSING_EVIDENCE` 与 `FAIL` 都不得当成通过。"""

    PASS = "PASS"
    FAIL = "FAIL"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    VETO = "VETO"


class PurityClass(StrEnum):
    """节点纯度分类。`STRICT_PURE` 是唯一可申请 DC 的类别。"""

    STRICT_PURE = "STRICT_PURE"
    DB_WRITE = "DB_WRITE"
    NETWORK = "NETWORK"
    GLOBAL_STATE = "GLOBAL_STATE"
    READS_CLOCK = "READS_CLOCK"
    READS_EXTERNAL_RANDOM = "READS_EXTERNAL_RANDOM"
    UNKNOWN = "UNKNOWN"


#: §8.2「节点纯度」明确列出的五类污染源 + 未知。命中任一，永不签 DC。
IMPURE_PURITY: Final[frozenset[PurityClass]] = frozenset(
    {
        PurityClass.DB_WRITE,
        PurityClass.NETWORK,
        PurityClass.GLOBAL_STATE,
        PurityClass.READS_CLOCK,
        PurityClass.READS_EXTERNAL_RANDOM,
        PurityClass.UNKNOWN,
    }
)


class DcEligibilityError(RuntimeError):
    """输入事实自相矛盾（不是「资格不合格」）。对外 422。"""

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422

    def __init__(self, reason: str, field_path: str, detail: str) -> None:
        self.reason = reason
        self.field_path = field_path
        self.detail = detail
        super().__init__(f"{self.error_code}/{reason} at {field_path}：{detail}")


class DcNotEnabled(RuntimeError):
    """T0/T1 或 `dc_spa=false` 时申请 DC：能力未开。对外 403。"""

    error_code: Final[str] = "FEATURE_FLAG_NOT_PERMITTED"
    http_status: Final[int] = 403

    def __init__(self, tier: str, flag_state: str) -> None:
        self.reason = "DC_SPA_REQUIRES_T2"
        self.detail = f"tier={tier!r}，dc_spa={flag_state!r}；DC 判定只在 T2 且开关为 true 时可用"
        super().__init__(f"{self.error_code}/{self.reason}：{self.detail}")


# ---------------------------------------------------------------------------
# 3. 策略与输入对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DcPolicy:
    """DC 判定参数。除 `k_min=3` 外全部是 PROPOSED（OQ-P9-04/05）。"""

    tier: str = "T2"
    dc_spa_enabled: bool = True
    k_min: int = 3
    k_sensitive_step: int = 2
    k_max: int = 9
    ttl_max_days: int = 30
    require_distinct_process: bool = True
    require_distinct_directory: bool = True
    policy_version: str = DC_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.k_min < 1:
            raise DcEligibilityError("K_MIN_INVALID", "policy.k_min", "k 下限必须 ≥ 1")
        if self.k_sensitive_step < 0:
            raise DcEligibilityError("K_STEP_INVALID", "policy.k_sensitive_step", "增量不得为负")
        if self.k_max < self.k_min:
            raise DcEligibilityError("K_MAX_INVALID", "policy.k_max", "k 上限不得小于下限")
        if self.ttl_max_days <= 0:
            raise DcEligibilityError("TTL_MAX_INVALID", "policy.ttl_max_days", "TTL 上限必须为正")


DEFAULT_DC_POLICY: Final[DcPolicy] = DcPolicy()


@dataclass(frozen=True, slots=True)
class DcCandidate:
    """节点的静态声明：能决定「能不能申请 DC」的那部分。

    `is_stochastic` 与 `purity` 都是**声明**，不是本文件去探测的结果；声明为随机即否决，
    即使这次 k 次恰好一致——那是「碰巧一样」，不是资格。
    """

    node_id: str
    node_type: str
    purity: PurityClass
    is_stochastic: bool
    has_side_effect: bool = False
    sensitive_factors: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.node_type.strip():
            raise DcEligibilityError("IDENTITY_MISSING", "node_id/node_type", "节点身份不得为空")
        if len(set(self.sensitive_factors)) != len(self.sensitive_factors):
            raise DcEligibilityError(
                "SENSITIVE_FACTOR_DUPLICATE",
                "sensitive_factors",
                "同一敏感因素重复登记会虚增 k",
            )


@dataclass(frozen=True, slots=True)
class DcBinding:
    """§8.2「输入固定」要求绑定的一整套哈希（缺一项即 MISSING_EVIDENCE）。"""

    input_schema_hash: str
    code_hash: str
    dependency_lock_hash: str
    template_hash: str
    env_fingerprint: str
    ruleset_hash: str
    upstream_hash: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "input_schema_hash",
            "code_hash",
            "dependency_lock_hash",
            "template_hash",
            "env_fingerprint",
            "ruleset_hash",
            "upstream_hash",
        ):
            _require_hash(getattr(self, name), f"binding.{name}")

    def as_map(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "input_schema_hash": self.input_schema_hash,
                "code_hash": self.code_hash,
                "dependency_lock_hash": self.dependency_lock_hash,
                "template_hash": self.template_hash,
                "env_fingerprint": self.env_fingerprint,
                "ruleset_hash": self.ruleset_hash,
                "upstream_hash": self.upstream_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class EnvComparisonView:
    """M03 环境比较结果的只读投影：每个组成项是否与历史一致。"""

    compared_components: tuple[str, ...]
    mismatched_components: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = set(self.compared_components) - set(REQUIRED_ENV_COMPONENTS)
        if unknown:
            raise DcEligibilityError(
                "ENV_COMPONENT_UNKNOWN",
                "env.compared_components",
                f"未登记的环境组成项：{sorted(unknown)}",
            )

    @property
    def complete(self) -> bool:
        return set(self.compared_components) == set(REQUIRED_ENV_COMPONENTS)

    @property
    def missing_components(self) -> tuple[str, ...]:
        return tuple(c for c in REQUIRED_ENV_COMPONENTS if c not in self.compared_components)


@dataclass(frozen=True, slots=True)
class RunProbe:
    """单次探针运行的可观测事实（由 M05 采集，本文件只读）。"""

    run_id: str
    pid: int
    working_directory: str
    run_fingerprint: str
    input_schema_hash: str
    code_hash: str
    template_hash: str
    env_fingerprint: str
    ruleset_hash: str
    output_hashes: tuple[str, ...]
    metric_hash: str
    exit_code: int = 0
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise DcEligibilityError("RUN_ID_MISSING", "run.run_id", "探针运行必须有编号")
        if self.pid <= 0:
            raise DcEligibilityError("PID_INVALID", "run.pid", "进程号必须为正整数")
        if not self.working_directory.strip():
            raise DcEligibilityError("CWD_MISSING", "run.working_directory", "工作目录不得为空")
        for name in ("run_fingerprint", "input_schema_hash", "code_hash", "template_hash", "env_fingerprint", "ruleset_hash", "metric_hash"):
            _require_hash(getattr(self, name), f"run.{name}")
        if not self.output_hashes:
            raise DcEligibilityError("OUTPUT_HASHES_MISSING", "run.output_hashes", "没有产物哈希无法比对")
        for index, digest in enumerate(self.output_hashes):
            _require_hash(digest, f"run.output_hashes[{index}]")


# ---------------------------------------------------------------------------
# 4. 结论对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ConditionResult:
    """一条条件的结论。

    核心约束：`PASS` 必须带 `evidence_ids`——没有证据编号的「通过」无法复核，
    与「没检查」等价（AGENTS §8「正例通过不构成完成证据」）。
    """

    condition: Condition
    status: ConditionStatus
    reason: DcReason | None
    evidence_ids: tuple[str, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status is ConditionStatus.PASS:
            if not self.evidence_ids:
                raise DcEligibilityError(
                    "PASS_WITHOUT_EVIDENCE",
                    f"results.{self.condition.value}",
                    "PASS 必须带证据编号；无证据的通过按缺失处理",
                )
            if self.reason is not None:
                raise DcEligibilityError(
                    "PASS_WITH_REASON",
                    f"results.{self.condition.value}",
                    "PASS 不得同时带拒绝原因",
                )
        elif self.reason is None:
            raise DcEligibilityError(
                "FAIL_WITHOUT_REASON",
                f"results.{self.condition.value}",
                f"{self.status.value} 必须给出原因",
            )
        if self.status is ConditionStatus.VETO and self.condition not in VETO_CONDITIONS:
            raise DcEligibilityError(
                "VETO_ON_NON_VETO_CONDITION",
                f"results.{self.condition.value}",
                "只有 VETO_CONDITIONS 里的条件可以产生 VETO",
            )

    @property
    def passed(self) -> bool:
        return self.status is ConditionStatus.PASS

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "condition": self.condition.value,
                "status": self.status.value,
                "reason": self.reason.value if self.reason else None,
                "evidence_ids": list(self.evidence_ids),
                "detail": self.detail,
            }
        )


@dataclass(frozen=True, slots=True)
class RunComparison:
    """k 次运行比对结果。`bit_exact` 为真时才可能签 DC。"""

    bit_exact: bool
    k_required: int
    k_observed: int
    checks: tuple[tuple[str, bool, str], ...]
    run_fingerprints: tuple[str, ...]
    output_hashes: tuple[str, ...]
    divergences: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.bit_exact and self.divergences:
            raise DcEligibilityError(
                "BIT_EXACT_WITH_DIVERGENCE",
                "run_comparison",
                "bit_exact=True 却记录了分歧",
            )
        if self.k_observed < 0:
            raise DcEligibilityError("K_OBSERVED_INVALID", "run_comparison.k_observed", "观测次数不得为负")

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(name for name, ok, _ in self.checks if not ok)

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "bit_exact": self.bit_exact,
                "k_required": self.k_required,
                "k_observed": self.k_observed,
                "checks": [{"check": n, "ok": ok, "detail": d} for n, ok, d in self.checks],
                "divergences": list(self.divergences),
            }
        )


@dataclass(frozen=True, slots=True)
class EligibilityVerdict:
    """六条件结论汇总。`eligible` 由结构强制，不由调用方填。"""

    node_id: str
    node_type: str
    results: tuple[ConditionResult, ...]
    run_comparison: RunComparison | None
    policy_version: str = DC_POLICY_VERSION
    scope_statement: str = DC_SCOPE_STATEMENT

    def __post_init__(self) -> None:
        present = tuple(r.condition for r in self.results)
        if set(present) != set(CONDITION_ORDER):
            raise DcEligibilityError(
                "CONDITIONS_INCOMPLETE",
                "results",
                f"六条件必须全量求值，缺少 {sorted(set(CONDITION_ORDER) - set(present))}",
            )
        if len(present) != len(set(present)):
            raise DcEligibilityError("CONDITION_DUPLICATE", "results", "同一条件出现两次")
        # `eligible` 是派生属性而不是字段：调用方无法把「不合格」写成「合格」。
        # 这里只做一致性自检，防止有人把属性改成可赋值字段。
        if any(r.passed for r in self.results) and self.eligible:
            if self.run_comparison is None or not self.run_comparison.bit_exact:
                raise DcEligibilityError(
                    "ELIGIBLE_WITHOUT_BIT_EXACT",
                    "run_comparison",
                    "k 次未 bit-exact 不得判定为合格",
                )

    @property
    def eligible(self) -> bool:
        """六条件全 PASS 且 k 次 bit-exact。没有「人工置真」的入口。"""
        return all(r.passed for r in self.results) and bool(
            self.run_comparison is not None and self.run_comparison.bit_exact
        )

    @property
    def vetoes(self) -> tuple[ConditionResult, ...]:
        return tuple(r for r in self.results if r.status is ConditionStatus.VETO)

    def result_for(self, condition: Condition) -> ConditionResult:
        for item in self.results:
            if item.condition is condition:
                return item
        raise DcEligibilityError("CONDITION_ABSENT", "results", f"缺少条件 {condition.value}")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "node_type": self.node_type,
                "eligible": self.eligible,
                "policy_version": self.policy_version,
                "results": [r.as_detail() for r in self.results],
                "run_comparison": self.run_comparison.as_detail() if self.run_comparison else None,
            }
        )


# ---------------------------------------------------------------------------
# 5. 形态校验
# ---------------------------------------------------------------------------
def _require_hash(value: str, field_path: str) -> None:
    """哈希必须是 64 位小写十六进制（ENCODING_RULES §4）。"""
    if not isinstance(value, str) or len(value) != 64:
        raise DcEligibilityError("HASH_INVALID", field_path, f"期望 64 位十六进制，实际 {value!r}")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise DcEligibilityError("HASH_INVALID", field_path, "哈希只允许小写十六进制")


def _require_utc(moment: datetime, field_path: str) -> None:
    """时间必须是带时区的 UTC（不接受 naive，不猜本地时区）。"""
    if not isinstance(moment, datetime):
        raise DcEligibilityError("TIME_INVALID", field_path, "必须是 datetime")
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise DcEligibilityError("TIME_NOT_UTC", field_path, "必须是带时区的 UTC 时间")


def _canonical_directory(raw: str) -> str:
    """目录比较用的保守规范化：去尾分隔符、转小写、统一分隔符。

    真实实现必须 `realpath` 后再比较；这里只固定比较口径，避免 `D:\\a` 与 `d:/a/`
    被当成两个目录而虚增「跨目录」证据。
    """
    text = raw.replace("\\", "/").rstrip("/")
    if not text:
        raise DcEligibilityError("CWD_EMPTY", "run.working_directory", "规范化后目录为空")
    return text.lower()


# ---------------------------------------------------------------------------
# 6. 探针数
# ---------------------------------------------------------------------------
def required_k(candidate: DcCandidate, policy: DcPolicy = DEFAULT_DC_POLICY) -> int:
    """按敏感因素计算所需探针次数：`k_min + step × 因子数`，封顶 `k_max`。

    参数：候选节点（读 `sensitive_factors`）、策略。
    返回：整数 k ≥ k_min。
    副作用：无。
    依据：§8.2 R05「默认 k=3 独立进程/目录；敏感因素增加探针」；增量与上限为 PROPOSED。
    """
    # 1. 基准
    needed = policy.k_min
    # 2. 每个敏感因素加一档
    needed += policy.k_sensitive_step * len(candidate.sensitive_factors)
    # 3. 封顶
    return min(needed, policy.k_max)


# ---------------------------------------------------------------------------
# 7. k 次运行 bit-exact 比对（主逻辑）
# ---------------------------------------------------------------------------
def _divergent(reason: DcReason, detail: str) -> tuple[str, bool, str]:
    """构造一条「不通过」的检查行。"""
    return (reason.value, False, detail)


def compare_runs(
    candidate: DcCandidate,
    binding: DcBinding,
    runs: Sequence[RunProbe],
    policy: DcPolicy = DEFAULT_DC_POLICY,
) -> RunComparison:
    """比对 k 次探针运行是否 bit-exact，并检查「独立」与「未被复用」。

    输入：候选节点、绑定哈希、探针列表、策略。
    输出：`RunComparison`；`bit_exact=False` 时 `divergences` 列出全部原因。
    副作用：无（纯函数）。
    错误：`DcEligibilityError`（探针少于 k_min 且无法给出结论时仍返回结果，不抛）。
    依据：§8.2 R05、§8.4「跨进程、跨目录」。

    步骤（10 项，全部求值，不只到第一个失败）：
      1. 观测次数 ≥ required_k；
      2. `run_id` 不重复；
      3. 进程号互不相同（跨进程）；
      4. 工作目录互不相同（跨目录）；
      5. `run_fingerprint` 互不相同（运行身份未被复用）；
      6. 每次运行的输入/代码/模板/环境/规则与绑定一致；
      7. 产物哈希逐字节一致；
      8. 指标哈希一致；
      9. 退出码全为 0；
      10. 每次运行都带证据编号。
    """
    checks: list[tuple[str, bool, str]] = []
    divergences: list[str] = []

    k_required = required_k(candidate, policy)
    k_observed = len(runs)

    # 1. 次数
    if k_observed < k_required:
        checks.append(_divergent(DcReason.K_RUNS_INSUFFICIENT, f"{k_observed} < {k_required}"))
        divergences.append(f"k={k_observed}，要求 {k_required}")
    else:
        checks.append(("K_RUNS", True, f"{k_observed} ≥ {k_required}"))

    # 2. run_id 唯一
    run_ids = [run.run_id for run in runs]
    if len(set(run_ids)) != len(run_ids):
        checks.append(_divergent(DcReason.RUN_ID_DUPLICATE, "同一 run_id 出现多次（重复计数）"))
        divergences.append("run_id 重复")
    else:
        checks.append(("RUN_ID_UNIQUE", True, "run_id 互不相同"))

    # 3. 跨进程
    pids = {run.pid for run in runs}
    if policy.require_distinct_process and len(pids) != len(runs):
        checks.append(_divergent(DcReason.PROCESS_REUSED, f"仅 {len(pids)} 个进程跑 {len(runs)} 次"))
        divergences.append("进程复用")
    else:
        checks.append(("DISTINCT_PROCESS", True, f"{len(pids)} 个进程"))

    # 4. 跨目录
    directories = {_canonical_directory(run.working_directory) for run in runs}
    if policy.require_distinct_directory and len(directories) != len(runs):
        checks.append(_divergent(DcReason.DIRECTORY_REUSED, f"仅 {len(directories)} 个目录跑 {len(runs)} 次"))
        divergences.append("目录复用")
    else:
        checks.append(("DISTINCT_DIRECTORY", True, f"{len(directories)} 个目录"))

    # 5. 运行指纹不复用
    fingerprints = [run.run_fingerprint for run in runs]
    if len(set(fingerprints)) != len(fingerprints):
        checks.append(_divergent(DcReason.RUN_FINGERPRINT_REUSED, "同一 run_fingerprint 出现多次"))
        divergences.append("运行指纹复用")
    else:
        checks.append(("RUN_FINGERPRINT_UNIQUE", True, "运行身份互不相同"))

    # 6. 输入/代码/模板/环境/规则与绑定一致
    mismatch: list[str] = []
    for run in runs:
        if run.input_schema_hash != binding.input_schema_hash:
            mismatch.append(f"{run.run_id}:input_schema_hash")
        if run.code_hash != binding.code_hash:
            mismatch.append(f"{run.run_id}:code_hash")
        if run.template_hash != binding.template_hash:
            mismatch.append(f"{run.run_id}:template_hash")
        if run.env_fingerprint != binding.env_fingerprint:
            mismatch.append(f"{run.run_id}:env_fingerprint")
        if run.ruleset_hash != binding.ruleset_hash:
            mismatch.append(f"{run.run_id}:ruleset_hash")
    if mismatch:
        checks.append(_divergent(DcReason.INPUT_NOT_FIXED, f"绑定不一致：{mismatch}"))
        divergences.append("输入/代码/模板/环境/规则不一致")
    else:
        checks.append(("BINDING_STABLE", True, "五个哈希与绑定一致"))

    # 7. 产物哈希一致
    outputs = [tuple(run.output_hashes) for run in runs]
    if len(set(outputs)) > 1:
        checks.append(_divergent(DcReason.OUTPUT_DIVERGED, "产物哈希在不同运行间不同"))
        divergences.append("产物分歧")
    else:
        checks.append(("OUTPUT_HASHES_IDENTICAL", True, f"{len(outputs[0]) if outputs else 0} 个产物"))

    # 8. 指标哈希一致
    metrics = {run.metric_hash for run in runs}
    if len(metrics) > 1:
        checks.append(_divergent(DcReason.METRIC_DIVERGED, "指标哈希不一致"))
        divergences.append("指标分歧")
    else:
        checks.append(("METRIC_HASH_IDENTICAL", True, "指标哈希一致"))

    # 9. 退出码
    bad_exit = [run.run_id for run in runs if run.exit_code != 0]
    if bad_exit:
        checks.append(_divergent(DcReason.EXIT_CODE_NONZERO, f"非零退出：{bad_exit}"))
        divergences.append("存在非零退出")
    else:
        checks.append(("EXIT_CODES_ZERO", True, "全部退出码为 0"))

    # 10. 证据
    no_evidence = [run.run_id for run in runs if not run.evidence_ids]
    if no_evidence:
        checks.append(_divergent(DcReason.EVIDENCE_MISSING, f"无证据编号：{no_evidence}"))
        divergences.append("探针缺证据")
    else:
        checks.append(("RUN_EVIDENCE_PRESENT", True, "每次运行都有证据"))

    bit_exact = not divergences
    # 产物哈希取「排序去重」的产物集（OQ-P9-02）：bit-exact 时各次相同，可直接取首个。
    output_hashes = tuple(sorted(set(outputs[0]))) if outputs else ()
    return RunComparison(
        bit_exact=bit_exact,
        k_required=k_required,
        k_observed=k_observed,
        checks=tuple(checks),
        run_fingerprints=tuple(fingerprints),
        output_hashes=output_hashes,
        divergences=tuple(divergences),
        evidence_ids=tuple(sorted({eid for run in runs for eid in run.evidence_ids})),
    )


# ---------------------------------------------------------------------------
# 8. 六个条件
# ---------------------------------------------------------------------------
def _randomness_result(candidate: DcCandidate) -> ConditionResult:
    """条件 5：随机性节点一票否决（EVALUATION_ORDER 第一位）。

    即使 k 次运行恰好一致，声明为随机波动的节点也**不签 DC**：
    §8.2 要求用多种子/TOST 评估，不允许用 DC 剪枝。
    """
    if candidate.is_stochastic:
        return ConditionResult(
            condition=Condition.RANDOMNESS,
            status=ConditionStatus.VETO,
            reason=DcReason.RANDOM_NODE,
            evidence_ids=candidate.evidence_ids,
            detail="节点声明为随机波动（训练/采样）：不得签 DC、不得剪枝",
        )
    if not candidate.evidence_ids:
        # 「没声明随机」不等于「有证据证明非随机」：缺声明证据按缺失处理。
        return ConditionResult(
            condition=Condition.RANDOMNESS,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.EVIDENCE_MISSING,
            detail="缺少节点静态声明的证据编号",
        )
    return ConditionResult(
        condition=Condition.RANDOMNESS,
        status=ConditionStatus.PASS,
        reason=None,
        evidence_ids=candidate.evidence_ids,
        detail="节点未声明随机波动（有声明证据）",
    )


def _purity_result(candidate: DcCandidate) -> ConditionResult:
    """条件 1：节点纯度。任一污染源命中即「永不签 DC」。"""
    if candidate.purity is PurityClass.STRICT_PURE and not candidate.has_side_effect:
        if not candidate.evidence_ids:
            return ConditionResult(
                condition=Condition.NODE_PURITY,
                status=ConditionStatus.MISSING_EVIDENCE,
                reason=DcReason.EVIDENCE_MISSING,
                detail="缺少纯度声明的证据编号",
            )
        return ConditionResult(
            condition=Condition.NODE_PURITY,
            status=ConditionStatus.PASS,
            reason=None,
            evidence_ids=candidate.evidence_ids,
            detail="声明为 STRICT_PURE 且无副作用",
        )
    if candidate.has_side_effect:
        return ConditionResult(
            condition=Condition.NODE_PURITY,
            status=ConditionStatus.FAIL,
            reason=DcReason.SIDE_EFFECT_NODE,
            evidence_ids=candidate.evidence_ids,
            detail="节点有外部副作用",
        )
    if candidate.purity is PurityClass.UNKNOWN:
        return ConditionResult(
            condition=Condition.NODE_PURITY,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.PURITY_UNKNOWN,
            evidence_ids=candidate.evidence_ids,
            detail="纯度未知：不能按纯函数处理",
        )
    return ConditionResult(
        condition=Condition.NODE_PURITY,
        status=ConditionStatus.FAIL,
        reason=DcReason.NODE_NOT_PURE,
        evidence_ids=candidate.evidence_ids,
        detail=f"污染源 {candidate.purity.value} 命中 §8.2 禁止清单",
    )


def _input_fixed_result(binding: DcBinding | None) -> ConditionResult:
    """条件 2：输入固定。数据/配置/代码/模板/依赖/上游哈希必须齐全且一致。"""
    if binding is None:
        return ConditionResult(
            condition=Condition.INPUT_FIXED,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.INPUT_HASH_MISSING,
            detail="未提供绑定哈希",
        )
    if not binding.evidence_ids:
        return ConditionResult(
            condition=Condition.INPUT_FIXED,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.EVIDENCE_MISSING,
            evidence_ids=(),
            detail="绑定哈希没有证据编号",
        )
    return ConditionResult(
        condition=Condition.INPUT_FIXED,
        status=ConditionStatus.PASS,
        reason=None,
        evidence_ids=binding.evidence_ids,
        detail="七项绑定哈希齐全",
    )


def _env_result(env: EnvComparisonView | None) -> ConditionResult:
    """条件 3：环境指纹。七组成项缺一项即不完整；不一致即失效。"""
    if env is None:
        return ConditionResult(
            condition=Condition.ENV_FINGERPRINT,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.ENV_INCOMPLETE,
            detail="未提供环境比较结果",
        )
    if env.mismatched_components:
        return ConditionResult(
            condition=Condition.ENV_FINGERPRINT,
            status=ConditionStatus.FAIL,
            reason=DcReason.ENV_CHANGED,
            evidence_ids=env.evidence_ids,
            detail=f"不一致组成项：{list(env.mismatched_components)}",
        )
    if not env.complete:
        return ConditionResult(
            condition=Condition.ENV_FINGERPRINT,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.ENV_INCOMPLETE,
            evidence_ids=env.evidence_ids,
            detail=f"缺少组成项：{list(env.missing_components)}",
        )
    if not env.evidence_ids:
        return ConditionResult(
            condition=Condition.ENV_FINGERPRINT,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.EVIDENCE_MISSING,
            detail="环境比较没有证据编号",
        )
    return ConditionResult(
        condition=Condition.ENV_FINGERPRINT,
        status=ConditionStatus.PASS,
        reason=None,
        evidence_ids=env.evidence_ids,
        detail="七组成项齐全且一致",
    )


def _k_run_result(comparison: RunComparison | None) -> ConditionResult:
    """条件 4：重复执行。k 次跨进程跨目录且产物/指标 bit-exact。"""
    if comparison is None:
        return ConditionResult(
            condition=Condition.REPEATED_RUNS,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.K_RUNS_INSUFFICIENT,
            detail="未做 k 次比对",
        )
    if comparison.k_observed < comparison.k_required:
        return ConditionResult(
            condition=Condition.REPEATED_RUNS,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.K_RUNS_INSUFFICIENT,
            evidence_ids=comparison.evidence_ids,
            detail=f"k={comparison.k_observed} < {comparison.k_required}",
        )
    if not comparison.bit_exact:
        name, _, detail = next((c for c in comparison.checks if not c[1]), ("UNKNOWN", False, ""))
        reason = _reason_of(comparison)
        return ConditionResult(
            condition=Condition.REPEATED_RUNS,
            status=ConditionStatus.FAIL,
            reason=reason,
            evidence_ids=comparison.evidence_ids,
            detail=f"{name}: {detail}",
        )
    if not comparison.evidence_ids:
        return ConditionResult(
            condition=Condition.REPEATED_RUNS,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.EVIDENCE_MISSING,
            detail="比对结果没有证据编号",
        )
    return ConditionResult(
        condition=Condition.REPEATED_RUNS,
        status=ConditionStatus.PASS,
        reason=None,
        evidence_ids=comparison.evidence_ids,
        detail=f"k={comparison.k_observed}，跨进程跨目录 bit-exact",
    )


def _reason_of(comparison: RunComparison) -> DcReason:
    """从失败的检查行反推原因，保证条件结果与比对明细一致。"""
    for name, ok, _ in comparison.checks:
        if ok:
            continue
        try:
            return DcReason(name)
        except ValueError:
            continue
    return DcReason.OUTPUT_DIVERGED


def _validity_result(
    binding: DcBinding | None,
    now: datetime,
    expires_at: datetime | None,
    policy: DcPolicy,
) -> ConditionResult:
    """条件 6：有效期与规则版本。四个字段必须在、未过期、TTL 不超上限。"""
    if binding is None:
        return ConditionResult(
            condition=Condition.VALIDITY,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.RULESET_UNBOUND,
            detail="未绑定规则版本",
        )
    if expires_at is None:
        return ConditionResult(
            condition=Condition.VALIDITY,
            status=ConditionStatus.MISSING_EVIDENCE,
            reason=DcReason.EXPIRES_AT_MISSING,
            detail="§8.2 R07 要求 expires_at 必填",
        )
    _require_utc(now, "now")
    _require_utc(expires_at, "expires_at")
    if expires_at <= now:
        return ConditionResult(
            condition=Condition.VALIDITY,
            status=ConditionStatus.FAIL,
            reason=DcReason.EXPIRY_PASSED,
            evidence_ids=binding.evidence_ids,
            detail=f"expires_at={expires_at.isoformat()} 已到期",
        )
    if expires_at - now > timedelta(days=policy.ttl_max_days):
        return ConditionResult(
            condition=Condition.VALIDITY,
            status=ConditionStatus.FAIL,
            reason=DcReason.TTL_TOO_LONG,
            evidence_ids=binding.evidence_ids,
            detail=f"TTL 超过 {policy.ttl_max_days} 天上限（PROPOSED，OQ-P9-05）",
        )
    return ConditionResult(
        condition=Condition.VALIDITY,
        status=ConditionStatus.PASS,
        reason=None,
        evidence_ids=binding.evidence_ids,
        detail=f"expires_at={expires_at.isoformat()}，ruleset={binding.ruleset_hash[:12]}…",
    )


# ---------------------------------------------------------------------------
# 9. 主入口
# ---------------------------------------------------------------------------
def evaluate_dc_eligibility(
    candidate: DcCandidate,
    *,
    binding: DcBinding | None,
    runs: Sequence[RunProbe],
    env: EnvComparisonView | None,
    now: datetime,
    expires_at: datetime | None,
    policy: DcPolicy = DEFAULT_DC_POLICY,
) -> EligibilityVerdict:
    """六条件逐条判定，返回资格结论（不签发）。

    输入：候选节点、绑定、探针、环境比较、当前时刻、拟签发到期时间、策略。
    输出：`EligibilityVerdict`；`eligible` 属性由结构强制。
    副作用：无。
    错误：`DcNotEnabled`（T0/T1）；`DcEligibilityError`（事实自相矛盾）。

    步骤：
      1. 能力门：tier 必须 T2 且开关为 true；
      2. 先算 k 次比对（它是条件 4 的输入，也用于吊销「假独立」）；
      3. 按 `EVALUATION_ORDER` 逐条求值（随机性第一位）；
      4. 按 `CONDITION_ORDER` 重新排列结果（报告顺序）；
      5. 汇总为 `EligibilityVerdict`（结构会拒绝「有失败却 eligible」）。
    """
    # 1. 能力门
    if policy.tier != "T2" or not policy.dc_spa_enabled:
        raise DcNotEnabled(policy.tier, str(policy.dc_spa_enabled).lower())

    # 2. k 次比对
    comparison: RunComparison | None = None
    if binding is not None and runs:
        comparison = compare_runs(candidate, binding, runs, policy)

    # 3. 逐条求值（否决优先）
    by_condition: dict[Condition, ConditionResult] = {}
    for condition in EVALUATION_ORDER:
        if condition is Condition.RANDOMNESS:
            by_condition[condition] = _randomness_result(candidate)
        elif condition is Condition.NODE_PURITY:
            by_condition[condition] = _purity_result(candidate)
        elif condition is Condition.INPUT_FIXED:
            by_condition[condition] = _input_fixed_result(binding)
        elif condition is Condition.ENV_FINGERPRINT:
            by_condition[condition] = _env_result(env)
        elif condition is Condition.REPEATED_RUNS:
            by_condition[condition] = _k_run_result(comparison)
        elif condition is Condition.VALIDITY:
            by_condition[condition] = _validity_result(binding, now, expires_at, policy)
        else:  # pragma: no cover - 枚举新增而漏分支时立刻暴露
            raise DcEligibilityError("CONDITION_UNHANDLED", "condition", condition.value)

    # 4. 报告顺序
    ordered = tuple(by_condition[c] for c in CONDITION_ORDER)

    # 5. 汇总
    return EligibilityVerdict(
        node_id=candidate.node_id,
        node_type=candidate.node_type,
        results=ordered,
        run_comparison=comparison,
        policy_version=policy.policy_version,
    )


# ---------------------------------------------------------------------------
# 10. 静态守卫（实现阶段用；P9 不执行）
# ---------------------------------------------------------------------------
def assert_randomness_is_veto() -> tuple[str, ...]:
    """随机性必须是否决项，且结构上无法绕过。返回空元组表示通过。"""
    problems: list[str] = []
    if VETO_CONDITIONS != (Condition.RANDOMNESS,):
        problems.append(f"VETO_CONDITIONS={VETO_CONDITIONS}，期望只有 RANDOMNESS")
    if EVALUATION_ORDER[0] is not Condition.RANDOMNESS:
        problems.append("EVALUATION_ORDER 首位不是 RANDOMNESS")
    stochastic = DcCandidate(
        node_id="node_probe",
        node_type="train",
        purity=PurityClass.STRICT_PURE,
        is_stochastic=True,
        evidence_ids=("ev_decl",),
    )
    result = _randomness_result(stochastic)
    if result.status is not ConditionStatus.VETO:
        problems.append("随机节点的条件结论不是 VETO")
    try:
        ConditionResult(
            condition=Condition.INPUT_FIXED,
            status=ConditionStatus.VETO,
            reason=DcReason.RANDOM_NODE,
        )
    except DcEligibilityError:
        pass
    else:
        problems.append("非否决条件被允许标 VETO")
    return tuple(problems)


def assert_conservative_defaults() -> tuple[str, ...]:
    """缺证据不得通过；默认策略必须保守。返回空元组表示通过。"""
    problems: list[str] = []
    missing = _input_fixed_result(None)
    if missing.status is ConditionStatus.PASS:
        problems.append("缺绑定被判 PASS")
    try:
        ConditionResult(
            condition=Condition.INPUT_FIXED,
            status=ConditionStatus.PASS,
            reason=None,
            evidence_ids=(),
        )
    except DcEligibilityError:
        pass
    else:
        problems.append("无证据的 PASS 未被拒绝")
    if DEFAULT_DC_POLICY.k_min != 3:
        problems.append("默认 k 不是 3")
    if not DEFAULT_DC_POLICY.require_distinct_process or not DEFAULT_DC_POLICY.require_distinct_directory:
        problems.append("默认未要求跨进程/跨目录")
    return tuple(problems)


def assert_scope_statement() -> tuple[str, ...]:
    """限定语必须写明「不是数学确定性证明」。返回空元组表示通过。"""
    problems: list[str] = []
    for token in ("经验性资格", "不是数学意义上的普遍确定性证明"):
        if token not in DC_SCOPE_STATEMENT:
            problems.append(f"DC_SCOPE_STATEMENT 缺少「{token}」")
    if "确定性证明" not in KEY_CORRECTION:
        problems.append("KEY_CORRECTION 与 §8.2 原文不一致")
    return tuple(problems)


def assert_condition_math() -> tuple[str, ...]:
    """六条件齐全、k 单调、封顶生效。返回空元组表示通过。"""
    problems: list[str] = []
    if len(CONDITION_ORDER) != 6 or set(CONDITION_ORDER) != set(Condition):
        problems.append("CONDITION_ORDER 不是六类条件的全排列")
    if set(EVALUATION_ORDER) != set(CONDITION_ORDER):
        problems.append("EVALUATION_ORDER 与 CONDITION_ORDER 条件集合不一致")
    base = DcCandidate(node_id="n", node_type="t", purity=PurityClass.STRICT_PURE, is_stochastic=False)
    one = DcCandidate(
        node_id="n",
        node_type="t",
        purity=PurityClass.STRICT_PURE,
        is_stochastic=False,
        sensitive_factors=("gpu",),
    )
    if required_k(one) <= required_k(base):
        problems.append("敏感因素未增加探针数")
    many = DcCandidate(
        node_id="n",
        node_type="t",
        purity=PurityClass.STRICT_PURE,
        is_stochastic=False,
        sensitive_factors=tuple(f"f{i}" for i in range(10)),
    )
    if required_k(many) > DEFAULT_DC_POLICY.k_max:
        problems.append("k 未按 k_max 封顶")
    return tuple(problems)