"""MODULE: M10 · verifier/attribution.py — L3 差异六类归因（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-007、策划书 §9.3（六类归因）、§9.4
FR/依赖: FR-007；依赖 M03 环境指纹、M06 Split Manifest、M08 ruleset、M10 l3_replay 的比较结果
不变量/错误码: 归因只允许六类：环境/数据/代码/随机性/规则/未知；每类都有机器判据与置信说明；
             不得把“未知”当垃圾桶（已知因子不一致时必须先归到已知类）；
             固定种子/确定性模式下输出不同，不得归因为随机性。
             错误码：SCHEMA_INVALID（422，归因输入非法）、REQUIRED_EVIDENCE_MISSING（409，缺判据）
写入者: **无**；纯只读分析，不写证据/报告/状态
状态: 伪代码；不建环境、不跑测试、不写业务代码

## 六类判据（机器可判）

  | 类别 | 判据 | 置信 |
  |---|---|---|
  | 环境 | 环境指纹组成项/依赖锁/Python 版本任一不同；缺项按不一致 | HIGH（单因子）/MEDIUM（多因子） |
  | 数据 | dataset_hash、row_id_hash、fold_assignment_hash、行数/标签任一不同 | HIGH |
  | 代码 | code_hash、config_hash、template_version、parameters_hash 任一不同 | HIGH |
  | 随机性 | 同环境/数据/代码 + 随机性模式 + ≥5 预注册种子 + 观测方差落在等价边界内 | MEDIUM/HIGH |
  | 规则 | ruleset_hash、指标定义、等价性计划哈希任一不同（比较本身失效） | HIGH |
  | 未知 | 以上因子全部一致（或无法判定），仍无法解释差异 | LOW；必须人工复核 |

## 优先级

  `规则 > 数据 > 代码 > 环境 > 随机性 > 未知`。规则不一致时，其他差异可能是规则变化导致，
  因此规则优先；数据/代码/环境按“谁能解释输入差异”的顺序。多个因子同时不一致时，
  primary 取最高优先级，其余进 contributors，置信降为 MEDIUM，并要求人工复核。

## 不做什么

  - 不把“结果不同”直接归因为随机性；固定种子/确定性模式下这是禁止的。
  - 不声称归因是因果证明；它只是“在已有哈希/清单证据下最可能的类别”。
  - 不在 UNKNOWN 时编造原因；必须保留 `unexplained=True` 并转人工。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "AttributionInput",
    "AttributionReport",
    "Cause",
    "Confidence",
    "FactorCheck",
    "RandomnessCheck",
    "assert_attribution_boundary",
    "attribute",
]

FACTOR_PRECEDENCE: Final[tuple[str, ...]] = (
    "RULES", "DATA", "CODE", "ENVIRONMENT",
)


class Cause(StrEnum):
    ENVIRONMENT = "ENVIRONMENT"
    DATA = "DATA"
    CODE = "CODE"
    RANDOMNESS = "RANDOMNESS"
    RULES = "RULES"
    UNKNOWN = "UNKNOWN"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class FactorCheck:
    """一个已知因子的逐项比较结果；`matched=False` 表示该因子可解释差异。"""

    factor: Cause
    matched: bool
    expected: str
    actual: str
    components: Mapping[str, bool] = field(default_factory=lambda: MappingProxyType({}))
    note: str = ""

    def __post_init__(self) -> None:
        if self.factor not in (Cause.ENVIRONMENT, Cause.DATA, Cause.CODE, Cause.RULES):
            raise ValueError(f"FactorCheck 只接受四个已知因子，实际 {self.factor!r}")
        if self.matched and self.expected != self.actual:
            raise ValueError("matched=True 时 expected/actual 必须相同")
        if not self.matched and self.expected == self.actual and not self.note:
            raise ValueError("不匹配但没有差异说明")

    def mismatched_components(self) -> tuple[str, ...]:
        return tuple(name for name, ok in self.components.items() if not ok)


@dataclass(frozen=True, slots=True)
class RandomnessCheck:
    """随机性判据；只有随机性模式 + 预注册种子 + 方差可解释才允许归因。"""

    fixed_seed: bool
    seeds_pre_registered: bool
    seed_count: int
    within_variance: bool
    variance_explains: bool
    details: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if isinstance(self.seed_count, bool) or not isinstance(self.seed_count, int) or self.seed_count < 0:
            raise ValueError("seed_count 必须是非负 integer")

    def can_explain(self) -> bool:
        return (
            not self.fixed_seed
            and self.seeds_pre_registered
            and self.seed_count >= 5
            and self.within_variance
            and self.variance_explains
        )


@dataclass(frozen=True, slots=True)
class AttributionInput:
    """归因输入；四个 FactorCheck 必须齐全，缺项用 matched=False + note 表达。"""

    rules: FactorCheck
    data: FactorCheck
    code: FactorCheck
    environment: FactorCheck
    randomness: RandomnessCheck
    equivalence_mode: str
    output_differs: bool
    note: str = ""

    def __post_init__(self) -> None:
        for check, expected in (
            (self.rules, Cause.RULES), (self.data, Cause.DATA),
            (self.code, Cause.CODE), (self.environment, Cause.ENVIRONMENT),
        ):
            if check.factor is not expected:
                raise ValueError(f"因子位置错位：期望 {expected}，实际 {check.factor}")
        if self.equivalence_mode not in ("DETERMINISTIC", "STOCHASTIC"):
            raise ValueError(f"未知等价性模式：{self.equivalence_mode!r}")


@dataclass(frozen=True, slots=True)
class AttributionReport:
    """六类归因结论；`unexplained=True` 时不得声称已解释。"""

    primary: Cause | None
    contributors: tuple[Cause, ...]
    confidence: Confidence
    basis: tuple[str, ...]
    unexplained: bool
    requires_human_review: bool
    no_difference: bool = False

    def __post_init__(self) -> None:
        if self.no_difference:
            if self.primary is not None or self.contributors or self.unexplained:
                raise ValueError("无差异时不得带 primary/contributors/unexplained")
        elif self.primary is None:
            raise ValueError("有差异但 primary 为空：必须归到六类之一")

    def to_dict(self) -> dict[str, object]:
        return {
            "primary": self.primary.value if self.primary else None,
            "contributors": [cause.value for cause in self.contributors],
            "confidence": self.confidence.value,
            "basis": list(self.basis),
            "unexplained": self.unexplained,
            "requires_human_review": self.requires_human_review,
            "no_difference": self.no_difference,
        }


def attribute(attribution_input: AttributionInput) -> AttributionReport:
    """按优先级归因；返回类别、置信、依据与是否需人工复核。

    步骤：
      1. 无差异 → no_difference=True；
      2. 按 `规则 > 数据 > 代码 > 环境` 收集 matched=False 的因子；
      3. 有多个 → primary 取最高优先级，其余 contributors，置信 MEDIUM，人工复核；
      4. 恰有一个 → primary 该因子，置信 HIGH（环境缺组成项时 MEDIUM）；
      5. 没有已知因子：
         a. 确定性模式 → UNKNOWN（HIGH），明确“随机性被排除”；
         b. 随机性模式且 RandomnessCheck.can_explain() → RANDOMNESS（MEDIUM），
            否则 UNKNOWN（LOW）；
      6. 任何 UNKNOWN 都 `unexplained=True` 且要求人工复核。
    """
    checks: Mapping[str, FactorCheck] = MappingProxyType({
        "RULES": attribution_input.rules,
        "DATA": attribution_input.data,
        "CODE": attribution_input.code,
        "ENVIRONMENT": attribution_input.environment,
    })

    if not attribution_input.output_differs:
        return AttributionReport(
            primary=None, contributors=(), confidence=Confidence.HIGH,
            basis=("compare(predictions, metrics, artifacts) == equal",),
            unexplained=False, requires_human_review=False, no_difference=True,
        )

    mismatched = [name for name in FACTOR_PRECEDENCE if not checks[name].matched]
    if len(mismatched) > 1:
        primary = Cause(mismatched[0])
        contributors = tuple(Cause(name) for name in mismatched[1:])
        basis = tuple(
            f"{name}: expected={checks[name].expected} actual={checks[name].actual}"
            for name in mismatched
        )
        return AttributionReport(
            primary=primary, contributors=contributors, confidence=Confidence.MEDIUM,
            basis=basis, unexplained=False, requires_human_review=True,
        )

    if len(mismatched) == 1:
        name = mismatched[0]
        check = checks[name]
        confidence = Confidence.HIGH
        if name == "ENVIRONMENT" and check.mismatched_components():
            # 环境多组成项同时不同，无法区分主因；降为 MEDIUM。
            confidence = Confidence.MEDIUM
        basis = (
            f"{name}: expected={check.expected} actual={check.actual}",
            f"other_factors_matched={all(checks[n].matched for n in FACTOR_PRECEDENCE if n != name)}",
        )
        return AttributionReport(
            primary=Cause(name), contributors=(), confidence=confidence,
            basis=basis, unexplained=False, requires_human_review=False,
        )

    # 已知因子全部一致：确定性模式禁止归因随机性。
    if attribution_input.equivalence_mode == "DETERMINISTIC":
        return AttributionReport(
            primary=Cause.UNKNOWN, contributors=(), confidence=Confidence.HIGH,
            basis=(
                "all known factor hashes matched",
                "equivalence_mode=DETERMINISTIC => randomness excluded",
            ),
            unexplained=True, requires_human_review=True,
        )

    randomness = attribution_input.randomness
    if randomness.can_explain():
        return AttributionReport(
            primary=Cause.RANDOMNESS, contributors=(), confidence=Confidence.MEDIUM,
            basis=(
                "all known factor hashes matched",
                f"seeds_pre_registered={randomness.seeds_pre_registered}",
                f"seed_count={randomness.seed_count}",
                f"within_variance={randomness.within_variance}",
                f"variance_explains={randomness.variance_explains}",
            ),
            unexplained=False, requires_human_review=False,
        )
    return AttributionReport(
        primary=Cause.UNKNOWN, contributors=(), confidence=Confidence.LOW,
        basis=(
            "all known factor hashes matched",
            "randomness cannot explain: "
            f"fixed_seed={randomness.fixed_seed}, "
            f"seeds_pre_registered={randomness.seeds_pre_registered}, "
            f"seed_count={randomness.seed_count}, "
            f"within_variance={randomness.within_variance}, "
            f"variance_explains={randomness.variance_explains}",
        ),
        unexplained=True, requires_human_review=True,
    )


def assert_attribution_boundary() -> list[str]:
    """归因不得引入第七类，也不得用“人工判断”代替机器判据。"""
    problems: list[str] = []
    if {cause.value for cause in Cause} != {
        "ENVIRONMENT", "DATA", "CODE", "RANDOMNESS", "RULES", "UNKNOWN",
    }:
        problems.append("Cause 必须是且仅是六类")
    if FACTOR_PRECEDENCE != ("RULES", "DATA", "CODE", "ENVIRONMENT"):
        problems.append("因子优先级被改动")
    # 构造一个“确定性模式、全部匹配、输出不同”的场景，必须得到 UNKNOWN 而非 RANDOMNESS。
    report = attribute(AttributionInput(
        rules=FactorCheck(Cause.RULES, True, "a" * 64, "a" * 64),
        data=FactorCheck(Cause.DATA, True, "b" * 64, "b" * 64),
        code=FactorCheck(Cause.CODE, True, "c" * 64, "c" * 64),
        environment=FactorCheck(Cause.ENVIRONMENT, True, "d" * 64, "d" * 64),
        randomness=RandomnessCheck(False, True, 5, True, True),
        equivalence_mode="DETERMINISTIC",
        output_differs=True,
    ))
    if report.primary is not Cause.UNKNOWN or not report.unexplained:
        problems.append("确定性模式不得把差异归因为随机性")
    return problems