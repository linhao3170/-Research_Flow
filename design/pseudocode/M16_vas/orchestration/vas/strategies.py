"""M16 · orchestration/vas/strategies.py — 四策略与同预算对照（P9 伪代码）。
阶段：P9「DC/SPA 与 VAS」｜追踪：FR-016（T2）、策划书 §8.8 / TABLE 37、§4.2 R11、§4.3 统计纪律
依赖：M16 `knapsack`（强制集合先占预算、DP/贪心与差距口径）、M16 `risk_features`（R 由调用方填入）
不变量：四策略使用**同一预算、同一任务、同一验证器、同一候选集、同一强制集合、同一成本模型**；
        强制集合（最终报告、报告指标来源、证据异常、安全关键）不可被任何策略排除；
        RANDOM 必须使用预注册种子且同种子可复现；重复运行不得当作独立样本
错误码：SCHEMA_INVALID（422，策略/输入结构错误）；RESOURCE_BUDGET_EXCEEDED（429，强制集合超预算）
写入者：无（只分配；不执行验证、不改状态、不写实验记录）
状态：伪代码；不跑对照实验、不读 G-hold、不调用验证器

## 四策略（§8.8 TABLE 37）

  | 策略 | 可选集顺序 | 目的 |
  |---|---|---|
  | `RANDOM` | 预注册种子洗牌 | 检验风险优先是否优于无信息分配 |
  | `TOPOLOGICAL` | 拓扑序升序 | 检验固定顺序是否偏向早期节点 |
  | `REPORT_FIRST` | 报告节点先（已在强制集），再逆拓扑 | 检验只看最终输出是否足够 |
  | `RISK_PRIORITY` | `Utility / max(Cost, ε)` + DP/贪心 | 比较同预算下有效检出效率 |

## 强制集合的最小定义（写死在类型里）

  `MANDATORY_BUCKETS` 四个桶：`FINAL_REPORT`、`REPORT_METRIC_SOURCE`、`EVIDENCE_ANOMALY`、
  `SAFETY_CRITICAL`。`StrategyCandidate.__post_init__` 规定：任一桶为真 ⇒ `mandatory` 必须为真。
  想“为了省预算”把报告节点改成可选，会在构造候选时失败，而不是在预算优化里被悄悄排除。

## 同预算的可比性

  `compare_strategies()` 只接受一个 `StrategyInput`，四个策略都从它取预算与候选；
  `assert_comparable()` 再逐项核对预算/强制集/候选集指纹/成本模型版本。四条都相同才允许出对照表。
  统计口径写在 `STATISTICAL_NOTE`：任务是统计单位；同一任务重复运行不是独立样本；
  二值检出用 McNemar，连续效用用任务级 bootstrap，多重比较用 Holm 或标探索性。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from .knapsack import (
    KnapsackRefused,
    KnapsackResult,
    SelectionMode,
    ValidationCandidate,
    candidate_universe_hash,
    reserve_mandatory,
    select,
)

__all__ = [
    "MANDATORY_BUCKETS",
    "STATISTICAL_NOTE",
    "Allocation",
    "ComparisonReport",
    "MandatoryBucket",
    "Strategy",
    "StrategyCandidate",
    "StrategyInput",
    "StrategyRefused",
    "allocate",
    "assert_comparable",
    "assert_mandatory_buckets",
    "assert_same_budget",
    "compare_strategies",
]

MANDATORY_BUCKETS: Final[tuple[str, ...]] = (
    "FINAL_REPORT",
    "REPORT_METRIC_SOURCE",
    "EVIDENCE_ANOMALY",
    "SAFETY_CRITICAL",
)

STATISTICAL_NOTE: Final[str] = (
    "任务是统计单位；同一任务重复运行不是独立样本。四策略在同一 task/verifier/预算/候选集/"
    "强制集合/成本模型下配对比较；RANDOM 使用预注册种子。二值检出用 McNemar，"
    "连续效用用任务级 bootstrap；多重比较用 Holm 校正或标为探索性。不得只报百分比，必须给分子/分母。"
)

_TASK_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_NODE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class StrategyRefused(RuntimeError):
    """策略输入/对照条件不成立。"""

    def __init__(
        self,
        reason: str,
        detail: str,
        *,
        error_code: str = "SCHEMA_INVALID",
        http_status: int = 422,
        field_path: str = "strategy",
    ) -> None:
        self.error_code = error_code
        self.http_status = http_status
        self.reason = reason
        self.detail = detail
        self.field_path = field_path
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {detail}")


class MandatoryBucket(StrEnum):
    """强制集合的四个最小桶。"""

    FINAL_REPORT = "FINAL_REPORT"
    REPORT_METRIC_SOURCE = "REPORT_METRIC_SOURCE"
    EVIDENCE_ANOMALY = "EVIDENCE_ANOMALY"
    SAFETY_CRITICAL = "SAFETY_CRITICAL"


class Strategy(StrEnum):
    """四种验证预算策略；顺序与 §8.8 TABLE 37 一致。"""

    RANDOM = "RANDOM"
    TOPOLOGICAL = "TOPOLOGICAL"
    REPORT_FIRST = "REPORT_FIRST"
    RISK_PRIORITY = "RISK_PRIORITY"


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    """一个候选 + 策略所需的拓扑/报告/异常/安全标记。"""

    candidate: ValidationCandidate
    topological_index: int
    is_final_report: bool = False
    is_report_source: bool = False
    has_evidence_anomaly: bool = False
    is_safety_critical: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.topological_index, int) or isinstance(self.topological_index, bool):
            raise StrategyRefused("TOPOLOGICAL_INDEX_INVALID", "topological_index 必须是整数")
        if self.topological_index < 0:
            raise StrategyRefused("TOPOLOGICAL_INDEX_NEGATIVE", "topological_index 不得为负")
        for name in ("is_final_report", "is_report_source", "has_evidence_anomaly", "is_safety_critical"):
            if not isinstance(getattr(self, name), bool):
                raise StrategyRefused("BUCKET_FLAG_NOT_BOOL", f"{name} 必须是布尔", field_path=name)
        buckets = self.buckets()
        if buckets and not self.candidate.mandatory:
            raise StrategyRefused(
                "MANDATORY_BUCKET_NOT_MANDATORY",
                f"候选 {self.candidate.node_id!r} 命中强制桶 {buckets}，但 mandatory=False；"
                "强制节点不得被预算优化排除",
                error_code="RESOURCE_BUDGET_EXCEEDED",
                http_status=429,
                field_path="mandatory",
            )

    @property
    def node_id(self) -> str:
        return self.candidate.node_id

    @property
    def cost_ticks(self) -> int:
        return self.candidate.cost_ticks

    @property
    def utility_units(self) -> int:
        return self.candidate.utility_units

    def buckets(self) -> tuple[str, ...]:
        result: list[str] = []
        if self.is_final_report:
            result.append(MandatoryBucket.FINAL_REPORT.value)
        if self.is_report_source:
            result.append(MandatoryBucket.REPORT_METRIC_SOURCE.value)
        if self.has_evidence_anomaly:
            result.append(MandatoryBucket.EVIDENCE_ANOMALY.value)
        if self.is_safety_critical:
            result.append(MandatoryBucket.SAFETY_CRITICAL.value)
        return tuple(result)

    def as_body(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "topological_index": self.topological_index,
                "buckets": list(self.buckets()),
                "candidate": dict(self.candidate.as_body()),
            }
        )


@dataclass(frozen=True, slots=True)
class StrategyInput:
    """一次同预算对照的完整输入；四个策略共用同一个对象。"""

    task_id: str
    verifier_id: str
    budget_ticks: int
    cost_model_version: str
    candidates: tuple[StrategyCandidate, ...]
    mandatory_ids: tuple[str, ...]
    seed: int

    def __post_init__(self) -> None:
        if not _TASK_ID_RE.fullmatch(self.task_id):
            raise StrategyRefused("TASK_ID_INVALID", "task_id 形态非法", field_path="task_id")
        if not self.verifier_id:
            raise StrategyRefused("VERIFIER_ID_EMPTY", "verifier_id 不得为空", field_path="verifier_id")
        if not isinstance(self.budget_ticks, int) or isinstance(self.budget_ticks, bool) or self.budget_ticks < 0:
            raise StrategyRefused("BUDGET_INVALID", "budget_ticks 必须是非负整数", field_path="budget_ticks")
        if not self.cost_model_version:
            raise StrategyRefused("COST_MODEL_EMPTY", "cost_model_version 不得为空", field_path="cost_model_version")
        if not self.candidates:
            raise StrategyRefused("CANDIDATES_EMPTY", "候选集不得为空", field_path="candidates")
        ids = [candidate.node_id for candidate in self.candidates]
        if len(set(ids)) != len(ids):
            raise StrategyRefused("DUPLICATE_CANDIDATE", "候选节点重复", field_path="candidates")
        indexes = [candidate.topological_index for candidate in self.candidates]
        if len(set(indexes)) != len(indexes):
            raise StrategyRefused("DUPLICATE_TOPOLOGICAL_INDEX", "拓扑序号不得重复", field_path="topological_index")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or not 0 <= self.seed < 2 ** 32:
            raise StrategyRefused("SEED_INVALID", "seed 必须是 [0, 2^32) 的整数", field_path="seed")
        declared = {candidate.node_id for candidate in self.candidates if candidate.candidate.mandatory}
        if declared != set(self.mandatory_ids):
            raise StrategyRefused(
                "MANDATORY_SET_MISMATCH",
                f"mandatory 标记与 mandatory_ids 不一致：{sorted(declared)} vs {sorted(set(self.mandatory_ids))}",
                field_path="mandatory_ids",
            )

    def knapsack_candidates(self) -> tuple[ValidationCandidate, ...]:
        return tuple(candidate.candidate for candidate in sorted(self.candidates, key=lambda c: c.node_id))

    def universe_hash(self) -> str:
        return candidate_universe_hash(self.knapsack_candidates())


@dataclass(frozen=True, slots=True)
class Allocation:
    """一个策略的分配结果。"""

    strategy: Strategy
    task_id: str
    verifier_id: str
    budget_ticks: int
    cost_model_version: str
    universe_hash: str
    selected_ids: tuple[str, ...]
    mandatory_ids: tuple[str, ...]
    spent_ticks: int
    utility_units: int
    seed: int | None
    mode: SelectionMode | None
    trace: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise StrategyRefused("SELECTED_DUPLICATE", "selected_ids 不得重复")
        if not set(self.mandatory_ids).issubset(set(self.selected_ids)):
            raise StrategyRefused(
                "MANDATORY_EXCLUDED",
                "分配排除了强制节点",
                error_code="RESOURCE_BUDGET_EXCEEDED",
                http_status=429,
                field_path="selected_ids",
            )
        if self.spent_ticks > self.budget_ticks:
            raise StrategyRefused(
                "BUDGET_OVERSPENT", "spent 超过 budget", error_code="RESOURCE_BUDGET_EXCEEDED", http_status=429
            )
        if self.strategy is Strategy.RANDOM and self.seed is None:
            raise StrategyRefused("RANDOM_WITHOUT_SEED", "RANDOM 必须记录预注册种子")

    @property
    def remaining_ticks(self) -> int:
        return self.budget_ticks - self.spent_ticks

    @property
    def utility_per_spent(self) -> float | None:
        return (self.utility_units / self.spent_ticks) if self.spent_ticks > 0 else None

    def as_row(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "strategy": self.strategy.value,
                "task_id": self.task_id,
                "verifier_id": self.verifier_id,
                "budget_ticks": self.budget_ticks,
                "cost_model_version": self.cost_model_version,
                "universe_hash": self.universe_hash,
                "selected": list(self.selected_ids),
                "selected_count": len(self.selected_ids),
                "mandatory": list(self.mandatory_ids),
                "mandatory_count": len(self.mandatory_ids),
                "spent_ticks": self.spent_ticks,
                "remaining_ticks": self.remaining_ticks,
                "utility_units": self.utility_units,
                "utility_per_spent": self.utility_per_spent,
                "seed": self.seed,
                "mode": self.mode.value if self.mode else None,
                "trace": list(self.trace),
            }
        )


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """四策略同预算对照表。"""

    task_id: str
    verifier_id: str
    budget_ticks: int
    cost_model_version: str
    universe_hash: str
    rows: tuple[Allocation, ...]
    statistical_note: str = STATISTICAL_NOTE

    def __post_init__(self) -> None:
        if len(self.rows) != 4:
            raise StrategyRefused("COMPARISON_INCOMPLETE", "必须恰好四条策略结果")
        if {row.strategy for row in self.rows} != set(Strategy):
            raise StrategyRefused("COMPARISON_STRATEGY_SET", "四条策略必须各出现一次")
        if any(row.budget_ticks != self.budget_ticks for row in self.rows):
            raise StrategyRefused(
                "COMPARISON_BUDGET_MISMATCH",
                "四策略预算不一致：不可比",
                error_code="RESOURCE_BUDGET_EXCEEDED",
                http_status=429,
            )
        if any(row.task_id != self.task_id or row.verifier_id != self.verifier_id for row in self.rows):
            raise StrategyRefused("COMPARISON_CONTEXT_MISMATCH", "四策略的任务/验证器不一致")

    def as_table(self) -> tuple[Mapping[str, object], ...]:
        return tuple(row.as_row() for row in self.rows)

    def as_body(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "task_id": self.task_id,
                "verifier_id": self.verifier_id,
                "budget_ticks": self.budget_ticks,
                "cost_model_version": self.cost_model_version,
                "universe_hash": self.universe_hash,
                "rows": [dict(row.as_row()) for row in self.rows],
                "statistical_note": self.statistical_note,
            }
        )


# ---------------------------------------------------------------------------
# 分配
# ---------------------------------------------------------------------------
def _reserve(plan_input: StrategyInput):
    """四策略共用的第一步：强制集合先占预算。"""
    return reserve_mandatory(
        plan_input.knapsack_candidates(),
        budget_ticks=plan_input.budget_ticks,
        mandatory_ids=plan_input.mandatory_ids,
    )


def _candidate_map(plan_input: StrategyInput) -> Mapping[str, StrategyCandidate]:
    return MappingProxyType({candidate.node_id: candidate for candidate in plan_input.candidates})


def _ordered_optional(
    strategy: Strategy, plan_input: StrategyInput, optional_ids: Sequence[str]
) -> tuple[str, ...]:
    """可选集的确定性顺序（除 RANDOM 外都与输入迭代序无关）。"""
    by_id = _candidate_map(plan_input)
    ids = sorted(optional_ids)
    if strategy is Strategy.RANDOM:
        rng = random.Random(plan_input.seed)   # LIB: 预注册种子；同种子同序列
        rng.shuffle(ids)
        return tuple(ids)
    if strategy is Strategy.TOPOLOGICAL:
        return tuple(sorted(ids, key=lambda node_id: (by_id[node_id].topological_index, node_id)))
    if strategy is Strategy.REPORT_FIRST:
        # 报告节点本身已在强制集合；可选阶段按“逆拓扑追溯”。
        return tuple(sorted(ids, key=lambda node_id: (-by_id[node_id].topological_index, node_id)))
    raise StrategyRefused("STRATEGY_UNKNOWN", f"未知策略 {strategy!r}")


def _greedy_from_order(
    plan_input: StrategyInput,
    mandatory_ids: Sequence[str],
    order: Sequence[str],
    *,
    strategy: Strategy,
) -> Allocation:
    """按给定顺序装包；强制集合已预留。零成本正效用项总是选入。"""
    by_id = _candidate_map(plan_input)
    mandatory = [by_id[node_id] for node_id in mandatory_ids]
    mandatory_cost = sum(candidate.cost_ticks for candidate in mandatory)
    mandatory_units = sum(candidate.utility_units for candidate in mandatory)
    remaining = plan_input.budget_ticks - mandatory_cost
    selected: list[str] = list(mandatory_ids)
    spent = mandatory_cost
    units = mandatory_units
    for node_id in order:
        candidate = by_id[node_id]
        if candidate.utility_units <= 0:
            continue
        if candidate.cost_ticks <= remaining:
            selected.append(node_id)
            spent += candidate.cost_ticks
            remaining -= candidate.cost_ticks
            units += candidate.utility_units
    return Allocation(
        strategy=strategy,
        task_id=plan_input.task_id,
        verifier_id=plan_input.verifier_id,
        budget_ticks=plan_input.budget_ticks,
        cost_model_version=plan_input.cost_model_version,
        universe_hash=plan_input.universe_hash(),
        selected_ids=tuple(selected),
        mandatory_ids=tuple(mandatory_ids),
        spent_ticks=spent,
        utility_units=units,
        seed=plan_input.seed if strategy is Strategy.RANDOM else None,
        mode=None,
        trace=("MANDATORY_RESERVED", "ORDERED_SELECTION"),
    )


def _risk_priority(plan_input: StrategyInput, mandatory_ids: Sequence[str]) -> Allocation:
    """风险优先：交给 knapsack（DP/贪心 + 差距口径）。"""
    result: KnapsackResult = select(
        plan_input.knapsack_candidates(),
        budget_ticks=plan_input.budget_ticks,
        mandatory_ids=mandatory_ids,
        mode=SelectionMode.AUTO,
        reference_optimum_units=None,
    )
    return Allocation(
        strategy=Strategy.RISK_PRIORITY,
        task_id=plan_input.task_id,
        verifier_id=plan_input.verifier_id,
        budget_ticks=plan_input.budget_ticks,
        cost_model_version=plan_input.cost_model_version,
        universe_hash=plan_input.universe_hash(),
        selected_ids=result.selected_ids,
        mandatory_ids=result.mandatory_ids,
        spent_ticks=result.spent_ticks,
        utility_units=result.utility_units,
        seed=None,
        mode=result.mode,
        trace=result.trace,
    )


def allocate(strategy: Strategy, plan_input: StrategyInput) -> Allocation:
    """执行一个策略；强制集合先占预算，可选集按策略顺序装包。

    输入：策略、同一份 `StrategyInput`。
    输出：`Allocation`。
    副作用：无。
    不变量：强制集合完整；不超预算；RANDOM 记录种子且同种子同结果。
    错误：`StrategyRefused` / `KnapsackRefused`。
    """
    reservation = _reserve(plan_input)
    optional_ids = [candidate.node_id for candidate in reservation.optional]
    if strategy is Strategy.RISK_PRIORITY:
        return _risk_priority(plan_input, reservation.mandatory_ids)
    order = _ordered_optional(strategy, plan_input, optional_ids)
    return _greedy_from_order(plan_input, reservation.mandatory_ids, order, strategy=strategy)


def assert_same_budget(allocations: Sequence[Allocation]) -> None:
    """四策略必须同一预算；否则直接拒绝出对照表。"""
    budgets = {allocation.budget_ticks for allocation in allocations}
    if len(budgets) != 1:
        raise StrategyRefused(
            "STRATEGY_BUDGET_MISMATCH",
            f"四策略预算不一致：{sorted(budgets)}；同预算比较是硬条件",
            error_code="RESOURCE_BUDGET_EXCEEDED",
            http_status=429,
        )


def assert_comparable(allocations: Sequence[Allocation]) -> None:
    """核对预算、任务、验证器、强制集合、成本模型；任一不同即不可比。"""
    if len(allocations) != 4:
        raise StrategyRefused("STRATEGY_COUNT_INVALID", "必须恰好四个策略")
    assert_same_budget(allocations)
    if {allocation.strategy for allocation in allocations} != set(Strategy):
        raise StrategyRefused("STRATEGY_SET_INVALID", "四策略集合不完整")
    mandated = {frozenset(allocation.mandatory_ids) for allocation in allocations}
    if len(mandated) != 1:
        raise StrategyRefused("STRATEGY_MANDATORY_MISMATCH", "四策略的强制集合不一致")
    contexts = {(allocation.task_id, allocation.verifier_id) for allocation in allocations}
    if len(contexts) != 1:
        raise StrategyRefused("STRATEGY_CONTEXT_MISMATCH", "四策略的任务/验证器不一致")
    models = {allocation.cost_model_version for allocation in allocations}
    if len(models) != 1:
        raise StrategyRefused("STRATEGY_COST_MODEL_MISMATCH", "四策略的成本模型版本不一致")
    universes = {allocation.universe_hash for allocation in allocations}
    if len(universes) != 1:
        raise StrategyRefused(
            "STRATEGY_UNIVERSE_MISMATCH",
            "四策略的候选集指纹不一致：不可比",
        )


def compare_strategies(plan_input: StrategyInput) -> ComparisonReport:
    """在**同一输入**上跑四策略并出配对对照表。

    输入：`StrategyInput`（预算、候选、强制集、种子、成本模型）。
    输出：`ComparisonReport`。
    副作用：无。
    不变量：四策略预算/强制集/上下文/成本模型一致；RANDOM 同种子可复现。
    错误：`StrategyRefused` / `KnapsackRefused`。
    """
    allocations = tuple(allocate(strategy, plan_input) for strategy in Strategy)
    assert_comparable(allocations)
    return ComparisonReport(
        task_id=plan_input.task_id,
        verifier_id=plan_input.verifier_id,
        budget_ticks=plan_input.budget_ticks,
        cost_model_version=plan_input.cost_model_version,
        universe_hash=plan_input.universe_hash(),
        rows=allocations,
    )


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def _sample_input(seed: int = 20261111) -> StrategyInput:
    candidates = (
        StrategyCandidate(
            ValidationCandidate("node_report", 0.90, 1.00, 4, True),
            topological_index=5,
            is_final_report=True,
        ),
        StrategyCandidate(
            ValidationCandidate("node_metric", 0.70, 0.90, 3, True),
            topological_index=4,
            is_report_source=True,
        ),
        StrategyCandidate(ValidationCandidate("node_a", 0.80, 0.80, 3, False), topological_index=0),
        StrategyCandidate(ValidationCandidate("node_b", 0.60, 0.70, 2, False), topological_index=1),
        StrategyCandidate(ValidationCandidate("node_c", 0.40, 0.50, 1, False), topological_index=2),
        StrategyCandidate(ValidationCandidate("node_d", 0.20, 0.30, 1, False), topological_index=3),
    )
    return StrategyInput(
        task_id="task_00000000-0000-0000-0000-000000000000",
        verifier_id="verifier-t2",
        budget_ticks=12,
        cost_model_version="cost/1.0",
        candidates=candidates,
        mandatory_ids=("node_report", "node_metric"),
        seed=seed,
    )


def assert_mandatory_buckets() -> list[str]:
    """自检：四类强制桶任一命中都必须 mandatory=True。"""
    problems: list[str] = []
    if len(MANDATORY_BUCKETS) != 4:
        problems.append("强制桶必须恰好 4 类")
    for bucket_flag in (
        "is_final_report",
        "is_report_source",
        "has_evidence_anomaly",
        "is_safety_critical",
    ):
        kwargs = {bucket_flag: True}
        try:
            StrategyCandidate(
                ValidationCandidate("node_bad", 0.9, 0.9, 1, False),
                topological_index=0,
                **kwargs,
            )
        except StrategyRefused as exc:
            if exc.reason != "MANDATORY_BUCKET_NOT_MANDATORY":
                problems.append(f"{bucket_flag} 的拒绝原因不符：{exc.reason}")
        else:
            problems.append(f"{bucket_flag}=True 但 mandatory=False 未被拒绝")
    return problems


def assert_same_budget_contract() -> list[str]:
    """自检：四策略在同一输入上预算/强制集一致；RANDOM 同种子可复现。"""
    problems: list[str] = []
    plan_input = _sample_input()
    report = compare_strategies(plan_input)
    if report.budget_ticks != plan_input.budget_ticks:
        problems.append("对照表预算与输入不一致")
    if any(row.budget_ticks != plan_input.budget_ticks for row in report.rows):
        problems.append("存在不同预算的策略行")
    mandatory = frozenset(plan_input.mandatory_ids)
    for row in report.rows:
        if not mandatory.issubset(set(row.selected_ids)):
            problems.append(f"{row.strategy.value} 排除了强制节点 {sorted(mandatory - set(row.selected_ids))}")
        if row.spent_ticks > row.budget_ticks:
            problems.append(f"{row.strategy.value} 超预算")
    random_a = allocate(Strategy.RANDOM, plan_input)
    random_b = allocate(Strategy.RANDOM, plan_input)
    if random_a.selected_ids != random_b.selected_ids:
        problems.append("RANDOM 同种子两次选择不一致")
    if random_a.seed != plan_input.seed:
        problems.append("RANDOM 未记录预注册种子")
    # 不同预算必须被 assert_same_budget 拒绝。
    other = Allocation(
        strategy=Strategy.TOPOLOGICAL,
        task_id=plan_input.task_id,
        verifier_id=plan_input.verifier_id,
        budget_ticks=plan_input.budget_ticks + 1,
        cost_model_version=plan_input.cost_model_version,
        universe_hash=plan_input.universe_hash(),
        selected_ids=plan_input.mandatory_ids,
        mandatory_ids=plan_input.mandatory_ids,
        spent_ticks=0,
        utility_units=0,
        seed=None,
        mode=None,
        trace=("MANDATORY_RESERVED", "ORDERED_SELECTION"),
    )
    try:
        assert_same_budget([*report.rows, other])
    except StrategyRefused as exc:
        if exc.reason != "STRATEGY_BUDGET_MISMATCH":
            problems.append(f"预算不一致的拒绝原因不符：{exc.reason}")
    else:
        problems.append("预算不一致未被拒绝")
    return problems


def assert_report_first_order() -> list[str]:
    """自检：REPORT_FIRST 的可选阶段必须逆拓扑，且报告节点在强制集中。"""
    problems: list[str] = []
    plan_input = _sample_input()
    report = allocate(Strategy.REPORT_FIRST, plan_input)
    if not set(plan_input.mandatory_ids).issubset(set(report.selected_ids)):
        problems.append("REPORT_FIRST 未包含报告节点")
    by_id = _candidate_map(plan_input)
    optional_selected = [
        node_id for node_id in report.selected_ids if node_id not in plan_input.mandatory_ids
    ]
    indexes = [by_id[node_id].topological_index for node_id in optional_selected]
    if indexes != sorted(indexes, reverse=True):
        problems.append(f"REPORT_FIRST 可选阶段不是逆拓扑：{indexes}")
    return problems