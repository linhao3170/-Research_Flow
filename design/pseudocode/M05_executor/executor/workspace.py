"""M05 · executor/workspace.py — 每次尝试的工作目录（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-004（目录隔离）、I-03（Executor/Verifier 目录分离）
依赖：M01 encoding（hash/id 规则只按符号引用）、M03 security.yaml（`path_allowlist`）、M03 limits（磁盘配额）
不变量：每次 attempt 独立目录；越界写入必须拒绝；证据/产物不得被清理逻辑删除
错误码：TOOL_NOT_ALLOWLISTED（不涉及）、SCHEMA_INVALID（不涉及）、
        RESOURCE_BUDGET_EXCEEDED（429，`detail.limit_kind="disk"`，仅配额）
状态：伪代码；**不创建目录、不写文件、不删文件**；只定义命名、检查与策略

## 目录命名（确定性，可反推）

    <root>/tasks/<task_id>/nodes/<node_id>/attempts/<attempt_id>/
        inputs/     只读输入（Executor 写入；模板只读）
        artifacts/  模板产物（模板写；Executor 复算哈希）
        logs/       模板/子进程 stdout·stderr（Executor 写）
        tmp/        模板临时文件（**唯一允许清理的目录**）

  - `<root>` 由部署注入，且必须落在 `security.yaml:path_allowlist` 之内（见 OQ-P3-06：
    当前配置没有独立的 `workspace_root` 键，P3 不改 M03 schema）。
  - `<attempt_id>` 形如 `attempt_02`（M01 `new_attempt_id`）；**每次真实执行唯一**，
    重试不复用 → 目录天然不撞。撞名不是“复用”，而是安全事件（见 `WorkspaceCollision`）。

## 为什么要自己做路径检查

  `open(os.path.join(root, user_rel))` 在 Windows 上至少有三类逃逸：
    1. `..\\..\\` 与绝对路径（含盘符、UNC `\\\\server\\share`）；
    2. 符号链接 / 目录联接（junction）：路径字符串合法，realpath 之后在根外；
    3. NTFS 备用数据流（ADS，`file.txt:evil`）与设备名（`con`、`nul`）。
  因此本模块规定：**所有**对外路径都必须经 `resolve_inside()`；
  它先做语法拒绝，再做 `realpath` + `commonpath` 语义拒绝。两道都过才算“在根内”。

## 本模块不做（避免虚假承诺）

  - 不设 Windows ACL、不建受限用户、不做沙箱：受控子进程 ≠ 沙箱（07 §2.6 风险已登记）。
  - 不清理 `artifacts/`/`logs/`：它们可能已成为证据引用对象（一删就没法复算哈希）。
  - 不跨盘移动目录：`os.replace` 跨卷会退化为复制+删除，破坏“目录即现场”。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol

__all__ = [
    "ARTIFACT_DIR",
    "ATTEMPT_DIR_NAME",
    "CLEANUP_RULES",
    "INPUT_DIR",
    "LOG_DIR",
    "MAX_ABS_PATH_CHARS",
    "RESERVED_COMPONENT_NAMES",
    "TMP_DIR",
    "AllowlistPort",
    "AttemptWorkspace",
    "CleanupDecision",
    "CleanupPolicy",
    "FORBIDDEN_IO_SURFACE",
    "PATH_RULES",
    "QuotaGuard",
    "WORKSPACE_SUBDIRS",
    "WorkspaceCollision",
    "WorkspaceEscape",
    "WorkspaceFault",
    "WorkspaceLayout",
    "WorkspacePolicy",
    "WorkspaceQuotaExceeded",
    "WorkspaceRootRejected",
    "assert_workspace_contract",
    "check_component",
    "plan_cleanup",
    "resolve_inside",
]

INPUT_DIR: Final[str] = "inputs"
ARTIFACT_DIR: Final[str] = "artifacts"
LOG_DIR: Final[str] = "logs"
TMP_DIR: Final[str] = "tmp"
ATTEMPT_DIR_NAME: Final[str] = "attempts"

# Windows MAX_PATH 默认 260；留出 19 字符余量给临时后缀与 8.3 名字。
MAX_ABS_PATH_CHARS: Final[int] = 240

# 目录名层面的保留名（与 builder 的 node_id 规则同源；这里覆盖任意路径组件）。
RESERVED_COMPONENT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "con", "prn", "aux", "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)

CLEANUP_RULES: Final[tuple[str, ...]] = (
    "T0 默认 KEEP_ALL：attempt 目录整体保留，直到任务归档（归档策略属 P7/P10）。",
    "只允许清理 tmp/；artifacts/ 与 logs/ 一律保留（可能已被证据引用）。",
    "孤儿目录（有目录无 launch 证据）可清理，但必须同时满足：无证据 + 超过保留期 + 有审计。",
    "清理不得跨盘、不得跟随符号链接、不得递归删除根目录或 attempt 根。",
    "任何“腾空间”的清理都不得触碰证据与产物（M03 limits：不得删证据/产物）。",
)


# ---------------------------------------------------------------------------
# 1. 故障
# ---------------------------------------------------------------------------
class WorkspaceFault(StrEnum):
    """内部故障码（**不是**注册表错误码；对外映射见各类异常的 `error_code`）。"""

    ESCAPE = "WORKSPACE_ESCAPE"
    COLLISION = "WORKSPACE_COLLISION"
    PATH_TOO_LONG = "WORKSPACE_PATH_TOO_LONG"
    NOT_WRITABLE = "WORKSPACE_NOT_WRITABLE"
    QUOTA_EXCEEDED = "WORKSPACE_QUOTA_EXCEEDED"
    ROOT_OUTSIDE_ALLOWLIST = "WORKSPACE_ROOT_OUTSIDE_ALLOWLIST"
    INVALID_COMPONENT = "WORKSPACE_INVALID_COMPONENT"


class WorkspaceEscape(PermissionError):
    """路径逃逸（`..`、绝对路径、ADS、联接/符号链接指向根外）。

    对外错误码的选择：这是**请求/参数形态非法**导致的拒绝，且发生在写文件之前，
    因此用 `SCHEMA_INVALID`(422) 而不是 500；同时 `fault` 保留具体原因供负例断言。
    消息里**只出现相对路径**，不出现绝对路径（日志安全：M03 logging §FORBIDDEN_CONTENT）。
    """

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422

    def __init__(self, relative_path: str, *, reason: str) -> None:
        self.fault = WorkspaceFault.ESCAPE
        self.relative_path = relative_path
        self.reason = reason
        super().__init__(f"{self.error_code}/{self.fault.value}：{relative_path!r}（{reason}）")


class WorkspaceRootRejected(PermissionError):
    """工作根不在 `path_allowlist` 内、或根本身是链接。启动期错误，不监听端口。"""

    error_code: Final[str] = "TOOL_NOT_ALLOWLISTED"
    http_status: Final[int] = 403

    def __init__(self, reason: str) -> None:
        self.fault = WorkspaceFault.ROOT_OUTSIDE_ALLOWLIST
        self.reason = reason
        super().__init__(f"{self.error_code}/{self.fault.value}：{reason}")


class WorkspaceCollision(RuntimeError):
    """attempt 目录已存在：`attempt_id` 被复用（或并发重复执行）。

    这是**安全事件**而不是可重试错误：每次真实执行必须有唯一 `attempt_id`
    （06 §4.5）。命中即拒绝，绝不 `exist_ok=True` 覆盖。
    """

    error_code: Final[str] = "STATE_TRANSITION_DENIED"
    http_status: Final[int] = 409

    def __init__(self, attempt_id: str, reason: str) -> None:
        self.fault = WorkspaceFault.COLLISION
        self.attempt_id = attempt_id
        self.reason = reason
        super().__init__(f"{self.error_code}/{self.fault.value}：attempt {attempt_id!r}（{reason}）")


class WorkspacePathTooLong(RuntimeError):
    """绝对路径超过安全长度：提前拒绝，避免一半文件写不进去。"""

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422

    def __init__(self, length: int) -> None:
        self.fault = WorkspaceFault.PATH_TOO_LONG
        self.length = length
        super().__init__(
            f"{self.error_code}/{self.fault.value}：路径长 {length} > {MAX_ABS_PATH_CHARS}"
        )


class WorkspaceQuotaExceeded(RuntimeError):
    """磁盘配额超限：沿用 E.3 `RESOURCE_BUDGET_EXCEEDED` + `limit_kind="disk"`（M03 limits）。"""

    error_code: Final[str] = "RESOURCE_BUDGET_EXCEEDED"
    http_status: Final[int] = 429
    limit_kind: Final[str] = "disk"

    def __init__(self, *, used_mb: int, quota_mb: int) -> None:
        self.fault = WorkspaceFault.QUOTA_EXCEEDED
        self.used_mb = used_mb
        self.quota_mb = quota_mb
        super().__init__(
            f"{self.error_code}：disk 用量 {used_mb} MiB > 配额 {quota_mb} MiB"
        )


# ---------------------------------------------------------------------------
# 2. 组件与路径检查
# ---------------------------------------------------------------------------
def check_component(name: str) -> str:
    """校验单个路径组件（目录名）。

    拒绝：空、`.`、`..`、绝对/相对分隔符、盘符冒号、ADS 冒号、控制字符、
    Windows 保留设备名、结尾句点/空格（Windows 会静默去掉，导致名字与记录不一致）、
    超长（>128，与 node_id/attempt_id 的量级一致）。
    """
    if not isinstance(name, str) or not name:
        raise WorkspaceEscape(name, reason="组件为空")
    if name in (".", ".."):
        raise WorkspaceEscape(name, reason="组件不得为 . 或 ..")
    if "/" in name or "\\" in name:
        raise WorkspaceEscape(name, reason="组件不得含路径分隔符")
    if ":" in name:
        raise WorkspaceEscape(name, reason="组件不得含冒号（盘符/ADS）")
    if any(not ch.isprintable() for ch in name):
        raise WorkspaceEscape(name, reason="组件含控制/不可打印字符")
    if name != name.strip():
        raise WorkspaceEscape(name, reason="组件首尾不得含空白")
    if name.endswith(".") or name.endswith(" "):
        raise WorkspaceEscape(name, reason="Windows 会去掉结尾句点/空格")
    if name.lower() in RESERVED_COMPONENT_NAMES:
        raise WorkspaceEscape(name, reason="Windows 保留设备名")
    if len(name) > 128:
        raise WorkspaceEscape(name, reason="组件过长（>128）")
    return name


def resolve_inside(root: str, relative_path: str) -> str:
    """把**相对路径**解析成根内的绝对路径；越界即抛 `WorkspaceEscape`。

    两道闸（顺序不可交换）：

    **语法闸**（不碰文件系统）：
      1. 拒绝对路径：`os.path.isabs`、盘符 `C:`、UNC `\\\\`、协议式 `file://`；
      2. 拒绝 `:`（ADS）与空字节；
      3. 逐段 `check_component`（含保留名、结尾句点、控制字符）；
      4. 归一化后不得含 `..`。

    **语义闸**（碰文件系统，只读）：
      5. `os.path.realpath(root)` 与 `os.path.realpath(join)`；
      6. `os.path.commonpath([root_real, target_real])` 必须等于 `root_real`
         （`normcase` 后比较，Windows 大小写不敏感）；
      7. 若目标已存在且是符号链接/联接：`realpath` 已解析，若最终不在根内即拒绝。

    返回：绝对路径（已归一）。**不创建任何东西**。

    残余风险（必须写进评审，不得声称已解决）：
      - Windows 8.3 短名（`PROGRA~1`）与 NTFS 硬链接：`realpath` 不展开短名；
        缓解是“根由部署注入且必须在 allowlist 内”，不是本函数能证明的；
      - TOCTOU：检查与创建之间目录可被替换；缓解是单机单用户 + attempt 目录独占
        + 创建后立即 `lstat` 复核（见 `AttemptWorkspace.create()` 的步骤 6）。
    """
    if not isinstance(relative_path, str) or not relative_path:
        raise WorkspaceEscape("", reason="相对路径为空")
    if "\x00" in relative_path:
        raise WorkspaceEscape(relative_path, reason="路径含空字节")
    if os.path.isabs(relative_path) or relative_path.startswith(("\\\\", "//")):
        raise WorkspaceEscape(relative_path, reason="不得使用绝对路径/UNC")
    if len(relative_path) >= 2 and relative_path[1] == ":":
        raise WorkspaceEscape(relative_path, reason="不得使用盘符")
    if "://" in relative_path:
        raise WorkspaceEscape(relative_path, reason="不得使用 URL 形式")
    if ":" in relative_path:
        raise WorkspaceEscape(relative_path, reason="不得含冒号（ADS）")

    parts = [p for p in relative_path.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        raise WorkspaceEscape(relative_path, reason="解析后没有有效组件")
    for part in parts:
        if part == "..":
            raise WorkspaceEscape(relative_path, reason="不得含 .. 组件")
        check_component(part)

    root_real = os.path.realpath(root)
    target = os.path.join(root_real, *parts)
    target_real = os.path.realpath(target)
    try:
        inside = os.path.commonpath(
            [os.path.normcase(root_real), os.path.normcase(target_real)]
        ) == os.path.normcase(root_real)
    except ValueError:      # 不同盘符：commonpath 直接抛，按逃逸处理
        inside = False
    if not inside:
        raise WorkspaceEscape(relative_path, reason="realpath 归一后不在工作根内（链接逃逸）")
    if len(target_real) > MAX_ABS_PATH_CHARS:
        raise WorkspacePathTooLong(len(target_real))
    return target_real


# ---------------------------------------------------------------------------
# 3. 根与策略
# ---------------------------------------------------------------------------
class AllowlistPort(Protocol):
    """`security.yaml:path_allowlist` 的只读视图（必需；未注入即构造失败）。"""

    def contains(self, absolute_path: str) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class WorkspacePolicy:
    """工作根的部署策略。

    `root` 必须：
      - 绝对路径；
      - `realpath(root)` 后仍在 `allowlist` 内；
      - 不是符号链接/联接（根自己是链接时，realpath 会指向别处，等于把整个工作区搬走）；
      - 与 Verifier 工作目录不重叠（I-03；由 P5 的 Verifier 配置保证，本类只记录该要求）。
    """

    root: str
    allowlist: AllowlistPort
    quota_mb_per_task: int
    per_attempt_required: bool = True

    def __post_init__(self) -> None:
        if not self.root or not os.path.isabs(self.root):
            raise WorkspaceRootRejected("工作根必须是绝对路径")
        if ".." in self.root.replace("\\", "/").split("/"):
            raise WorkspaceRootRejected("工作根不得含 ..")
        real = os.path.realpath(self.root)
        if os.path.normcase(real) != os.path.normcase(os.path.abspath(self.root)):
            raise WorkspaceRootRejected("工作根不得是符号链接/联接（realpath 改变了它）")
        if not self.allowlist.contains(real):
            raise WorkspaceRootRejected("工作根不在 security.yaml:path_allowlist 内")
        if self.quota_mb_per_task < 1:
            raise WorkspaceRootRejected("quota_mb_per_task 必须 ≥ 1")


# ---------------------------------------------------------------------------
# 4. 目录布局
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    """一次 attempt 的目录布局（纯值对象；不创建目录）。"""

    root: str
    task_id: str
    node_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        # 组件级校验：id 直接成为目录名，必须先过 `check_component`。
        for name in (self.task_id, self.node_id, self.attempt_id):
            check_component(name)
        if not self.attempt_id.startswith("attempt_"):
            raise WorkspaceEscape(self.attempt_id, reason="attempt_id 必须以 attempt_ 开头")
        if not self.task_id.startswith("task_"):
            raise WorkspaceEscape(self.task_id, reason="task_id 必须以 task_ 开头")

    # -- 相对路径 ---------------------------------------------------------
    @property
    def relative_attempt(self) -> str:
        return f"tasks/{self.task_id}/nodes/{self.node_id}/{ATTEMPT_DIR_NAME}/{self.attempt_id}"

    @property
    def relative_inputs(self) -> str:
        return f"{self.relative_attempt}/{INPUT_DIR}"

    @property
    def relative_artifacts(self) -> str:
        return f"{self.relative_attempt}/{ARTIFACT_DIR}"

    @property
    def relative_logs(self) -> str:
        return f"{self.relative_attempt}/{LOG_DIR}"

    @property
    def relative_tmp(self) -> str:
        return f"{self.relative_attempt}/{TMP_DIR}"

    # -- 绝对路径（一律经 resolve_inside） --------------------------------
    def attempt_path(self) -> str:
        return resolve_inside(self.root, self.relative_attempt)

    def inputs_path(self) -> str:
        return resolve_inside(self.root, self.relative_inputs)

    def artifacts_path(self) -> str:
        return resolve_inside(self.root, self.relative_artifacts)

    def logs_path(self) -> str:
        return resolve_inside(self.root, self.relative_logs)

    def tmp_path(self) -> str:
        return resolve_inside(self.root, self.relative_tmp)

    def artifact_path(self, relative_name: str) -> str:
        """产物路径：只允许 `artifacts/` 下的相对名（不得跨 attempt、不得绝对）。"""
        return resolve_inside(self.root, f"{self.relative_artifacts}/{relative_name}")

    def log_file(self, name: str) -> str:
        return resolve_inside(self.root, f"{self.relative_logs}/{check_component(name)}")

    def layout_id(self) -> str:
        """日志/事件里用的稳定标识（不含绝对路径，满足 M03 logging 禁写绝对路径）。"""
        return f"{self.task_id}/{self.node_id}/{self.attempt_id}"


class AttemptWorkspace:
    """已创建的 attempt 目录句柄（只在 `create()` 成功后存在）。

    对外只暴露“拿路径”与“写日志/参数”两类方法；**没有** `delete()`：
    删除只走 `CleanupPolicy`（且 T0 只清 tmp/）。
    """

    def __init__(self, layout: WorkspaceLayout, *, created_at: str) -> None:
        self._layout = layout
        self.created_at = created_at

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    def create(self) -> None:
        """创建目录树：attempt 根 `exist_ok=False`，子目录 `exist_ok=True`。

        步骤：
          1. 先在内存里算出全部目标路径（全部过 `resolve_inside`）；
          2. `os.makedirs(attempt_root, exist_ok=False)`：已存在 → `WorkspaceCollision`；
          3. 建四个子目录；
          4. `lstat` 复核 attempt 根：必须是目录、且不是符号链接（防 TOCTOU 替换）；
          5. 写失败不吞：任何 `OSError` 原样抛出（由 worker 记为 `WORKSPACE_NOT_WRITABLE`）。

        副作用：创建目录。**不写文件内容**（参数文件由 worker 写）。
        """
        raise NotImplementedError("P3 伪代码：目录创建由 WP-06 落地")

    def write_text_atomic(self, relative_path: str, text: str) -> str:
        """在 attempt 内原子写文本（`tmp` + `os.replace`），返回绝对路径。

        用途：`inputs/params.json`、`inputs/attempt.json`、`logs/*.log` 的收尾。
        规则：
          - 内容必须是 UTF-8 文本；二进制产物由模板写、由 worker 复算哈希；
          - 写入前再次 `resolve_inside`（防调用方传入已构造好的逃逸路径）；
          - `os.replace` 只在同一卷内原子；跨卷会退化为复制，因此临时文件必须落在同目录。
        """
        raise NotImplementedError("P3 伪代码：原子写由 WP-06 落地")


# ---------------------------------------------------------------------------
# 5. 清理策略
# ---------------------------------------------------------------------------
class CleanupPolicy(StrEnum):
    """T0 只用 `KEEP_ALL`；其余两项为显式的、需审计的运维动作。"""

    KEEP_ALL = "KEEP_ALL"                      # 默认：什么都不删
    TMP_ONLY = "TMP_ONLY"                      # 只清 tmp/
    ORPHAN_NO_EVIDENCE = "ORPHAN_NO_EVIDENCE"  # 清“有目录、无证据、超期”的孤儿


@dataclass(frozen=True, slots=True)
class CleanupDecision:
    policy: CleanupPolicy
    allowed: bool
    targets: tuple[str, ...]        # 相对路径（不出现绝对路径）
    reason: str


def plan_cleanup(
    layout: WorkspaceLayout,
    *,
    policy: CleanupPolicy,
    evidence_seen: bool,
    age_sec: float,
    orphan_retention_sec: float,
    audit_available: bool,
) -> CleanupDecision:
    """决定“能不能删、删什么”。**只出决策，不执行删除。**

    规则（对应 `CLEANUP_RULES`）：
      - `KEEP_ALL` → 不删；
      - `TMP_ONLY` → 只删 `tmp/`；即使 `evidence_seen=True` 也允许（tmp 不承载证据）；
      - `ORPHAN_NO_EVIDENCE` → 必须同时满足：无证据、`age_sec > orphan_retention_sec`、
        审计可用；否则不删（fail-closed）。
    任何策略都**不把 `artifacts/`、`logs/`、`inputs/` 放进 target**。
    """
    if policy is CleanupPolicy.KEEP_ALL:
        return CleanupDecision(policy, False, (), "T0 默认保留全部现场")
    if policy is CleanupPolicy.TMP_ONLY:
        return CleanupDecision(policy, True, (layout.relative_tmp,), "只清理 tmp/")
    if evidence_seen:
        return CleanupDecision(policy, False, (), "已有证据引用：不得清理（可能破坏可复算性）")
    if age_sec <= orphan_retention_sec:
        return CleanupDecision(policy, False, (), "未超过孤儿保留期")
    if not audit_available:
        return CleanupDecision(policy, False, (), "审计不可用：不得清理（fail-closed）")
    return CleanupDecision(policy, True, (layout.relative_attempt,), "孤儿目录，已过保留期且有审计")


# ---------------------------------------------------------------------------
# 6. 配额
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class QuotaGuard:
    """任务级磁盘配额守卫（只测量、只拒绝；不删东西）。"""

    quota_mb: int
    reserved_mb: int = 0     # 预留给证据/日志的量，不允许被产物吃满

    def check(self, *, used_mb: int) -> None:
        """`used_mb + reserved_mb > quota_mb` → 抛 `WorkspaceQuotaExceeded`。

        等于上限不算超限（闭区间上界，与 M03 `limits.exceeded` 一致）。
        """
        if used_mb < 0 or self.quota_mb < 1:
            raise ValueError("用量/配额必须非负且配额 ≥ 1")
        if used_mb + self.reserved_mb > self.quota_mb:
            raise WorkspaceQuotaExceeded(used_mb=used_mb + self.reserved_mb,
                                         quota_mb=self.quota_mb)

    def measure_tree(self, root: str) -> int:
        """测量目录树字节数（只读；不跟随符号链接）。

        实现意图：`os.scandir` 递归，`entry.is_file(follow_symlinks=False)` 才计大小；
        遇到符号链接跳过并计数（由调用方决定是否告警）。
        失败（权限/消失）不得当成 0：抛 `OSError`，由 worker 记为采样失败。
        """
        raise NotImplementedError("P3 伪代码：目录测量由 WP-06 落地")


# ---------------------------------------------------------------------------
# 7. 自检
# ---------------------------------------------------------------------------
WORKSPACE_SUBDIRS: Final[tuple[str, ...]] = (INPUT_DIR, ARTIFACT_DIR, LOG_DIR, TMP_DIR)

FORBIDDEN_IO_SURFACE: Final[tuple[str, ...]] = (
    "open_any", "write_any", "remove_tree", "delete_all", "chdir", "symlink",
)


def assert_workspace_contract() -> list[str]:
    """自检：子目录齐全、清理规则不碰产物、无危险 IO 入口。返回违反项。"""
    problems: list[str] = []
    if set(WORKSPACE_SUBDIRS) != {INPUT_DIR, ARTIFACT_DIR, LOG_DIR, TMP_DIR}:
        problems.append("四个子目录必须恰为 inputs/artifacts/logs/tmp")
    if TMP_DIR not in CLEANUP_RULES[1]:
        problems.append("清理规则必须只允许 tmp/")
    for name in FORBIDDEN_IO_SURFACE:
        if name in globals():
            problems.append(f"workspace 不得暴露 {name}")
    # 布局不得把 artifacts/logs 放进任何清理目标（用一条样例布局做结构断言）
    sample = WorkspaceLayout(root=os.path.abspath(os.sep), task_id="task_x",
                             node_id="n", attempt_id="attempt_01")
    for policy in CleanupPolicy:
        decision = plan_cleanup(sample, policy=policy, evidence_seen=True, age_sec=1e9,
                                orphan_retention_sec=0, audit_available=True)
        for target in decision.targets:
            if ARTIFACT_DIR in target or LOG_DIR in target or INPUT_DIR in target:
                problems.append(f"{policy} 清理目标包含受保护子目录：{target}")
    return problems


PATH_RULES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "task_id": "task_<uuid>（M01）；目录名组件，必须过 check_component",
        "node_id": "NODE_ID_PATTERN（M01）；不得含路径分隔符/保留名",
        "attempt_id": "attempt_NN（M01）；每次真实执行唯一，重试不复用",
        "artifact_rel": "artifacts/ 下的相对名；不得 ../、不得绝对路径、不得 ADS",
        "log_name": "logs/ 下的文件名；由 Executor 生成（stdout.txt/stderr.txt/sample.jsonl）",
    }
)