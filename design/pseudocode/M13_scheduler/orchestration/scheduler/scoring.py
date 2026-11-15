"""M13 · orchestration/scheduler/scoring.py — SchedScore 与五项归一化（P7 伪代码）。
阶段：P7「调度与定向恢复」｜追踪：FR-011（Ready Scheduler 与 Governor；正式属 T1/G4）、策划书 §8.5 / P0216–P0218
依赖：M03 config（权重必须来自配置，缺失拒绝启动）、M04 NodeDraft（side_effect_class/retry_policy）、M03 limits（ResourceCaps）
不变量：五项归一化各有 0 与 1 边界；权重只来自配置且标「未校准」；分数只用于排序，**不得**进入 plan 正文或 plan_hash
错误码：CONFIG_MISSING_KEY / CONFIG_UNKNOWN_KEY / CONFIG_TYPE_INVALID / CONFIG_VALUE_OUT_OF_RANGE（配置类，503）；
        FEATURE_FLAG_NOT_PERMITTED（T0 声称已校准）；SCHEMA_INVALID（`detail.reason=SCORING_INPUT_INVALID`，度量为负/超域）
写入者：无。本文件是纯函数集合：不读配置、不读时钟、不写状态、不写证据、不写审计
状态：伪代码；不执行、不排序、不派发

## 本文件回答三个问题

  1. SchedScore 的五个特征各自怎么归一化？边界在哪里？（验收判据 1）
  2. 权重从哪来？为什么不能写死在代码里并声称最优？（§8.5「权重为配置初值」）
  3. 两条分数相等时按什么规则决出先后？（必须确定性，否则调度不可复核）

## 权重纪律（写死）

  | 事实 | 本文件的处理 |
  |---|---|
  | 策划书 §8.5 给的是「建议初始评分」 | 常量名带 `PROPOSED`，值带 `CALIBRATION=UNCALIBRATED` |
  | 「须通过历史回放和敏感性分析校准」 | T0/T1 的回放校准尚未发生 → 任何 `CALIBRATED` 声明一律拒绝（`FEATURE_FLAG_NOT_PERMITTED`） |
  | 校准前不得声称最优 | 每次输出分数必须带 `CALIBRATION_DISCLAIMER`；`assert_not_optimality_claim()` 检查它出现在日志字段里 |
  | M03 `scheduler.yaml` 目前**没有**权重键 | `weights_from_config()` 只接受显式键；缺键拒绝启动，**不取默认值**（M03 硬规则）；键名以 OQ-P7-02 登记 |

## 为什么分数不进 plan_hash

  分数含 `Age`，依赖运行时时钟；把它写进恢复计划会让同一输入在不同时刻得到不同 `plan_hash`，
  直接违反 ADR-004 §3「计划正文不得含时间戳」。见 `SCORE_IS_NOT_PLAN_INPUT`。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

__all__ = [
    "CALIBRATION_DISCLAIMER",
    "DEFAULT_RISK_POLICY_PROPOSED",
    "EPS",
    "FEATURE_ORDER",
    "PROPOSED_RISK_POLICY",
    "PROPOSED_WEIGHTS",
    "RISK_IMPERATIVE_BY_CLASS",
    "SCORE_IS_NOT_PLAN_INPUT",
    "SchedFeatures",
    "SchedScore",
    "SchedScoreWeights",
    "ScoringConfigInvalid",
    "ScoringInputInvalid",
    "CalibrationState",
    "NodeScoreFacts",
    "ResourceCaps",
    "ResourceDemand",
    "RiskPolicy",
    "assert_boundaries",
    "assert_not_optimality_claim",
    "compare_scores",
    "compute_score",
    "normalize_age",
    "normalize_critical_path",
    "normalize_resource_fit",
    "normalize_risk",
    "normalize_user_priority",
    "risk_policy_from_config",
    "weights_from_config",
]

# ---------------------------------------------------------------------------
# 0. 常量与口径声明
# ---------------------------------------------------------------------------
# 策划书 §8.5 的原始建议值；**不是**默认值，也不是校准结果。
PROPOSED_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "critical_path": 0.30,
        "risk": 0.25,
        "age": 0.20,
        "resource_fit": 0.15,
        "user_priority": 0.10,
    }
)

# 五项特征的固定顺序：日志、并列比较、配置键都按这个顺序，避免字典遍历序进入任何输出。
FEATURE_ORDER: Final[tuple[str, ...]] = (
    "critical_path",
    "risk",
    "age",
    "resource_fit",
    "user_priority",
)

EPS: Final[float] = 1e-9  # 浮点并列判定的唯一容差；不得按需放大

CALIBRATION_DISCLAIMER: Final[str] = (
    "权重为策划书 §8.5 的初始值，未经历史回放与敏感性分析校准；"
    "本分数只用于排队顺序，不构成最优性声明，也不作为任何验收阈值。"
)

SCORE_IS_NOT_PLAN_INPUT: Final[str] = (
    "SchedScore 含 Age（运行时时钟），**不得**写入恢复计划正文、dispatch 审计的 plan_* 字段或 plan_hash 前像；"
    "调度可复核性靠「特征原值 + 权重版本 + 队列快照」的调度日志，不靠把分数塞进计划。"
)

# 目标更高表示需要更多资源；用 M03 limits 的维度名，便于 `detail.limit_kind` 对齐。
RESOURCE_DIMENSIONS: Final[tuple[str, ...]] = ("memory_mb", "disk_mb", "wall_sec")

# 用户优先级的合法取值（有序档位）；映射到 [0,1] 时 0 → 0.0、3 → 1.0。
USER_PRIORITY_LEVELS: Final[tuple[int, ...]] = (0, 1, 2, 3)


class CalibrationState(StrEnum):
    """权重的校准状态。T0/T1 只有 `UNCALIBRATED` 可达。"""

    UNCALIBRATED = "UNCALIBRATED"  # 初始值；未经回放/敏感性分析
    CALIBRATED = "CALIBRATED"      # 有回放校准证据；T0 拒绝（FEATURE_FLAG_NOT_PERMITTED）


# ---------------------------------------------------------------------------
# 1. 配置异常与配置对象
# ---------------------------------------------------------------------------
class ScoringConfigInvalid(RuntimeError):
    """权重/风险策略配置不可用；`code` 必须是 M01 注册表里的配置类码。

    设计意图：配置错误必须在**启动期**暴露（M03 硬规则「缺键拒绝启动」），
    不得在第一次调度时才发现，更不得静默退回 `PROPOSED_WEIGHTS`。
    """

    def __init__(self, code: str, field_path: str, message: str) -> None:
        self.code = code
        self.field_path = field_path
        super().__init__(f"[{code}] {field_path}: {message}")


def _require_float(raw: Mapping[str, object], key: str, field_path: str) -> float:
    """取一个有限浮点；bool 与字符串一律拒绝（不做类型强转）。"""
    if key not in raw:
        raise ScoringConfigInvalid(
            "CONFIG_MISSING_KEY", f"{field_path}.{key}", "配置没有隐式默认值，缺失必须拒绝启动"
        )
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScoringConfigInvalid(
            "CONFIG_TYPE_INVALID", f"{field_path}.{key}", f"必须是数字，实际 {type(value).__name__}"
        )
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):  # NaN / ±Inf
        raise ScoringConfigInvalid(
            "CONFIG_TYPE_INVALID", f"{field_path}.{key}", "不允许 NaN/Infinity"
        )
    return number


def _require_enum_text(raw: Mapping[str, object], key: str, field_path: str) -> str:
    if key not in raw:
        raise ScoringConfigInvalid(
            "CONFIG_MISSING_KEY", f"{field_path}.{key}", "配置没有隐式默认值，缺失必须拒绝启动"
        )
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise ScoringConfigInvalid(
            "CONFIG_TYPE_INVALID", f"{field_path}.{key}", "必须是非空字符串"
        )
    return value


@dataclass(frozen=True, slots=True)
class SchedScoreWeights:
    """SchedScore 的五个权重（以及校准声明）。

    校验（构造期，全部 fail-fast）：
      1. 五个权重齐全，非负，且各自 ≤ 1；
      2. 总和必须为 1（±EPS）；不归一化的权重会让「总分」不可比；
      3. `calibration` 只允许 `UNCALIBRATED`；声称已校准必须另有校准证据（T0/T1 无）。
    """

    critical_path: float
    risk: float
    age: float
    resource_fit: float
    user_priority: float
    calibration: CalibrationState = CalibrationState.UNCALIBRATED
    source: str = "策划书 §8.5 P0217（初始建议评分，未校准）"

    def __post_init__(self) -> None:
        for name in FEATURE_ORDER:
            value = float(getattr(self, name))
            if not (0.0 <= value <= 1.0):
                raise ScoringConfigInvalid(
                    "CONFIG_VALUE_OUT_OF_RANGE",
                    f"scheduler.yaml: sched_score_weights.{name}",
                    f"权重必须在 [0,1]，实际 {value}",
                )
        total = sum(float(getattr(self, n)) for n in FEATURE_ORDER)
        if abs(total - 1.0) > EPS:
            raise ScoringConfigInvalid(
                "CONFIG_VALUE_OUT_OF_RANGE",
                "scheduler.yaml: sched_score_weights",
                f"权重和必须为 1（±{EPS}），实际 {total!r}",
            )
        if self.calibration is CalibrationState.CALIBRATED:
            # 校准证据（历史回放 + 敏感性分析）属 T1+；T0 不得声称已校准。
            raise ScoringConfigInvalid(
                "FEATURE_FLAG_NOT_PERMITTED",
                "scheduler.yaml: sched_score_weights.calibration",
                "T0 不允许声明 CALIBRATED：缺少回放/敏感性分析证据（§8.5；OQ-P7-02）",
            )

    def as_mapping(self) -> Mapping[str, float]:
        """固定顺序的权重视图（供调度日志；顺序来自 `FEATURE_ORDER`，不是 dict 序）。"""
        return MappingProxyType({name: float(getattr(self, name)) for name in FEATURE_ORDER})

    @property
    def weights_id(self) -> str:
        """权重身份的**唯一**来源：值 + 校准状态。

        不含时间戳；同一组权重在任何时刻得到同一个 `weights_id`。
        落地阶段用 M01 `canonical_bytes` + sha256 计算，**不得**用 `repr()` 拼字符串。
        """
        # LIB: researchflow.contracts.encoding.canonical_bytes + hashlib.sha256
        raise NotImplementedError("P7 伪代码：weights_id 由 M01 canonical_bytes 落地")


def weights_from_config(raw: Mapping[str, object]) -> SchedScoreWeights:
    """从 `scheduler.yaml: sched_score_weights` 装载权重。

    输入：该键下的映射（不是整份 YAML）。必须恰好包含
    `critical_path/risk/age/resource_fit/user_priority/calibration` 六个键。
    输出：`SchedScoreWeights`。
    副作用：无。
    错误：缺键 → `CONFIG_MISSING_KEY`；多余键 → `CONFIG_UNKNOWN_KEY`（拼写错误不得静默忽略）；
         类型错 → `CONFIG_TYPE_INVALID`；越界/和不为一 → `CONFIG_VALUE_OUT_OF_RANGE`；
         `calibration="CALIBRATED"` → `FEATURE_FLAG_NOT_PERMITTED`。
    """
    # 步骤 1：键集合必须精确相等（未知键拒绝）
    allowed = frozenset((*FEATURE_ORDER, "calibration"))
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ScoringConfigInvalid(
            "CONFIG_UNKNOWN_KEY",
            "scheduler.yaml: sched_score_weights",
            f"未声明的键 {unknown}；T1/T2 字段不得提前混入 T0 配置",
        )
    # 步骤 2：逐项取数（缺键即拒绝，不取默认）
    values = {
        name: _require_float(raw, name, "scheduler.yaml: sched_score_weights")
        for name in FEATURE_ORDER
    }
    # 步骤 3：校准状态必须是枚举内字面值
    calibration_text = _require_enum_text(raw, "calibration", "scheduler.yaml: sched_score_weights")
    if calibration_text not in {state.value for state in CalibrationState}:
        raise ScoringConfigInvalid(
            "CONFIG_VALUE_OUT_OF_RANGE",
            "scheduler.yaml: sched_score_weights.calibration",
            f"只允许 {[s.value for s in CalibrationState]}，实际 {calibration_text!r}",
        )
    # 步骤 4：交给构造期做范围/归一化/校准三重校验
    return SchedScoreWeights(
        critical_path=values["critical_path"],
        risk=values["risk"],
        age=values["age"],
        resource_fit=values["resource_fit"],
        user_priority=values["user_priority"],
        calibration=CalibrationState(calibration_text),
    )


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    """Risk 特征的两个子权重（也是配置项，同样未校准）。"""

    failure_pressure: float
    imperative: float
    calibration: CalibrationState = CalibrationState.UNCALIBRATED

    def __post_init__(self) -> None:
        for name in ("failure_pressure", "imperative"):
            value = float(getattr(self, name))
            if not (0.0 <= value <= 1.0):
                raise ScoringConfigInvalid(
                    "CONFIG_VALUE_OUT_OF_RANGE",
                    f"scheduler.yaml: sched_score_risk.{name}",
                    f"子权重必须在 [0,1]，实际 {value}",
                )
        if abs((self.failure_pressure + self.imperative) - 1.0) > EPS:
            raise ScoringConfigInvalid(
                "CONFIG_VALUE_OUT_OF_RANGE",
                "scheduler.yaml: sched_score_risk",
                "两个子权重和必须为 1（Risk 才能取到 0 与 1 两个边界）",
            )
        if self.calibration is CalibrationState.CALIBRATED:
            raise ScoringConfigInvalid(
                "FEATURE_FLAG_NOT_PERMITTED",
                "scheduler.yaml: sched_score_risk.calibration",
                "T0 不允许声明 CALIBRATED（OQ-P7-02）",
            )


# 仅是 §8.5 的提议值，**不是**默认值：任何函数都不得把它当 fallback。
# 运行路径必须经 `risk_policy_from_config()` 取配置；这两个常量只用于配置模板、文档与自检。
DEFAULT_RISK_POLICY_PROPOSED: Final[Mapping[str, float]] = MappingProxyType(
    {"failure_pressure": 0.6, "imperative": 0.4}
)

# 同一组值的对象形态（仅供自检与文档引用，例如 `assert_boundaries()` 的边界探测）；
# 同上：**不是**配置默认值 —— 缺键仍拒绝启动。
PROPOSED_RISK_POLICY: Final[RiskPolicy] = RiskPolicy(
    failure_pressure=0.6,
    imperative=0.4,
    calibration=CalibrationState.UNCALIBRATED,
)


def risk_policy_from_config(raw: Mapping[str, object]) -> RiskPolicy:
    """从 `scheduler.yaml: sched_score_risk` 装载 Risk 子权重（缺键拒绝，不取默认）。"""
    allowed = frozenset(("failure_pressure", "imperative", "calibration"))
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ScoringConfigInvalid(
            "CONFIG_UNKNOWN_KEY", "scheduler.yaml: sched_score_risk", f"未声明的键 {unknown}"
        )
    calibration_text = _require_enum_text(raw, "calibration", "scheduler.yaml: sched_score_risk")
    return RiskPolicy(
        failure_pressure=_require_float(raw, "failure_pressure", "scheduler.yaml: sched_score_risk"),
        imperative=_require_float(raw, "imperative", "scheduler.yaml: sched_score_risk"),
        calibration=CalibrationState(calibration_text),
    )


# ---------------------------------------------------------------------------
# 2. 度量异常
# ---------------------------------------------------------------------------
class ScoringInputInvalid(RuntimeError):
    """特征原值越域（负年龄、负长度、未知档位）：属于**采集/调用错误**，不得静默钳制。

    与「资源需求超过上限」不同：达到上限是**正常业务状态**（归一化结果 0.0），
    而「负的等待秒数」「长度为 0 的关键路径」是数据错误，钳制会把错误变成看似合理的分数。
    """

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422
    reason: Final[str] = "SCORING_INPUT_INVALID"

    def __init__(self, field: str, detail: str) -> None:
        self.field = field
        self.detail = detail
        super().__init__(f"{self.error_code}/{self.reason}：{field} {detail}")


def _clamp_unit(value: float, field: str) -> float:
    """把**比值**钳制到 [0,1]；NaN/Inf 拒绝（钳制不能掩盖采集错误）。"""
    if value != value or value in (float("inf"), float("-inf")):
        raise ScoringInputInvalid(field, "为非有限数，无法归一化")
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


# ---------------------------------------------------------------------------
# 3. 五项归一化（每项都写明 0 与 1 边界）
# ---------------------------------------------------------------------------
def normalize_critical_path(length: int, longest_path_len: int) -> float:
    """CriticalPath：该节点到汇点的最长路径长度，按图内最长路径归一化。

    边界（验收判据 1）：
      - `length == 1`（汇点/无下游） → **0.0**
      - `length == longest_path_len` → **1.0**
      - `longest_path_len == 1`（单节点图，任何节点都是最长路径）→ **1.0**，并在此写明：
        此退化情形没有 0 边界可取，属图规模为 1 的特例，不伪造 0 值。

    输入域：`1 <= length <= longest_path_len`，`longest_path_len >= 1`。
    错误：越域 → `ScoringInputInvalid`（关键路径长度算错说明图或拓扑序错了，必须暴露）。
    """
    if not isinstance(length, int) or isinstance(length, bool) or length < 1:
        raise ScoringInputInvalid("critical_path_length", f"必须是 ≥1 的整数，实际 {length!r}")
    if not isinstance(longest_path_len, int) or isinstance(longest_path_len, bool):
        raise ScoringInputInvalid("longest_path_len", f"必须是整数，实际 {longest_path_len!r}")
    if longest_path_len < 1:
        raise ScoringInputInvalid("longest_path_len", f"必须 ≥1，实际 {longest_path_len}")
    if length > longest_path_len:
        raise ScoringInputInvalid(
            "critical_path_length", f"{length} 超过图内最长路径 {longest_path_len}"
        )
    if longest_path_len == 1:
        return 1.0
    return (length - 1) / (longest_path_len - 1)


def normalize_risk(
    failure_pressure: float,
    imperative: float,
    *,
    policy: RiskPolicy,
) -> float:
    """Risk：失败压力与副作用强度的加权和。

    - `failure_pressure` = 已失败 attempt 数 / `retry_policy.max_attempts`（0 → 0.0，用满 → 1.0）；
    - `imperative` = `side_effect_class` 的序数映射，见 `RISK_IMPERATIVE_BY_CLASS`
      （`PURE_FUNCTION` 0.0 / `PURE_ARTIFACT` 0.5 / `SIDE_EFFECT` 1.0，来自已冻结三值枚举）；
    - `policy` 为**必填** keyword-only：子权重必须来自配置（`risk_policy_from_config`），
      本函数不带默认值，也不接受 `None` —— 缺配置必须抛错，不得静默回退到提议值。

    边界：两项都为 0 → **0.0**；两项都为 1 → **1.0**（子权重和已校验为 1）。
    错误：任一子项越出 [0,1] → `ScoringInputInvalid`（不钳制：失败压力 1.4 说明计数或上限错了）；
         未传 `policy` → `TypeError`（签名层面拒绝）。
    """
    for name, value in (("failure_pressure", failure_pressure), ("imperative", imperative)):
        if value != value or value in (float("inf"), float("-inf")):
            raise ScoringInputInvalid(name, "为非有限数")
        if not (0.0 <= value <= 1.0):
            raise ScoringInputInvalid(name, f"必须在 [0,1]，实际 {value}")
    return policy.failure_pressure * failure_pressure + policy.imperative * imperative


def normalize_age(wait_sec: float, horizon_sec: float) -> float:
    """Age：等待时长相对饥饿视界的比例（§8.5「Age 防止饥饿」）。

    边界：`wait_sec == 0` → **0.0**；`wait_sec >= horizon_sec` → **1.0**（之后保持 1，不再加分）。
    为什么饱和：Age 的职责是「抵消 starving」，不是「永远压过关键路径」；
    真正的饥饿保证由 `ready_queue` 的老化提升（硬阈值）承担，不靠把 Age 无限放大。

    错误：`wait_sec < 0` → `ScoringInputInvalid`（时钟回拨/传参错误必须暴露）；
         `horizon_sec <= 0` → `ScoringConfigInvalid`（配置错，不是运行时错误）。
    """
    if wait_sec != wait_sec or wait_sec in (float("inf"), float("-inf")):
        raise ScoringInputInvalid("wait_sec", "为非有限数")
    if wait_sec < 0.0:
        raise ScoringInputInvalid("wait_sec", f"不得为负（实际 {wait_sec}）")
    if horizon_sec != horizon_sec or horizon_sec <= 0.0:
        raise ScoringConfigInvalid(
            "CONFIG_VALUE_OUT_OF_RANGE",
            "scheduler.yaml: age_horizon_sec",
            f"必须 > 0，实际 {horizon_sec!r}",
        )
    if wait_sec == 0.0:
        return 0.0
    if wait_sec >= horizon_sec:
        return 1.0
    return wait_sec / horizon_sec


@dataclass(frozen=True, slots=True)
class ResourceDemand:
    """一个节点本次执行预计需要的资源（三项都可为 0，表示不申请该维度）。"""

    memory_mb: float = 0.0
    disk_mb: float = 0.0
    wall_sec: float = 0.0

    def __post_init__(self) -> None:
        for name in RESOURCE_DIMENSIONS:
            value = float(getattr(self, name))
            if value != value or value in (float("inf"), float("-inf")) or value < 0.0:
                raise ScoringInputInvalid(name, f"资源需求必须是有限非负数，实际 {value!r}")

    def as_mapping(self) -> Mapping[str, float]:
        return MappingProxyType({name: float(getattr(self, name)) for name in RESOURCE_DIMENSIONS})


@dataclass(frozen=True, slots=True)
class ResourceCaps:
    """对应维度的上限（来自 M03 limits / scheduler.yaml，不得在本文件给默认值）。"""

    memory_mb: float
    disk_mb: float
    wall_sec: float

    def __post_init__(self) -> None:
        for name in RESOURCE_DIMENSIONS:
            value = float(getattr(self, name))
            if value != value or value in (float("inf"), float("-inf")) or value <= 0.0:
                raise ScoringConfigInvalid(
                    "CONFIG_VALUE_OUT_OF_RANGE",
                    f"limits.yaml: <{name} 对应上限>",
                    f"上限必须 > 0，实际 {value!r}",
                )


def normalize_resource_fit(demand: ResourceDemand, caps: ResourceCaps) -> float:
    """ResourceFit：三项需求里**最紧**的一项相对上限的剩余比例。

    计算：`ratio = max(需求/上限)`（逐维钳制到 [0,1]），`fit = 1 - ratio`。
    取 max 而不是平均：一个维度打满就运行不了，平均值会掩盖这一点。

    边界：需求全为 0 → **1.0**；任一维度需求 ≥ 上限 → **0.0**。
    错误：负需求 → `ScoringInputInvalid`；上限 ≤ 0 → `ScoringConfigInvalid`（构造期已拦）。
    """
    ratios: list[float] = []
    for name in RESOURCE_DIMENSIONS:
        need = float(getattr(demand, name))
        cap = float(getattr(caps, name))
        if need < 0.0:
            raise ScoringInputInvalid(name, f"需求不得为负，实际 {need}")
        ratios.append(_clamp_unit(need / cap, name))
    tightest = max(ratios)
    if tightest == 0.0:
        return 1.0
    if tightest >= 1.0:
        return 0.0
    return 1.0 - tightest


# side_effect_class → 副作用强度序数（值来自冻结枚举的三值，映射本身是 P7 约定）。
RISK_IMPERATIVE_BY_CLASS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "PURE_FUNCTION": 0.0,
        "PURE_ARTIFACT": 0.5,
        "SIDE_EFFECT": 1.0,
    }
)


def normalize_user_priority(priority: int) -> float:
    """UserPriority：用户显式档位 0–3 映射到 [0,1]。

    边界：档位 0 → **0.0**；档位 3 → **1.0**（`p / 3`）。
    错误：非整数、越界档位 → `ScoringInputInvalid`（不得把 7 当成「比 3 更高」）。

    说明：`TaskSpec` 的 19 个冻结字段里**没有** priority（05 §2.1）。
    档位只能来自调度侧的显式登记表（OQ-P7-03），默认 0；本函数不读任何存储。
    """
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ScoringInputInvalid("user_priority", f"必须是整数档位，实际 {priority!r}")
    if priority not in USER_PRIORITY_LEVELS:
        raise ScoringInputInvalid(
            "user_priority", f"只允许 {USER_PRIORITY_LEVELS}，实际 {priority}"
        )
    return priority / 3.0


# ---------------------------------------------------------------------------
# 4. 特征向量与总分
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SchedFeatures:
    """归一化后的五个特征；构造期断言每项都在 [0,1]。"""

    critical_path: float
    risk: float
    age: float
    resource_fit: float
    user_priority: float

    def __post_init__(self) -> None:
        for name in FEATURE_ORDER:
            value = float(getattr(self, name))
            if not (0.0 <= value <= 1.0):
                raise ScoringInputInvalid(name, f"归一化结果必须落在 [0,1]，实际 {value}")

    def as_mapping(self) -> Mapping[str, float]:
        return MappingProxyType({name: float(getattr(self, name)) for name in FEATURE_ORDER})


@dataclass(frozen=True, slots=True)
class SchedScore:
    """一次评分的完整记录。

    `total` 由特征与权重算出，**不接受外部传入**（调用方不能自报高分）。
    `weights_id` 用于把分数绑定到一组权重；权重变了，分数不可横向比较。
    """

    node_id: str
    features: SchedFeatures
    weights: SchedScoreWeights
    total: float
    calibration: CalibrationState
    disclaimer: str = CALIBRATION_DISCLAIMER

    def __post_init__(self) -> None:
        if not (0.0 <= self.total <= 1.0 + EPS):
            raise ScoringInputInvalid("total", f"总分必须落在 [0,1]，实际 {self.total}")
        if self.calibration is not self.weights.calibration:
            raise ScoringConfigInvalid(
                "CONFIG_VALUE_OUT_OF_RANGE",
                "SchedScore.calibration",
                "分数的校准状态必须与权重一致（不得单独放宽）",
            )

    def contributions(self) -> Mapping[str, float]:
        """逐项贡献（`权重 × 特征`），供调度日志解释「为什么它先跑」。"""
        return MappingProxyType(
            {
                name: float(getattr(self.weights, name)) * float(getattr(self.features, name))
                for name in FEATURE_ORDER
            }
        )

    def as_log_fields(self) -> Mapping[str, object]:
        """写进调度日志的字段：特征原值 + 贡献 + 校准声明 + 权重身份。

        不含时间戳（时间由日志框架记录），不含 plan_* 字段（见 `SCORE_IS_NOT_PLAN_INPUT`）。
        """
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "features": dict(self.features.as_mapping()),
                "contributions": dict(self.contributions()),
                "total": round(self.total, 9),
                "calibration": self.calibration.value,
                "disclaimer": self.disclaimer,
            }
        )


@dataclass(frozen=True, slots=True)
class NodeScoreFacts:
    """计算分数所需的**已观测事实**（不含仓储、不含时钟）。

    这些字段来自 M04 节点声明、执行历史与调度状态；本模块只消费，不推断。
    """

    node_id: str
    critical_path_len: int
    longest_path_len: int
    failed_attempts: int
    max_attempts: int
    side_effect_class: str
    wait_sec: float
    demand: ResourceDemand
    user_priority: int = 0


class ClockPort(Protocol):
    """只读单调时钟；只服务 Age，不参与任何哈希。"""

    def monotonic(self) -> float:
        ...


def _failure_pressure(failed_attempts: int, max_attempts: int) -> float:
    """失败压力：`失败次数 / max_attempts`，钳制到 [0,1]。

    边界：0 次失败 → 0.0；失败次数用满 `max_attempts` → 1.0。
    校验：`max_attempts >= 1`（05 §3.1）；失败次数不得为负。
    """
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ScoringInputInvalid("max_attempts", f"必须 ≥1 的整数，实际 {max_attempts!r}")
    if isinstance(failed_attempts, bool) or not isinstance(failed_attempts, int):
        raise ScoringInputInvalid("failed_attempts", f"必须是整数，实际 {failed_attempts!r}")
    if failed_attempts < 0:
        raise ScoringInputInvalid("failed_attempts", f"不得为负，实际 {failed_attempts}")
    return _clamp_unit(failed_attempts / max_attempts, "failure_pressure")


def compute_score(
    facts: NodeScoreFacts,
    *,
    weights: SchedScoreWeights,
    risk_policy: RiskPolicy,
    caps: ResourceCaps,
    age_horizon_sec: float,
) -> SchedScore:
    """按 §8.5 公式计算一个节点的 SchedScore。

    步骤：
      1. CriticalPath 归一化（图内最长路径）；
      2. Risk = 失败压力 + 副作用强度的加权和；
      3. Age = 等待时长 / 饥饿视界（饱和于 1）；
      4. ResourceFit = 1 - 最紧维度占用比；
      5. UserPriority = 显式档位 / 3；
      6. 加权求和，构造 `SchedScore`（含逐项贡献与校准声明）。

    输入：`NodeScoreFacts` + 权重 + **必填**的风险策略（keyword-only `risk_policy`）+ 维度上限 + Age 视界。
    输出：`SchedScore`。
    副作用：无（不读时钟：`wait_sec` 由调用方用 `ClockPort` 算好后传入）。
    错误：输入越域 → `ScoringInputInvalid`；配置越界 → `ScoringConfigInvalid`。
    """
    # 步骤 1：关键路径
    critical_path = normalize_critical_path(facts.critical_path_len, facts.longest_path_len)
    # 步骤 2：风险（副作用类别必须是已冻结三值之一）
    imperative = RISK_IMPERATIVE_BY_CLASS.get(facts.side_effect_class)
    if imperative is None:
        raise ScoringInputInvalid(
            "side_effect_class",
            f"未登记类别 {facts.side_effect_class!r}（只允许 {tuple(RISK_IMPERATIVE_BY_CLASS)}）",
        )
    risk = normalize_risk(
        _failure_pressure(facts.failed_attempts, facts.max_attempts),
        imperative,
        policy=risk_policy,
    )
    # 步骤 3：Age（饱和型）
    age = normalize_age(facts.wait_sec, age_horizon_sec)
    # 步骤 4：资源适配
    resource_fit = normalize_resource_fit(facts.demand, caps)
    # 步骤 5：用户优先级
    user_priority = normalize_user_priority(facts.user_priority)
    # 步骤 6：加权求和（顺序固定，避免浮点累加顺序随字典变化）
    features = SchedFeatures(
        critical_path=critical_path,
        risk=risk,
        age=age,
        resource_fit=resource_fit,
        user_priority=user_priority,
    )
    total = 0.0
    for name in FEATURE_ORDER:
        total += float(getattr(weights, name)) * float(getattr(features, name))
    return SchedScore(
        node_id=facts.node_id,
        features=features,
        weights=weights,
        total=min(max(total, 0.0), 1.0),
        calibration=weights.calibration,
    )


# ---------------------------------------------------------------------------
# 5. 确定性比较（含并列规则）
# ---------------------------------------------------------------------------
def compare_scores(
    left: SchedScore,
    right: SchedScore,
    *,
    topological_rank: Mapping[str, int],
) -> int:
    """比较两个候选：返回 -1（left 先）/ 0 / 1（right 先）。

    规则（顺序固定，全部可复核）：
      1. 总分降序（先四舍五入到 9 位，消除浮点尾差）；
      2. 并列时 CriticalPath 降序（偏向更长的下游链）；
      3. 再并列时**拓扑序名次升序**（`topological_then_node_id`，M03 `ready_order` 的口径）；
      4. 最后按 `node_id` 字典序（UTF-16 码元序，与 JCS 口径一致）——保证全序、无随机。

    为什么第 3/4 条存在：Python 的 `sorted` 是稳定排序，但堆（`heapq`）不稳定；
    没有全序键时同一批候选可能在不同运行中给出不同顺序，调度就不可复核。
    副作用：无。错误：候选缺少拓扑名次 → `ScoringInputInvalid`（不得“当作无穷大”）。
    """
    def _total(score: SchedScore) -> float:
        return round(float(score.total), 9)

    if abs(_total(left) - _total(right)) > EPS:
        return -1 if _total(left) > _total(right) else 1

    if abs(left.features.critical_path - right.features.critical_path) > EPS:
        return -1 if left.features.critical_path > right.features.critical_path else 1

    for score in (left, right):
        if score.node_id not in topological_rank:
            raise ScoringInputInvalid(
                "topological_rank", f"候选 {score.node_id!r} 没有拓扑名次"
            )
    left_rank = topological_rank[left.node_id]
    right_rank = topological_rank[right.node_id]
    if left_rank != right_rank:
        return -1 if left_rank < right_rank else 1
    if left.node_id == right.node_id:
        return 0
    return -1 if left.node_id < right.node_id else 1


# ---------------------------------------------------------------------------
# 6. 自检（落地阶段由测试逐条断言；P7 不执行）
# ---------------------------------------------------------------------------
def assert_boundaries() -> list[str]:
    """验收判据 1 的自检：五项归一化都能取到 0 与 1。

    返回违反项列表（空 = 通过）。检查项：
      1. 每项特征都有 `normalize_*` 命名、且都能返回 0.0 与 1.0；
      2. `SchedFeatures` 拒绝越界值；
      3. Risk 子权重和 == 1（否则 Risk 取不到 1 边界）；
      4. `normalize_age` 在 `wait_sec >= horizon` 处饱和为 1.0（不是持续增长）。
    """
    problems: list[str] = []
    probes: tuple[tuple[str, float], ...] = (
        ("critical_path(score0=1)", normalize_critical_path(1, 4)),
        ("critical_path(score1=longest)", normalize_critical_path(4, 4)),
        ("risk(score0)", normalize_risk(0.0, 0.0, policy=PROPOSED_RISK_POLICY)),
        ("risk(score1)", normalize_risk(1.0, 1.0, policy=PROPOSED_RISK_POLICY)),
        ("age(score0=0)", normalize_age(0.0, 60.0)),
        ("age(score1=horizon)", normalize_age(60.0, 60.0)),
        (
            "resource_fit(score0=at cap)",
            normalize_resource_fit(ResourceDemand(memory_mb=1024.0), _probe_caps()),
        ),
        ("resource_fit(score1=no demand)", normalize_resource_fit(ResourceDemand(), _probe_caps())),
        ("user_priority(score0=0)", normalize_user_priority(0)),
        ("user_priority(score1=3)", normalize_user_priority(3)),
    )
    seen: dict[str, set[float]] = {}
    for label, value in probes:
        feature = label.split("(")[0]
        seen.setdefault(feature, set()).add(round(value, 12))
    for feature, values in sorted(seen.items()):
        if 0.0 not in values:
            problems.append(f"{feature} 缺少 0 边界")
        if 1.0 not in values:
            problems.append(f"{feature} 缺少 1 边界")
    if normalize_age(600.0, 60.0) != 1.0:
        problems.append("normalize_age 未在 horizon 处饱和")
    try:
        SchedFeatures(1.5, 0.0, 0.0, 0.0, 0.0)
    except ScoringInputInvalid:
        pass
    else:
        problems.append("SchedFeatures 未拒绝越界特征")
    return problems


def _probe_caps() -> ResourceCaps:
    """自检专用上限（仅函数内临时值，不是配置默认值）。"""
    return ResourceCaps(memory_mb=1024.0, disk_mb=4096.0, wall_sec=600.0)


def assert_not_optimality_claim() -> list[str]:
    """自检：本模块不得声称已校准/最优，也不得存在「缺键回退到提议值」的通路。

    检查项：
      1. 常量名带 `PROPOSED`（评审可见的标记），且 `PROPOSED_WEIGHTS` 和为 1；
      2. `CALIBRATION_DISCLAIMER` 非空且提到「未校准」；
      3. `SchedScoreWeights` 的默认校准状态是 `UNCALIBRATED`；
      4. 构造一个 `CALIBRATED` 权重必须抛 `FEATURE_FLAG_NOT_PERMITTED`（T0 无校准证据）；
      5. 缺键装载必须抛 `CONFIG_MISSING_KEY`（不存在“悄悄用提议值”的分支）。
    """
    problems: list[str] = []
    if globals().get("PROPOSED_WEIGHTS") is None:
        problems.append("权重常量必须以 PROPOSED_ 命名（未校准标记）")
    if abs(sum(PROPOSED_WEIGHTS.values()) - 1.0) > EPS:
        problems.append("策划书 §8.5 的五项权重和不为一，公式有误")
    if not CALIBRATION_DISCLAIMER or "未校准" not in CALIBRATION_DISCLAIMER:
        problems.append("必须提供含『未校准』的声明")
    if SchedScoreWeights.__dataclass_fields__["calibration"].default is not CalibrationState.UNCALIBRATED:
        problems.append("权重默认校准状态必须是 UNCALIBRATED")
    try:
        SchedScoreWeights(0.30, 0.25, 0.20, 0.15, 0.10, calibration=CalibrationState.CALIBRATED)
    except ScoringConfigInvalid as exc:
        if exc.code != "FEATURE_FLAG_NOT_PERMITTED":
            problems.append(f"声明 CALIBRATED 的拒绝码应为 FEATURE_FLAG_NOT_PERMITTED，实际 {exc.code}")
    else:
        problems.append("T0 竟然允许声明 CALIBRATED")
    try:
        weights_from_config({"critical_path": 0.30})
    except ScoringConfigInvalid as exc:
        if exc.code != "CONFIG_MISSING_KEY":
            problems.append(f"缺键应报 CONFIG_MISSING_KEY，实际 {exc.code}")
    else:
        problems.append("缺键竟然没有拒绝（存在隐式默认值）")
    return problems


def assert_feature_order_complete() -> list[str]:
    """自检：`FEATURE_ORDER` 与五个 dataclass 字段、五条配置键必须一一对应。"""
    problems: list[str] = []
    expected = {
        "critical_path", "risk", "age", "resource_fit", "user_priority",
    }
    if set(FEATURE_ORDER) != expected:
        problems.append(f"FEATURE_ORDER 与五项特征不一致：{FEATURE_ORDER}")
    if set(PROPOSED_WEIGHTS) != expected:
        problems.append("PROPOSED_WEIGHTS 的键与 FEATURE_ORDER 不一致")
    return problems


def _sequence_guard(values: Sequence[float]) -> None:
    """占位：确保比较逻辑的输入是序列而不是集合（顺序敏感）。

    P7 不调用；保留它是为了让“集合绝对不能进排序”这件事在评审时可见。
    """
    if isinstance(values, (set, frozenset)):
        raise ScoringInputInvalid("values", "不得用集合承载候选（顺序不可控）")