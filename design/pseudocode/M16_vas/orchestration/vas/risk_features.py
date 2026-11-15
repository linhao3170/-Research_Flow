"""M16 · orchestration/vas/risk_features.py — F/N/G/I/A 五特征与权重冻结（P9 伪代码）。
MODULE: M16 VAS ｜ 阶段：P9「DC/SPA 与 VAS」
追踪：FR-016（T2）、策划书 §8.7 风险公式、§4.2 R11、§4.3 统计纪律
FR+依赖：M08 Gate coverage 聚合（只读）、M05 运行结果计数、M09 报告指标来源标记；
        **不**依赖 DC/SPA 判定结果（VAS 与 DC 剪枝是两个正交决策）
不变量：五个特征全部归一化到 [0,1]；`RiskWeights` 五项之和必须为 1；内部权重/cap 是预注册常量，
        只有五维总权重允许在 G-dev 校准，且必须在 G-hold 前冻结；G-hold 阶段不得调参
错误码：SCHEMA_INVALID（形态错误，422）、FEATURE_FLAG_NOT_PERMITTED（tier≠T2，403）、
        WEIGHTS_FREEZE_VIOLATION（冻结边界被违反，409）
写入者：无（只计算分数；不写预算账本、不写实验记录、不改 Gate 结论）
状态：伪代码；不跑 G-dev 校准、不做 G-hold 盲测

## 公式（§8.7 逐字）

  `R_i = 0.25·F_i + 0.20·N_i + 0.20·G_i + 0.20·I_i + 0.15·A_i`

  | 特征 | 含义 | 本文件实现 |
  |---|---|---|
  | F | 历史失败风险 | Beta-Binomial 平滑，Jeffreys α=β=0.5；0 试验 → 0.5 |
  | N | 输入/配置新颖度 | `0.50·未见输入 + 0.30·配置变更 + 0.10·新数据集 + 0.10·新模板` |
  | G | 证据缺口 | `1 − 已覆盖/必检 + 0.5·未解释冲突/必检`，截断 [0,1] |
  | I | 下游/报告影响 | `0.70·报告来源 + 0.30·后代占比` |
  | A | 异常信号 | `Σ w_i·min(1, count_i/cap_i)`，cap 防单信号放大 |

## 为什么用 Beta-Binomial 而不是失败率

  直接 `failures/trials` 会让「0/1」变成风险 0、「无历史」无法排序，还会让只跑过一次的节点
  压过跑过 200 次的节点。Beta-Binomial 把两者拉回中性值 0.5，试验越多数据越占主导。
  它只是**排序先验**，不裁决节点对错，也不替代 Gate。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

__all__ = [
    "ANOMALY_CAPS",
    "ANOMALY_WEIGHTS",
    "DEFAULT_PRIOR",
    "DEFAULT_WEIGHTS",
    "FEATURE_VERSION",
    "GAP_CONFLICT_WEIGHT",
    "IMPACT_WEIGHTS",
    "NOVELTY_WEIGHTS",
    "POST_G_DEV_PRE_G_HOLD",
    "WEIGHTS_STATUS",
    "BetaPrior",
    "RiskFacts",
    "RiskFeatures",
    "RiskRefused",
    "RiskWeights",
    "WeightRegistry",
    "WeightsFreeze",
    "assert_bounds_hold",
    "assert_calibration_boundary",
    "assert_weights_sum",
    "compute_features",
    "compute_risk",
    "freeze_weights",
    "smoothed_failure_rate",
]

STAGE: Final[str] = "P9"

#: 特征公式版本。G-dev 前固定；改公式必须升版本并重跑全部对照。
FEATURE_VERSION: Final[str] = "vas-features/1.0"

#: 默认权重**未校准**：不得当成最终值写进实验报告。
WEIGHTS_STATUS: Final[str] = "UNCALIBRATED_UNTIL_G_DEV"

#: 唯一允许的冻结阶段：G-dev 之后、G-hold 之前。
POST_G_DEV_PRE_G_HOLD: Final[str] = "POST_G_DEV_PRE_G_HOLD"

#: N 的内部权重（和 = 1；预注册常量，OQ-P9-11）。
NOVELTY_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "unseen_input_ratio": 0.50,
        "config_change_ratio": 0.30,
        "new_dataset": 0.10,
        "new_template": 0.10,
    }
)

#: I 的内部权重（和 = 1）。
IMPACT_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "is_report_source": 0.70,
        "descendant_ratio": 0.30,
    }
)

#: A 的五类异常权重（和 = 1）。
ANOMALY_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "schema_gap": 0.25,
        "chain_gap": 0.20,
        "seq_gap": 0.20,
        "hash_mismatch": 0.20,
        "coverage_drop": 0.15,
    }
)

#: A 的计数上限：单个信号不得无限放大（预注册常量）。
ANOMALY_CAPS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "schema_gap": 3,
        "chain_gap": 3,
        "seq_gap": 3,
        "hash_mismatch": 2,
        "coverage_drop": 2,
    }
)

#: G 里「未解释冲突」的权重：0.5 个必检项的等效缺口。
GAP_CONFLICT_WEIGHT: Final[float] = 0.5


# ---------------------------------------------------------------------------
# 1. 错误
# ---------------------------------------------------------------------------
class RiskRefused(RuntimeError):
    """特征/权重/冻结边界错误。"""

    def __init__(
        self,
        reason: str,
        detail: str,
        *,
        error_code: str = "SCHEMA_INVALID",
        http_status: int = 422,
        field_path: str = "risk_features",
    ) -> None:
        self.error_code = error_code
        self.http_status = http_status
        self.reason = reason
        self.detail = detail
        self.field_path = field_path
        super().__init__(f"{self.error_code}/{reason} @ {field_path}：{detail}")


# ---------------------------------------------------------------------------
# 2. 形态校验
# ---------------------------------------------------------------------------
def _require_unit(value: object, field_path: str) -> float:
    """[0,1] 实数；拒绝 bool 与 NaN。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskRefused("NOT_A_NUMBER", f"{field_path} 必须是数值", field_path=field_path)
    number = float(value)
    if number != number:
        raise RiskRefused("NAN_REJECTED", f"{field_path} 不得为 NaN", field_path=field_path)
    if not 0.0 <= number <= 1.0:
        raise RiskRefused("OUT_OF_RANGE", f"{field_path}={number} 不在 [0,1]", field_path=field_path)
    return number


