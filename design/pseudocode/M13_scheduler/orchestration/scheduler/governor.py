"""M13 · orchestration/scheduler/governor.py — 资源感知治理（P7 伪代码）。
阶段：P7「调度与定向恢复」｜追踪：FR-011（Governor；正式属 T1/G4）、NFR-06、策划书 §8.6 / §8.9
依赖：M03 limits（LimitKind / 并发硬上限 2）、M05 process_control（进程树回收由它执行）、M13 ready_queue（资源视图）
不变量：阈值全部可配置且标「初始待校准」；硬阈值未解除不得派发；**绝不取消必检项与 L3**；**绝不直接改节点状态**
错误码：RESOURCE_BUDGET_EXCEEDED（429，`detail.limit_kind` + reason=GOVERNOR_*）、
        REQUIRED_EVIDENCE_MISSING（409，`reason=MANDATORY_CHECK_DEFERRAL_REFUSED`）、CONFIG_*（503）
写入者：无。Governor 只产出**指令**：进程回收由 M05 执行、状态迁移由 StateMachine 执行
状态：伪代码；不采样、不杀进程、不读配置、不写日志

## 五类监控与动作（策划书 §8.6 TABLE 36 的逐行落地）

  | 监控 | 读什么 | 软阈值动作 | 硬阈值动作 |
  |---|---|---|---|
  | 内存 | 已用 / 应用预算 | 减并发（−1，下限 1） | 暂停派发 + 回收超限进程树 |
  | CPU | 持续高负载比值 + 持续时间 | 减并发 | 减并发 + 延后非关键验证 |
  | 磁盘 | 工作区剩余空间 | 告警 + 停止新的入队 | 暂停派发（**只清临时缓存，不删证据**） |
  | 预算 | token / wall-clock / 重试次数 | 延后非关键验证 | 建议换模板/模型（须经图变更流程）+ 暂停派发 |
  | 进程 | 僵尸数 / 未退出子进程树 | 记录 | 回收进程树（按进程组/Job Object）+ 暂停派发（未解除前不派发新节点） |

## 三条硬边界（本文件为什么“看起来什么都不做”）

  1. **不改节点状态**：`GovernorDirective.state_change` 是 `ClassVar[None]`，类里没有
     `transition`/`set_state`/`mark_*`。要改状态，必须由 Orchestrator 另发起
     `StateMachine.transition()`（例如回收失败后 `RUNNING→FAILED`，见 OQ-P3-10）。
  2. **不取消必检与 L3**：`GovernorAction` 里没有取消类动作（`FORBIDDEN_ACTIONS` 显式列出禁名）；
     唯一能“延后”的入口 `request_deferral()` 对 `ProtectedWork.is_protected=True` 直接抛
     `MandatoryWorkProtected`。所以“为省预算取消必检”在本模块里**构造不出来**。
  3. **阈值不是最优值**：70%/85%/85%/30s 来自策划书 §8.6 原文的「初始待校准值」，
     本文件把它们登记为 `PROPOSED_INITIAL_THRESHOLDS`，装载必须从配置读，缺键拒绝启动。
     任何「已调优」的表述都没有依据，`CALIBRATION` 恒为 `UNCALIBRATED`。

## 为什么不在这里采样

  采样频率、采样归属（进程/线程/外部探针）没有冻结（OQ-P7-05）。本文件只接受
  `ResourceSample` 快照；谁采样、多久采一次，由部署层决定并在 MODULE 的 OQ 里登记。
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, Mapping, Sequence

from .scoring import ScoringConfigInvalid

__all__ = [
    "CALIBRATION_NOTE",
    "CONCURRENCY_FLOOR",
    "CONCURRENCY_HARD_CAP",
    "EVALUATION_ORDER",
    "FOOTPRINT_KEYS",
    "FORBIDDEN_ACTIONS",
    "Governor",
    "GovernorAction",
    "GovernorDirective",
    "GovernorState",
    "GovernorThresholds",
    "Admission",
    "CONFIG_PATH",
    "MandatoryWorkProtected",
    "MonitorKind",
    "PressureLevel",
    "ProtectedWork",
    "PROPOSED_INITIAL_THRESHOLDS",
    "ResourceSample",
    "MonitorReading",
    "assert_no_forbidden_action",
    "assert_no_state_change",
    "assert_preservation",
    "assert_thresholds_configurable",
    "thresholds_from_config",
]

# 并发下限/上限：上限 2 是 05 §2.1 / NFR-06 的契约值；下限 1 是“再省也要能跑”。
CONCURRENCY_HARD_CAP: Final[int] = 2
CONCURRENCY_FLOOR: Final[int] = 1

CONFIG_PATH: Final[str] = "scheduler.yaml: governor"

CALIBRATION_NOTE: Final[str] = (
    "以下阈值是「初始待校准值」：内存 70%/85%、CPU 85% 持续 30 秒来自策划书 §8.6 原文，"
    "其余为本阶段提议；均未经历史回放/敏感性分析校准，不得写成最优值或验收阈值。"
)

# 监控项的求值顺序：先不可逆（残留进程、磁盘写满），再内存，再 CPU，最后预算。
# 依据：与 M03 `ENFORCEMENT_PRECEDENCE` 同一条「先硬后软、先不可逆后可逆」的理由。
EVALUATION_ORDER: Final[tuple[str, ...]] = (
    "PROCESS",
    "DISK",
    "MEMORY",
    "CPU",
    "BUDGET",
)


class MonitorKind(StrEnum):
    MEMORY = "MEMORY"
    CPU = "CPU"
    DISK = "DISK"
    BUDGET = "BUDGET"
    PROCESS = "PROCESS"


class PressureLevel(StrEnum):
    NORMAL = "NORMAL"
    SOFT = "SOFT"
    HARD = "HARD"


# ---------------------------------------------------------------------------
# 1. 阈值（全部来自配置；本文件不含默认值）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GovernorThresholds:
    """Governor 的全部阈值。每一项都必须由配置给出，缺键即拒绝启动。

    字段与 `scheduler.yaml: governor.*` 的键一一对应；键名本身还是 `[P7 提议]`，
    因为 M03 的 `scheduler.yaml` 目前只冻结了 `max_workers/ready_order/memory_watermark_mb/
    disk_watermark_mb`，动态 Governor 参数被登记为「T1/G4 未定义」（见 OQ-P7-02）。
    """

    memory_soft_ratio: float
    memory_hard_ratio: float
    cpu_sustained_ratio: float
    cpu_sustained_window_sec: float
    disk_watermark_mb: float
    disk_soft_factor: float
    budget_soft_ratio: float
    budget_hard_ratio: float
    zombie_process_limit: int
    runaway_tree_limit: int
    reclaim_grace_sec: float
    max_concurrency: int  # 必填（原默认值已移除：默认值会绕过「缺键拒绝启动」）

    def __post_init__(self) -> None:
        # 比值型阈值：0 < soft < hard ≤ 1（软阈值必须先于硬阈值触发）
        for soft, hard, name in (
            (self.memory_soft_ratio, self.memory_hard_ratio, "memory"),
            (self.budget_soft_ratio, self.budget_hard_ratio, "budget"),
        ):
            for value in (soft, hard):
                if not (0.0 < float(value) <= 1.0):
                    raise ValueError(f"{name} 阈值必须在 (0,1]，实际 {value!r}")
            if not float(soft) < float(hard):
                raise ValueError(f"{name} 软阈值必须严格小于硬阈值（{soft} ≥ {hard}）")
        if not (0.0 < self.cpu_sustained_ratio <= 1.0):
            raise ValueError("CPU 持续阈值必须在 (0,1]")
        if self.cpu_sustained_window_sec <= 0:
            raise ValueError("CPU 持续窗口必须 > 0 秒")
        if self.disk_watermark_mb <= 0:
            raise ValueError("磁盘水位必须 > 0 MB")
        if self.disk_soft_factor <= 1.0:
            raise ValueError("磁盘软阈值系数必须 > 1（软阈值 = 水位 × 系数）")
        if self.zombie_process_limit < 0 or self.runaway_tree_limit < 0:
            raise ValueError("进程阈值不得为负")
        if self.reclaim_grace_sec < 0:
            raise ValueError("回收宽限期不得为负")
        if not (CONCURRENCY_FLOOR <= self.max_concurrency <= CONCURRENCY_HARD_CAP):
            raise ValueError(
                f"并发必须在 [{CONCURRENCY_FLOOR},{CONCURRENCY_HARD_CAP}]，实际 {self.max_concurrency}"
            )

    def as_mapping(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "memory_soft_ratio": self.memory_soft_ratio,
                "memory_hard_ratio": self.memory_hard_ratio,
                "cpu_sustained_ratio": self.cpu_sustained_ratio,
                "cpu_sustained_window_sec": self.cpu_sustained_window_sec,
                "disk_watermark_mb": self.disk_watermark_mb,
                "disk_soft_factor": self.disk_soft_factor,
                "budget_soft_ratio": self.budget_soft_ratio,
                "budget_hard_ratio": self.budget_hard_ratio,
                "zombie_process_limit": self.zombie_process_limit,
                "runaway_tree_limit": self.runaway_tree_limit,
                "reclaim_grace_sec": self.reclaim_grace_sec,
                "max_concurrency": self.max_concurrency,
            }
        )


# 配置键清单（供 M03 schema 扩展与启动守卫；值本身不是默认值）
FOOTPRINT_KEYS: Final[tuple[str, ...]] = (
    "memory_soft_ratio",
    "memory_hard_ratio",
    "cpu_sustained_ratio",
    "cpu_sustained_window_sec",
    "disk_watermark_mb",
    "disk_soft_factor",
    "budget_soft_ratio",
    "budget_hard_ratio",
    "zombie_process_limit",
    "runaway_tree_limit",
    "reclaim_grace_sec",
    "max_concurrency",
)

# 策划书 §8.6 的原文值 + 本阶段提议值；**不是**默认值，只是配置模板的候选内容。
PROPOSED_INITIAL_THRESHOLDS: Final[Mapping[str, object]] = MappingProxyType(
    {
        "memory_soft_ratio": 0.70,          # §8.6 原文「70% 仅作初始待校准值」
        "memory_hard_ratio": 0.85,          # §8.6 原文「85%」
        "cpu_sustained_ratio": 0.85,        # §8.6 原文「例如 85%」
        "cpu_sustained_window_sec": 30.0,   # §8.6 原文「持续 30 秒」
        "disk_watermark_mb": 2048.0,        # [P7 提议] 无原文依据
        "disk_soft_factor": 1.5,            # [P7 提议] 剩余空间 < 1.5×水位 视为 SOFT
        "budget_soft_ratio": 0.80,          # [P7 提议] 无原文依据
        "budget_hard_ratio": 0.95,          # [P7 提议] 无原文依据
        "zombie_process_limit": 0,          # [P7 提议] T0 不容忍僵尸进程
        "runaway_tree_limit": 0,            # [P7 提议] T0 不容忍未退出的进程树
        "reclaim_grace_sec": 5.0,           # 对齐 M05 process_control.DEFAULT_GRACE_SEC（该值同样非契约）
        "max_concurrency": CONCURRENCY_HARD_CAP,
    }
)


def thresholds_from_config(raw: Mapping[str, object]) -> GovernorThresholds:
    """从 `scheduler.yaml: governor.*` 装载阈值。

    规则：键集合必须与 `FOOTPRINT_KEYS` 精确相等；缺键 → `CONFIG_MISSING_KEY`；
    多余键 → `CONFIG_UNKNOWN_KEY`；类型不符（含 bool 冒充 int）→ `CONFIG_TYPE_INVALID`。
    **不存在**「缺键就用 PROPOSED_INITIAL_THRESHOLDS」的分支。
    """
    unknown = sorted(set(raw) - set(FOOTPRINT_KEYS))
    if unknown:
        raise ScoringConfigInvalid(
            "CONFIG_UNKNOWN_KEY", CONFIG_PATH, f"未声明的键 {unknown}"
        )
    missing = [key for key in FOOTPRINT_KEYS if key not in raw]
    if missing:
        raise ScoringConfigInvalid(
            "CONFIG_MISSING_KEY", CONFIG_PATH, f"缺少键 {missing}（配置没有隐式默认值）"
        )
    numeric: dict[str, float] = {}
    for key in FOOTPRINT_KEYS:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScoringConfigInvalid("CONFIG_TYPE_INVALID", f"{CONFIG_PATH}.{key}", "必须是数字")
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ScoringConfigInvalid(
                "CONFIG_TYPE_INVALID", f"{CONFIG_PATH}.{key}", "不允许 NaN/Infinity"
            )
        numeric[key] = number
    for key in ("zombie_process_limit", "runaway_tree_limit", "max_concurrency"):
        if not float(numeric[key]).is_integer():
            raise ScoringConfigInvalid(
                "CONFIG_TYPE_INVALID", f"{CONFIG_PATH}.{key}", "必须是整数"
            )
    try:
        return GovernorThresholds(
            memory_soft_ratio=numeric["memory_soft_ratio"],
            memory_hard_ratio=numeric["memory_hard_ratio"],
            cpu_sustained_ratio=numeric["cpu_sustained_ratio"],
            cpu_sustained_window_sec=numeric["cpu_sustained_window_sec"],
            disk_watermark_mb=numeric["disk_watermark_mb"],
            disk_soft_factor=numeric["disk_soft_factor"],
            budget_soft_ratio=numeric["budget_soft_ratio"],
            budget_hard_ratio=numeric["budget_hard_ratio"],
            zombie_process_limit=int(numeric["zombie_process_limit"]),
            runaway_tree_limit=int(numeric["runaway_tree_limit"]),
            reclaim_grace_sec=numeric["reclaim_grace_sec"],
            max_concurrency=int(numeric["max_concurrency"]),
        )
    except ValueError as exc:
        raise ScoringConfigInvalid(
            "CONFIG_VALUE_OUT_OF_RANGE", CONFIG_PATH, str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# 2. 观测样本
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ResourceSample:
    """某一时刻的一次资源快照（由部署层采样后传入）。

    全部字段都是**观测值**：`*_budget` 是配置上限，`*_used` 是已用量。
    构造期拒绝负数与非有限值 —— 采样失败不得用 0 冒充“一切正常”。
    """

    memory_used_mb: float
    memory_budget_mb: float
    cpu_ratio: float
    cpu_sustained_sec: float
    disk_free_mb: float
    tokens_used: int
    token_budget: int
    wall_used_sec: float
    wall_budget_sec: float
    attempts_used: int
    attempts_cap: int
    zombie_processes: int = 0
    runaway_trees: int = 0

    def __post_init__(self) -> None:
        finite_non_negative = (
            "memory_used_mb", "memory_budget_mb", "cpu_ratio", "cpu_sustained_sec",
            "disk_free_mb", "wall_used_sec", "wall_budget_sec",
        )
        for name in finite_non_negative:
            value = float(getattr(self, name))
            if value != value or value in (float("inf"), float("-inf")) or value < 0.0:
                raise ValueError(f"{name} 必须是有限非负数，实际 {value!r}")
        if not (0.0 <= self.cpu_ratio <= 1.0):
            raise ValueError("cpu_ratio 必须落在 [0,1]")
        for name in ("tokens_used", "token_budget", "attempts_used", "attempts_cap",
                     "zombie_processes", "runaway_trees"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} 必须是非负整数，实际 {value!r}")
        if self.memory_budget_mb <= 0 or self.wall_budget_sec <= 0 or self.token_budget < 0:
            raise ValueError("预算上限必须为正（token 预算可为 0，表示 T0 无 LLM）")

    # -- 派生比值（全部钳制到 [0,1]，避免“已用 > 预算”时得到 >1 的伪值） --
    def memory_ratio(self) -> float:
        return min(1.0, self.memory_used_mb / self.memory_budget_mb)

    def budget_ratio(self) -> float:
        """预算占用：token / wall / 重试次数三者取最紧。"""
        ratios = [min(1.0, self.wall_used_sec / self.wall_budget_sec)]
        if self.token_budget > 0:
            ratios.append(min(1.0, self.tokens_used / self.token_budget))
        else:
            # token 预算为 0（T0 无 LLM）：任何消耗即视为 100% 占用。
            ratios.append(1.0 if self.tokens_used > 0 else 0.0)
        if self.attempts_cap > 0:
            ratios.append(min(1.0, self.attempts_used / self.attempts_cap))
        return max(ratios)

    def budget_binding_kind(self) -> str:
        """哪一维预算最紧（映射到 M03 `LimitKind` 的字面值）。"""
        candidates: list[tuple[float, str]] = [
            (min(1.0, self.wall_used_sec / self.wall_budget_sec), "wall_clock")
        ]
        if self.token_budget > 0:
            candidates.append((min(1.0, self.tokens_used / self.token_budget), "token"))
        else:
            candidates.append((1.0 if self.tokens_used > 0 else 0.0, "token"))
        if self.attempts_cap > 0:
            candidates.append((min(1.0, self.attempts_used / self.attempts_cap), "retry"))
        # max 遇到并列时按（比值, 维度名）取第一，保证确定性
        return max(candidates, key=lambda pair: (pair[0], pair[1]))[1]


@dataclass(frozen=True, slots=True)
class MonitorReading:
    """一类监控的一次读数与判定。"""

    monitor: MonitorKind
    level: PressureLevel
    observed: float
    threshold: float
    unit: str
    note: str = ""

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "monitor": self.monitor.value,
                "level": self.level.value,
                "observed": round(self.observed, 6),
                "threshold": self.threshold,
                "unit": self.unit,
                "note": self.note,
            }
        )


# ---------------------------------------------------------------------------
# 3. 动作与受保护的工作
# ---------------------------------------------------------------------------
class GovernorAction(StrEnum):
    """Governor 可以做的五件事。**只有这五个**。

    注意这里**没有** `CANCEL_*` / `SKIP_*` / `PAUSE_L3` / `MARK_*`：
    取消必检项、跳过 L3、把节点标成别的状态，都不是 Governor 的权力。
    """

    REDUCE_CONCURRENCY = "REDUCE_CONCURRENCY"
    PAUSE_DISPATCH = "PAUSE_DISPATCH"
    RECLAIM_PROCESS_TREE = "RECLAIM_PROCESS_TREE"
    SWITCH_TEMPLATE_OR_MODEL = "SWITCH_TEMPLATE_OR_MODEL"
    DEFER_NON_CRITICAL_VERIFICATION = "DEFER_NON_CRITICAL_VERIFICATION"


# 禁名清单：静态扫描 `GovernorAction` 成员名，出现任何一个即契约破坏。
FORBIDDEN_ACTIONS: Final[tuple[str, ...]] = (
    "CANCEL", "SKIP", "DROP", "DISABLE", "MARK_", "SET_STATE", "TRANSITION",
    "BYPASS", "PAUSE_L3", "IGNORE_REQUIRED",
)

# 绝不延后的工作类型（来源于契约/ADR，不是运行时可配的）。
PROTECTED_WORK_KINDS: Final[tuple[str, ...]] = ("required_check", "l3_replay")


class MandatoryWorkProtected(RuntimeError):
    """有人试图让 Governor 延后/取消必检项或 L3。

    对外语义：必检项没有合格证据 → `REQUIRED_EVIDENCE_MISSING`（409）。
    Governor 不是 Gate，但它**不能**成为“因为没有证据所以跳过”的入口。
    """

    error_code: Final[str] = "REQUIRED_EVIDENCE_MISSING"
    http_status: Final[int] = 409
    reason: Final[str] = "MANDATORY_CHECK_DEFERRAL_REFUSED"

    def __init__(self, work_id: str, kind: str) -> None:
        self.work_id = work_id
        self.kind = kind
        super().__init__(
            f"{self.error_code}/{self.reason}：{kind} {work_id!r} 属必检/L3，"
            "不得因资源或预算被取消或延后（AGENTS §4；策划书 §8.9）"
        )


@dataclass(frozen=True, slots=True)
class ProtectedWork:
    """一件可能被“延后”的工作（验证项）。

    `is_protected=True` 的判定依据只有两条：它是必检项，或它是 L3/IRC 重执行。
    这两类在任何预算压力下都必须保留；Governor 只能在 `optional_work` 集合里挑。
    """

    work_id: str
    kind: str
    is_required_check: bool = False
    is_l3: bool = False

    def __post_init__(self) -> None:
        protected_kinds = {kind for kind in PROTECTED_WORK_KINDS}
        optional_kinds = {"optional_check", "optional_replay"}
        if self.kind not in protected_kinds | optional_kinds:
            raise ValueError(
                f"kind 只允许 {sorted(protected_kinds | optional_kinds)}，实际 {self.kind!r}"
            )
        if self.is_required_check and self.kind != "required_check":
            raise ValueError("is_required_check=True 时 kind 必须是 'required_check'")
        if self.is_l3 and self.kind != "l3_replay":
            raise ValueError("is_l3=True 时 kind 必须是 'l3_replay'")
        if not self.is_protected and self.kind in protected_kinds:
            raise ValueError("标注为必检/L3 的工作不得同时声明为不可延后之外的可选项")

    @property
    def is_protected(self) -> bool:
        return self.is_required_check or self.is_l3

    def assert_deferrable(self) -> None:
        """延后前的唯一闸门：受保护的工作直接抛异常，不进入任何“待延后”列表。

        调用顺序写死：`Governor.request_deferral()` 在把工作加入延后集合之前**必须**调用本方法。
        """
        if self.is_protected:
            raise MandatoryWorkProtected(self.work_id, self.kind)


@dataclass(frozen=True, slots=True)
class GovernorDirective:
    """一条治理指令。**不是**状态变更，也**不是**执行动作本身。"""

    action: GovernorAction
    monitor: MonitorKind
    reason: str
    scope: str
    detail: str = ""
    requires_orchestrator: bool = False     # 换模板/模型必须走图变更流程（8.9）
    requires_executor: bool = False         # 回收进程树由 M05 执行
    forbidden_side_effects: tuple[str, ...] = ()

    # 结构性声明：指令不携带状态变更（ClassVar 不是实例字段，构造时无法赋值）。
    state_change: ClassVar[None] = None

    def __post_init__(self) -> None:
        # 任何指令都不得把“删除证据/产物/审计”写成允许的副作用
        illegal = set(self.forbidden_side_effects) & {
            "delete_evidence", "delete_artifacts", "delete_audit", "update_evidence",
        }
        if self.action is GovernorAction.RECLAIM_PROCESS_TREE and not self.requires_executor:
            raise ValueError("回收进程树必须标记 requires_executor=True（由 M05 执行）")
        if self.action is GovernorAction.SWITCH_TEMPLATE_OR_MODEL and not self.requires_orchestrator:
            raise ValueError("换模板/模型必须标记 requires_orchestrator=True（图变更需审批）")
        if illegal:
            raise ValueError(f"指令不得包含破坏性副作用 {sorted(illegal)}")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "action": self.action.value,
                "monitor": self.monitor.value,
                "reason": self.reason,
                "scope": self.scope,
                "detail": self.detail,
                "requires_orchestrator": self.requires_orchestrator,
                "requires_executor": self.requires_executor,
                "forbidden_side_effects": list(self.forbidden_side_effects),
            }
        )


@dataclass(frozen=True, slots=True)
class GovernorState:
    """一次评估的完整结果。"""

    readings: tuple[MonitorReading, ...]
    directives: tuple[GovernorDirective, ...]
    level: PressureLevel
    paused: bool
    allowed_slots: int
    deferred_optional: tuple[str, ...]
    mandatory_preserved: bool = True
    l3_preserved: bool = True
    binding_limit_kind: str | None = None   # 预算硬阈值时最紧的维度（memory/disk/token/wall_clock/retry）

    def __post_init__(self) -> None:
        if not (0 <= self.allowed_slots <= CONCURRENCY_HARD_CAP):
            raise ValueError("allowed_slots 必须在 [0,2]")
        if self.paused and self.allowed_slots != 0:
            raise ValueError("暂停派发时 allowed_slots 必须为 0")
        if not self.mandatory_preserved or not self.l3_preserved:
            # 不允许构造出“牺牲必检/L3”的状态：一旦出现就是设计事故，直接拒绝。
            raise MandatoryWorkProtected("<state>", "required_check")

    def directive_for(self, action: GovernorAction) -> tuple[GovernorDirective, ...]:
        return tuple(d for d in self.directives if d.action is action)

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "level": self.level.value,
                "paused": self.paused,
                "allowed_slots": self.allowed_slots,
                "readings": [r.as_detail() for r in self.readings],
                "directives": [d.as_detail() for d in self.directives],
                "deferred_optional": list(self.deferred_optional),
                "mandatory_preserved": self.mandatory_preserved,
                "l3_preserved": self.l3_preserved,
                "binding_limit_kind": self.binding_limit_kind,
            }
        )


@dataclass(frozen=True, slots=True)
class Admission:
    """一次「能否派发」的裁决（由 dispatch 消费，不写状态）。"""

    allowed: bool
    reason: str
    limit_kind: str | None = None
    slots_after: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        if self.allowed and self.limit_kind is not None:
            raise ValueError("允许派发时不得带 limit_kind")
        if not self.allowed and not self.reason:
            raise ValueError("拒绝必须给出 reason")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "allowed": self.allowed,
                "reason": self.reason,
                "limit_kind": self.limit_kind,
                "slots_after": self.slots_after,
                "detail": self.detail,
            }
        )


# ---------------------------------------------------------------------------
# 4. Governor
# ---------------------------------------------------------------------------
class Governor:
    """资源感知治理器：只读样本 → 只出指令。

    没有 StateMachine 端口、没有仓储、没有进程句柄、没有时钟：
    这让“Governor 直接改节点状态”在**签名层面**就做不到。
    """

    def __init__(self, thresholds: GovernorThresholds) -> None:
        self._thresholds = thresholds
        self._slots = thresholds.max_concurrency

    @property
    def thresholds(self) -> GovernorThresholds:
        return self._thresholds

    @property
    def slots(self) -> int:
        """当前允许的并发槽（已按软阈值下调；下限 1，上限 2）。"""
        return self._slots

    # -- 评估 -------------------------------------------------------------
    def evaluate(
        self,
        sample: ResourceSample,
        *,
        optional_work: Sequence[ProtectedWork] = (),
    ) -> GovernorState:
        """按五类监控求值，产出读数、指令与允许并发。

        步骤：
          1. 逐项计算读数（`EVALUATION_ORDER`：进程 → 磁盘 → 内存 → CPU → 预算）；
          2. 汇总压力等级（任一 HARD → HARD；否则任一 SOFT → SOFT）；
          3. 由等级与读数推导指令（见各 monitor 分支）；
          4. 计算允许槽位（HARD 暂停 → 0；软内存/CPU → 下调 1，下限 1）；
          5. 处理可选验证的延后：受保护的项**直接抛**，绝不进入延后集合；
          6. 断言必检与 L3 均保留。

        输入：`ResourceSample` + 可选的可延后工作（必须是非必检、非 L3）。
        输出：`GovernorState`。
        副作用：无（不写日志、不写审计、不改状态）。允许槽位的变化由调用方持久化。
        错误：传入受保护工作 → `MandatoryWorkProtected`；样本非法 → 构造期已拒绝。
        """
        # 步骤 1：五类读数（顺序固定）
        readings = (
            self._read_process(sample),
            self._read_disk(sample),
            self._read_memory(sample),
            self._read_cpu(sample),
            self._read_budget(sample),
        )
        # 步骤 2：压力等级汇总
        level = self._aggregate_level(readings)
        # 步骤 3：指令推导（顺序与 EVALUATION_ORDER 一致）
        directives: list[GovernorDirective] = []
        paused = False
        if readings[0].level is not PressureLevel.NORMAL:
            directives.append(
                GovernorDirective(
                    action=GovernorAction.RECLAIM_PROCESS_TREE,
                    monitor=MonitorKind.PROCESS,
                    reason="PROCESS_RESIDUAL_OR_ZOMBIE",
                    scope="worker-tree",
                    detail=f"僵尸 {sample.zombie_processes} / 未退出进程树 {sample.runaway_trees}",
                    requires_executor=True,
                )
            )
            if readings[0].level is PressureLevel.HARD:
                # 未退出进程树会污染后续 attempt：硬阈值期间不派发新节点（与磁盘/内存/预算同口径）。
                # 同时给出 PAUSE_DISPATCH 指令，使 `admit()` 的暂停原因可追溯到“无可用派发容量”。
                directives.append(
                    GovernorDirective(
                        action=GovernorAction.PAUSE_DISPATCH,
                        monitor=MonitorKind.PROCESS,
                        reason="NO_CONCURRENCY_SLOT",
                        scope="new-dispatch",
                        detail=(
                            f"未退出进程树 {sample.runaway_trees} > 上限 "
                            f"{self._thresholds.runaway_tree_limit}：回收确认前不派发新节点"
                        ),
                    )
                )
                paused = True
        if readings[1].level is PressureLevel.HARD:
            directives.append(
                GovernorDirective(
                    action=GovernorAction.PAUSE_DISPATCH,
                    monitor=MonitorKind.DISK,
                    reason="DISK_BELOW_WATERMARK",
                    scope="new-dispatch",
                    detail=f"剩余 {sample.disk_free_mb:.0f} MB < 水位 {self._thresholds.disk_watermark_mb:.0f} MB",
                    forbidden_side_effects=("delete_evidence", "delete_artifacts", "delete_audit"),
                )
            )
            paused = True
        elif readings[1].level is PressureLevel.SOFT:
            directives.append(
                GovernorDirective(
                    action=GovernorAction.REDUCE_CONCURRENCY,
                    monitor=MonitorKind.DISK,
                    reason="DISK_NEAR_WATERMARK",
                    scope="concurrency",
                    detail="磁盘接近水位：下调并发并停止新的入队",
                    forbidden_side_effects=("delete_evidence",),
                )
            )
        if readings[2].level is PressureLevel.HARD:
            directives.append(
                GovernorDirective(
                    action=GovernorAction.PAUSE_DISPATCH,
                    monitor=MonitorKind.MEMORY,
                    reason="MEMORY_HARD_LIMIT",
                    scope="new-dispatch",
                    detail=f"内存占用 {sample.memory_ratio():.1%} ≥ 硬阈值",
                )
            )
            directives.append(
                GovernorDirective(
                    action=GovernorAction.RECLAIM_PROCESS_TREE,
                    monitor=MonitorKind.MEMORY,
                    reason="MEMORY_OVER_BUDGET_WORKER",
                    scope="worker-tree-over-budget",
                    detail="回收超过单 worker 内存上限的进程树",
                    requires_executor=True,
                )
            )
            paused = True
        elif readings[2].level is PressureLevel.SOFT:
            directives.append(
                GovernorDirective(
                    action=GovernorAction.REDUCE_CONCURRENCY,
                    monitor=MonitorKind.MEMORY,
                    reason="MEMORY_SOFT_LIMIT",
                    scope="concurrency",
                    detail=f"内存占用 {sample.memory_ratio():.1%} ≥ 软阈值",
                )
            )
        if readings[3].level is not PressureLevel.NORMAL:
            directives.append(
                GovernorDirective(
                    action=GovernorAction.REDUCE_CONCURRENCY,
                    monitor=MonitorKind.CPU,
                    reason="CPU_SUSTAINED_HIGH",
                    scope="concurrency",
                    detail=(
                        f"CPU {sample.cpu_ratio:.0%} 持续 {sample.cpu_sustained_sec:.0f}s "
                        f"≥ 阈值 {self._thresholds.cpu_sustained_ratio:.0%}/"
                        f"{self._thresholds.cpu_sustained_window_sec:.0f}s"
                    ),
                )
            )
        if readings[4].level is PressureLevel.HARD:
            directives.append(
                GovernorDirective(
                    action=GovernorAction.PAUSE_DISPATCH,
                    monitor=MonitorKind.BUDGET,
                    reason="BUDGET_EXHAUSTED",
                    scope="new-dispatch",
                    detail=f"预算占用 {sample.budget_ratio():.1%} ≥ 硬阈值",
                )
            )
            directives.append(
                GovernorDirective(
                    action=GovernorAction.SWITCH_TEMPLATE_OR_MODEL,
                    monitor=MonitorKind.BUDGET,
                    reason="BUDGET_HARD_LIMIT",
                    scope="template",
                    detail="建议改用更省的模板/模型；必须经图变更（graph_patch）审批，不得就地替换",
                    requires_orchestrator=True,
                )
            )
            paused = True
        # 步骤 4：允许槽位（暂停 → 0；软压力 → 下调；绝不低于 1，绝不高于 2）
        allowed_slots = 0 if paused else self._reduced_slots(level)
        # 步骤 5：可选验证的延后（受保护项直接抛）
        defer_needed = (
            readings[3].level is not PressureLevel.NORMAL
            or readings[4].level is not PressureLevel.NORMAL
        )
        deferred: list[str] = []
        if defer_needed:
            for work in optional_work:
                work.assert_deferrable()   # 必检/L3 在这里被挡住
                deferred.append(work.work_id)
            directives.append(
                GovernorDirective(
                    action=GovernorAction.DEFER_NON_CRITICAL_VERIFICATION,
                    monitor=MonitorKind.BUDGET,
                    reason="DEFER_OPTIONAL_VERIFICATION",
                    scope="verification",
                    detail=f"延后 {len(deferred)} 项非关键验证；必检与 L3 不在其中",
                )
            )
        # 步骤 6：状态构造期再断言一次“必检与 L3 保留”
        state = GovernorState(
            readings=readings,
            directives=tuple(directives),
            level=level,
            paused=paused,
            allowed_slots=allowed_slots,
            deferred_optional=tuple(sorted(deferred)),
            mandatory_preserved=True,
            l3_preserved=True,
            binding_limit_kind=(
                sample.budget_binding_kind()
                if readings[4].level is not PressureLevel.NORMAL
                else None
            ),
        )
        problems = assert_preservation(state)
        if problems:
            raise MandatoryWorkProtected("<evaluate>", "required_check")
        return state

    # -- 准入 -------------------------------------------------------------
    def admit(
        self,
        *,
        state: GovernorState,
        demand_mb: float,
        disk_needed_mb: float = 0.0,
        sample: ResourceSample | None = None,
    ) -> Admission:
        """裁决“现在能不能派发这个节点”。

        步骤：
          1. 暂停（硬阈值）→ 拒绝，reason 取第一条 PAUSE_DISPATCH 的原因；
          2. 槽位为 0 → 拒绝（`limit_kind=concurrency`）；
          3. 内存/磁盘需求超出剩余 → 拒绝（`limit_kind=memory/disk`）；
          4. 全部通过 → 允许，`slots_after = allowed_slots - 1`。

        注意：**硬阈值下永远不允许派发**（这是负例 NEG-M13-11 的判定点）。
        返回值只是裁决，真正扣减槽位由调用方完成（Governor 不持有执行状态）。
        """
        if demand_mb < 0.0 or disk_needed_mb < 0.0:
            raise ValueError("需求不得为负")
        if state.paused:
            pause_reasons = state.directive_for(GovernorAction.PAUSE_DISPATCH)
            reason = pause_reasons[0].reason if pause_reasons else "GOVERNOR_PAUSED"
            limit_kind = state.binding_limit_kind or _limit_kind_of(reason)
            return Admission(
                allowed=False,
                reason=reason,
                limit_kind=limit_kind,
                slots_after=0,
                detail="硬阈值未解除，不得派发任何新节点",
            )
        if state.allowed_slots <= 0:
            return Admission(
                allowed=False,
                reason="NO_CONCURRENCY_SLOT",
                limit_kind="concurrency",
                slots_after=0,
                detail="并发槽已用尽（上限 2，配置不得上调）",
            )
        if sample is not None:
            remaining_mb = max(0.0, sample.memory_budget_mb - sample.memory_used_mb)
            if demand_mb > remaining_mb:
                return Admission(
                    allowed=False,
                    reason="MEMORY_INSUFFICIENT",
                    limit_kind="memory",
                    slots_after=state.allowed_slots,
                    detail=f"需求 {demand_mb:.0f} MB > 剩余 {remaining_mb:.0f} MB",
                )
            if disk_needed_mb > sample.disk_free_mb:
                return Admission(
                    allowed=False,
                    reason="DISK_INSUFFICIENT",
                    limit_kind="disk",
                    slots_after=state.allowed_slots,
                    detail=f"需求 {disk_needed_mb:.0f} MB > 剩余 {sample.disk_free_mb:.0f} MB",
                )
        return Admission(
            allowed=True,
            reason="ADMITTED",
            slots_after=state.allowed_slots - 1,
            detail="资源与预算允许",
        )

    # -- 延后请求（唯一入口） ---------------------------------------------
    def request_deferral(self, work: ProtectedWork) -> None:
        """请求延后一件验证工作；受保护项一律拒绝。

        这个函数存在的意义：把“绝不取消必检与 L3”从**注释**变成**调用点**。
        任何延后路径都必须经过它，因此静态评审只需看这一个函数。
        """
        work.assert_deferrable()

    # -- 读数 -------------------------------------------------------------
    def _read_process(self, sample: ResourceSample) -> MonitorReading:
        threshold = float(self._thresholds.zombie_process_limit)
        level = PressureLevel.NORMAL
        if sample.runaway_trees > self._thresholds.runaway_tree_limit:
            level = PressureLevel.HARD
        elif sample.zombie_processes > self._thresholds.zombie_process_limit:
            level = PressureLevel.SOFT
        return MonitorReading(
            monitor=MonitorKind.PROCESS,
            level=level,
            observed=float(sample.zombie_processes + sample.runaway_trees),
            threshold=threshold,
            unit="count",
            note="未退出子进程树按 HARD 处理（残留会污染后续 attempt）",
        )

    def _read_disk(self, sample: ResourceSample) -> MonitorReading:
        watermark = self._thresholds.disk_watermark_mb
        soft_line = watermark * self._thresholds.disk_soft_factor
        if sample.disk_free_mb < watermark:
            level = PressureLevel.HARD
        elif sample.disk_free_mb < soft_line:
            level = PressureLevel.SOFT
        else:
            level = PressureLevel.NORMAL
        return MonitorReading(
            monitor=MonitorKind.DISK,
            level=level,
            observed=sample.disk_free_mb,
            threshold=watermark,
            unit="MiB",
            note=(
                f"软阈值 = 水位 × {self._thresholds.disk_soft_factor}；"
                "只允许清理临时缓存；证据与产物不得删除（8.6 / AGENTS §4）"
            ),
        )

    def _read_memory(self, sample: ResourceSample) -> MonitorReading:
        ratio = sample.memory_ratio()
        if ratio >= self._thresholds.memory_hard_ratio:
            level = PressureLevel.HARD
        elif ratio >= self._thresholds.memory_soft_ratio:
            level = PressureLevel.SOFT
        else:
            level = PressureLevel.NORMAL
        return MonitorReading(
            monitor=MonitorKind.MEMORY,
            level=level,
            observed=ratio,
            threshold=self._thresholds.memory_hard_ratio,
            unit="ratio",
            note=f"软阈值 {self._thresholds.memory_soft_ratio:.0%}；初始待校准值",
        )

    def _read_cpu(self, sample: ResourceSample) -> MonitorReading:
        sustained = (
            sample.cpu_ratio >= self._thresholds.cpu_sustained_ratio
            and sample.cpu_sustained_sec >= self._thresholds.cpu_sustained_window_sec
        )
        level = PressureLevel.SOFT if sustained else PressureLevel.NORMAL
        return MonitorReading(
            monitor=MonitorKind.CPU,
            level=level,
            observed=sample.cpu_ratio,
            threshold=self._thresholds.cpu_sustained_ratio,
            unit="ratio",
            note=(
                f"必须持续 ≥ {self._thresholds.cpu_sustained_window_sec:.0f}s 才触发；"
                "瞬时尖峰不降并发"
            ),
        )

    def _read_budget(self, sample: ResourceSample) -> MonitorReading:
        ratio = sample.budget_ratio()
        if ratio >= self._thresholds.budget_hard_ratio:
            level = PressureLevel.HARD
        elif ratio >= self._thresholds.budget_soft_ratio:
            level = PressureLevel.SOFT
        else:
            level = PressureLevel.NORMAL
        return MonitorReading(
            monitor=MonitorKind.BUDGET,
            level=level,
            observed=ratio,
            threshold=self._thresholds.budget_hard_ratio,
            unit="ratio",
            note="预算动作只允许换模板/模型与延后非关键验证；必检与 L3 保留",
        )

    # -- 汇总 -------------------------------------------------------------
    @staticmethod
    def _aggregate_level(readings: Sequence[MonitorReading]) -> PressureLevel:
        levels = [reading.level for reading in readings]
        if PressureLevel.HARD in levels:
            return PressureLevel.HARD
        if PressureLevel.SOFT in levels:
            return PressureLevel.SOFT
        return PressureLevel.NORMAL

    def _reduced_slots(self, level: PressureLevel) -> int:
        """软压力下调 1 个槽；下限 1；上限仍受契约硬上限 2 约束。"""
        if level is PressureLevel.NORMAL:
            return self._thresholds.max_concurrency
        return max(CONCURRENCY_FLOOR, self._thresholds.max_concurrency - 1)


def _limit_kind_of(reason: str) -> str | None:
    """把治理原因映射到 M03 `LimitKind`（用于 `RESOURCE_BUDGET_EXCEEDED.detail.limit_kind`）。"""
    mapping = {
        "MEMORY_HARD_LIMIT": "memory",
        "DISK_BELOW_WATERMARK": "disk",
        "BUDGET_EXHAUSTED": "token",
        "BUDGET_HARD_LIMIT": "token",
        "NO_CONCURRENCY_SLOT": "concurrency",
    }
    return mapping.get(reason)


# ---------------------------------------------------------------------------
# 5. 自检（验收判据 2 的落点：动作与「绝不取消 L3」在代码里可见）
# ---------------------------------------------------------------------------
def assert_no_state_change() -> list[str]:
    """自检：Governor 不能改状态。

    检查项：
      1. `GovernorDirective.state_change` 是 `ClassVar[None]`，实例上没有该属性；
      2. `Governor` 的公开面没有 `transition` / `set_state` / `mark_*` / `update_state`；
      3. 模块内不出现 `StateMachine` / `TransitionPort` 的引用。
    """
    problems: list[str] = []
    instance_fields = {f.name for f in dataclass_fields(GovernorDirective)}
    if "state_change" in instance_fields:
        problems.append("state_change 不得是实例字段（只能是 ClassVar[None]）")
    if getattr(GovernorDirective, "state_change", "missing") is not None:
        problems.append("state_change 必须恒为 None")
    for forbidden in ("transition", "set_state", "update_state", "mark_verified", "mark_failed"):
        if hasattr(Governor, forbidden):
            problems.append(f"Governor 不得暴露 {forbidden}()")
    for key in ("machine", "state_machine", "repository", "conn"):
        if hasattr(Governor, key):
            problems.append(f"Governor 不得持有 {key}")
    return problems


def assert_no_forbidden_action() -> list[str]:
    """自检：动作枚举里不得出现取消/跳过/直改状态的成员名。"""
    problems: list[str] = []
    for member in GovernorAction:
        upper = member.name.upper()
        for forbidden in FORBIDDEN_ACTIONS:
            if forbidden in upper:
                problems.append(f"动作 {member.name} 命中禁名 {forbidden}")
    if len(GovernorAction) != 5:
        problems.append(f"动作必须恰好 5 个，实际 {len(GovernorAction)}")
    return problems


def assert_preservation(state: GovernorState) -> list[str]:
    """自检：一次评估输出里，必检项与 L3 都没有被取消/延后。

    检查项：
      1. `mandatory_preserved` 与 `l3_preserved` 必须为 True；
      2. 延后集合里不得出现 `required_check` / `l3_replay` 前缀的 work_id
         （`work_id` 由 Gate/Verifier 的 check_id 生成，这两类前缀属保留命名）；
      3. 指令集合里不得出现取消类动作（由 `assert_no_forbidden_action` 保证）。
    """
    problems: list[str] = []
    if not state.mandatory_preserved:
        problems.append("必检项被标记为未保留")
    if not state.l3_preserved:
        problems.append("L3 被标记为未保留")
    for work_id in state.deferred_optional:
        lowered = work_id.lower()
        if lowered.startswith("required:") or lowered.startswith("l3:"):
            problems.append(f"延后集合中出现受保护工作 {work_id!r}")
    return problems


def assert_thresholds_configurable() -> list[str]:
    """自检：阈值全部可配置、没有写死成“最优值”。

    检查项：
      1. `FOOTPRINT_KEYS` 与 `GovernorThresholds` 的字段一一对应；
      2. `thresholds_from_config({})` 必须抛 `CONFIG_MISSING_KEY`（不存在默认值回退）；
      3. `PROPOSED_INITIAL_THRESHOLDS` 只用于模板，键集合与 `FOOTPRINT_KEYS` 相同。
    """
    problems: list[str] = []
    fields = {
        name for name in GovernorThresholds.__dataclass_fields__ if name != "max_concurrency"
    }
    if set(FOOTPRINT_KEYS) != fields | {"max_concurrency"}:
        problems.append("FOOTPRINT_KEYS 与 GovernorThresholds 字段不一致")
    if set(PROPOSED_INITIAL_THRESHOLDS) != set(FOOTPRINT_KEYS):
        problems.append("提议值键集合与配置键不一致")
    try:
        thresholds_from_config({})
    except ScoringConfigInvalid as exc:
        if exc.code != "CONFIG_MISSING_KEY":
            problems.append(f"缺键应报 CONFIG_MISSING_KEY，实际 {exc.code}")
    else:
        problems.append("缺键竟然装载成功（存在隐式默认阈值）")
    return problems