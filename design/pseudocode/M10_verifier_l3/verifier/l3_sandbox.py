"""MODULE: M10 · verifier/l3_sandbox.py — L3 新目录、只读白名单、独立进程（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-007、策划书 §9.3、AGENTS §4.9/§4.13
FR/依赖: FR-007；依赖 M03 环境指纹、M05 workspace 的目录分离约束、M08 ruleset（L3 阈值）
不变量/错误码: L3 必须在新临时目录、独立进程、从原始数据真实重跑；读取**默认拒绝**，
             只允许 `READONLY_ALLOWLIST`；不得读取原运行产物/metrics/predictions/模型/结果目录；
             不得在原 attempt 目录内重跑；不得复用 Executor 进程。
             错误码：TOOL_NOT_ALLOWLISTED（403，L3 读取白名单拒绝/进程隔离拒绝）、
             RESOURCE_BUDGET_EXCEEDED（429，沙箱磁盘/时长）、SCHEMA_INVALID（422，路径/计划非法）
写入者: **无**；沙箱只创建自己的目录与进程，不写证据/状态/报告
状态: 伪代码；目录创建/进程启动属 WP-08，本文件定义计划、允许清单与拒绝点

## 允许清单（不是黑名单）

  L3 读取路径的**唯一**判据是 `SandboxPolicy.is_read_allowed(relative_path)`：
  未命中 `READONLY_ALLOWLIST` 的一律拒绝，不存在“先看黑名单再放行”的分支。
  允许项只有九类（都相对 `source_root`；下表 `task_spec`/`graph` 各算一类）：

  | 逻辑名 | 允许路径模式 | 用途 |
  |---|---|---|
  | dataset | `datasets/*/*.csv`、`datasets/*/*.json` | 原始数据字节（只读） |
  | dataset_binding | `inputs/dataset_binding.json` | 数据登记/哈希声明 |
  | code_snapshot | `code/*/*.py`、`code/*/*.json` | 本次执行的代码快照 |
  | config_snapshot | `config/*/*.json`、`config/*/*.yaml` | 参数/配置快照 |
  | dependency_lock | `deps/requirements.lock` | 依赖锁 |
  | split_manifest | `inputs/split_manifest.json` | 六字段划分清单 |
  | ruleset | `inputs/ruleset.json` | 规则版本 |
  | task_spec / graph | `inputs/task_spec.json`、`inputs/graph.json` | 任务声明 / 任务图（两类） |

## L3 禁止读取的路径清单（文档与负例用；机制仍走允许清单）

  下列路径**不在允许清单**内，因此默认拒绝；把它们写出来是为了让负例有明确目标，
  不是让实现去匹配黑名单：

  1. 原运行 attempt 目录下的 `artifacts/`、`logs/`、`tmp/`；
  2. 原运行的 `metrics.json`、`predictions.csv`、`run_summary.json`、`leakage_report.json`；
  3. 任何模型二进制（`.pkl/.joblib/.dill`）与结果目录；
  4. Evidence Store 数据库、payload sidecar、证据包导出目录；
  5. Executor 工作区（`tasks/<task>/nodes/<node>/attempts/<attempt>`）；
  6. 其它 L3 run 的目录、Verifier 的私有报告/密钥目录；
  7. 用户主目录、桌面、下载、系统临时目录中的任意文件；
  8. UNC/网络路径、`http(s)://`、`file://`。

## 独立进程（不是“同一进程换个函数”）

  `ProcessSpec` 固定：`shell=False`、`close_fds=True`、`cwd=<sandbox>/work/<seed>`、
  `stdin=DEVNULL`、stdout/stderr 重定向到 `<sandbox>/logs/`；环境变量只来自
  `environment_allowlist()`（`PYTHONHASHSEED=0`、`TZ=UTC`、`LC_ALL=C`、BLAS 线程=1），
  不继承 Executor 的 `PYTHONPATH`/代理/凭据。进程 PID 不得等于 Executor PID，
  cwd 不得在原 attempt 目录内；启动后记录 executable 哈希与开始时间。

## 边界声明

  这是**目录/进程隔离**，不是 OS 沙箱：不设 Windows ACL、不建受限用户、不承诺阻断
  同机 root/管理员。残余风险必须写进评审；不得声称“已沙箱化”。
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "DENIED_PATH_CLASSES",
    "READONLY_ALLOWLIST",
    "AllowlistEntry",
    "ProcessIdentity",
    "ProcessSpec",
    "SandboxHandle",
    "SandboxPlan",
    "SandboxPolicy",
    "SandboxViolation",
    "assert_process_isolated",
    "assert_sandbox_boundary",
    "build_process_spec",
    "environment_allowlist",
    "plan_sandbox",
]

_HASH64 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^l3_[0-9a-f]{32}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$")

SANDBOX_SUBDIRS: Final[tuple[str, ...]] = ("inputs", "work", "out", "logs")

# 只读白名单：路径模式相对 source_root；顺序固定，`assert_sandbox_boundary` 会核对。
READONLY_ALLOWLIST: Final[tuple["AllowlistEntry", ...]] = ()  # 在 AllowlistEntry 定义后填充

# 文档化的禁止读取类别（不在代码里做匹配；机制是上面的允许清单）。
DENIED_PATH_CLASSES: Final[tuple[str, ...]] = (
    "原运行 artifacts/logs/tmp",
    "原运行 metrics.json / predictions.csv / run_summary.json / leakage_report.json",
    "模型二进制（.pkl/.joblib/.dill）与结果目录",
    "Evidence Store 数据库与 payload sidecar",
    "Executor 工作区 tasks/<task>/nodes/<node>/attempts/<attempt>",
    "其它 L3 run 目录与 Verifier 私有报告/密钥目录",
    "用户主目录 / 桌面 / 下载 / 系统临时目录中的任意文件",
    "UNC / 网络路径 / http(s) / file://",
)


class SandboxViolation(RuntimeError):
    """L3 隔离拒绝；对外统一 `TOOL_NOT_ALLOWLISTED`(403)，内部 reason 可断言。"""

    def __init__(self, reason: str, message: str, *, field_path: str = "sandbox") -> None:
        self.error_code = "TOOL_NOT_ALLOWLISTED"
        self.reason = reason
        self.field_path = field_path
        self.http_status = 403
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    """一个允许读取的逻辑类别；`patterns` 是相对 source_root 的 fnmatch 模式。"""

    logical_name: str
    patterns: tuple[str, ...]
    required: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.logical_name or not self.patterns:
            raise ValueError("logical_name/patterns 不得为空")
        for pattern in self.patterns:
            if pattern.startswith("/") or ".." in pattern.split("/"):
                raise ValueError(f"允许清单模式不得是绝对路径/含 ..：{pattern!r}")

    def matches(self, relative_path: str) -> bool:
        return any(fnmatch.fnmatch(relative_path, pattern) for pattern in self.patterns)


# 九类允许读取；`required=True` 的项在 L3 开始前必须存在且哈希可读。
READONLY_ALLOWLIST = (
    AllowlistEntry("dataset", ("datasets/*/*.csv", "datasets/*/*.json"), True,
                   "原始数据字节（仅只读）"),
    AllowlistEntry("dataset_binding", ("inputs/dataset_binding.json",), True,
                   "数据登记/哈希声明"),
    AllowlistEntry("code_snapshot", ("code/*/*.py", "code/*/*.json"), True,
                   "本次执行的代码快照"),
    AllowlistEntry("config_snapshot", ("config/*/*.json", "config/*/*.yaml"), True,
                   "参数/配置快照"),
    AllowlistEntry("dependency_lock", ("deps/requirements.lock",), True,
                   "依赖锁"),
    AllowlistEntry("split_manifest", ("inputs/split_manifest.json",), True,
                   "六字段划分清单"),
    AllowlistEntry("ruleset", ("inputs/ruleset.json",), True,
                   "规则版本"),
    AllowlistEntry("task_spec", ("inputs/task_spec.json",), True,
                   "任务声明"),
    AllowlistEntry("graph", ("inputs/graph.json",), True,
                   "任务图"),
)

_BY_NAME: Final[Mapping[str, AllowlistEntry]] = MappingProxyType(
    {entry.logical_name: entry for entry in READONLY_ALLOWLIST}
)


def _normalize_relative(relative_path: str) -> str:
    """只接受相对路径；统一 `/`；拒绝 `..`、盘符、UNC、URL、空字节。"""
    if not isinstance(relative_path, str) or not relative_path:
        raise SandboxViolation("L3_PATH_EMPTY", "读取路径不得为空", field_path="path")
    if "\x00" in relative_path:
        raise SandboxViolation("L3_PATH_NUL", "路径含空字节", field_path="path")
    if os.path.isabs(relative_path) or relative_path.startswith(("\\\\", "//")):
        raise SandboxViolation("L3_PATH_ABSOLUTE", "不得使用绝对路径/UNC", field_path="path")
    if len(relative_path) >= 2 and relative_path[1] == ":":
        raise SandboxViolation("L3_PATH_DRIVE", "不得使用盘符", field_path="path")
    if "://" in relative_path:
        raise SandboxViolation("L3_PATH_URL", "不得使用 URL", field_path="path")
    normalized = relative_path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts:
        raise SandboxViolation("L3_PATH_EMPTY", "路径没有有效组件", field_path="path")
    if any(part == ".." for part in parts):
        raise SandboxViolation("L3_PATH_TRAVERSAL", "不得含 ..", field_path="path")
    return "/".join(parts)


def _parse_utc(value: str) -> datetime:
    """把 RFC3339 UTC 解析为带时区 datetime；Z 与 +00:00 等价。"""
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("时间必须带时区")
    return parsed.astimezone(timezone.utc)


def _is_within(parent: str, child: str) -> bool:
    try:
        parent_real = os.path.normcase(os.path.realpath(parent))
        child_real = os.path.normcase(os.path.realpath(child))
        return os.path.commonpath([parent_real, child_real]) == parent_real
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """L3 沙箱部署策略；所有路径必须是绝对路径且互不嵌套。"""

    verifier_root: str
    source_root: str
    executor_workspace_root: str
    python_executable: str
    python_executable_hash: str
    max_disk_mb: int = 1024
    max_wall_time_sec: int = 1800
    network_allowed: bool = False
    allowlist: tuple[AllowlistEntry, ...] = READONLY_ALLOWLIST

    def __post_init__(self) -> None:
        for name in ("verifier_root", "source_root", "executor_workspace_root", "python_executable"):
            value = getattr(self, name)
            if not os.path.isabs(value):
                raise SandboxViolation(
                    "L3_POLICY_PATH_NOT_ABSOLUTE", f"{name} 必须是绝对路径", field_path=name,
                )
        if self.network_allowed:
            raise SandboxViolation(
                "L3_NETWORK_FORBIDDEN", "L3 不得允许网络", field_path="network_allowed",
            )
        if self.max_disk_mb < 1 or self.max_wall_time_sec < 1:
            raise SandboxViolation(
                "L3_POLICY_LIMIT_INVALID", "磁盘/时长上限必须 ≥1", field_path="max_disk_mb",
            )
        if not _HASH64.match(self.python_executable_hash):
            raise SandboxViolation(
                "L3_PYTHON_HASH_INVALID", "python_executable_hash 必须是 64 位十六进制",
                field_path="python_executable_hash",
            )
        if _is_within(self.executor_workspace_root, self.source_root) or _is_within(
            self.source_root, self.executor_workspace_root
        ):
            raise SandboxViolation(
                "L3_SOURCE_OVERLAPS_EXECUTOR", "source_root 不得与 Executor 工作区重叠",
                field_path="source_root",
            )
        if _is_within(self.executor_workspace_root, self.verifier_root) or _is_within(
            self.verifier_root, self.executor_workspace_root
        ):
            raise SandboxViolation(
                "L3_VERIFIER_OVERLAPS_EXECUTOR", "verifier_root 不得与 Executor 工作区重叠",
                field_path="verifier_root",
            )
        names = [entry.logical_name for entry in self.allowlist]
        if len(set(names)) != len(names):
            raise SandboxViolation(
                "L3_ALLOWLIST_DUPLICATED", "允许清单 logical_name 不得重复", field_path="allowlist",
            )

    def is_read_allowed(self, relative_path: str) -> bool:
        """**唯一**读取判据：命中允许清单即 True，否则 False；没有黑名单分支。"""
        try:
            normalized = _normalize_relative(relative_path)
        except SandboxViolation:
            return False
        return any(entry.matches(normalized) for entry in self.allowlist)

    def resolve_read(self, relative_path: str) -> str:
        """把允许的读路径解析到 source_root 内；越界/未命中即拒绝。"""
        normalized = _normalize_relative(relative_path)
        if not self.is_read_allowed(normalized):
            raise SandboxViolation(
                "L3_READ_OUTSIDE_ALLOWLIST",
                f"路径不在只读允许清单内：{normalized!r}", field_path="path",
            )
        absolute = os.path.realpath(os.path.join(self.source_root, *normalized.split("/")))
        if not _is_within(self.source_root, absolute):
            raise SandboxViolation(
                "L3_READ_ESCAPE", "realpath 归一后不在 source_root 内", field_path="path",
            )
        return absolute

    def require_allowlist(self, logical_name: str) -> AllowlistEntry:
        entry = _BY_NAME.get(logical_name)
        if entry is None:
            raise SandboxViolation(
                "L3_ALLOWLIST_UNKNOWN", f"未登记的逻辑输入 {logical_name!r}", field_path="allowlist",
            )
        return entry


@dataclass(frozen=True, slots=True)
class SandboxPlan:
    """纯路径计划；不创建目录、不写文件。"""

    policy: SandboxPolicy
    task_id: str
    run_id: str
    root: str
    inputs_dir: str
    work_dir: str
    out_dir: str
    logs_dir: str
    created_at: str

    def __post_init__(self) -> None:
        if not self.task_id.startswith("task_"):
            raise SandboxViolation("L3_TASK_ID_INVALID", "task_id 形态非法", field_path="task_id")
        if not _RUN_ID.match(self.run_id):
            raise SandboxViolation("L3_RUN_ID_INVALID", "run_id 形态必须是 l3_<32 hex>", field_path="run_id")
        if not _UTC.match(self.created_at):
            raise SandboxViolation("L3_CREATED_AT_INVALID", "created_at 必须是 UTC RFC 3339",
                                   field_path="created_at")
        if not _is_within(self.policy.verifier_root, self.root):
            raise SandboxViolation("L3_ROOT_OUTSIDE_VERIFIER", "沙箱根必须在 verifier_root 内",
                                   field_path="root")
        if _is_within(self.policy.executor_workspace_root, self.root):
            raise SandboxViolation("L3_ROOT_INSIDE_EXECUTOR", "沙箱根不得在 Executor 工作区内",
                                   field_path="root")

    def seed_dir(self, seed: int) -> str:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise SandboxViolation("L3_SEED_INVALID", "seed 必须是非负 integer", field_path="seed")
        return os.path.join(self.work_dir, f"seed_{seed}")

    def output_dir(self, seed: int) -> str:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise SandboxViolation("L3_SEED_INVALID", "seed 必须是非负 integer", field_path="seed")
        return os.path.join(self.out_dir, f"seed_{seed}")


def plan_sandbox(
    policy: SandboxPolicy,
    *,
    task_id: str,
    run_id: str,
    created_at: str,
) -> SandboxPlan:
    """生成新目录计划；`run_id` 必须由 Verifier 新生成（不复用）。"""
    root = os.path.join(policy.verifier_root, "l3", task_id, run_id)
    return SandboxPlan(
        policy=policy,
        task_id=task_id,
        run_id=run_id,
        root=root,
        inputs_dir=os.path.join(root, "inputs"),
        work_dir=os.path.join(root, "work"),
        out_dir=os.path.join(root, "out"),
        logs_dir=os.path.join(root, "logs"),
        created_at=created_at,
    )


@dataclass(frozen=True, slots=True)
class SandboxHandle:
    """已创建沙箱的句柄；创建动作属 WP-08，本类只保存身份。"""

    plan: SandboxPlan
    device: int
    inode: int

    def create(self) -> None:
        """落地步骤（WP-08）：

          1. `os.makedirs(plan.root, exist_ok=False)`：已存在 → `L3_RUN_DIR_COLLISION`；
          2. 建 inputs/work/out/logs 四个子目录；
          3. `lstat(plan.root)` 复核：是目录、不是符号链接/联接；
          4. `os.stat(plan.root)` 记录 (st_dev, st_ino) 供复用检测；
          5. 任何写入失败原样抛错，不吞成“已创建”。

        本阶段不执行；`SandboxHandle` 只在创建成功后存在。
        """
        raise NotImplementedError("P5 伪代码：沙箱目录创建由 WP-08 落地")

    def open_readonly(self, relative_path: str) -> int:
        """只读打开允许清单内的源文件（`os.O_RDONLY`）；未命中即拒绝。"""
        absolute = self.plan.policy.resolve_read(relative_path)
        # LIB: fd = os.open(absolute, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        # 返回 fd 后由调用方 with os.fdopen(fd, "rb") 读取；不得以 "w"/"a" 打开。
        raise NotImplementedError("P5 伪代码：只读打开由 WP-08 落地")


# ---------------------------------------------------------------------------
# 进程隔离
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """进程身份（启动后由 Verifier 采集，不由子进程自报）。"""

    pid: int
    parent_pid: int
    executable: str
    executable_hash: str
    cwd: str
    sandbox_root: str
    started_at: str


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    """独立进程的启动参数；不可变，不含 shell。"""

    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]
    stdin: str = "DEVNULL"
    stdout_path: str = ""
    stderr_path: str = ""
    timeout_sec: int = 1800
    close_fds: bool = True
    shell: bool = False
    creationflags: int = 0

    def __post_init__(self) -> None:
        if not self.argv:
            raise SandboxViolation("L3_ARGV_EMPTY", "argv 不得为空", field_path="argv")
        if self.shell:
            raise SandboxViolation("L3_SHELL_FORBIDDEN", "L3 不得使用 shell", field_path="shell")
        if not self.close_fds:
            raise SandboxViolation("L3_INHERIT_FDS", "必须 close_fds=True", field_path="close_fds")
        if self.stdin != "DEVNULL":
            raise SandboxViolation("L3_STDIN_FORBIDDEN", "stdin 必须是 DEVNULL", field_path="stdin")
        if self.timeout_sec < 1:
            raise SandboxViolation("L3_TIMEOUT_INVALID", "timeout_sec 必须 ≥1", field_path="timeout_sec")
        for key in self.env:
            if key.upper() in ("PYTHONPATH", "PYTHONHOME", "HTTP_PROXY", "HTTPS_PROXY",
                               "ALL_PROXY", "NO_PROXY"):
                raise SandboxViolation(
                    "L3_ENV_INHERITED", f"不得继承环境变量 {key}", field_path="env",
                )


def environment_allowlist(run_id: str) -> Mapping[str, str]:
    """最小环境：确定性、无代理、无线程并行、无凭据。"""
    if not _RUN_ID.match(run_id):
        raise SandboxViolation("L3_RUN_ID_INVALID", "run_id 形态非法", field_path="run_id")
    return MappingProxyType({
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TZ": "UTC",
        "LC_ALL": "C",
        "LANG": "C",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "RF_L3_RUN_ID": run_id,
    })


def build_process_spec(
    plan: SandboxPlan,
    *,
    seed: int,
    entrypoint: str,
    timeout_sec: int,
) -> ProcessSpec:
    """构造独立进程参数；cwd 在 `work/<seed>`，输出在 `out/<seed>`/`logs/`。"""
    if not entrypoint or ".." in entrypoint or entrypoint.startswith("/"):
        raise SandboxViolation("L3_ENTRYPOINT_INVALID", "entrypoint 必须是相对模块名",
                               field_path="entrypoint")
    work_dir = plan.seed_dir(seed)
    argv = (
        plan.policy.python_executable,
        "-I",                 # isolated mode：不读用户 site-packages / PYTHON* 环境
        "-B",                 # 不写 .pyc
        "-m", entrypoint,
        "--seed", str(seed),
        "--output-dir", plan.output_dir(seed),
    )
    return ProcessSpec(
        argv=argv,
        cwd=work_dir,
        env=environment_allowlist(plan.run_id),
        stdout_path=os.path.join(plan.logs_dir, f"seed_{seed}.stdout.log"),
        stderr_path=os.path.join(plan.logs_dir, f"seed_{seed}.stderr.log"),
        timeout_sec=timeout_sec,
        creationflags=0x08000000,  # LIB: Windows CREATE_NO_WINDOW；不是安全边界
    )


def assert_process_isolated(
    *,
    plan: SandboxPlan,
    process: ProcessIdentity,
    executor_pid: int,
    original_run_root: str,
) -> None:
    """进程隔离的机器判据；任一条不满足即拒绝。"""
    if process.pid == executor_pid:
        raise SandboxViolation("L3_SAME_PID", "L3 进程不得复用 Executor PID", field_path="pid")
    if process.parent_pid == executor_pid:
        raise SandboxViolation("L3_PARENT_IS_EXECUTOR", "L3 进程不得由 Executor 直接派生",
                               field_path="parent_pid")
    if not _is_within(plan.root, process.cwd) or _is_within(original_run_root, process.cwd):
        raise SandboxViolation("L3_CWD_REUSED", "L3 cwd 必须在沙箱内且不在原运行目录",
                               field_path="cwd")
    if _is_within(original_run_root, process.sandbox_root) or _is_within(
        process.sandbox_root, original_run_root
    ):
        raise SandboxViolation("L3_SANDBOX_REUSED", "沙箱根不得与原运行目录重叠",
                               field_path="sandbox_root")
    if process.executable_hash != plan.policy.python_executable_hash:
        raise SandboxViolation("L3_EXECUTABLE_MISMATCH", "L3 解释器哈希与基线不符",
                               field_path="executable_hash")
    try:
        started_at = _parse_utc(process.started_at)
        created_at = _parse_utc(plan.created_at)
    except ValueError as exc:
        raise SandboxViolation("L3_TIMESTAMP_INVALID",
                               f"进程/沙箱时间无法解析：{exc}",
                               field_path="started_at") from exc
    if started_at < created_at:
        raise SandboxViolation("L3_PROCESS_BEFORE_SANDBOX", "进程启动早于沙箱创建",
                               field_path="started_at")


def assert_sandbox_boundary() -> list[str]:
    """静态检查：只读判据是允许清单；没有黑名单分支；无网络/shell。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("deny", "denylist", "blacklist", "blocked_paths", "allow_all"):
        if hasattr(module, attr):
            problems.append(f"sandbox 暴露黑名单/放行入口 {attr!r}")
    names = [entry.logical_name for entry in READONLY_ALLOWLIST]
    if len(names) != 9 or len(set(names)) != len(names):
        problems.append(f"允许清单必须恰好 9 类且不重复，实际 {names}")
    policy = SandboxPolicy(
        verifier_root=os.path.join(os.path.abspath(os.sep), "rf-verifier"),
        source_root=os.path.join(os.path.abspath(os.sep), "rf-source"),
        executor_workspace_root=os.path.join(os.path.abspath(os.sep), "rf-exec"),
        python_executable=os.path.join(os.path.abspath(os.sep), "python.exe"),
        python_executable_hash="0" * 64,
    )
    if not policy.is_read_allowed("datasets/wine/wine.csv"):
        problems.append("允许清单没有放行数据集")
    for denied in (
        "artifacts/metrics.json",
        "predictions.csv",
        "models/model.pkl",
        "../escape.csv",
        "C:/elsewhere/secret.bin",
    ):
        if policy.is_read_allowed(denied):
            problems.append(f"允许清单错误放行 {denied!r}")
    if policy.network_allowed:
        problems.append("L3 不得允许网络")
    return problems