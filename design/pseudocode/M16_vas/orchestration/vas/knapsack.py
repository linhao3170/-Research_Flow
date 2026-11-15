"""M16 · orchestration/vas/knapsack.py — 验证预算分配：强制先占 + DP/贪心 + 差距口径（P9 伪代码）。
MODULE: M16 VAS ｜ 阶段：P9「DC/SPA 与 VAS」
追踪：FR-016（T2）、策划书 §8.7、§8.8 可比性、§4.2 R11
FR+依赖：M16 `risk_features`（R 与 CoverageBenefit 由调用方给出）、M08 Gate coverage（只读聚合）、
        M13 Governor 给出的整数预算 tick
不变量：强制集合先占预算，超预算**抛 429 且不删强制项**；`Utility=R×CoverageBenefit`；
        `Priority=Utility/max(Cost,ε)`；DP 精确、贪心给 LP 上界差距；没有参考最优就**不报**相对最优差距
错误码：SCHEMA_INVALID（形态错误，422）、RESOURCE_BUDGET_EXCEEDED（强制集超预算/预算非法，429）
写入者：无（只返回分配结果；不写预算账本、不执行验证）
状态：伪代码；不跑真实预算、不做 G-dev 校准

## 分配顺序（写死在 `SELECTION_STEPS` 里）

  1. `VALIDATE`：候选/预算/强制集一致性；
  2. `MANDATORY_RESERVED`：强制集合**先占**预算；超预算 → 429，绝不从强制集合里删节点；
  3. `OPTIONAL_OPTIMIZED`：剩余预算上做 DP（小规模）或贪心（大规模）；
  4. `GAP_REPORTED`：精确解给 `relative_gap=0`；贪心给 LP 上界与 `bound_gap`；
     没有参考最优时 `relative_gap=None`、`gap_basis=UPPER_BOUND_ONLY`。

## 为什么差距要分三种口径

  「贪心比最优差 3%」只有在真的算出最优时才成立。节点多时只有 LP 松弛上界，
  这时能说「不差于上界的 X%」，不能说「比最优差 X%」。`GapBasis` 把这两件事分开，
  避免把上界差距写成最优差距（验收判据 5）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType
from typing import Final, Mapping, Sequence

__all__ = [
    "EPS",
    "EXACT_MAX_BUDGET_TICKS",
    "EXACT_MAX_ITEMS",
    "MANDATORY_BUDGET_EXCEEDED",
    "SELECTION_STEPS",
    "UTILITY_SCALE",
    "GapBasis",
    "KnapsackRefused",
    "KnapsackResult",
    "MandatoryReservation",
    "SelectionItem",
    "SelectionMode",
    "SelectionStatus",
    "ValidationCandidate",
    "assert_cost_units",
    "assert_gap_honesty",
    "assert_mandatory_first",
    "candidate_universe_hash",
    "reserve_mandatory",
    "select",
    "utility_units",
]

STAGE: Final[str] = "P9"

#: `Priority = Utility / max(Cost, EPS)`；成本为 0 时仍可排序。
EPS: Final[float] = 1e-9

#: 整数 micro-utility 的缩放因子：`round(R × Coverage × 1e6)`，避免浮点结合律。
UTILITY_SCALE: Final[int] = 1_000_000

#: 精确 DP 的规模阈值（PROPOSED，OQ-P9-14；不得写成验收阈值）。
EXACT_MAX_ITEMS: Final[int] = 24
EXACT_MAX_BUDGET_TICKS: Final[int] = 200_000

#: 强制集合超预算的唯一错误码（429）。
MANDATORY_BUDGET_EXCEEDED: Final[str] = "MANDATORY_BUDGET_EXCEEDED"

#: 分配步骤。顺序即语义，`select()` 的 `trace` 必须按这个顺序记录。
SELECTION_STEPS: Final[tuple[str, ...]] = (
    "VALIDATE",
    "MANDATORY_RESERVED",
    "OPTIONAL_OPTIMIZED",
    "GAP_REPORTED",
)


# ---------------------------------------------------------------------------
# 1. 错误
# ---------------------------------------------------------------------------
class KnapsackRefused(RuntimeError):
    """预算分配拒绝：形态错误（422）或资源/强制集错误（429）。"""

    def __init__(
        self,
        reason: str,
        detail: str,
        *,
        error_code: str = "SCHEMA_INVALID",
        http_status: int = 422,
        field_path: str = "knapsack",
    ) -> None:
        self.error_code = error_code
        self.http_status = http_status
        self.reason = reason
        self.detail = detail
        self.field_path = field_path
        super().__init__(f"{self.error_code}/{reason} @ {field_path}：{detail}")


# ---------------------------------------------------------------------------
# 2. 枚举
# ---------------------------------------------------------------------------
class SelectionMode(StrEnum):
    """选择模式。`AUTO` 按阈值挑 DP/贪心；显式 `EXACT_DP` 超阈值时**拒绝**，不静默降级。"""

    AUTO = "AUTO"
    EXACT_DP = "EXACT_DP"
    GREEDY = "GREEDY"


class SelectionStatus(StrEnum):
    """单项在分配里的状态。"""

    MANDATORY = "MANDATORY"
    SELECTED = "SELECTED"
    EXCLUDED_BUDGET = "EXCLUDED_BUDGET"
    ZERO_UTILITY = "ZERO_UTILITY"


class GapBasis(StrEnum):
    """差距口径。`UPPER_BOUND_ONLY` 时 `relative_gap` 必须为 None。"""

    EXACT_OPTIMUM = "EXACT_OPTIMUM"
    RELATIVE_TO_REFERENCE_OPTIMUM = "RELATIVE_TO_REFERENCE_OPTIMUM"
    UPPER_BOUND_ONLY = "UPPER_BOUND_ONLY"


# ---------------------------------------------------------------------------
# 3. 形态校验与效用
# ---------------------------------------------------------------------------
def _require_float01(value: object, field_path: str) -> float:
    """特征/收益必须在 [0,1]（不是 bool，不是 NaN）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KnapsackRefused("FEATURE_NOT_NUMBER", f"{field_path} 必须是数值", field_path=field_path)
    number = float(value)
    if number != number:  # NaN
        raise KnapsackRefused("FEATURE_NAN", f"{field_path} 不得为 NaN", field_path=field_path)
    if not 0.0 <= number <= 1.0:
        raise KnapsackRefused("FEATURE_OUT_OF_RANGE", f"{field_path}={number} 不在 [0,1]", field_path=field_path)
    return number


