"""M14 · orchestration/recovery/plan_freeze.py — 计划冻结、内容寻址与三条守卫（P7 伪代码）。
阶段：P7「调度与定向恢复」｜追踪：FR-010（T0 最小切片）、ADR-004 §2、05 §9.3 / §13（INVALIDATED→READY 三条件）、06 §1.1/§1.2
依赖：M14 `planner`（正文与 `PLAN_FORMAT_VERSION`）、M01 `canonical_bytes`（JCS）、M03 `recovery.yaml: plan_store_root`、
      M03 `audit_events.RECOVERY_PLAN_FROZEN`（审计事件定义）
不变量：文件名 = `plan_hash` = `sha256(文件字节)`；计划正文不含时间戳；冻结记录只写 `audit_log`；
        三条守卫任一不满足 → 拒绝（`PLAN_HASH_MISMATCH` + 具体 reason），**不得“计划缺失但放行”**
错误码：PLAN_HASH_MISMATCH（500 内部，守卫失败）、AUDIT_WRITE_FAILED（500，冻结审计不可用）、
        SCHEMA_INVALID（422，正文形态非法）
写入者：本文件写**计划文件**（内容寻址、只增不改）；`audit_log` 只经 `FreezeAuditPort`（唯一实现 = StateMachine 审计服务）
状态：伪代码；不建目录、不写文件、不连库、不读时钟

## 存储形态（ADR-004 §2.2 逐条）

  | 事实 | 本文件的做法 |
  |---|---|
  | 文件名 = SHA-256 | `path_for()` 只接受 64 位小写十六进制；**不加扩展名**（ADR 原文是“文件名=SHA-256”） |
  | 不入库 | 本文件没有 SQL、没有仓储；`plan_id`/`plan_hash` 由 `nodes` 两列保存（由 StateMachine 写） |
  | 不签名、不进七契约、不对外 | 只有字节 + 哈希；没有 signature/key 字段 |
  | 只增不改 | `put()` 目标已存在时**比对字节**：相同 → 幂等返回；不同 → `PlanStoreCorrupt`（拒绝覆盖） |
  | 冻结时间只在审计里 | `FreezeRecord.frozen_at` 由 `ClockPort` 提供，**不进入正文** |

## 三条守卫（05 §9.3，I-12）

  1. `guard_plan_file_present`：内容寻址路径上的文件存在且可读；
  2. `guard_plan_hash_matches`：`sha256(文件字节) == plan_hash`，且 `plan_id`/`plan_hash`
     与 `audit_log` 的冻结记录一致；
  3. `guard_frozen_before_rerun`：冻结事件严格早于本次重跑尝试。

  **判定的所有权在 StateMachine**：M02 `_guard_plan_three` 会在
  `INVALIDATED→READY` 时用同一套条件再判一次；本文件提供的是同一判定的可复用实现
  与负例锚点，**不得**被用作绕过 StateMachine 的旁路（`assert_guard_is_not_a_bypass()`）。

## `plan_hash` 稳定性的完整论证（验收判据 3）

  见 `HASH_STABILITY_ARGUMENT`：七条，任何一条失效都会让“同一输入两次生成同一哈希”不成立。
  落地阶段必须用 NEG-M14-12/13/14/15/16/17/18（时间戳、路径、集合、`plan_id`、两次生成、
  JCS 替代）真实执行验证；NEG-M14-07/08 是受影响集合与拓扑序校验，**不是**哈希稳定性负例。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Final, Mapping, Protocol

from .planner import PLAN_FORMAT_VERSION

__all__ = [
    "FORBIDDEN_BODY_KEYS",
    "FORBIDDEN_STORE_MARKERS",
    "HASH_STABILITY_ARGUMENT",
    "PLAN_HASH_RE",
    "VOLATILE_VALUE_PATTERNS",
    "ClockPort",
    "FreezeAuditPort",
    "FreezeRecord",
    "FreezeRefused",
    "FrozenPlan",
    "GuardReport",
    "PlanGuardDenied",
    "PlanStore",
    "PlanStoreCorrupt",
    "assert_body_time_free",
    "assert_guard_is_not_a_bypass",
    "assert_hash_stability_contract",
    "assert_no_approval_state",
    "assert_reproducible",
    "assert_store_root",
    "canonical_plan_bytes",
    "freeze_plan",
    "guard_frozen_before_rerun",
    "guard_plan_file_present",
    "guard_plan_hash_matches",
    "plan_hash_of",
    "plan_id_for",
    "verify_three_guards",
]

# 64 位小写十六进制：与 ENCODING_RULES §4、M01 `$defs/hash64` 同源。
PLAN_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

# 正文里**禁止出现**的键（时间、进程、主机、临时路径）。
# 命中任意一个 → 计划不可复现，必须拒绝冻结（不是“警告”）。
FORBIDDEN_BODY_KEYS: Final[tuple[str, ...]] = (
    "frozen_at", "created_at", "updated_at", "timestamp", "issued_at", "generated_at",
    "now", "started_at", "finished_at", "mtime", "duration_ms", "elapsed_sec",
    "pid", "process_id", "hostname", "host", "tmp_dir", "temp_path", "absolute_path",
    "nonce", "request_id", "trace_id",
)

# 正文**值**里禁止出现的易变内容模式（即使键名合法，值也不能像时间/路径/pid）。
VOLATILE_VALUE_PATTERNS: Final[tuple[str, ...]] = (
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",   # RFC3339 时间
    r"[A-Za-z]:\\",                              # Windows 绝对路径
    r"/(?:home|Users|tmp|var|workspace)/",       # POSIX 绝对路径
    r"\bpid[=: ]\d+",
    r"\b0x[0-9a-fA-F]{6,}\b",
)

# 稳定性论证（同时用于 MODULE.md 与 NEGATIVE_TESTS 的锚点）。
HASH_STABILITY_ARGUMENT: Final[tuple[str, ...]] = (
    "① 正文由纯函数产生：`planner.plan_recovery` 只读端口，不读时钟、不读随机源、不读环境变量。",
    "② 正文键集合封闭且固定：`assert_plan_structure` 断言 9 个键的**顺序**；多一个键即失败。",
    "③ 决策顺序 = 受影响子图的拓扑序：`assert_topological_subset` 校验；不依赖 set/dict 迭代序。",
    "④ 正文无时间/随机/pid/路径：`assert_body_time_free` 同时扫键名与值，命中即拒绝冻结。",
    "⑤ 规范化由 M01 `canonical_bytes`（JCS/RFC 8785）完成，**不是** `json.dumps(sort_keys=True)`；"
    "数组保持原顺序（JCS 只排对象键）。",
    "⑥ `plan_hash = sha256(字节)`，文件名 = `plan_hash`；同内容重复冻结是幂等（同文件、同哈希）。",
    "⑦ `plan_id` / `plan_hash` **不进入正文**（自指会让哈希无解）；它们只出现在文件名、nodes 两列与审计记录里。",
)


# ---------------------------------------------------------------------------
# 1. 异常
# ---------------------------------------------------------------------------
class PlanGuardDenied(RuntimeError):
    """三条守卫之一失败。

    `error_code` 固定为 `PLAN_HASH_MISMATCH`（与 M02 `INVALIDATED→READY` 的
    `denial_code` 一致）；`reason` 取 M02 `ReasonCode` 中已登记的字面值。
    """

    error_code: Final[str] = "PLAN_HASH_MISMATCH"
    http_status: Final[int] = 500

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{self.error_code}/{reason}：{detail}")


class PlanStoreCorrupt(RuntimeError):
    """内容寻址冲突：同一 `plan_hash` 对应的字节不同（或读回哈希不符）。

    这**不是**“覆盖一下就好”的情况：要么磁盘损坏，要么有人在改写冻结计划。
    """

    error_code: Final[str] = "PLAN_HASH_MISMATCH"
    http_status: Final[int] = 500


class FreezeRefused(RuntimeError):
    """冻结被拒绝：正文不合规，或冻结审计不可用（无审计的计划永远过不了守卫 2/3）。"""

    def __init__(self, error_code: str, detail: str) -> None:
        self.error_code = error_code
        self.detail = detail
        super().__init__(f"{error_code}：{detail}")


# ---------------------------------------------------------------------------
# 2. 端口
# ---------------------------------------------------------------------------
class ClockPort(Protocol):
    """UTC 时钟；返回值必须是 27 字符 `YYYY-MM-DDTHH:MM:SS.ffffffZ`。

    只用于 `FreezeRecord.frozen_at`（进审计），**绝不**进入计划正文。
    （`_normalize_utc()` 的输出是 30 字符形态，与该输入契约不同，勿混用。）
    """

    def now_utc(self) -> str:
        ...


class FreezeAuditPort(Protocol):
    """冻结审计的追加口。

    唯一合法实现是 StateMachine 的审计服务（06 §3：`audit_log` 唯一写者）。
    本模块**没有** SQL、没有连接；端口不可用时必须 fail-closed（`FreezeRefused`）。
    """

    def append(self, record: "FreezeRecord") -> None:
        ...


# ---------------------------------------------------------------------------
# 3. 值对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FreezeRecord:
    """一条 `RECOVERY_PLAN_FROZEN` 审计记录（字段与 06 §1.3 `audit_log` 对齐）。

    `frozen_at` 只在这里出现；正文里没有它。
    一条记录对应一个 `plan_id`/`plan_hash`；`node_id` 取计划的失败节点（OQ-P7-11：
    一份计划可能覆盖多个节点，审计只有一个 node_id 列）。
    """

    plan_id: str
    plan_hash: str
    task_id: str
    node_id: str
    actor: str
    correlation_id: str
    rule_version: str
    frozen_at: str
    action: str = "RECOVERY_PLAN_FROZEN"
    result: str = "OK"

    def __post_init__(self) -> None:
        if not PLAN_HASH_RE.match(self.plan_hash):
            raise FreezeRefused("SCHEMA_INVALID", f"plan_hash 形态非法：{self.plan_hash!r}")
        if self.plan_id != self.plan_hash:
            raise FreezeRefused(
                "SCHEMA_INVALID",
                "plan_id 必须等于 plan_hash（P7 约定；plan_id 形态属 OQ-P7-08）",
            )
        for name in ("task_id", "node_id", "actor", "correlation_id", "rule_version", "frozen_at"):
            if not getattr(self, name):
                raise FreezeRefused("SCHEMA_INVALID", f"{name} 不得为空（审计必填）")
        if self.action != "RECOVERY_PLAN_FROZEN" or self.result != "OK":
            raise FreezeRefused("SCHEMA_INVALID", "冻结记录只能是 RECOVERY_PLAN_FROZEN/OK")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "action": self.action,
                "result": self.result,
                "plan_id": self.plan_id,
                "plan_hash": self.plan_hash,
                "task_id": self.task_id,
                "node_id": self.node_id,
                "actor": self.actor,
                "correlation_id": self.correlation_id,
                "rule_version": self.rule_version,
                "frozen_at": self.frozen_at,
            }
        )


@dataclass(frozen=True, slots=True)
class FrozenPlan:
    """一次冻结的结果（**不**包含计划正文：正文只在文件里）。"""

    plan_id: str
    plan_hash: str
    path: str
    created_new: bool
    frozen_at: str

    def __post_init__(self) -> None:
        if not PLAN_HASH_RE.match(self.plan_hash):
            raise FreezeRefused("SCHEMA_INVALID", "plan_hash 形态非法")
        if self.plan_id != self.plan_hash:
            raise FreezeRefused("SCHEMA_INVALID", "plan_id 必须等于 plan_hash")
        if not self.path:
            raise FreezeRefused("SCHEMA_INVALID", "path 不得为空")


@dataclass(frozen=True, slots=True)
class GuardReport:
    """三条守卫的检查报告（按 1→2→3 顺序；失败即停，但保留已通过的步骤）。"""

    passed: bool
    checked_steps: tuple[str, ...]
    failure_reason: str | None = None
    failure_detail: str = ""

    def __post_init__(self) -> None:
        if self.passed and self.failure_reason is not None:
            raise ValueError("通过时不得带 failure_reason")
        if not self.passed and not self.failure_reason:
            raise ValueError("失败必须带 failure_reason")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "passed": self.passed,
                "checked_steps": list(self.checked_steps),
                "failure_reason": self.failure_reason,
                "failure_detail": self.failure_detail,
            }
        )


# ---------------------------------------------------------------------------
# 4. 正文校验与规范化
# ---------------------------------------------------------------------------
def assert_body_time_free(body: Mapping[str, object]) -> list[str]:
    """扫描正文，返回所有“不可复现”问题（空列表 = 通过）。

    检查两层：
      1. 键名命中 `FORBIDDEN_BODY_KEYS`；
      2. 字符串值命中 `VOLATILE_VALUE_PATTERNS`。
    递归遍历 dict / list / tuple；非字符串标量不检查（哈希、版本号、布尔都是稳定的）。
    """
    problems: list[str] = []

    def _walk(node: object, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if not isinstance(key, str):
                    problems.append(f"{path}: 键不是字符串（{key!r}）")
                    continue
                lowered = key.lower()
                if lowered in FORBIDDEN_BODY_KEYS:
                    problems.append(f"{path}.{key}: 正文禁止出现时间/进程/路径类键")
                _walk(value, f"{path}.{key}")
            return
        if isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                _walk(item, f"{path}[{index}]")
            return
        if isinstance(node, str):
            for pattern in VOLATILE_VALUE_PATTERNS:
                if re.search(pattern, node):
                    problems.append(f"{path}: 值命中易变模式 {pattern}：{node!r}")
            return

    _walk(body, "$")
    return problems


def canonical_plan_bytes(
    body: Mapping[str, object], *, canonical_bytes: Callable[[object], bytes]
) -> bytes:
    """把计划正文规范化成字节（JCS）。

    步骤：
      1. 校验 `plan_format_version` 与当前常量一致（未知版本拒绝，不猜）；
      2. 跑 `assert_body_time_free`；有任何问题 → `FreezeRefused(SCHEMA_INVALID)`；
      3. 调 M01 `canonical_bytes`（RFC 8785）得到字节。

    纪律：**不得**用 `json.dumps(sort_keys=True)` 代替（ENCODING_RULES §5：
    Python 按码点排序，JCS 按 UTF-16 码元排序，astral 字符会得到不同字节）。
    数组顺序由 JCS 保留 —— 因此决策顺序必须在正文里已经是拓扑序。
    """
    version = body.get("plan_format_version")
    if version != PLAN_FORMAT_VERSION:
        raise FreezeRefused(
            "SCHEMA_INVALID",
            f"plan_format_version 必须是 {PLAN_FORMAT_VERSION!r}，实际 {version!r}",
        )
    problems = assert_body_time_free(body)
    if problems:
        raise FreezeRefused("SCHEMA_INVALID", "正文含不可复现内容：" + "；".join(problems))
    # LIB: researchflow.contracts.encoding.canonical_bytes(body) → RFC 8785 JCS UTF-8 bytes
    return canonical_bytes(body)


def plan_hash_of(data: bytes) -> str:
    """`sha256(字节)` → 64 位小写十六进制。

    输入必须是**二进制**读到的字节（ENCODING_RULES §4：Windows 文本模式会把 `\\r\\n`
    规范化，导致同一文件在两台机器上哈希不同）。
    """
    if not isinstance(data, (bytes, bytearray)):
        raise FreezeRefused("SCHEMA_INVALID", "plan_hash_of 只接受 bytes（禁止 str）")
    # LIB: hashlib.sha256(bytes(data)).hexdigest()
    raise NotImplementedError("P7 伪代码：哈希由 hashlib.sha256 落地")


def plan_id_for(plan_hash: str) -> str:
    """`plan_id` 的当前形态：**等于** `plan_hash`。

    为什么不是 `plan_<hash>`：ENCODING_RULES §1 明确 `plan_` **不是**既定前缀，
    `plan_id` 形态仍属未决（OQ-P7-08）。用 `plan_hash` 本身作为身份是最小假设：
    不新造前缀、不引入第二套标识、也不影响“`plan_id` + `plan_hash` 成对”的契约要求。
    """
    if not PLAN_HASH_RE.match(plan_hash):
        raise FreezeRefused("SCHEMA_INVALID", f"plan_hash 形态非法：{plan_hash!r}")
    return plan_hash


# ---------------------------------------------------------------------------
# 5. 内容寻址存储
# ---------------------------------------------------------------------------
# 计划存储根不得落在这些目录里：证据目录（只追加的证据面）、Git 树、系统临时目录。
FORBIDDEN_STORE_MARKERS: Final[tuple[str, ...]] = (
    "/evidence/", "\\evidence\\",
    "/.git/", "\\.git\\",
    "/tmp/", "\\tmp\\",
)


def _normalize(path: str) -> str:
    """把路径规范化成可比对形态（统一分隔符、去尾分隔符）。**不做**大小写折叠。

    Windows 文件系统大小写不敏感，但本函数只做比较用途；是否同一文件由落地阶段的
    `os.path.realpath` + `commonpath` 决定。这里不折叠大小写，避免把两个不同目录判成同一个。
    """
    if not path:
        raise FreezeRefused("SCHEMA_INVALID", "路径不得为空")
    unified = path.replace("\\", "/")
    while unified.endswith("/") and len(unified) > 1:
        unified = unified[:-1]
    return unified


def assert_store_root(root: str) -> None:
    """校验 `recovery.yaml: plan_store_root` 的形态与位置。

    规则：
      1. 必须是绝对路径（`X:/...` 或 `/...`）；
      2. 不得落在证据目录、`.git`、系统临时目录（`FORBIDDEN_STORE_MARKERS`）；
      3. 不得为空。

    不满足 → `FreezeRefused(SCHEMA_INVALID)`（配置错误，不得“先用着再说”）。
    """
    normalized = _normalize(root)
    is_absolute = bool(re.match(r"^[A-Za-z]:/", normalized)) or normalized.startswith("/")
    if not is_absolute:
        raise FreezeRefused("SCHEMA_INVALID", f"plan_store_root 必须是绝对路径：{root!r}")
    lowered = "/" + normalized.lower().strip("/") + "/"
    for marker in FORBIDDEN_STORE_MARKERS:
        if marker.lower() in lowered:
            raise FreezeRefused(
                "SCHEMA_INVALID",
                f"plan_store_root 不得落在 {marker.strip('/')} 内（会污染证据面或 Git 树）",
            )


class PlanStore:
    """内容寻址的计划文件存储（无数据库、无索引、无状态）。

    唯一标识是 `plan_hash`；文件内容就是规范化后的计划字节。
    """

    def __init__(self, root: str) -> None:
        assert_store_root(root)
        self._root = _normalize(root)

    @property
    def root(self) -> str:
        return self._root

    def path_for(self, plan_hash: str) -> str:
        """`<root>/<plan_hash>`（无扩展名，ADR-004 §2.2）。

        校验：
          1. `plan_hash` 必须是 64 位小写十六进制（拒绝 `../`、绝对路径、大小写混合）；
          2. 拼出的路径必须仍在 `root` 之下（防目录逃逸）。

        错误：形态非法或越界 → `PlanGuardDenied(UNSAFE_PLAN_PATH)`。
        """
        if not isinstance(plan_hash, str) or not PLAN_HASH_RE.match(plan_hash):
            raise PlanGuardDenied("UNSAFE_PLAN_PATH", f"plan_hash 形态非法：{plan_hash!r}")
        candidate = f"{self._root}/{plan_hash}"
        # 由于 plan_hash 已限定为 [0-9a-f]{64}，不存在 ../ 或分隔符；这里再做一次前缀断言，
        # 防止未来有人放宽正则以“方便测试”。
        if not _normalize(candidate).startswith(self._root + "/"):
            raise PlanGuardDenied("UNSAFE_PLAN_PATH", f"路径逃出存储根：{candidate!r}")
        return candidate

    def exists(self, plan_hash: str) -> bool:
        # LIB: os.path.isfile(self.path_for(plan_hash))
        raise NotImplementedError("P7 伪代码：IO 属落地阶段")

    def read(self, plan_hash: str) -> bytes:
        """读回字节并**重新计算哈希**；不符 → `PlanStoreCorrupt`。"""
        # LIB: with open(self.path_for(plan_hash), "rb") as fh: data = fh.read()
        raise NotImplementedError("P7 伪代码：IO 属落地阶段")

    def put(self, data: bytes) -> tuple[str, str, bool]:
        """写入内容寻址文件；返回 `(plan_hash, path, created_new)`。

        步骤：
          1. 计算 `plan_hash`；
          2. 已存在 → 读回比对字节：相同返回 `created_new=False`；不同 → `PlanStoreCorrupt`
             （**绝不覆盖**已冻结计划）；
          3. 不存在 → 写临时文件 + `os.replace` 原子改名（Windows 上同卷原子）；
             临时文件名可含 pid（它不进入计划正文，因此不影响哈希）。

        副作用：创建文件。错误：见 `PlanStoreCorrupt` / `FreezeRefused`。
        """
        # LIB: hashlib.sha256(data).hexdigest(); open(tmp, "xb"); os.replace(tmp, path)
        raise NotImplementedError("P7 伪代码：原子写入由落地阶段实现")


# ---------------------------------------------------------------------------
# 6. 冻结
# ---------------------------------------------------------------------------
def freeze_plan(
    *,
    store: PlanStore,
    body: Mapping[str, object],
    task_id: str,
    failed_node: str,
    actor: str,
    correlation_id: str,
    rule_version: str,
    canonical_bytes: Callable[[object], bytes],
    clock: ClockPort,
    audit: FreezeAuditPort,
) -> FrozenPlan:
    """规范化 → 哈希 → 落盘 → 写冻结审计。

    步骤：
      1. `canonical_plan_bytes`（版本 + 时间检查 + JCS）；
      2. `plan_hash = sha256(bytes)`；`plan_id = plan_id_for(plan_hash)`；
      3. `store.put(bytes)`（幂等；冲突即拒绝）；
      4. 组装 `FreezeRecord`（`frozen_at` 来自时钟，**只进审计**）；
      5. `audit.append(record)`；失败 → `FreezeRefused(AUDIT_WRITE_FAILED)`，并保留文件
         （文件留下不会造成错误放行：没有冻结记录，守卫 2 必失败）。

    输入：存储、正文、任务/节点/审计字段、canonicalizer、时钟、审计端口。
    输出：`FrozenPlan`。
    副作用：写一个文件 + 追加一条审计（由端口实现）。
    错误：正文不合规 → `SCHEMA_INVALID`；审计不可用 → `AUDIT_WRITE_FAILED`。
    """
    data = canonical_plan_bytes(body, canonical_bytes=canonical_bytes)
    plan_hash = plan_hash_of(data)
    plan_id = plan_id_for(plan_hash)
    path, created_new = _put(store, data)
    record = FreezeRecord(
        plan_id=plan_id,
        plan_hash=plan_hash,
        task_id=task_id,
        node_id=failed_node,
        actor=actor,
        correlation_id=correlation_id,
        rule_version=rule_version,
        frozen_at=clock.now_utc(),
    )
    try:
        audit.append(record)
    except Exception as exc:  # 审计写失败：计划不可用（守卫 2/3 无法满足）
        raise FreezeRefused(
            "AUDIT_WRITE_FAILED",
            f"冻结审计不可用（{type(exc).__name__}）：没有冻结记录的计划不得复用",
        ) from exc
    return FrozenPlan(
        plan_id=plan_id,
        plan_hash=plan_hash,
        path=path,
        created_new=created_new,
        frozen_at=record.frozen_at,
    )


def _put(store: PlanStore, data: bytes) -> tuple[str, bool]:
    """`store.put` 的结构化包装（把返回值拆成 path + created_new）。"""
    plan_hash, path, created_new = store.put(data)
    if plan_hash != plan_hash_of(data):
        raise PlanStoreCorrupt("store.put 返回的 plan_hash 与字节不符")
    return path, created_new


# ---------------------------------------------------------------------------
# 7. 三条守卫
# ---------------------------------------------------------------------------
def guard_plan_file_present(store: PlanStore, plan_hash: str) -> None:
    """守卫 ①：计划文件存在且可读。

    失败 → `PlanGuardDenied(PLAN_FILE_MISSING)`。
    """
    if not store.exists(plan_hash):
        raise PlanGuardDenied("PLAN_FILE_MISSING", f"内容寻址路径上没有计划文件：{plan_hash}")


def guard_plan_hash_matches(
    store: PlanStore, plan_hash: str, freeze_record: FreezeRecord | None
) -> None:
    """守卫 ②：`sha256(文件字节) == plan_hash`，且与冻结记录一致。

    判定顺序（每步各自一个 reason，便于负例断言）：
      1. 冻结记录缺失 → `PLAN_FREEZE_RECORD_MISSING`；
      2. 记录里的 `plan_hash` 与请求不一致 → `PLAN_HASH_MISMATCH`；
      3. 记录里的 `plan_id` 与请求不一致 → `PLAN_ID_MISMATCH`；
      4. 文件字节重算的哈希与 `plan_hash` 不一致 → `PLAN_HASH_MISMATCH`。

    注意：**不得**用 `mtime`/文件大小代替内容哈希（ADR-004 §5 明确禁止）。
    """
    if freeze_record is None:
        raise PlanGuardDenied(
            "PLAN_FREEZE_RECORD_MISSING", f"audit_log 中没有 {plan_hash} 的冻结记录"
        )
    if freeze_record.plan_hash != plan_hash:
        raise PlanGuardDenied(
            "PLAN_HASH_MISMATCH",
            f"冻结记录的 plan_hash={freeze_record.plan_hash} ≠ 请求 {plan_hash}",
        )
    if freeze_record.plan_id != plan_id_for(plan_hash):
        raise PlanGuardDenied(
            "PLAN_ID_MISMATCH",
            f"冻结记录 plan_id={freeze_record.plan_id} ≠ {plan_id_for(plan_hash)}",
        )
    data = store.read(plan_hash)
    actual = plan_hash_of(data)
    if actual != plan_hash:
        raise PlanGuardDenied(
            "PLAN_HASH_MISMATCH", f"sha256(文件字节)={actual} ≠ plan_hash={plan_hash}"
        )


def _normalize_utc(text: str) -> str:
    """把 `Z` / `+00:00`、0–9 位小数的 UTC 时间规范成**固定 30 字符**形态（小数补足 9 位、统一 `Z` 结尾）。

    这不是 `ClockPort.now_utc()` 的输入契约（输入契约见 `ClockPort` 的 docstring），而是**比较专用**的规范形态：
    两侧同形态、定长，字典序才等于时间序。

    为什么需要：`2026-11-11T09:00:00Z` 与 `2026-11-11T09:00:00+00:00` 是同一时刻，
    但字符串比较里 `'Z' > '+'`，直接比会把“同刻冻结”判成“冻结更晚”，
    从而在守卫 3 上产生一个**放行方向相反**的漏洞（冻结在重跑之后却通过）。
    规范化后再比较，才不会因时区写法或小数位数不同而失真。
    """
    match = re.match(
        r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|\+00:00)$", text
    )
    if match is None:
        raise PlanGuardDenied("PLAN_FROZEN_AFTER_RERUN", f"时间形态非法：{text!r}")
    date_part, time_part, fraction, _suffix = match.groups()
    padded = (fraction or "").ljust(9, "0")[:9]
    return f"{date_part}T{time_part}.{padded}Z"


def guard_frozen_before_rerun(freeze_record: FreezeRecord, rerun_requested_at: str) -> None:
    """守卫 ③：冻结事件**严格早于**本次重跑尝试。

    输入：冻结记录的 `frozen_at`、本次重跑请求时间（UTC，`Z` 或 `+00:00`）。
    比较方式：先规范化到**固定 30 字符** `...Z`，再字符串比较（ENCODING_RULES §3：定长时字典序 = 时间序）。
    失败：相等（同一时刻无法证明“先冻结”）或冻结更晚 → `PLAN_FROZEN_AFTER_RERUN`。
    异常：时间形态不合法 → 直接拒绝（不得“格式不对就放行”）。
    """
    frozen = _normalize_utc(freeze_record.frozen_at)
    rerun = _normalize_utc(rerun_requested_at)
    if not frozen < rerun:
        raise PlanGuardDenied(
            "PLAN_FROZEN_AFTER_RERUN",
            f"冻结时间 {freeze_record.frozen_at} 不早于重跑请求 {rerun_requested_at}",
        )


def verify_three_guards(
    *,
    store: PlanStore,
    plan_hash: str,
    freeze_record: FreezeRecord | None,
    rerun_requested_at: str,
) -> GuardReport:
    """按 1→2→3 执行三条守卫，返回报告（不抛异常）。

    与 `verify_three_guards_strict` 的分工：本函数给**审计/日志**用（要报告），
    StateMachine 的守卫给**判定**用（要异常）。二者判定条件必须一致。
    """
    checked: list[str] = []
    checks: tuple[tuple[str, Callable[[], None]], ...] = (
        ("PLAN_FILE_PRESENT", lambda: guard_plan_file_present(store, plan_hash)),
        ("PLAN_HASH_MATCHES", lambda: guard_plan_hash_matches(store, plan_hash, freeze_record)),
        ("FROZEN_BEFORE_RERUN", lambda: guard_frozen_before_rerun(
            _require_record(freeze_record), rerun_requested_at
        )),
    )
    for name, check in checks:
        try:
            check()
        except PlanGuardDenied as denied:
            return GuardReport(
                passed=False,
                checked_steps=tuple(checked),
                failure_reason=denied.reason,
                failure_detail=denied.detail,
            )
        checked.append(name)
    return GuardReport(passed=True, checked_steps=tuple(checked))


def _require_record(record: FreezeRecord | None) -> FreezeRecord:
    """守卫 3 需要记录；若守卫 2 已失败则不会走到这里，这里只处理“直接调用”的情况。"""
    if record is None:
        raise PlanGuardDenied("PLAN_FREEZE_RECORD_MISSING", "缺少冻结记录，无法比较冻结时间")
    return record


# ---------------------------------------------------------------------------
# 8. 自检
# ---------------------------------------------------------------------------
def assert_hash_stability_contract() -> list[str]:
    """验收判据 3 的自检：七条稳定性论证都有对应实现锚点。

    返回缺失项（空 = 通过）。检查的是“机制存在”，不是“已实测”：
    真实两次生成比对见 NEG-M14-07 / GUARD-M14-01，必须落地后执行。
    """
    problems: list[str] = []
    if len(HASH_STABILITY_ARGUMENT) != 7:
        problems.append("稳定性论证必须恰好 7 条")
    if not PLAN_HASH_RE.match("0" * 64):
        problems.append("plan_hash 形态正则错误")
    if PLAN_HASH_RE.match("0" * 63) or PLAN_HASH_RE.match("A" * 64):
        problems.append("plan_hash 形态正则过宽（长度/大小写必须严格）")
    try:
        assert_store_root("relative/path")
    except FreezeRefused:
        pass
    else:
        problems.append("相对路径的 plan_store_root 未被拒绝")
    # 正文时间检查必须同时覆盖键名与值（这里断言“确实报出问题”，而不是把问题本身当失败）
    if not assert_body_time_free({"plan_format_version": PLAN_FORMAT_VERSION, "frozen_at": "x"}):
        problems.append("正文时间检查未覆盖键名")
    if not assert_body_time_free(
        {"plan_format_version": PLAN_FORMAT_VERSION, "note": "2026-11-11T09:00:00Z"}
    ):
        problems.append("正文时间检查未覆盖值")
    # 版本不符必须拒绝（不得“先冻结再解释”）
    try:
        canonical_plan_bytes({"plan_format_version": "9.9"}, canonical_bytes=lambda body: b"")
    except FreezeRefused:
        pass
    else:
        problems.append("未知 plan_format_version 未被拒绝")
    # plan_id 必须等于 plan_hash（不新造前缀）
    sample = "a" * 64
    if plan_id_for(sample) != sample:
        problems.append("plan_id 必须等于 plan_hash")
    return problems


def assert_reproducible(
    make_body: Callable[[], Mapping[str, object]],
    *,
    canonical_bytes: Callable[[object], bytes],
    expected_hash: str | None = None,
) -> list[str]:
    """同一输入生成两次，比较规范化字节与哈希。

    返回问题列表（空 = 通过）：
      1. 两次 `canonical_bytes` 必须逐字节相同；
      2. 两次 `plan_hash` 必须相同；
      3. 若给了 `expected_hash`，必须相等（防止“两次都错但一致”）。

    这只是**进程内**复现；跨进程/跨机器复现还需要 JCS 与哈希实现一致（P6 已冻结口径）。
    """
    first = canonical_plan_bytes(make_body(), canonical_bytes=canonical_bytes)
    second = canonical_plan_bytes(make_body(), canonical_bytes=canonical_bytes)
    problems: list[str] = []
    if first != second:
        problems.append("同一输入两次规范化得到不同字节")
    first_hash = plan_hash_of(first)
    if first_hash != plan_hash_of(second):
        problems.append("同一输入两次得到不同 plan_hash")
    if expected_hash is not None and first_hash != expected_hash:
        problems.append(f"plan_hash 与期望值不符：{first_hash} ≠ {expected_hash}")
    return problems


def assert_guard_is_not_a_bypass() -> list[str]:
    """自检：本文件不得提供绕过 StateMachine 的状态变更。

    检查项：
      1. `PlanStore` / `FrozenPlan` 没有 `set_state` / `transition` / `mark_*`；
      2. 模块没有仓储/连接对象；
      3. `FreezeRecord` 携带 `previous_state`/`next_state` 之类的状态字段 → 说明越界。
    """
    problems: list[str] = []
    for forbidden in ("transition", "set_state", "mark_verified", "mark_ready", "apply_transition"):
        if hasattr(PlanStore, forbidden):
            problems.append(f"PlanStore 不得暴露 {forbidden}()")
    for forbidden in ("conn", "connection", "repository", "machine", "session"):
        if forbidden in globals():
            problems.append(f"冻结模块不得持有 {forbidden}")
    record_fields = set(FreezeRecord.__dataclass_fields__)
    for forbidden in ("previous_state", "next_state", "state"):
        if forbidden in record_fields:
            problems.append(f"FreezeRecord 不得含字段 {forbidden}")
    return problems


def assert_no_approval_state() -> list[str]:
    """自检：T0 的冻结产物里没有审批状态、没有审批字段。"""
    problems: list[str] = []
    for name, value in globals().items():
        if name.startswith("__"):
            continue
        if isinstance(value, str) and value in {
            "PROPOSED", "APPROVED", "EXECUTING", "RECHECKED", "CLOSED",
        }:
            problems.append(f"模块级常量 {name} 出现审批状态 {value}")
    for field in set(FrozenPlan.__dataclass_fields__) | set(FreezeRecord.__dataclass_fields__):
        if "approv" in field.lower() or field.lower() in {"state", "status"}:
            problems.append(f"冻结产物不得有审批/状态字段：{field}")
    if FreezeRecord.__dataclass_fields__["action"].default != "RECOVERY_PLAN_FROZEN":
        problems.append("审计动作必须是 RECOVERY_PLAN_FROZEN")
    return problems