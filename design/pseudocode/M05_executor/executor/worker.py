"""M05 · executor/worker.py — `run_attempt()` 主流程（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-004（受控执行）、FR-005（E2 来自真实受控执行）
依赖：M05 registry / workspace / process_control / template_protocol、M03 limits、M01 encoding
不变量：只执行不裁决；不写状态、不写证据、不写数据库；attempt_id 每次唯一；产物哈希由 Executor 算
错误码：TOOL_NOT_ALLOWLISTED（未注册模板）、SCHEMA_INVALID（参数/产物形态）、
        RESOURCE_BUDGET_EXCEEDED（429，超时/内存/磁盘）；其余为内部故障 → 结构化事件
写入者：工作目录（inputs/artifacts/logs）；**不写** tasks/nodes/evidence/audit_log
状态：伪代码；不启动进程、不写文件、不跑模板

## `run_attempt` 的十步（顺序不可交换）

   1. preflight：模板已注册、节点类型匹配、参数合 Schema、`parameters_hash` 对得上、
      `attempt_id` 形态合法且**未被用过**；
   2. 计算生效上限：`min(模板上限, 任务上限, 配置上限)`；
   3. 建 attempt 目录（已存在 = attempt_id 复用 = 安全事件，拒绝）；
   4. 原子写 `inputs/params.json` 与 `inputs/attempt.json`；
   5. 向 Collector 记录 `executor_launch`（**记不了就不启动**：没有 E2 的“启动”不可审计）；
   6. 启动子进程（CREATE_SUSPENDED → 作业对象 → Resume）；
   7. 采样（墙钟/峰值内存/磁盘），直到退出、超时或取消；
   8. 超时/取消 → `terminate_tree()`；回收失败走“失败也回收”分支并升级；
   9. 收产物：遍历声明、二进制读、算 SHA-256 与字节数、拒绝未声明/越界/链接；
  10. 向 Collector 记录 `executor_process_exit`（+ 每条产物 `artifact_observed`），返回 `AttemptOutcome`。

## 明确不做（与 AGENTS §4 一致）

  | 东西 | 谁做 | 本文件 |
  |---|---|---|
  | 判定 PASS/FAIL | Gate / Verifier | ❌ 结构上没有 verdict 字段 |
  | 写 `nodes.state` / `tasks.state` | StateMachine | ❌ 不持有仓储，无 transition 调用 |
  | 写 `evidence` 行 | Collector（E2）/ Verifier（E3） | ❌ 只提交事件草稿 |
  | 写 `audit_log` | StateMachine | ❌ 不写 |
  | 决定重试/退避 | Scheduler/Orchestrator | ❌ 只返回“这次 attempt 发生了什么” |
  | 选模板/选节点 | Builder/Scheduler | ❌ 入参已给定 |

## 为什么“记不了 launch 就不启动”

  E2 的定义是“真实受控执行的观测”，而 Collector 是 E2 的唯一写入者（05 §4.5）。
  如果先跑后记，写链失败就会出现“跑过但没有 launch 证据”的 attempt；
  这种 attempt 既不能进 VERIFYING（守卫要 attempt 结束事实），也不能被 Gate 采信，
  只能靠重启恢复判 FAILED —— 把可预防的失败变成不可解释的状态。
  因此这里选择前置：写不了 launch，就不启动，直接返回 `COLLECTOR_UNAVAILABLE`。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final, Mapping, Protocol, Sequence

from .process_control import (
    ProcessLaunchSpec,
    ReclaimReport,
    ResourceSample,
    RunningProcess,
)
from .registry import TemplateRegistration
from .template_protocol import ArtifactDeclaration
from .workspace import AttemptWorkspace, WorkspaceLayout, WorkspacePolicy

__all__ = [
    "ATTEMPT_EVENT_KINDS",
    "EXECUTOR_BOUNDARY",
    "ArtifactManifest",
    "ArtifactRecord",
    "AttemptDisposition",
    "AttemptOutcome",
    "AttemptRequest",
    "ClockPort",
    "CollectorPort",
    "EffectiveLimits",
    "EventDraft",
    "ExecutorFault",
    "ExecutorInternalError",
    "ProcessControlPort",
    "WorkspaceFactoryPort",
    "assert_executor_boundary",
    "run_attempt",
]

# 只允许这三个 kind（05 §4.5 的 7 值里与本模块相关的子集）。不得新增。
ATTEMPT_EVENT_KINDS: Final[tuple[str, ...]] = (
    "executor_launch",
    "executor_process_exit",
    "artifact_observed",
)

EXECUTOR_BOUNDARY: Final[tuple[str, ...]] = (
    "只执行：不判定成功/AI 结果是否成立。",
    "不写状态：不持有仓储、不调用 StateMachine.transition。",
    "不写证据：只向 Collector 提交 EventDraft；event_seq/chain_hash 由 Collector 分配。",
    "不写审计：audit_log 的唯一写者是 StateMachine。",
    "产物哈希由 Executor 计算（二进制读），不接受模板自报。",
    "每次真实执行一个 attempt_id；重试必须新 ID，目录不覆盖。",
)


# ---------------------------------------------------------------------------
# 1. 故障与处置
# ---------------------------------------------------------------------------
class ExecutorFault(StrEnum):
    """执行器内部故障码（**不是**注册表错误码）。

    只有三种情况会映射到已注册码（见各类 `error_code`）：
    未注册模板、参数/产物形态非法、资源超限。其余只出结构化事件 + 日志 + 升级。
    """

    TEMPLATE_NOT_REGISTERED = "TEMPLATE_NOT_REGISTERED"
    NODE_TYPE_MISMATCH = "NODE_TYPE_MISMATCH"
    PARAM_SCHEMA_VIOLATION = "PARAM_SCHEMA_VIOLATION"
    PARAMS_HASH_MISMATCH = "PARAMS_HASH_MISMATCH"
    ATTEMPT_ID_REUSED = "ATTEMPT_ID_REUSED"
    WORKSPACE_ESCAPE = "WORKSPACE_ESCAPE"
    WORKSPACE_NOT_WRITABLE = "WORKSPACE_NOT_WRITABLE"
    ISOLATION_UNAVAILABLE = "PROCESS_ISOLATION_UNAVAILABLE"
    LAUNCH_FAILED = "PROCESS_LAUNCH_FAILED"
    WAIT_FAILED = "PROCESS_WAIT_FAILED"
    TIMED_OUT = "WALL_CLOCK_EXCEEDED"
    TREE_KILL_FAILED = "PROCESS_TREE_KILL_FAILED"
    RESIDUAL_PROCESSES = "PROCESS_RESIDUAL_PROCESSES"
    ARTIFACT_UNDECLARED = "ARTIFACT_UNDECLARED"
    ARTIFACT_OUTSIDE = "ARTIFACT_OUTSIDE_WORKSPACE"
    ARTIFACT_TOO_MANY = "ARTIFACT_TOO_MANY"
    ARTIFACT_TOO_LARGE = "ARTIFACT_TOO_LARGE"
    ARTIFACT_HASH_FAILED = "ARTIFACT_HASH_FAILED"
    COLLECTOR_UNAVAILABLE = "COLLECTOR_UNAVAILABLE"
    SAMPLING_FAILED = "SAMPLING_FAILED"
    CANCELLED = "EXECUTION_CANCELLED"


class AttemptDisposition(StrEnum):
    """一次 attempt 的**事实分类**（不是裁决）。

    `EXITED` 只说明进程退出了，`exit_code` 是几就是几 —— 0 也不代表研究结论成立。
    """

    EXITED = "EXITED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    LAUNCH_FAILED = "LAUNCH_FAILED"
    TEMPLATE_ERROR = "TEMPLATE_ERROR"        # 子进程非 0 退出（模板自己报错）
    ARTIFACT_ERROR = "ARTIFACT_ERROR"        # 产物缺失/未声明/越界/哈希失败
    RECLAIM_FAILED = "RECLAIM_FAILED"        # 进程树回收失败（最高优先级：必须先处置）
    WORKSPACE_ERROR = "WORKSPACE_ERROR"
    PRECHECK_FAILED = "PRECHECK_FAILED"


class ExecutorInternalError(RuntimeError):
    """内部故障：带 `fault`；只有 allow-listed 的情形带注册表 `error_code`。"""

    def __init__(self, fault: ExecutorFault, detail: str, *, error_code: str | None = None) -> None:
        self.fault = fault
        self.detail = detail
        self.error_code = error_code
        suffix = f"/{error_code}" if error_code else ""
        super().__init__(f"{fault.value}{suffix}：{detail}")


# ---------------------------------------------------------------------------
# 2. 请求与端口
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EffectiveLimits:
    """生效上限 = 三方最小值。构造时校验，避免“配置 0 秒超时”。"""

    wall_time_sec: int
    memory_mb: int
    disk_mb: int
    max_attempts: int
    grace_sec: float = 5.0

    def __post_init__(self) -> None:
        for name in ("wall_time_sec", "memory_mb", "disk_mb", "max_attempts"):
            if getattr(self, name) < 1:
                raise ValueError(f"EffectiveLimits.{name} 必须 ≥ 1")

    @classmethod
    def combine(
        cls,
        *,
        template_wall: int, template_mem: int, template_disk: int, template_attempts: int,
        task_wall: int, task_mem: int, task_disk: int, task_attempts: int,
        grace_sec: float = 5.0,
    ) -> "EffectiveLimits":
        return cls(
            wall_time_sec=min(template_wall, task_wall),
            memory_mb=min(template_mem, task_mem),
            disk_mb=min(template_disk, task_disk),
            max_attempts=min(template_attempts, task_attempts),
            grace_sec=grace_sec,
        )


class ClockPort(Protocol):
    def now(self) -> object:
        """返回带时区 datetime；UTC 格式化由调用方用 M02 `format_utc`。"""
        ...


class CollectorPort(Protocol):
    """Collector 的写入口（E2 唯一写者）。**只有** record 与两个只读探测。"""

    def record(self, event: "EventDraft") -> str:
        """追加一条事件，返回 `evidence_id`；失败必须抛（调用方 fail-closed）。"""
        ...

    def has_launch(self, *, task_id: str, node_id: str, attempt_id: str) -> bool:
        """该 attempt 是否已有 launch 事件（用于 attempt_id 复用检测）。"""
        ...

    def has_exit(self, *, task_id: str, node_id: str, attempt_id: str) -> bool:
        ...


class WorkspaceFactoryPort(Protocol):
    def create(self, layout: WorkspaceLayout, *, created_at: str) -> AttemptWorkspace:
        ...


class ProcessControlPort(Protocol):
    def start(self, spec: ProcessLaunchSpec) -> RunningProcess:
        ...

    def wait(self, proc: RunningProcess, *, timeout_sec: float) -> int | None:
        ...

    def terminate_tree(self, proc: RunningProcess, *, reason: str) -> ReclaimReport:
        ...

    def sample(self, proc: RunningProcess) -> ResourceSample:
        ...


@dataclass(frozen=True, slots=True)
class EventDraft:
    """交给 Collector 的事件草稿。

    **刻意没有** `event_seq` / `prev_hash` / `chain_hash` / `level`：
    序号与哈希链由 Collector 分配（05 §4.1、I-11 之外的单写队列）。
    本类若出现这些字段，就等于 Executor 在自造证据链。
    """

    kind: str
    task_id: str
    node_id: str
    attempt_id: str
    observed_at: str                 # UTC 27 字符
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.kind not in ATTEMPT_EVENT_KINDS:
            raise ValueError(f"未登记的事件类型 {self.kind!r}（只允许 {ATTEMPT_EVENT_KINDS}）")
        if not self.attempt_id.startswith("attempt_"):
            raise ValueError("attempt_id 必须以 attempt_ 开头")


@dataclass(frozen=True, slots=True)
class AttemptRequest:
    """一次 attempt 的完整输入。**没有** 仓储、没有 machine、没有 verifier 句柄。"""

    task_id: str
    node_id: str
    attempt_id: str
    attempt_seq: int
    registration: TemplateRegistration
    params: Mapping[str, object]
    parameters_hash: str
    limits: EffectiveLimits
    python_exe: str                  # 部署注入的绝对路径（项目 3.11.16 / .venv）
    workspace: WorkspacePolicy
    correlation_id: str

    def __post_init__(self) -> None:
        if self.attempt_seq < 1:
            raise ValueError("attempt_seq 必须 ≥ 1（READY→RUNNING 时递增）")
        if not self.attempt_id.startswith("attempt_"):
            raise ValueError("attempt_id 形态非法")
        if not self.python_exe or not os.path.isabs(self.python_exe):
            raise ValueError("python_exe 必须是绝对路径")


# ---------------------------------------------------------------------------
# 3. 产物清单
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """产物清单的一行。

    验收要求四项齐全：`relative_path` + `sha256` + `size_bytes` + `attempt_id`。
    `sha256` 由 Executor 二进制读计算；模板**无权**提供。
    """

    relative_path: str
    sha256: str
    size_bytes: int
    attempt_id: str
    declared_name: str
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        rel = self.relative_path.replace("\\", "/")
        if rel.startswith("/") or ".." in rel.split("/") or ":" in rel:
            raise ValueError(f"产物相对路径非法：{self.relative_path!r}")
        if not rel.startswith("artifacts/"):
            raise ValueError("产物必须位于 artifacts/ 下")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("sha256 必须是 64 位小写十六进制")
        if self.size_bytes < 0:
            raise ValueError("size_bytes 不得为负")
        if not self.attempt_id.startswith("attempt_"):
            raise ValueError("产物记录必须带产生它的 attempt_id")


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """一次 attempt 的完整产物清单（确定性排序 + 可复算摘要）。"""

    attempt_id: str
    records: tuple[ArtifactRecord, ...]

    def __post_init__(self) -> None:
        if any(r.attempt_id != self.attempt_id for r in self.records):
            raise ValueError("清单内所有产物必须来自同一个 attempt_id")
        paths = [r.relative_path for r in self.records]
        if len(set(paths)) != len(paths):
            raise ValueError("产物路径重复")

    @property
    def total_bytes(self) -> int:
        return sum(r.size_bytes for r in self.records)

    def as_payload(self) -> Mapping[str, object]:
        """写进 `artifact_observed` 事件与产物清单文件的 payload。"""
        return MappingProxyType({
            "attempt_id": self.attempt_id,
            "artifacts": [
                {
                    "relative_path": r.relative_path,
                    "sha256": r.sha256,
                    "size_bytes": r.size_bytes,
                    "attempt_id": r.attempt_id,
                    "declared_name": r.declared_name,
                    "media_type": r.media_type,
                }
                for r in sorted(self.records, key=lambda r: r.relative_path)
            ],
            "count": len(self.records),
            "total_bytes": self.total_bytes,
        })

    def digest(self) -> str:
        """清单摘要：`sha256(JCS(as_payload()))`（排序后，跨机器稳定）。

        纪律：JCS 必须由 M01 `canonical_bytes` 提供；**不得**用
        `json.dumps(sort_keys=True)` 冒充（ENCODING_RULES §5：码点序 ≠ UTF-16 码元序）。
        """
        # LIB: researchflow.contracts.encoding.canonical_bytes + hashlib.sha256
        raise NotImplementedError("P3 伪代码：清单摘要由 M01 encoding.canonical_bytes 落地")


# ---------------------------------------------------------------------------
# 4. 结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """一次 attempt 的**执行事实**。

    结构上没有 verdict：`VERDICT` 恒为 `None`，且类里没有 `passed`/`success`/`status` 字段。
    上层若需要“是否通过”，必须走 Gate/Verifier，不得从本对象推断。
    """

    VERDICT: ClassVar[None] = None   # 结构性声明：执行结果不携带裁决（不是实例字段）

    task_id: str
    node_id: str
    attempt_id: str
    attempt_seq: int
    disposition: AttemptDisposition
    exit_code: int | None
    timed_out: bool
    wall_time_sec: float
    peak_memory_mb: int | None
    artifacts: ArtifactManifest | None
    reclaim: ReclaimReport | None
    fault: ExecutorFault | None
    fault_detail: str
    sample_failures: int
    evidence_ids: tuple[str, ...]
    escalation_required: bool

    def __post_init__(self) -> None:
        if self.disposition is AttemptDisposition.EXITED and self.exit_code is None:
            raise ValueError("EXITED 必须带 exit_code")
        if self.disposition in (AttemptDisposition.TIMED_OUT, AttemptDisposition.RECLAIM_FAILED):
            if self.exit_code is not None:
                raise ValueError(f"{self.disposition} 不得带 exit_code（不得表达为正常退出）")
        if self.disposition is AttemptDisposition.RECLAIM_FAILED and not self.escalation_required:
            raise ValueError("回收失败必须 escalation_required=True")
        if self.artifacts is not None and self.artifacts.attempt_id != self.attempt_id:
            raise ValueError("清单 attempt_id 与本次 attempt 不一致")
        if self.sample_failures < 0:
            raise ValueError("sample_failures 不得为负")

    @property
    def requires_human_attention(self) -> bool:
        return self.escalation_required or self.disposition is AttemptDisposition.RECLAIM_FAILED

    def summary_fields(self) -> Mapping[str, object]:
        """可安全写日志/事件的字段（无绝对路径、无命令行、无环境变量）。"""
        return MappingProxyType({
            "task_id": self.task_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "attempt_seq": self.attempt_seq,
            "disposition": self.disposition.value,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "wall_time_sec": round(self.wall_time_sec, 3),
            "artifact_count": len(self.artifacts.records) if self.artifacts else 0,
            "escalation_required": self.escalation_required,
            "fault": self.fault.value if self.fault else None,
        })


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------
def run_attempt(
    request: AttemptRequest,
    *,
    collector: CollectorPort,
    workspace_factory: WorkspaceFactoryPort,
    processes: ProcessControlPort,
    clock: ClockPort,
    is_cancelled: "CancellationPort | None" = None,
) -> AttemptOutcome:
    """执行一次 attempt 并返回事实；**不写状态、不写证据、不裁决**。

    这个函数是“执行”这件事的全部入口；它接受的依赖里没有仓储、没有 StateMachine、
    没有 Verifier，因此“Executor 顺手写状态/证据”在结构上不可达。

    关键不变量：
      - `request.attempt_id` 已由 Orchestrator 在 `READY→RUNNING` 时分配（attempt_seq +1）；
      - 每个真实执行一个 ID；本函数**不生成** attempt_id（生成器不在执行器里）；
      - 任何分支都必须留下事件或明确故障，不允许“静默返回一个看起来正常的 outcome”。
    """
    # 落地阶段的步骤骨架（编号与 docstring 十步一一对应）：
    # 1)  preflight：
    #       registration = registry.resolve_for(request.registration.template_id, node_type)
    #       violations = schema.validate(request.params)
    #       hash_payload(request.params) == request.parameters_hash
    #       collector.has_launch(...) → True 则 fault=ATTEMPT_ID_REUSED（拒绝，不复用目录）
    # 2)  limits = EffectiveLimits.combine(...)
    # 3)  attempt = workspace_factory.create(layout, created_at=now)
    # 4)  attempt.write_text_atomic("inputs/params.json", jcs_text(params))
    #       attempt.write_text_atomic("inputs/attempt.json", attempt_meta_text)
    # 5)  collector.record(EventDraft(kind="executor_launch", payload={...}))
    #       —— 失败 → COLLECTOR_UNAVAILABLE，**不启动**
    # 6)  proc = processes.start(build_launch_spec(...))
    # 7)  采样循环（线程）：elapsed/peak_mem/disk；is_cancelled() → 走 8 的 CANCELLED
    # 8)  exit_code = processes.wait(proc, timeout_sec=limits.wall_time_sec)
    #       超时/取消 → report = processes.terminate_tree(...)；
    #       report.ok=False → disposition=RECLAIM_FAILED, escalation_required=True（先处置）
    # 9)  manifest = _collect_artifacts(attempt, declarations, limits)
    # 10) collector.record(executor_process_exit) + 每条 artifact_observed
    #       → AttemptOutcome(...)
    #
    # 落地纪律：上面每一步都必须落“事件或故障”，不允许只有 return 没有记录。
    raise NotImplementedError("P3 伪代码：run_attempt 由 WP-06 落地")


class CancellationPort(Protocol):
    """取消信号（来源：API 取消/任务级墙钟超限）。只读一个布尔。"""

    def is_cancelled(self) -> bool:
        ...


# ---------------------------------------------------------------------------
# 6. 产物收集（算法写清；实现属 WP-06）
# ---------------------------------------------------------------------------
def _collect_artifacts(
    *,
    workspace: AttemptWorkspace,
    declarations: Sequence[ArtifactDeclaration],
    max_artifacts: int,
    max_total_bytes: int,
) -> ArtifactManifest:
    """按声明收产物，逐条计算 SHA-256 与字节数。

    步骤：
      1. 声明数 > `max_artifacts` → `ARTIFACT_TOO_MANY`；
      2. 每条声明过 `workspace.resolve_inside`（相对 `artifacts/`）；
         命中绝对路径/`..`/ADS/链接 → `ARTIFACT_OUTSIDE`；
      3. `os.lstat`：必须是普通文件（拒绝符号链接/目录/设备）；
         不存在 → `ARTIFACT_UNDECLARED` 的反面：**声明了却没写** → `ARTIFACT_HASH_FAILED`
         （用同一个 fault 不够精确，落地时加 `ARTIFACT_MISSING` 子码；见 OQ-P3-07）；
      4. 逐个二进制读并增量 SHA-256（`open(path, "rb")`，分块）；
         累计字节 > `max_total_bytes` → `ARTIFACT_TOO_LARGE`；
      5. 扫 `artifacts/` 下实际文件集合，与声明集合比对：
         出现未声明文件 → `ARTIFACT_UNDECLARED`（不静默纳入）；
      6. 记录按 `relative_path` 排序，构造 `ArtifactManifest`。

    失败语义：任一步失败都返回 `ARTIFACT_ERROR` 的 disposition，
    **已成功的记录不写进清单**（半套清单比没有清单更危险）。
    """
    raise NotImplementedError("P3 伪代码：产物收集由 WP-06 落地")


# ---------------------------------------------------------------------------
# 7. 自检
# ---------------------------------------------------------------------------
FORBIDDEN_EXECUTOR_SURFACE: Final[tuple[str, ...]] = (
    "transition", "update_state", "set_state", "insert_evidence", "append_evidence",
    "write_audit", "verdict", "passed", "success", "status",
)


def assert_executor_boundary() -> list[str]:
    """自检：执行器不得出现状态/证据/审计写入或裁决字段。

    检查项：
      1. `AttemptOutcome` 的字段名不得含 `FORBIDDEN_EXECUTOR_SURFACE` 中任一项；
      2. 本模块公开面不得有 `transition`/`insert_*` 之类的方法；
      3. `EventDraft` 不得含 `event_seq`/`chain_hash`/`prev_hash`/`level`；
      4. `ATTEMPT_EVENT_KINDS` 必须恰为三个已冻结 kind 的子集。
    返回违反项（空 = 通过）。
    """
    problems: list[str] = []
    outcome_fields = set(AttemptOutcome.__dataclass_fields__)
    for name in FORBIDDEN_EXECUTOR_SURFACE:
        if name in outcome_fields:
            problems.append(f"AttemptOutcome 不得有 {name} 字段（执行器不裁决、不写状态）")
    draft_fields = set(EventDraft.__dataclass_fields__)
    for name in ("event_seq", "chain_hash", "prev_hash", "level"):
        if name in draft_fields:
            problems.append(f"EventDraft 不得有 {name}（证据链字段由 Collector 分配）")
    for kind in ATTEMPT_EVENT_KINDS:
        if kind not in ("executor_launch", "executor_process_exit", "artifact_observed"):
            problems.append(f"事件类型 {kind!r} 不在 05 §4.5 冻结集合内")
    if len(ATTEMPT_EVENT_KINDS) != len(set(ATTEMPT_EVENT_KINDS)):
        problems.append("ATTEMPT_EVENT_KINDS 有重复项")
    return problems


# 便于评审：本文件里出现的所有“外部事实来源”，逐条标注谁写。
FACT_OWNERSHIP: Final[Mapping[str, str]] = MappingProxyType(
    {
        "attempt_id": "Orchestrator 在 READY→RUNNING 时按 attempt_seq 生成（M01 new_attempt_id）",
        "exit_code": "操作系统/进程句柄（Executor 只读）",
        "wall_time_sec": "Executor 单调时钟测量",
        "peak_memory_mb": "作业对象统计（ProcessControl.sample）",
        "artifact sha256/size": "Executor 二进制读 + SHA-256",
        "event_seq/chain_hash": "Collector",
        "node state": "StateMachine",
        "PASS/FAIL/VERIFIED": "Gate / Verifier",
    }
)