def _require_cost(value: object, field_path: str) -> int:
    """成本必须是整数 tick（>=0）；小数成本一律拒绝，不做隐式取整。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise KnapsackRefused("COST_NOT_INTEGER", f"{field_path} 必须是整数 tick", field_path=field_path)
    if value < 0:
        raise KnapsackRefused("COST_NEGATIVE", f"{field_path}={value} 不得为负", field_path=field_path)
    return value


def utility_units(risk: float, coverage_benefit: float) -> int:
    """`Utility = R × CoverageBenefit`，转成整数 micro-utility。

    输入：风险 R、覆盖收益。
    输出：非负整数（`Decimal` + `ROUND_HALF_UP`，不用 float 乘法后 round）。
    依据：§8.7；整数化是为了让 DP 的加法满足结合律。
    """
    r = _require_float01(risk, "risk")
    c = _require_float01(coverage_benefit, "coverage_benefit")
    product = Decimal(str(r)) * Decimal(str(c)) * Decimal(UTILITY_SCALE)
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# 4. 候选
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ValidationCandidate:
    """一个可被验证的节点。风险与覆盖收益由调用方给出（VAS 不重算指标）。"""

    node_id: str
    risk: float
    coverage_benefit: float
    cost_ticks: int
    mandatory: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise KnapsackRefused("NODE_ID_MISSING", "node_id 不得为空", field_path="node_id")
        _require_float01(self.risk, f"{self.node_id}.risk")
        _require_float01(self.coverage_benefit, f"{self.node_id}.coverage_benefit")
        _require_cost(self.cost_ticks, f"{self.node_id}.cost_ticks")
        if not isinstance(self.mandatory, bool):
            raise KnapsackRefused("MANDATORY_NOT_BOOL", "mandatory 必须是布尔", field_path="mandatory")

    @property
    def utility(self) -> int:
        """`R × CoverageBenefit` 的整数化结果。"""
        return utility_units(self.risk, self.coverage_benefit)

    @property
    def priority(self) -> float:
        """`Utility / max(Cost, ε)`。"""
        return self.utility_units / max(float(self.cost_ticks), EPS)

    def as_body(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "risk": self.risk,
                "coverage_benefit": self.coverage_benefit,
                "cost_ticks": self.cost_ticks,
                "mandatory": self.mandatory,
                "utility_units": self.utility,
            }
        )


def candidate_universe_hash(candidates: Sequence[ValidationCandidate]) -> str:
    """候选集指纹：四策略可比性的依据（排序后 JCS + SHA-256，64 位小写十六进制）。"""
    import hashlib
    import json

    body = [dict(candidate.as_body()) for candidate in sorted(candidates, key=lambda c: c.node_id)]
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()  # LIB: 真实实现走 M01 hash_payload


# ---------------------------------------------------------------------------
# 5. 强制集合先占
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MandatoryReservation:
    """强制集合占预算的结果。`optional` 是剩下的可选候选，保持稳定顺序。"""

    budget_ticks: int
    mandatory_ids: tuple[str, ...]
    mandatory_cost: int
    mandatory_units: int
    optional: tuple[ValidationCandidate, ...]

    def __post_init__(self) -> None:
        if self.mandatory_cost > self.budget_ticks:
            raise KnapsackRefused(
                MANDATORY_BUDGET_EXCEEDED,
                f"强制集合成本 {self.mandatory_cost} 超过预算 {self.budget_ticks}",
                error_code="RESOURCE_BUDGET_EXCEEDED",
                http_status=429,
                field_path="mandatory_ids",
            )
        if any(candidate.mandatory for candidate in self.optional):
            raise KnapsackRefused("OPTIONAL_CONTAINS_MANDATORY", "可选集里混入了强制候选")

    @property
    def remaining_ticks(self) -> int:
        return self.budget_ticks - self.mandatory_cost

    @property
    def optional_count(self) -> int:
        return len(self.optional)


def reserve_mandatory(
    candidates: Sequence[ValidationCandidate],
    *,
    budget_ticks: int,
    mandatory_ids: Sequence[str],
) -> MandatoryReservation:
    """第 2 步：强制集合先占预算；超预算抛 429，**不**返回部分强制集合。

    输入：候选集、预算、强制 ID 集。
    输出：`MandatoryReservation`（强制成本/效用 + 可选候选）。
    副作用：无。
    错误：`KnapsackRefused`（预算非法、强制 ID 不存在、强制集超预算）。

    步骤：
      1. 预算与候选形态校验；
      2. 强制 ID 必须都在候选集里，且不能重复；
      3. 汇总强制成本；超过预算直接 429（不删节点、不降级）；
      4. 剩余候选按 node_id 排序，作为可选集。
    """
    # 1. 预算
    if isinstance(budget_ticks, bool) or not isinstance(budget_ticks, int) or budget_ticks < 0:
        raise KnapsackRefused("BUDGET_INVALID", f"budget_ticks={budget_ticks!r} 必须是非负整数", field_path="budget_ticks")
    if not candidates:
        raise KnapsackRefused("CANDIDATES_EMPTY", "候选集不得为空", field_path="candidates")

    # 2. 强制 ID
    ids = [candidate.node_id for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise KnapsackRefused("DUPLICATE_CANDIDATE", "候选 node_id 重复", field_path="candidates")
    by_id = {candidate.node_id: candidate for candidate in candidates}
    declared = tuple(dict.fromkeys(mandatory_ids))
    if len(declared) != len(mandatory_ids):
        raise KnapsackRefused("DUPLICATE_MANDATORY", "mandatory_ids 重复", field_path="mandatory_ids")
    unknown = [node_id for node_id in declared if node_id not in by_id]
    if unknown:
        raise KnapsackRefused("MANDATORY_UNKNOWN", f"强制 ID 不在候选集：{unknown}", field_path="mandatory_ids")

    # 3. 强制成本
    mandatory_cost = sum(by_id[node_id].cost_ticks for node_id in declared)
    mandatory_units = sum(by_id[node_id].utility for node_id in declared)
    if mandatory_cost > budget_ticks:
        raise KnapsackRefused(
            MANDATORY_BUDGET_EXCEEDED,
            f"强制集合成本 {mandatory_cost} > 预算 {budget_ticks}（缺口 {mandatory_cost - budget_ticks}）：拒绝分配，不删强制项",
            error_code="RESOURCE_BUDGET_EXCEEDED",
            http_status=429,
            field_path="budget_ticks",
        )

    # 4. 可选集
    optional = tuple(
        sorted(
            (candidate for candidate in candidates if candidate.node_id not in set(declared)),
            key=lambda candidate: candidate.node_id,
        )
    )
    return MandatoryReservation(
        budget_ticks=budget_ticks,
        mandatory_ids=declared,
        mandatory_cost=mandatory_cost,
        mandatory_units=mandatory_units,
        optional=optional,
    )


# ---------------------------------------------------------------------------
# 6. 选择结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SelectionItem:
    """逐项状态，便于复核「为什么没选它」。"""

    node_id: str
    status: SelectionStatus
    cost_ticks: int
    utility_units: int
    reason: str = ""

    def as_body(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "status": self.status.value,
                "cost_ticks": self.cost_ticks,
                "utility_units": self.utility_units,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class KnapsackResult:
    """分配结果与不变量。差距口径是类型化的，不能只报一个数。"""

    mode: SelectionMode
    gap_basis: GapBasis
    budget_ticks: int
    mandatory_ids: tuple[str, ...]
    selected_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    spent_ticks: int
    utility_units: int
    upper_bound_units: int
    bound_gap: float = 0.0
    relative_gap: float | None = None
    reference_optimum_units: int | None = None
    items: tuple[SelectionItem, ...] = ()
    trace: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        mandatory = set(self.mandatory_ids)
        if not mandatory.issubset(set(self.selected_ids)):
            raise KnapsackRefused(
                "MANDATORY_EXCLUDED",
                "结果排除了强制节点",
                error_code="RESOURCE_BUDGET_EXCEEDED",
                http_status=429,
                field_path="selected_ids",
            )
        if self.spent_ticks > self.budget_ticks:
            raise KnapsackRefused(
                "BUDGET_OVERSPENT",
                f"spent={self.spent_ticks} > budget={self.budget_ticks}",
                error_code="RESOURCE_BUDGET_EXCEEDED",
                http_status=429,
            )
        if self.gap_basis is GapBasis.UPPER_BOUND_ONLY and self.relative_gap is not None:
            raise KnapsackRefused("FALSE_OPTIMALITY_CLAIM", "只有上界时不得给 relative_gap")
        if self.gap_basis is not GapBasis.UPPER_BOUND_ONLY and self.relative_gap is None:
            raise KnapsackRefused("MISSING_RELATIVE_GAP", "声称精确/参考最优却没有 relative_gap")
        if self.utility_units > self.upper_bound_units:
            raise KnapsackRefused("ACHIEVED_ABOVE_BOUND", "达成值高于上界：上界算错")

    @property
    def remaining_ticks(self) -> int:
        return self.budget_ticks - self.spent_ticks

    def as_body(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "mode": self.mode.value,
                "gap_basis": self.gap_basis.value,
                "budget_ticks": self.budget_ticks,
                "mandatory": list(self.mandatory_ids),
                "selected": list(self.selected_ids),
                "excluded": list(self.excluded_ids),
                "spent_ticks": self.spent_ticks,
                "remaining_ticks": self.remaining_ticks,
                "utility_units": self.utility_units,
                "upper_bound_units": self.upper_bound_units,
                "bound_gap": self.bound_gap,
                "relative_gap": self.relative_gap,
                "reference_optimum_units": self.reference_optimum_units,
                "trace": list(self.trace),
            }
        )


# ---------------------------------------------------------------------------
# 7. 求解器
# ---------------------------------------------------------------------------
def _mask_key(mask: int, count: int) -> tuple[int, int]:
    """DP 平局决胜：先比选入项数（少者优先），再比位掩码（字典序小者优先）。"""
    return (bin(mask).count("1"), mask)


def _solve_exact(optional: Sequence[ValidationCandidate], budget_ticks: int) -> tuple[int, int]:
    """0/1 整数 DP 精确解。

    输入：可选候选（≤ `EXACT_MAX_ITEMS`）、剩余预算 tick。
    输出：(达成效用, 选中位掩码)。
    依据：§8.7「节点少时用动态规划求精确解」。
    """
    if budget_ticks < 0:
        raise KnapsackRefused("BUDGET_NEGATIVE", "剩余预算不得为负")
    n = len(optional)
    if n > EXACT_MAX_ITEMS:
        raise KnapsackRefused("EXACT_TOO_LARGE", f"{n} 项超过精确阈值 {EXACT_MAX_ITEMS}")
    if budget_ticks > EXACT_MAX_BUDGET_TICKS:
        raise KnapsackRefused("EXACT_BUDGET_TOO_LARGE", f"预算 {budget_ticks} 超过精确阈值 {EXACT_MAX_BUDGET_TICKS}")

    # dp[w] = (best_units, mask)；w 为已花 tick。
    dp: list[tuple[int, int]] = [(0, 0)] * (budget_ticks + 1)
    for index, candidate in enumerate(optional):
        cost = candidate.cost_ticks
        units = candidate.utility
        bit = 1 << index
        if cost == 0:
            # 零成本正效用：永远计入（不占预算）。
            if units > 0:
                dp = [(best + units, mask | bit) for best, mask in dp]
            continue
        for spent in range(budget_ticks, cost - 1, -1):
            previous_units, previous_mask = dp[spent - cost]
            candidate_units = previous_units + units
            best_units, best_mask = dp[spent]
            if candidate_units > best_units or (
                candidate_units == best_units and _mask_key(previous_mask | bit, n) < _mask_key(best_mask, n)
            ):
                dp[spent] = (candidate_units, previous_mask | bit)

    best_units, best_mask = 0, 0
    for spent in range(budget_ticks + 1):
        units, mask = dp[spent]
        if units > best_units or (units == best_units and _mask_key(mask, n) < _mask_key(best_mask, n)):
            best_units, best_mask = units, mask
    return best_units, best_mask


def _greedy_order(optional: Sequence[ValidationCandidate]) -> tuple[ValidationCandidate, ...]:
    """贪心顺序：`Priority` 降序，同优先级按 node_id 升序（确定性）。"""
    return tuple(sorted(optional, key=lambda candidate: (-candidate.priority, candidate.node_id)))


def _solve_greedy(optional: Sequence[ValidationCandidate], budget_ticks: int) -> tuple[int, int, tuple[str, ...]]:
    """贪心装包。返回 (效用, 已花 tick, 选中 node_id 序列)。"""
    spent = 0
    units = 0
    chosen: list[str] = []
    for candidate in _greedy_order(optional):
        if candidate.utility <= 0:
            continue
        if spent + candidate.cost_ticks <= budget_ticks:
            spent += candidate.cost_ticks
            units += candidate.utility
            chosen.append(candidate.node_id)
    return units, spent, tuple(chosen)


def _lp_upper_bound(optional: Sequence[ValidationCandidate], budget_ticks: int) -> int:
    """分数背包（LP 松弛）上界：按 Priority 排序后允许切开一项。

    用 `Fraction` 精确计算，最后向下取整——上界只能偏高，取整不能把它变成可达值。
    """
    remaining = Fraction(budget_ticks, 1)
    total = Fraction(0, 1)
    for candidate in _greedy_order(optional):
        if remaining <= 0:
            break
        cost = Fraction(candidate.cost_ticks, 1)
        gain = Fraction(candidate.utility, 1)
        if cost == 0:
            total += gain
            continue
        take = min(Fraction(1, 1), remaining / cost)
        total += gain * take
        remaining -= cost * take
    return int(total)  # 向下取整：上界不小于真实最优


# ---------------------------------------------------------------------------
# 8. 主入口
# ---------------------------------------------------------------------------
def select(
    candidates: Sequence[ValidationCandidate],
    *,
    budget_ticks: int,
    mandatory_ids: Sequence[str],
    mode: SelectionMode = SelectionMode.AUTO,
    reference_optimum_units: int | None = None,
) -> KnapsackResult:
    """在预算内选择验证项：强制先占 → 可选优化 → 差距报告。

    输入：候选、预算、强制 ID、模式、可选参考最优。
    输出：`KnapsackResult`。
    副作用：无。
    错误：`KnapsackRefused`（强制集超预算 429、显式 DP 超阈值、参考最优低于达成值）。

    步骤：
      1. `VALIDATE`：形态与强制集一致性；
      2. `MANDATORY_RESERVED`：调用 `reserve_mandatory`（唯一入口）；
      3. `OPTIONAL_OPTIMIZED`：AUTO 按阈值选 DP/贪心；显式 EXACT_DP 超阈值拒绝；
      4. `GAP_REPORTED`：按口径填 `gap_basis` / `upper_bound_units` / `relative_gap`。
    """
    # 1. VALIDATE
    trace: list[str] = ["VALIDATE"]
    if not isinstance(mode, SelectionMode):
        raise KnapsackRefused("MODE_INVALID", f"mode={mode!r}", field_path="mode")
    if reference_optimum_units is not None:
        if isinstance(reference_optimum_units, bool) or not isinstance(reference_optimum_units, int):
            raise KnapsackRefused("REFERENCE_NOT_INTEGER", "参考最优必须是整数", field_path="reference_optimum_units")
        if reference_optimum_units < 0:
            raise KnapsackRefused("REFERENCE_NEGATIVE", "参考最优不得为负", field_path="reference_optimum_units")

    # 2. MANDATORY_RESERVED
    reservation = reserve_mandatory(
        candidates,
        budget_ticks=budget_ticks,
        mandatory_ids=mandatory_ids,
    )
    trace.append("MANDATORY_RESERVED")

    optional = reservation.optional
    remaining = reservation.remaining_ticks
    exact_possible = len(optional) <= EXACT_MAX_ITEMS and remaining <= EXACT_MAX_BUDGET_TICKS

    # 3. OPTIONAL_OPTIMIZED
    if mode is SelectionMode.EXACT_DP and not exact_possible:
        raise KnapsackRefused(
            "EXACT_DP_NOT_APPLICABLE",
            f"可选 {len(optional)} 项 / 剩余 {remaining} tick 超过精确阈值；"
            "显式要求精确解时拒绝，不静默降级为贪心",
            field_path="mode",
        )
    use_exact = mode is SelectionMode.EXACT_DP or (mode is SelectionMode.AUTO and exact_possible)

    if use_exact:
        optional_units, mask = _solve_exact(optional, remaining)
        chosen_ids = tuple(optional[index].node_id for index in range(len(optional)) if mask & (1 << index))
        spent = sum(optional[index].cost_ticks for index in range(len(optional)) if mask & (1 << index))
        trace.append("OPTIONAL_OPTIMIZED_EXACT")
        basis = GapBasis.EXACT_OPTIMUM
        upper_bound = reservation.mandatory_units + optional_units
        bound_gap = 0.0
        relative_gap: float | None = 0.0
    else:
        optional_units, spent, chosen_ids = _solve_greedy(optional, remaining)
        trace.append("OPTIONAL_OPTIMIZED_GREEDY")
        upper_bound = reservation.mandatory_units + _lp_upper_bound(optional, remaining)
        bound_gap = (upper_bound - (reservation.mandatory_units + optional_units)) / max(upper_bound, 1)
        basis = GapBasis.UPPER_BOUND_ONLY
        relative_gap = None

    achieved = reservation.mandatory_units + optional_units
    total_spent = reservation.mandatory_cost + spent
    trace.append("GAP_REPORTED")

    # 4. GAP_REPORTED：参考最优只用于「相对最优」口径
    if reference_optimum_units is not None:
        if reference_optimum_units < achieved:
            raise KnapsackRefused(
                "REFERENCE_BELOW_ACHIEVED",
                f"参考最优 {reference_optimum_units} < 已达成 {achieved}：参考值不可信",
                field_path="reference_optimum_units",
            )
        basis = GapBasis.RELATIVE_TO_REFERENCE_OPTIMUM
        relative_gap = (reference_optimum_units - achieved) / max(reference_optimum_units, 1)

    selected_ids = tuple(reservation.mandatory_ids) + chosen_ids
    selected_set = set(selected_ids)
    excluded = tuple(candidate.node_id for candidate in candidates if candidate.node_id not in selected_set)

    items: list[SelectionItem] = []
    for node_id in reservation.mandatory_ids:
        candidate = next(c for c in candidates if c.node_id == node_id)
        items.append(
            SelectionItem(
                node_id=node_id,
                status=SelectionStatus.MANDATORY,
                cost_ticks=candidate.cost_ticks,
                utility_units=candidate.utility,
                reason="强制集合先占预算",
            )
        )
    for candidate in candidates:
        if candidate.node_id in selected_set or candidate.node_id in reservation.mandatory_ids:
            continue
        if candidate.utility <= 0:
            status, reason = SelectionStatus.ZERO_UTILITY, "效用为 0，不占预算"
        else:
            status, reason = SelectionStatus.EXCLUDED_BUDGET, "剩余预算不足"
        items.append(
            SelectionItem(
                node_id=candidate.node_id,
                status=status,
                cost_ticks=candidate.cost_ticks,
                utility_units=candidate.utility,
                reason=reason,
            )
        )

    return KnapsackResult(
        mode=mode,
        gap_basis=basis,
        budget_ticks=budget_ticks,
        mandatory_ids=tuple(reservation.mandatory_ids),
        selected_ids=selected_ids,
        excluded_ids=excluded,
        spent_ticks=total_spent,
        utility_units=achieved,
        upper_bound_units=upper_bound,
        bound_gap=bound_gap,
        relative_gap=relative_gap,
        reference_optimum_units=reference_optimum_units,
        items=tuple(items),
        trace=tuple(trace),
    )


# ---------------------------------------------------------------------------
# 9. 静态守卫（实现阶段用；P9 不执行）
# ---------------------------------------------------------------------------
def _probe_candidates() -> tuple[ValidationCandidate, ...]:
    """固定探针：两个强制项 + 四个可选，成本 2/2/3/2/1/1，预算 6。"""
    return (
        ValidationCandidate("node_report", 0.90, 1.00, 2, True),
        ValidationCandidate("node_metric", 0.70, 0.90, 2, True),
        ValidationCandidate("node_a", 0.80, 0.80, 3, False),
        ValidationCandidate("node_b", 0.60, 0.70, 2, False),
        ValidationCandidate("node_c", 0.40, 0.50, 1, False),
        ValidationCandidate("node_d", 0.20, 0.30, 1, False),
    )


def assert_mandatory_first() -> tuple[str, ...]:
    """强制集合先占预算；超预算必须 429 且不返回部分强制集合。"""
    problems: list[str] = []
    if SELECTION_STEPS.index("MANDATORY_RESERVED") > SELECTION_STEPS.index("OPTIONAL_OPTIMIZED"):
        problems.append("SELECTION_STEPS 顺序错：强制占预算必须在可选优化之前")

    result = select(_probe_candidates(), budget_ticks=6, mandatory_ids=("node_report", "node_metric"))
    if not set(result.mandatory_ids).issubset(set(result.selected_ids)):
        problems.append("强制项未全部入选")
    if result.trace[:2] != ("VALIDATE", "MANDATORY_RESERVED"):
        problems.append(f"trace 未先记强制预留：{result.trace}")
    if result.spent_ticks > result.budget_ticks:
        problems.append("超预算")

    try:
        select(_probe_candidates(), budget_ticks=1, mandatory_ids=("node_report", "node_metric"))
    except KnapsackRefused as exc:
        if exc.error_code != "RESOURCE_BUDGET_EXCEEDED" or exc.http_status != 429:
            problems.append(f"超预算错误码不符：{exc.error_code}/{exc.http_status}")
        if exc.reason != MANDATORY_BUDGET_EXCEEDED:
            problems.append(f"超预算 reason 不符：{exc.reason}")
    else:
        problems.append("强制集合超预算未被拒绝")
    return tuple(problems)


def assert_gap_honesty() -> tuple[str, ...]:
    """上界差距不得冒充最优差距；参考最优低于达成值必须拒绝。"""
    problems: list[str] = []
    greedy = select(
        _probe_candidates(),
        budget_ticks=6,
        mandatory_ids=("node_report", "node_metric"),
        mode=SelectionMode.GREEDY,
    )
    if greedy.gap_basis is not GapBasis.UPPER_BOUND_ONLY:
        problems.append(f"贪心口径变成 {greedy.gap_basis.value}")
    if greedy.relative_gap is not None:
        problems.append("只有上界却给了 relative_gap")
    if greedy.upper_bound_units < greedy.utility_units:
        problems.append("上界低于达成值")

    exact = select(
        _probe_candidates(),
        budget_ticks=6,
        mandatory_ids=("node_report", "node_metric"),
        mode=SelectionMode.EXACT_DP,
    )
    if exact.gap_basis is not GapBasis.EXACT_OPTIMUM or exact.relative_gap != 0.0:
        problems.append("精确解口径不正确")
    if exact.utility_units < greedy.utility_units:
        problems.append("精确解劣于贪心：求解器有错")

    try:
        select(
            _probe_candidates(),
            budget_ticks=6,
            mandatory_ids=("node_report", "node_metric"),
            mode=SelectionMode.GREEDY,
            reference_optimum_units=greedy.utility_units - 1,
        )
    except KnapsackRefused as exc:
        if exc.reason != "REFERENCE_BELOW_ACHIEVED":
            problems.append(f"参考最优过低的原因不符：{exc.reason}")
    else:
        problems.append("参考最优低于达成值未被拒绝")
    return tuple(problems)


def assert_cost_units() -> tuple[str, ...]:
    """成本必须是整数 tick；`utility_units` 必须用 Decimal 取整。"""
    problems: list[str] = []
    try:
        ValidationCandidate("node_x", 0.5, 0.5, 1.5)  # type: ignore[arg-type]
    except KnapsackRefused:
        pass
    else:
        problems.append("浮点成本未被拒绝")
    if utility_units(0.5, 0.5) != 250_000:
        problems.append(f"0.5×0.5 的整数效用={utility_units(0.5, 0.5)}，期望 250000")
    if utility_units(1.0, 1.0) != UTILITY_SCALE:
        problems.append("满效用不等于 UTILITY_SCALE")
    return tuple(problems)