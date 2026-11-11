"""M05 · executor/process_control.py — 子进程、超时与整棵进程树回收（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-004（受控执行）、NFR-06（资源上限）、策划书 §6.1「超时进程树清理」
依赖：M03 limits（wall_clock/memory 上限）、M05 registry（静态入口）、M05 workspace（cwd）
不变量：无隔离不启动；超时必回收整棵树；回收失败必须留痕并升级，绝不返回成功
错误码：RESOURCE_BUDGET_EXCEEDED（429，`limit_kind=wall_clock`）；其余为**内部故障**，
        只出结构化事件/日志（不新增注册表码）
状态：伪代码；**不启动进程、不杀进程、不调用 Windows API**

## Windows 上的正确做法（本文件的设计基准）

  1. `CreateJobObjectW` 建作业对象，设 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
     （句柄关闭即杀整棵树）与 `JOB_OBJECT_LIMIT_PROCESS_MEMORY`（内存上限）；
  2. 子进程用 `CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP` 启动；
  3. `AssignProcessToJobObject` 把它放进作业；
  4. `ResumeThread` 才开始执行 —— 顺序不能反过来：
     先跑后分配会留下“分配前已 fork 的孙子进程”，超时就杀不干净；
  5. 超时：先 `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pgid)` 请求退出，
     等宽限期；仍活着 → `TerminateJobObject`；
  6. **验证**：再查作业内活动进程数，必须为 0；不为 0 → 回收失败。

  不用 `psutil`（依赖未批准）、不用 `shell=True`、不用 `os.system`、
  不用“只 terminate 父进程”的写法、不给 `timeout=None`。

## “失败也回收”分支（本文件的重点）

  回收本身会失败（句柄被占用、作业分配失败、进程卡在不可中断状态、API 返回 0）。
  处理顺序固定：

    ① 记 `ReclaimReport(ok=False, residual_pids=[...], fault=...)` —— **留痕**；
    ② 写 CRITICAL 结构化日志（`component=executor`，`fault`、`residual_process_count`）；
    ③ `escalation_required=True`，由 Orchestrator 请求 `RUNNING→FAILED`；
    ④ 该节点**禁止**派发新 attempt，直到残留进程确认消失（`block_until_reclaimed`）；
    ⑤ `ExitStatus` 结构上禁止 `exit_code=0`（见 `__post_init__`）——
       残留进程还在跑却报成功，在本模块里是**构造不出来**的状态。

  绝不“尽力杀一下然后按超时失败继续跑下一个节点”：残留进程会污染后续 attempt 的
  目录、端口、内存与证据（同一台机器，16GB）。

## 本模块不做

  - 不做沙箱/权限隔离（受控子进程 ≠ 沙箱；07 §2.6 已登记风险）。
  - 不读用户环境变量全集：只传白名单（`ENV_ALLOWLIST`），不传凭据。
  - 不管磁盘配额（`workspace.QuotaGuard` 负责），不管证据写入（Collector 负责）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol

__all__ = [
    "DEFAULT_GRACE_SEC",
    "ENV_ALLOWLIST",
    "FORBIDDEN_PROCESS_PATTERNS",
    "JOB_LIMIT_FLAGS",
    "TREE_KILL_SEQUENCE",
    "ExitStatus",
    "JobObjectHandle",
    "ProcessControlFault",
    "ProcessIsolationUnavailable",
    "ProcessLaunchError",
    "ProcessLaunchSpec",
    "ProcessLimits",
    "ReclaimMethod",
    "ReclaimReport",
    "ReclaimStage",
    "ResourceSample",
    "RunningProcess",
    "build_argv",
    "assert_process_control_contract",
]

DEFAULT_GRACE_SEC: Final[float] = 5.0
SAMPLE_INTERVAL_SEC: Final[float] = 0.5   # [P3 约定] 没有配置键；采样频率不是契约

# 只传这些环境变量给子进程；凭据/token/私钥类一律不传（M03 logging / NFR-05）。
ENV_ALLOWLIST: Final[tuple[str, ...]] = (
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC",
    "PYTHONPATH", "PYTHONHASHSEED", "PYTHONIOENCODING", "PYTHONUTF8",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
)

JOB_LIMIT_FLAGS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE": 0x00002000,
        "JOB_OBJECT_LIMIT_PROCESS_MEMORY": 0x00000100,
        "JOB_OBJECT_LIMIT_JOB_MEMORY": 0x00000200,
        "JOB_OBJECT_LIMIT_ACTIVE_PROCESS": 0x00000008,
    }
)

# 回收阶段顺序（也是 `ReclaimReport.stages` 的顺序；不跳步）
TREE_KILL_SEQUENCE: Final[tuple[str, ...]] = (
    "REQUEST_EXIT",     # GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pgid)
    "GRACE_WAIT",       # 等 DEFAULT_GRACE_SEC
    "TERMINATE_JOB",    # TerminateJobObject
    "VERIFY_EMPTY",     # 查作业内活动进程数
    "CLOSE_JOB",        # 关句柄（KILL_ON_JOB_CLOSE 兜底）
)

# 静态扫描禁写项：出现即契约破坏。
FORBIDDEN_PROCESS_PATTERNS: Final[tuple[str, ...]] = (
    "shell=True", "os.system", "os.popen", "subprocess.call(", "subprocess.run(",
    "timeout=None", ".terminate()", ".kill()", "start_new_session=False",
)


# ---------------------------------------------------------------------------
# 1. 故障与异常
# ---------------------------------------------------------------------------
class ProcessControlFault(StrEnum):
    """内部故障码（不是注册表错误码；对外只出结构化事件）。"""

    ISOLATION_UNAVAILABLE = "PROCESS_ISOLATION_UNAVAILABLE"  # 建/分配作业失败 → 不启动
    LAUNCH_FAILED = "PROCESS_LAUNCH_FAILED"
    WAIT_FAILED = "PROCESS_WAIT_FAILED"
    TERMINATE_FAILED = "PROCESS_TERMINATE_FAILED"
    RESIDUAL_PROCESSES = "PROCESS_RESIDUAL_PROCESSES"
    SAMPLE_FAILED = "PROCESS_SAMPLE_FAILED"
    ARGV_REJECTED = "PROCESS_ARGV_REJECTED"


class ProcessIsolationUnavailable(RuntimeError):
    """作业对象不可用：**拒绝启动**，不是“降级继续”。

    理由：超时后整棵树的回收是 P0 验收项（策划书 §6.1）。没有 Job Object 就无法
    保证回收，先跑起来等于把“杀不干净”变成必然。对外无注册码 → worker 记
    `disposition=LAUNCH_FAILED` + CRITICAL 日志 + 升级，不返回 exit 0。
    """

    fault: Final[ProcessControlFault] = ProcessControlFault.ISOLATION_UNAVAILABLE

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"{self.fault.value}：{detail}")


class ProcessLaunchError(RuntimeError):
    """启动失败（解释器不存在、cwd 不可用、作业分配失败等）。"""

    fault: Final[ProcessControlFault] = ProcessControlFault.LAUNCH_FAILED

    def __init__(self, detail: str, *, argv_digest: str = "") -> None:
        self.detail = detail
        self.argv_digest = argv_digest
        super().__init__(f"{self.fault.value}：{detail}")


# ---------------------------------------------------------------------------
# 2. 启动规格（argv 只能来自静态登记）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProcessLimits:
    """单个 attempt 的进程侧上限。生效值由 worker 取三方最小值后传入。"""

    wall_time_sec: int
    memory_mb: int
    grace_sec: float = DEFAULT_GRACE_SEC

    def __post_init__(self) -> None:
        if self.wall_time_sec < 1:
            raise ValueError("wall_time_sec 必须 ≥ 1")
        if self.memory_mb < 1:
            raise ValueError("memory_mb 必须 ≥ 1")
        if self.grace_sec < 0 or self.grace_sec > 60:
            raise ValueError("grace_sec 必须在 0..60 秒（再长就是没打算回收）")


@dataclass(frozen=True, slots=True)
class ProcessLaunchSpec:
    """一次子进程启动的完整规格。

    `argv` 的**形状被固定**（见 `build_argv`）：
        (python_exe, "-m", "<module>.<entry>", "--params", "params.json")
    其中：
      - `python_exe` 来自部署配置（绝对路径，项目 3.11.16 或 `.venv` 解释器）；
      - `<module>` 来自 `TemplateRegistration.module`（静态、全小写、≥2 段）；
      - 参数值**不进命令行**（避免注入、长度限制、凭据泄漏），只传文件名。
    因此本类型里没有 `command: str`、没有 `shell: bool` 字段——结构上做不到。
    """

    argv: tuple[str, ...]
    cwd: str                    # attempt 目录的绝对路径（已 resolve_inside）
    env: Mapping[str, str]      # 白名单环境变量（不含凭据）
    stdout_path: str
    stderr_path: str
    limits: ProcessLimits
    attempt_id: str

    def __post_init__(self) -> None:
        if not self.argv:
            raise ProcessLaunchError("argv 不能为空")
        if any(not isinstance(a, str) or "\x00" in a for a in self.argv):
            raise ProcessLaunchError("argv 只允许非空字符串")
        if self.argv[0].lower().endswith((".bat", ".cmd", ".ps1", ".sh")):
            raise ProcessLaunchError("禁止用脚本作为 argv[0]")
        if not self.cwd or not self.attempt_id.startswith("attempt_"):
            raise ProcessLaunchError("cwd/attempt_id 非法")


def build_argv(
    *,
    python_exe: str,
    module: str,
    entry_module_suffix: str = "__main__",
    params_filename: str = "params.json",
) -> tuple[str, ...]:
    """拼 argv。**唯一**允许的形态；不做字符串拼接、不过 shell。

    规则：
      - `python_exe` 必须是绝对路径且文件名以 `python` 开头（防“同名脚本”）；
      - `module` 只允许 `[a-z0-9_.]`（与 registry 的 `_MODULE_RE` 同源约束）；
      - 固定 `-m <module>.<entry>`，固定 `--params <文件名>`；
      - `params_filename` 必须是单段文件名（不得含 `/`、`\\`、`..`）。
    拒绝即 `ProcessLaunchError(fault=ARGV_REJECTED)`：不尝试修正、不改写。
    """
    import os

    if not os.path.isabs(python_exe):
        raise ProcessLaunchError("python_exe 必须是绝对路径", )
    if not os.path.basename(python_exe).lower().startswith("python"):
        raise ProcessLaunchError("python_exe 文件名必须以 python 开头")
    if not module or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_." for ch in module):
        raise ProcessLaunchError(f"module {module!r} 只允许小写字母/数字/下划线/点")
    if module.startswith(".") or module.endswith(".") or ".." in module:
        raise ProcessLaunchError(f"module {module!r} 形态非法")
    if not entry_module_suffix.replace("_", "").isalnum():
        raise ProcessLaunchError("entry_module_suffix 只允许标识符字符")
    if "/" in params_filename or "\\" in params_filename or ".." in params_filename:
        raise ProcessLaunchError("params_filename 必须是单段文件名")
    return (python_exe, "-m", f"{module}.{entry_module_suffix}", "--params", params_filename)


# ---------------------------------------------------------------------------
# 3. 运行中的进程与作业句柄
# ---------------------------------------------------------------------------
class JobObjectHandle(Protocol):
    """作业对象端口（Windows 实现用 `ctypes.windll.kernel32`；测试用桩）。

    方法语义（与 Win32 一一对应）：
      - `create(kill_on_close=True, memory_mb=N)`：建作业并设上限；失败抛 OSError；
      - `assign(pid)`：`AssignProcessToJobObject`；失败必须抛出（不能“尽力而为”）；
      - `terminate()`：`TerminateJobObject`；返回是否成功；
      - `active_process_count()`：`QueryInformationJobObject` 的活动进程数；
      - `peak_memory_mb()`：作业峰值内存（`PeakJobMemoryUsed`）；
      - `close()`：关句柄；`KILL_ON_JOB_CLOSE` 在此时兜底。
    """

    def create(self, *, memory_mb: int) -> None:
        ...

    def assign(self, pid: int) -> None:
        ...

    def terminate(self) -> bool:
        ...

    def active_process_count(self) -> int:
        ...

    def peak_memory_mb(self) -> int:
        ...

    def close(self) -> None:
        ...


@dataclass(slots=True)
class RunningProcess:
    """已启动的子进程 + 它的作业对象。

    刻意**不**暴露 `pid` 之外的“杀进程”方法：杀只能走 `terminate_tree()`
    （走完整回收序列并产出 `ReclaimReport`）。`pid` 只用于日志与 `ResumeThread`。
    """

    pid: int
    pgid: int
    job: JobObjectHandle
    spec: ProcessLaunchSpec
    started_monotonic: float
    resumed: bool = False
    handle: object | None = None      # Win32 进程句柄（WaitForSingleObject 用）
    thread_handle: object | None = None
    closed: bool = False

    def resume(self) -> None:
        """`ResumeThread`：只有完成 `assign()` 之后才允许调用。"""
        if not self.resumed:
            # LIB: ctypes.windll.kernel32.ResumeThread(thread_handle)
            self.resumed = True


@dataclass(frozen=True, slots=True)
class ResourceSample:
    """一次资源采样。**采样失败不得当 0**（见 `failed` 字段）。"""

    wall_time_sec: float
    peak_memory_mb: int
    cpu_time_sec: float | None
    failed: bool = False
    failure_reason: str = ""


# ---------------------------------------------------------------------------
# 4. 退出与回收
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ExitStatus:
    """子进程的退出事实。**不是**“成功/失败”判定（判定属 Gate/Verifier）。

    结构不变量（构造即校验，绕不过去）：
      1. `timed_out=True` ⇒ `exit_code is None`
         —— 超时后残留状态不得表达成“正常退出”，更不得是 0；
      2. `tree_reclaimed=False` ⇒ `residual_pids` 非空
         —— 回收失败必须留痕，“杀失败且没记录”构造不出来；
      3. `exit_code == 0` ⇒ `tree_reclaimed=True 且 residual_pids == ()`
         —— 有残留还报 0 的路径被彻底封死；
      4. `exit_code` 只允许 0..255 或 None（Windows 退出码截断到低 8 位）。
    """

    exit_code: int | None
    timed_out: bool
    wall_time_sec: float
    tree_reclaimed: bool
    residual_pids: tuple[int, ...] = ()
    fault: ProcessControlFault | None = None

    def __post_init__(self) -> None:
        if self.timed_out and self.exit_code is not None:
            raise ValueError("超时不得带 exit_code（不得把超时表达为正常退出）")
        if not self.tree_reclaimed and not self.residual_pids:
            raise ValueError("tree_reclaimed=False 时必须记录 residual_pids（失败也要留痕）")
        if self.exit_code == 0 and not self.tree_reclaimed:
            raise ValueError("进程树未回收时不得报告 exit_code=0")
        if self.exit_code == 0 and self.residual_pids:
            raise ValueError("存在残留进程时不得报告 exit_code=0")
        if self.exit_code is not None and not (0 <= self.exit_code <= 255):
            raise ValueError("exit_code 必须在 0..255")
        if self.wall_time_sec < 0:
            raise ValueError("wall_time_sec 不得为负")


class ReclaimMethod(StrEnum):
    GRACEFUL_THEN_JOB = "GRACEFUL_THEN_JOB"   # CTRL_BREAK → 宽限 → TerminateJobObject
    JOB_TERMINATE_ONLY = "JOB_TERMINATE_ONLY"  # 子进程已退出，只补 TerminateJobObject
    NONE = "NONE"                              # 未执行回收（进程已自然结束）


class ReclaimStage(StrEnum):
    REQUEST_EXIT = "REQUEST_EXIT"
    GRACE_WAIT = "GRACE_WAIT"
    TERMINATE_JOB = "TERMINATE_JOB"
    VERIFY_EMPTY = "VERIFY_EMPTY"
    CLOSE_JOB = "CLOSE_JOB"


@dataclass(frozen=True, slots=True)
class ReclaimReport:
    """回收结果。`ok=False` 时**必须**有 `residual_pids` 与 `escalation_required=True`。"""

    ok: bool
    method: ReclaimMethod
    stages: tuple[ReclaimStage, ...]
    residual_pids: tuple[int, ...] = ()
    elapsed_sec: float = 0.0
    fault: ProcessControlFault | None = None
    escalation_required: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.ok:
            if not self.residual_pids and self.fault is None:
                raise ValueError("回收失败必须给 residual_pids 或 fault（不得空手而归）")
            if not self.escalation_required:
                raise ValueError("回收失败必须标记 escalation_required=True")
        if self.ok and self.residual_pids:
            raise ValueError("ok=True 却带 residual_pids：自相矛盾")

    def as_event_fields(self) -> Mapping[str, object]:
        """可安全写进结构化日志/事件字段（无绝对路径、无命令行）。"""
        return MappingProxyType(
            {
                "reclaim_ok": self.ok,
                "reclaim_method": self.method.value,
                "reclaim_stages": [s.value for s in self.stages],
                "residual_process_count": len(self.residual_pids),
                "escalation_required": self.escalation_required,
                "reclaim_fault": self.fault.value if self.fault else None,
            }
        )


# ---------------------------------------------------------------------------
# 5. 生命周期（伪代码；实现属 WP-06）
# ---------------------------------------------------------------------------
class ProcessController:
    """启动/等待/回收的唯一入口。

    调用方（`worker.run_attempt`）只能看到：
      - `start(spec) -> RunningProcess`；
      - `wait(proc, timeout_sec) -> int | None`；
      - `terminate_tree(proc, reason) -> ReclaimReport`；
      - `sample(proc) -> ResourceSample`。
    没有 `kill(pid)`、没有 `run(cmd)`、没有 `shell`。
    """

    def start(self, spec: ProcessLaunchSpec) -> RunningProcess:
        """启动子进程（CREATE_SUSPENDED → 建作业 → 分配 → Resume）。

        失败语义：
          - 作业创建/分配失败 → `ProcessIsolationUnavailable`（**不启动**）；
          - 其它启动失败 → `ProcessLaunchError`（带 `argv_digest`，不带完整 argv 进日志）。
        """
        raise NotImplementedError("P3 伪代码：启动由 WP-06 用 ctypes 落地")

    def wait(self, proc: RunningProcess, *, timeout_sec: float) -> int | None:
        """`WaitForSingleObject(handle, timeout_ms)`：返回退出码，超时返回 None。

        超时返回 None 时**不在这里杀进程**：由调用方走 `terminate_tree()`，
        这样“超时 → 回收 → 验证 → 留痕”是一条可审计的序列，而不是藏在 wait 里。
        """
        raise NotImplementedError("P3 伪代码：等待由 WP-06 落地")

    def terminate_tree(self, proc: RunningProcess, *, reason: str) -> ReclaimReport:
        """整棵树回收；按 `TREE_KILL_SEQUENCE` 逐阶段执行并记录。

        阶段与失败点一一对应：
          1. `REQUEST_EXIT`：`GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pgid)`；
             失败不致命（继续下一步），但要记 stage。
          2. `GRACE_WAIT`：等 `spec.limits.grace_sec`；期间轮询退出。
          3. `TERMINATE_JOB`：`job.terminate()`；返回 False → 继续做 4、5 再判失败。
          4. `VERIFY_EMPTY`：`job.active_process_count()` 必须为 0；
             否则 `residual_pids` 记录（实现阶段从作业查询枚举 pid），`ok=False`。
          5. `CLOSE_JOB`：关句柄（`KILL_ON_JOB_CLOSE` 兜底）；关句柄后**再查一次**
             进程是否存活（按 pid 存活探测）；仍存活 → `ok=False` +
             `fault=RESIDUAL_PROCESSES` + `escalation_required=True`。

        **“失败也回收”**：即使 1–4 都失败，5 仍必须执行；`ReclaimReport` 也要返回
        （不抛异常给上层当“无法处理”）——异常会把“回收失败”变成“没有回收记录”。
        """
        raise NotImplementedError("P3 伪代码：回收由 WP-06 落地")

    def sample(self, proc: RunningProcess) -> ResourceSample:
        """采样：`wall_time_sec` + 作业峰值内存（+ CPU 时间，尽力而为）。

        失败返回 `ResourceSample(failed=True, failure_reason=...)`；
        调用方（worker）必须把 `failed=True` 当作“采样缺口”，不得当 0 参与上限判定。
        """
        raise NotImplementedError("P3 伪代码：采样由 WP-06 落地")


# ---------------------------------------------------------------------------
# 6. 上限判定与异常路径的契约
# ---------------------------------------------------------------------------
def exceed_wall_clock(*, observed_sec: float, limit_sec: int) -> None:
    """墙钟超限：抛已注册码 `RESOURCE_BUDGET_EXCEEDED` + `limit_kind="wall_clock"`。

    语义与 M03 `limits.exceeded()` 一致：`observed > limit` 才算超限（闭区间上界）。
    抛出后由 worker 转入 `terminate_tree()`；**不是**在这里杀进程。
    """
    if observed_sec < 0:
        raise ValueError("观测值不得为负（负值是采集错误，不是未超限）")
    if observed_sec > limit_sec:
        raise ResourceBudgetExceeded(limit_kind="wall_clock", observed=observed_sec, limit=limit_sec)


def exceed_memory(*, observed_mb: int, limit_mb: int) -> None:
    if observed_mb < 0:
        raise ValueError("观测值不得为负")
    if observed_mb > limit_mb:
        raise ResourceBudgetExceeded(limit_kind="memory", observed=observed_mb, limit=limit_mb)


class ResourceBudgetExceeded(RuntimeError):
    """已注册码 `RESOURCE_BUDGET_EXCEEDED` 的进程侧抛出点（429）。"""

    error_code: Final[str] = "RESOURCE_BUDGET_EXCEEDED"
    http_status: Final[int] = 429

    def __init__(self, *, limit_kind: str, observed: float, limit: float) -> None:
        self.limit_kind = limit_kind
        self.observed = observed
        self.limit = limit
        super().__init__(
            f"{self.error_code}：limit_kind={limit_kind} observed={observed} limit={limit}"
        )

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {"limit_kind": self.limit_kind, "observed": self.observed, "limit": self.limit}
        )


# ---------------------------------------------------------------------------
# 7. 自检
# ---------------------------------------------------------------------------
def assert_process_control_contract() -> list[str]:
    """自检：结构上排除“无超时/无作业/只杀父进程/shell 拼接”。

    返回违反项（空 = 通过）。落地阶段由测试静态扫描本文件与本模块公开面。
    """
    problems: list[str] = []
    # 1) 公开面不能有“只杀父进程”或“直接执行命令”的方法
    for name in ("kill", "run", "shell", "system", "popen", "spawn_shell"):
        if hasattr(ProcessController, name):
            problems.append(f"ProcessController 不得有 {name}()")
    # 2) 回收序列必须包含验证阶段（否则“杀完就算成功”）
    if "VERIFY_EMPTY" not in TREE_KILL_SEQUENCE:
        problems.append("回收序列缺少 VERIFY_EMPTY：无法证明进程树已空")
    if TREE_KILL_SEQUENCE[-1] != "CLOSE_JOB":
        problems.append("回收序列必须以 CLOSE_JOB 收尾（KILL_ON_JOB_CLOSE 兜底）")
    # 3) 结构不变量：有残留不得报 0
    for kwargs in (
        dict(exit_code=0, timed_out=False, wall_time_sec=1.0, tree_reclaimed=False,
             residual_pids=(123,)),
        dict(exit_code=0, timed_out=False, wall_time_sec=1.0, tree_reclaimed=True,
             residual_pids=(123,)),
        dict(exit_code=0, timed_out=True, wall_time_sec=1.0, tree_reclaimed=True),
    ):
        try:
            ExitStatus(**kwargs)  # type: ignore[arg-type]
        except ValueError:
            continue
        problems.append(f"ExitStatus 允许了非法组合：{kwargs}")
    return problems