def _require_count(value: object, field_path: str) -> int:
    """非负整数计数（bool 不算）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskRefused("COUNT_NOT_INTEGER", f"{field_path} 必须是整数", field_path=field_path)
    if value < 0:
        raise RiskRefused("COUNT_NEGATIVE", f"{field_path}={value} 不得为负", field_path=field_path)
    return value


def _require_utc(text: str, field_path: str) -> None:
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as exc:
        raise RiskRefused("TIME_INVALID", f"{field_path} 不是 RFC3339 UTC：{text!r}", field_path=field_path) from exc


def _require_sha256(text: str, field_path: str) -> None:
    if not isinstance(text, str) or len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise RiskRefused("HASH_INVALID", f"{field_path} 不是 64 位小写十六进制", field_path=field_path)


# ---------------------------------------------------------------------------
# 3. Beta 先验与 F
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BetaPrior:
    """Beta 先验。Jeffreys 先验 α=β=0.5（§8.7 的平滑口径）。"""

    alpha: float = 0.5
    beta: float = 0.5

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 0:
            raise RiskRefused("PRIOR_INVALID", "α/β 必须为正")

    @property
    def mean(self) -> float:
        """先验均值：无试验时 F 取这个值（Jeffreys → 0.5）。"""
        return self.alpha / (self.alpha + self.beta)


DEFAULT_PRIOR: Final[BetaPrior] = BetaPrior()


def smoothed_failure_rate(
    failures: int,
    trials: int,
    prior: BetaPrior = DEFAULT_PRIOR,
) -> float:
    """Beta-Binomial 后验均值：`(failures + α) / (trials + α + β)`。

    输入：失败数、试验数、先验。
    输出：[0,1] 的平滑失败率；0 试验时为先验均值 0.5。
    错误：`RiskRefused`（计数为负或 failures > trials）。
    依据：§8.7「F 为历史失败风险（Beta-Binomial 平滑）」。
    """
    _require_count(failures, "failures")
    _require_count(trials, "trials")
    if failures > trials:
        raise RiskRefused("FAILURES_EXCEED_TRIALS", f"failures={failures} > trials={trials}", field_path="trials")
    return (failures + prior.alpha) / (trials + prior.alpha + prior.beta)


# ---------------------------------------------------------------------------
# 4. 特征事实与结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RiskFacts:
    """计算五特征所需的事实。全部是「已由别处观测到的计数/比例」，本文件不重新裁决。"""

    node_id: str
    failures: int = 0
    trials: int = 0
    unseen_input_ratio: float = 0.0
    config_change_ratio: float = 0.0
    new_dataset: bool = False
    new_template: bool = False
    required_checks: int = 0
    covered_checks: int = 0
    unexplained_conflicts: int = 0
    is_report_source: bool = False
    descendant_ratio: float = 0.0
    anomaly_counts: Mapping[str, int] = field(default_factory=dict)
    prior: BetaPrior = DEFAULT_PRIOR

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise RiskRefused("NODE_ID_MISSING", "node_id 不得为空", field_path="node_id")
        _require_count(self.failures, "failures")
        _require_count(self.trials, "trials")
        if self.failures > self.trials:
            raise RiskRefused("FAILURES_EXCEED_TRIALS", "failures 不得大于 trials", field_path="trials")
        _require_unit(self.unseen_input_ratio, "unseen_input_ratio")
        _require_unit(self.config_change_ratio, "config_change_ratio")
        _require_unit(self.descendant_ratio, "descendant_ratio")
        _require_count(self.required_checks, "required_checks")
        _require_count(self.covered_checks, "covered_checks")
        if self.covered_checks > self.required_checks:
            raise RiskRefused("COVERED_EXCEEDS_REQUIRED", "已覆盖数不得大于必检数", field_path="covered_checks")
        _require_count(self.unexplained_conflicts, "unexplained_conflicts")
        for name, value in self.anomaly_counts.items():
            if name not in ANOMALY_WEIGHTS:
                raise RiskRefused("ANOMALY_KIND_UNKNOWN", f"未登记的异常类型 {name!r}", field_path="anomaly_counts")
            _require_count(value, f"anomaly_counts.{name}")
        for flag in ("new_dataset", "new_template", "is_report_source"):
            if not isinstance(getattr(self, flag), bool):
                raise RiskRefused("FLAG_NOT_BOOL", f"{flag} 必须是布尔", field_path=flag)


@dataclass(frozen=True, slots=True)
class RiskFeatures:
    """五个特征，全部在 [0,1]。构造期即校验，越界不可能进入下一步。"""

    f: float
    n: float
    g: float
    i: float
    a: float
    feature_version: str = FEATURE_VERSION

    def __post_init__(self) -> None:
        for name in ("f", "n", "g", "i", "a"):
            _require_unit(getattr(self, name), name)

    def as_map(self) -> Mapping[str, float]:
        return MappingProxyType({"f": self.f, "n": self.n, "g": self.g, "i": self.i, "a": self.a})

    def risk(self, weights: "RiskWeights") -> float:
        """`R = Σ weight·feature`；权重由调用方给定，本类型不内置权重。"""
        total = 0.0
        for name, weight in weights.as_map().items():
            total += weight * getattr(self, name)
        return _clamp(total)


@dataclass(frozen=True, slots=True)
class RiskWeights:
    """五维总权重。只有它可以被 G-dev 校准；内部权重/cap 不行。"""

    f: float = 0.25
    n: float = 0.20
    g: float = 0.20
    i: float = 0.20
    a: float = 0.15

    def __post_init__(self) -> None:
        for name in ("f", "n", "g", "i", "a"):
            _require_unit(getattr(self, name), name)
        total = sum(self.as_map().values())
        if abs(total - 1.0) > 1e-9:
            raise RiskRefused(
                "WEIGHTS_NOT_NORMALIZED",
                f"五项权重之和={total}，必须为 1",
                field_path="weights",
            )

    def as_map(self) -> Mapping[str, float]:
        return MappingProxyType({"f": self.f, "n": self.n, "g": self.g, "i": self.i, "a": self.a})

    @property
    def normalized(self) -> bool:
        return abs(sum(self.as_map().values()) - 1.0) <= 1e-9

    def as_body(self) -> Mapping[str, object]:
        body = dict(self.as_map())
        body["status"] = WEIGHTS_STATUS
        return MappingProxyType(body)


DEFAULT_WEIGHTS: Final[RiskWeights] = RiskWeights()


def _clamp(value: float) -> float:
    """截断到 [0,1]；NaN 直接拒绝（截断不能掩盖 NaN）。"""
    if value != value:
        raise RiskRefused("NAN_REJECTED", "计算结果为 NaN")
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


# ---------------------------------------------------------------------------
# 5. 五个特征
# ---------------------------------------------------------------------------
def _failure_feature(facts: RiskFacts) -> float:
    """F：Beta-Binomial 平滑失败率。"""
    return _clamp(smoothed_failure_rate(facts.failures, facts.trials, facts.prior))


def _novelty_feature(facts: RiskFacts) -> float:
    """N：未见输入与配置变更的加权和，内部权重和为 1。"""
    total = 0.0
    total += NOVELTY_WEIGHTS["unseen_input_ratio"] * facts.unseen_input_ratio
    total += NOVELTY_WEIGHTS["config_change_ratio"] * facts.config_change_ratio
    total += NOVELTY_WEIGHTS["new_dataset"] * (1.0 if facts.new_dataset else 0.0)
    total += NOVELTY_WEIGHTS["new_template"] * (1.0 if facts.new_template else 0.0)
    return _clamp(total)


def _gap_feature(facts: RiskFacts) -> float:
    """G：证据缺口。`1 − 已覆盖/必检 + 0.5·未解释冲突/必检`。

    必检数为 0 时缺口记为 0（没有必检项就没有缺口；这不是「通过」判断）。
    """
    if facts.required_checks == 0:
        return 0.0
    uncovered = 1.0 - facts.covered_checks / facts.required_checks
    conflicts = GAP_CONFLICT_WEIGHT * facts.unexplained_conflicts / facts.required_checks
    return _clamp(uncovered + conflicts)


def _impact_feature(facts: RiskFacts) -> float:
    """I：报告来源 + 后代占比。"""
    total = IMPACT_WEIGHTS["is_report_source"] * (1.0 if facts.is_report_source else 0.0)
    total += IMPACT_WEIGHTS["descendant_ratio"] * facts.descendant_ratio
    return _clamp(total)


def _anomaly_feature(facts: RiskFacts) -> float:
    """A：五类异常信号的加权饱和和，每类先按 cap 截断。"""
    total = 0.0
    for kind, weight in ANOMALY_WEIGHTS.items():
        count = facts.anomaly_counts.get(kind, 0)
        cap = ANOMALY_CAPS[kind]
        total += weight * min(1.0, count / cap)
    return _clamp(total)


def compute_features(facts: RiskFacts) -> RiskFeatures:
    """计算 F/N/G/I/A 五特征。

    输入：`RiskFacts`。
    输出：`RiskFeatures`（五项都在 [0,1]）。
    副作用：无（纯函数）。
    错误：`RiskRefused`（事实形态错误）。
    依据：§8.7；`FEATURE_VERSION` 固定公式版本。
    """
    return RiskFeatures(
        f=_failure_feature(facts),
        n=_novelty_feature(facts),
        g=_gap_feature(facts),
        i=_impact_feature(facts),
        a=_anomaly_feature(facts),
    )


def compute_risk(facts: RiskFacts, weights: RiskWeights = DEFAULT_WEIGHTS) -> float:
    """`R = Σ weight·feature`（[0,1]）。"""
    return compute_features(facts).risk(weights)


# ---------------------------------------------------------------------------
# 6. 权重冻结
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WeightsFreeze:
    """一次权重冻结。阶段只允许 `POST_G_DEV_PRE_G_HOLD`。"""

    weights: RiskWeights
    calibration_phase: str
    frozen_at: str
    calibration_manifest_hash: str

    def __post_init__(self) -> None:
        if self.calibration_phase != POST_G_DEV_PRE_G_HOLD:
            raise RiskRefused(
                "FREEZE_PHASE_INVALID",
                f"只允许在 {POST_G_DEV_PRE_G_HOLD} 冻结，实际 {self.calibration_phase!r}",
                error_code="WEIGHTS_FREEZE_VIOLATION",
                http_status=409,
                field_path="calibration_phase",
            )
        _require_utc(self.frozen_at, "frozen_at")
        _require_sha256(self.calibration_manifest_hash, "calibration_manifest_hash")

    def as_body(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "weights": dict(self.weights.as_map()),
                "status": "FROZEN",
                "calibration_phase": self.calibration_phase,
                "frozen_at": self.frozen_at,
                "calibration_manifest_hash": self.calibration_manifest_hash,
            }
        )


class WeightRegistry:
    """P9 内存登记：只能冻结一次；冻结后不接受新权重。"""

    def __init__(self) -> None:
        self._freeze: WeightsFreeze | None = None

    @property
    def frozen(self) -> bool:
        return self._freeze is not None

    def freeze(self, freeze: WeightsFreeze) -> None:
        """登记冻结。重复冻结（即使权重相同）也拒绝，避免「悄悄换权重」。"""
        if self._freeze is not None:
            raise RiskRefused(
                "WEIGHTS_ALREADY_FROZEN",
                "权重已冻结；G-hold 阶段不得再改",
                error_code="WEIGHTS_FREEZE_VIOLATION",
                http_status=409,
            )
        self._freeze = freeze

    def current(self, *, require_frozen: bool = True) -> RiskWeights:
        """取当前权重。正式分配必须 `require_frozen=True`。"""
        if self._freeze is None:
            if require_frozen:
                raise RiskRefused(
                    "WEIGHTS_NOT_FROZEN",
                    "正式分配前必须先在 G-dev 后冻结权重",
                    error_code="WEIGHTS_FREEZE_VIOLATION",
                    http_status=409,
                )
            return DEFAULT_WEIGHTS
        return self._freeze.weights

    @property
    def freeze_record(self) -> WeightsFreeze | None:
        return self._freeze


def freeze_weights(
    weights: RiskWeights,
    *,
    calibration_phase: str,
    frozen_at: str,
    calibration_manifest_hash: str,
    registry: WeightRegistry | None = None,
) -> WeightsFreeze:
    """冻结权重：G-dev 后、G-hold 前一次完成。

    输入：权重、阶段、冻结时刻、校准清单哈希、可选登记表。
    输出：`WeightsFreeze`。
    副作用：若给 `registry`，登记一次。
    错误：`RiskRefused`（阶段不符 409 / 重复冻结 409 / 形态错误）。
    """
    freeze = WeightsFreeze(
        weights=weights,
        calibration_phase=calibration_phase,
        frozen_at=frozen_at,
        calibration_manifest_hash=calibration_manifest_hash,
    )
    if registry is not None:
        registry.freeze(freeze)
    return freeze


# ---------------------------------------------------------------------------
# 7. 静态守卫（实现阶段用；P9 不执行）
# ---------------------------------------------------------------------------
def _probe_facts(**overrides: object) -> RiskFacts:
    base: dict[str, object] = dict(
        node_id="node_probe",
        failures=1,
        trials=4,
        unseen_input_ratio=0.5,
        config_change_ratio=0.25,
        new_dataset=True,
        new_template=False,
        required_checks=5,
        covered_checks=3,
        unexplained_conflicts=1,
        is_report_source=True,
        descendant_ratio=0.5,
        anomaly_counts={"schema_gap": 1, "chain_gap": 2},
    )
    base.update(overrides)
    return RiskFacts(**base)  # type: ignore[arg-type]


def assert_bounds_hold() -> tuple[str, ...]:
    """五特征必须恒在 [0,1]，且边界输入不越界。"""
    problems: list[str] = []
    cases = (
        _probe_facts(),
        _probe_facts(failures=0, trials=0, required_checks=0, covered_checks=0, unexplained_conflicts=0),
        _probe_facts(failures=4, trials=4, covered_checks=0, unexplained_conflicts=9, descendant_ratio=1.0),
        _probe_facts(anomaly_counts={kind: 99 for kind in ANOMALY_WEIGHTS}),
    )
    for facts in cases:
        features = compute_features(facts)
        for name, value in features.as_map().items():
            if not 0.0 <= value <= 1.0:
                problems.append(f"{name}={value} 越界（node={facts.node_id}）")
    if compute_features(_probe_facts(failures=0, trials=0)).f != 0.5:
        problems.append("0 试验时 F 不等于先验均值 0.5")
    if compute_features(_probe_facts(anomaly_counts={})).a != 0.0:
        problems.append("无异常时 A 不为 0")
    return tuple(problems)


def assert_weights_sum() -> tuple[str, ...]:
    """权重和必须为 1；NaN/越界/不归一必须被拒绝。"""
    problems: list[str] = []
    if not DEFAULT_WEIGHTS.normalized:
        problems.append("默认权重和不为 1")
    for kwargs in (
        {"f": 0.5, "n": 0.5, "g": 0.5, "i": 0.0, "a": 0.0},
        {"f": float("nan"), "n": 0.25, "g": 0.25, "i": 0.25, "a": 0.25},
        {"f": -0.1, "n": 0.4, "g": 0.3, "i": 0.2, "a": 0.2},
    ):
        try:
            RiskWeights(**kwargs)  # type: ignore[arg-type]
        except RiskRefused:
            pass
        else:
            problems.append(f"非法权重未被拒绝：{kwargs}")
    return tuple(problems)


def assert_calibration_boundary() -> tuple[str, ...]:
    """G-hold 阶段不得冻结；冻结后不得再改。"""
    problems: list[str] = []
    weights = RiskWeights()
    for phase in ("G_HOLD", "PRE_G_DEV", "POST_G_HOLD"):
        try:
            freeze_weights(
                weights,
                calibration_phase=phase,
                frozen_at="2026-11-11T00:00:00Z",
                calibration_manifest_hash="0" * 64,
            )
        except RiskRefused as exc:
            if exc.http_status != 409:
                problems.append(f"{phase} 的拒绝状态码不是 409")
        else:
            problems.append(f"{phase} 阶段冻结未被拒绝")

    registry = WeightRegistry()
    freeze = freeze_weights(
        weights,
        calibration_phase=POST_G_DEV_PRE_G_HOLD,
        frozen_at="2026-11-11T00:00:00Z",
        calibration_manifest_hash="1" * 64,
        registry=registry,
    )
    if registry.current() is not freeze.weights:
        problems.append("冻结后取到的不是冻结权重")
    try:
        registry.freeze(freeze)
    except RiskRefused as exc:
        if exc.reason != "WEIGHTS_ALREADY_FROZEN":
            problems.append(f"重复冻结原因不符：{exc.reason}")
    else:
        problems.append("重复冻结未被拒绝")
    try:
        WeightRegistry().current(require_frozen=True)
    except RiskRefused:
        pass
    else:
        problems.append("未冻结就允许正式分配")
    return tuple(problems)