"""M03 · config/limits.py — 资源上限结构与超限动作（P1 伪代码）。

阶段：P1｜状态：上限分类、硬上限、超限动作、计量点；**不实现执行器/调度器**。

来源：NFR-06（token/并发/内存/CPU/磁盘/时长有配置上限）、05 §2.1（max_workers 1–2、
wall_time_sec>0、max_memory_mb>0）、07 WP-06（超时/资源采集/进程树回收）、
06 §4.1（POST /verify 429 预算不足）、06 §4.5（非幂等操作不自动重试）。

设计要点：
  1. 超限统一用 `RESOURCE_BUDGET_EXCEEDED`（附录 E.3），子类用 `detail.limit_kind` 区分；
     **不得**另开 LIMIT_* 错误码（errors.py 已登记该纪律）。
  2. 唯一**契约硬上限**是并发 2；其余上限来自配置，缺键即拒绝启动（见 schemas.py）。
  3. 超限不是“重试一下就好”：重试只会重复消耗；必须先降并发/缩任务/补预算。
  4. 任何超限都必须留证据或审计；不得只写一行日志就继续。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "CONCURRENCY_HARD_CAP",
    "ENFORCEMENT_PRECEDENCE",
    "LIMITS",
    "MEASUREMENTS",
    "LimitKind",
    "LimitSpec",
    "ResolvedLimits",
    "Unit",
    "exceeded",
]


class LimitKind(StrEnum):
    TOKEN = "token"
    WALL_CLOCK = "wall_clock"
    CONCURRENCY = "concurrency"
    MEMORY = "memory"
    DISK = "disk"
    RETRY = "retry"


class Unit(StrEnum):
    TOKEN = "token"
    SECOND = "sec"
    COUNT = "count"
    MIB = "MiB"


CONCURRENCY_HARD_CAP: Final[int] = 2  # 第一版；实测通过前不得宣称已达成


@dataclass(frozen=True, slots=True)
class LimitSpec:
    kind: LimitKind
    scope: str                 # task / node / worker / verify
    unit: Unit
    config_keys: tuple[str, ...]      # 值来自 configs/*.yaml 的哪些键（无默认）
    hard_cap: int | None              # 契约/第一版硬上限；None = 仅受配置约束
    exceed_action: str
    process_action: str
    durable_record: str               # 超限后必须留下的记录位置
    retry_after_exceed: str
    note: str


LIMITS: Final[Mapping[LimitKind, LimitSpec]] = MappingProxyType(
    {
        LimitKind.TOKEN: LimitSpec(
            kind=LimitKind.TOKEN,
            scope="task",
            unit=Unit.TOKEN,
            config_keys=("limits.yaml: token_budget_per_task",),
            hard_cap=None,
            exceed_action="终止当前 LLM/Agent 调用并拒绝后续派发；API 侧返回 429 RESOURCE_BUDGET_EXCEEDED",
            process_action="不杀已完成的 worker；不再派发新 worker；T0 无 LLM 时 token 恒为 0，任何消耗即超限",
            durable_record="audit_log(reason_code=TOKEN_BUDGET_EXCEEDED) + E1/E2 用量摘要",
            retry_after_exceed="仅提高预算或缩小任务后重跑；不得原样重试",
            note="T1 接入 Agent 后才有真实消耗；T0 只保留结构与 0 值路径。",
        ),
        LimitKind.WALL_CLOCK: LimitSpec(
            kind=LimitKind.WALL_CLOCK,
            scope="node",
            unit=Unit.SECOND,
            config_keys=("limits.yaml: wall_clock_sec_per_node", "limits.yaml: wall_clock_sec_per_task"),
            hard_cap=None,
            exceed_action="终止进程树 → 产生 E2 executor_process_exit（非零/超时标记）→ 节点按 retry_policy 决定重试或 FAILED",
            process_action="先请求退出，宽限后强杀整棵进程树（Windows Job Object）；不得只杀父进程",
            durable_record="E2 executor_process_exit + 资源峰值 + audit_log(reason_code=WALL_CLOCK_EXCEEDED)",
            retry_after_exceed="按 retry_policy 重试；每次重试必须新 attempt_id",
            note="任务级上限触发时终止全部 worker，任务 FAILED/BLOCKED。",
        ),
        LimitKind.CONCURRENCY: LimitSpec(
            kind=LimitKind.CONCURRENCY,
            scope="task",
            unit=Unit.COUNT,
            config_keys=("limits.yaml: max_workers", "scheduler.yaml: max_workers"),
            hard_cap=CONCURRENCY_HARD_CAP,
            exceed_action="拒绝派发（排队或 429）；**绝不**把并发提到 3 来“缓解”排队",
            process_action="不得通过多开进程绕过；两处配置必须一致",
            durable_record="调度审计 + 队列深度指标",
            retry_after_exceed="等待槽位；或降低单任务并发后重跑",
            note="配置 >2 在加载期即 CONFIG_VALUE_OUT_OF_RANGE；运行期永不超过硬上限。",
        ),
        LimitKind.MEMORY: LimitSpec(
            kind=LimitKind.MEMORY,
            scope="worker",
            unit=Unit.MIB,
            config_keys=("limits.yaml: max_memory_mb_per_worker",),
            hard_cap=None,
            exceed_action="终止该 worker 并记录峰值；节点 FAILED；继续派发前检查整机水位",
            process_action="回收进程树；不得依赖 GC 或交换区“再撑一会”",
            durable_record="E2 资源峰值 + audit_log(reason_code=MEMORY_LIMIT_EXCEEDED)",
            retry_after_exceed="降内存/缩数据后重试；重复 OOM 必须 BLOCKED 而不是无限重试",
            note="整机 16GB；并发 2 时必须预留系统与工作台内存。",
        ),
        LimitKind.DISK: LimitSpec(
            kind=LimitKind.DISK,
            scope="task",
            unit=Unit.MIB,
            config_keys=("limits.yaml: disk_quota_mb_per_task", "scheduler.yaml: disk_watermark_mb"),
            hard_cap=None,
            exceed_action="停止写入 → 节点 BLOCKED 并保留现场；不得删除证据/产物来腾空间",
            process_action="终止正在写产物的 worker；关闭文件句柄后复核产物哈希",
            durable_record="audit_log(reason_code=DISK_QUOTA_EXCEEDED) + 产物清单快照",
            retry_after_exceed="清理**非证据**临时文件或扩容后重跑；证据与审计不得删除",
            note="低于 disk_watermark 时不再接受新任务。",
        ),
        LimitKind.RETRY: LimitSpec(
            kind=LimitKind.RETRY,
            scope="node",
            unit=Unit.COUNT,
            config_keys=("limits.yaml: max_attempts_cap", "limits.yaml: backoff_sec_cap"),
            hard_cap=None,
            exceed_action="节点 FAILED（不是 429）；写审计并进入 T0 不可恢复的失败分支",
            process_action="最后一次 attempt 结束事件必须先落库，再判 FAILED",
            durable_record="audit_log(reason_code=RETRY_EXHAUSTED) + 每次 attempt 的 E2 记录",
            retry_after_exceed="不得自动再试；T0 无 POST /recover；T1 走恢复计划",
            note="max_attempts 含首次；T0 模板默认 2 属模板注册表约束，不是契约上限。",
        ),
    }
)

# 同时触发时的判定顺序（先硬后软；先不可逆后可逆）。
# 依据：磁盘/内存破坏现场且不可回滚，必须先判；token 与 retry 只影响预算与次数。
ENFORCEMENT_PRECEDENCE: Final[tuple[LimitKind, ...]] = (
    LimitKind.DISK,
    LimitKind.MEMORY,
    LimitKind.WALL_CLOCK,
    LimitKind.CONCURRENCY,
    LimitKind.TOKEN,
    LimitKind.RETRY,
)

MEASUREMENTS: Final[tuple[str, ...]] = (
    "peak_memory_mb（per worker）",
    "wall_time_sec（per node / per task）",
    "disk_bytes_written（per task）",
    "tokens_used（per task；T0 恒 0）",
    "concurrent_workers（峰值）",
    "attempts（per node）",
)


@dataclass(frozen=True, slots=True)
class ResolvedLimits:
    """启动时装配后的上限值（全部来自显式配置，无默认）。"""

    max_workers: int
    wall_clock_sec_per_task: int
    wall_clock_sec_per_node: int
    max_memory_mb_per_worker: int
    disk_quota_mb_per_task: int
    token_budget_per_task: int
    max_attempts_cap: int
    backoff_sec_cap: float
    verify_budget_sec: int


def exceeded(kind: LimitKind, observed: float, limit: float) -> None:
    """超限判定与抛出（P1 只定义契约，不实现）。

    规则：
      - `observed > limit` → 抛 RESOURCE_BUDGET_EXCEEDED，`detail.limit_kind = kind.value`；
      - 等于上限不算超限（闭区间上界）；
      - 负数/非有限观测值属于采集错误，不得当成“未超限”；
      - 任何分支都不得静默返回。
    """
    raise NotImplementedError("P1 伪代码：超限执行属 Executor/Governor 落地阶段")