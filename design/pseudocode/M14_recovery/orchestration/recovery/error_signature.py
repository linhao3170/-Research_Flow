"""M14 · orchestration/recovery/error_signature.py — 错误签名与分类（P7 伪代码）。
阶段：P7「调度与定向恢复」｜追踪：FR-010（T0 最小切片：失败 → 恢复）、策划书 §8.4 / P0201–P0214
依赖：M05 `AttemptDisposition` / `ExecutorFault`（字面值）、M03 `LimitKind`、M01 错误码注册表、M01 `canonical_bytes`（仅签名键）
不变量：签名只由**封闭枚举字段**构成；路径、时间、pid、主机名、堆栈、随机量一律不得进入；
        同一失败两次得到同一签名（否则 `plan_hash` 不稳定，违反 ADR-004 §3）
错误码：SCHEMA_INVALID（422，`detail.reason=ERROR_SIGNATURE_INPUT_INVALID`）
写入者：无（纯函数；不读日志、不解析堆栈、不连数据库）
状态：伪代码；不执行、不写计划

## 为什么签名必须“无时间、无路径”

  签名会进入恢复计划正文，而计划正文要算 `plan_hash`（ADR-004 §3：正文不得含时间戳/随机序）。
  如果签名里掺了 `C:\\...\\tmpabc123\\stderr.log` 或 `2026-11-11T09:00:01Z`，
  同一失败重算就会得到不同的计划哈希，`INVALIDATED→READY` 的三条守卫永远过不了。
  因此本文件只接受**分类后的桶**（`message_class`），永远不接受原始异常文本。

## 六类分类的判定顺序（固定，不得调整）

  `RESOURCE → PROTOCOL → INPUT → DATA → CODE → UNKNOWN`

  顺序本身就是策略：内存超限同时表现为“模板非 0 退出”时，必须先判 RESOURCE
  （否则重跑只会再 OOM 一次）；链路断裂同时伴随空产物时，必须先判 PROTOCOL
  （否则会把“链断了”误判成“数据坏了”）。

## 每类的可重试性（决定 T0 能不能生成重跑计划）

  | 类别 | 可重试性 | 理由 |
  |---|---|---|
  | `RESOURCE` | `RETRYABLE` | 资源压力可外部解除（Governor 减压/加预算），同一输入重跑有机会成功 |
  | `DATA` | `RETRYABLE_AFTER_FIX` | 数据/产物内容错了；**必须证明输入已变**才值得重跑，否则重复失败 |
  | `CODE` | `RETRYABLE_AFTER_FIX` | 模板/注册表/代码要改；T0 无法证明改动已发生 → 不自动重跑 |
  | `PROTOCOL` | `NOT_RETRYABLE` | 链断/序列缺口/声明违约重跑不会修复，必须先排查 |
  | `INPUT` | `NOT_RETRYABLE` | TaskSpec/参数错；改输入属新任务或图变更，不是重跑 |
  | `UNKNOWN` | `UNKNOWN_CONSERVATIVE` | 未知失败不得自动重跑；升级处理 |
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Callable, Final, Mapping

__all__ = [
    "CATEGORY_POLICY",
    "CLASSIFICATION_ORDER",
    "ExitCodeClass",
    "ErrorCategory",
    "ErrorSignature",
    "FailureInput",
    "MessageClass",
    "Retryability",
    "SignatureInputInvalid",
    "VOLATILE_PATTERNS",
    "assert_classification_total",
    "assert_no_volatile_fields",
    "classify",
    "classify_message",
    "signature_from_failure",
]

# ---------------------------------------------------------------------------
# 1. 枚举
# ---------------------------------------------------------------------------
class ErrorCategory(StrEnum):
    """六类失败。值即计划正文里的字面值，不得改名（改名会改变 plan_hash）。"""

    DATA = "DATA"
    CODE = "CODE"
    RESOURCE = "RESOURCE"
    PROTOCOL = "PROTOCOL"
    INPUT = "INPUT"
    UNKNOWN = "UNKNOWN"


class Retryability(StrEnum):
    RETRYABLE = "RETRYABLE"
    RETRYABLE_AFTER_FIX = "RETRYABLE_AFTER_FIX"
    NOT_RETRYABLE = "NOT_RETRYABLE"
    UNKNOWN_CONSERVATIVE = "UNKNOWN_CONSERVATIVE"


class ExitCodeClass(StrEnum):
    """退出码的**分类**，不是退出码本身（否则签名会随 exit_code=1..255 爆炸）。"""

    ZERO = "ZERO"
    NONZERO = "NONZERO"
    NONE = "NONE"          # 没有退出码（超时/启动失败/回收失败）

    @classmethod
    def of(cls, exit_code: int | None) -> "ExitCodeClass":
        if exit_code is None:
            return cls.NONE
        return cls.ZERO if exit_code == 0 else cls.NONZERO


class MessageClass(StrEnum):
    """异常文本的**分类桶**。原始文本永远不得进入签名。

    分桶规则见 `classify_message()`：只按关键字归桶，命中不了就是 `OTHER`。
    这样 `FileNotFoundError: C:\\tmp\\x1\\data.csv` 与 `... C:\\tmp\\x2\\data.csv`
    会得到同一个桶，计划哈希因此稳定。
    """

    TASK_SPEC = "TASK_SPEC"
    PARAMS = "PARAMS"
    DATASET = "DATASET"
    SPLIT_MANIFEST = "SPLIT_MANIFEST"
    TEMPLATE = "TEMPLATE"
    EVIDENCE = "EVIDENCE"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# 2. 失败输入（**只接受封闭字段**）
# ---------------------------------------------------------------------------
class SignatureInputInvalid(RuntimeError):
    """签名输入不合法（未知枚举值、自由文本混入）。"""

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422
    reason: Final[str] = "ERROR_SIGNATURE_INPUT_INVALID"

    def __init__(self, field: str, detail: str) -> None:
        self.field = field
        self.detail = detail
        super().__init__(f"{self.error_code}/{self.reason}：{field} {detail}")


@dataclass(frozen=True, slots=True)
class FailureInput:
    """一次失败的**可分类事实**。

    所有字段都是封闭取值：错误码/处置/退出码/限额维度/故障码/消息桶。
    这里**没有** `message`、`stderr`、`path`、`timestamp`、`pid` 槽位 ——
    想加这些字段必须先改本 dataclass，那会在评审时暴露。
    """

    error_code: str | None
    disposition: str
    exit_code: int | None = None
    limit_kind: str | None = None
    fault_code: str | None = None
    message_class: str = MessageClass.OTHER.value

    def __post_init__(self) -> None:
        if not self.disposition:
            raise SignatureInputInvalid("disposition", "不得为空")
        if self.error_code is not None and not _CODE_RE.match(self.error_code):
            raise SignatureInputInvalid("error_code", f"形态非法：{self.error_code!r}")
        if self.limit_kind is not None and self.limit_kind not in _LIMIT_KINDS:
            raise SignatureInputInvalid("limit_kind", f"未登记维度：{self.limit_kind!r}")
        if self.message_class not in _MESSAGE_CLASSES:
            raise SignatureInputInvalid("message_class", f"未登记桶：{self.message_class!r}")
        if self.exit_code is not None and not isinstance(self.exit_code, int):
            raise SignatureInputInvalid("exit_code", "必须是整数或 None")
        if isinstance(self.exit_code, bool):
            raise SignatureInputInvalid("exit_code", "bool 不是退出码")


# 注册表/内部码的形态：大写下划线。不接受自由文本来“凑”一个码。
_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

# 与 M03 limits.LimitKind 的字面值一致（不 import，避免跨模块运行期依赖）。
_LIMIT_KINDS: Final[frozenset[str]] = frozenset(
    {"token", "wall_clock", "concurrency", "memory", "disk", "retry"}
)

_MESSAGE_CLASSES: Final[frozenset[str]] = frozenset(member.value for member in MessageClass)

# 与 M05 AttemptDisposition 的字面值一致。
_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "EXITED", "TIMED_OUT", "CANCELLED", "LAUNCH_FAILED", "TEMPLATE_ERROR",
        "ARTIFACT_ERROR", "RECLAIM_FAILED", "WORKSPACE_ERROR", "PRECHECK_FAILED",
    }
)

# 与 M05 ExecutorFault 的字面值一致。
_FAULT_CODES: Final[frozenset[str]] = frozenset(
    {
        "TEMPLATE_NOT_REGISTERED", "NODE_TYPE_MISMATCH", "PARAM_SCHEMA_VIOLATION",
        "PARAMS_HASH_MISMATCH", "ATTEMPT_ID_REUSED", "WORKSPACE_ESCAPE",
        "WORKSPACE_NOT_WRITABLE", "PROCESS_ISOLATION_UNAVAILABLE", "PROCESS_LAUNCH_FAILED",
        "PROCESS_WAIT_FAILED", "WALL_CLOCK_EXCEEDED", "PROCESS_TREE_KILL_FAILED",
        "PROCESS_RESIDUAL_PROCESSES", "ARTIFACT_UNDECLARED", "ARTIFACT_OUTSIDE_WORKSPACE",
        "ARTIFACT_TOO_MANY", "ARTIFACT_TOO_LARGE", "ARTIFACT_HASH_FAILED",
        "COLLECTOR_UNAVAILABLE", "SAMPLING_FAILED", "EXECUTION_CANCELLED",
    }
)


# ---------------------------------------------------------------------------
# 3. 类别策略与判定顺序
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CategoryPolicy:
    """一个类别的可重试性、理由与依据。"""

    category: ErrorCategory
    retryability: Retryability
    rationale: str
    source: str

    @property
    def plan_eligible_in_t0(self) -> bool:
        """T0 是否允许为这类失败生成重跑计划。

        只有 `RESOURCE` 是“T0 可证明的最小集”：其它类别要重跑必须先证明
        “修复已发生/输入已变”，而 T0 没有这个证据端口（见 OQ-P7-12）。
        """
        return self.category is ErrorCategory.RESOURCE


CATEGORY_POLICY: Final[Mapping[ErrorCategory, CategoryPolicy]] = MappingProxyType(
    {
        ErrorCategory.DATA: CategoryPolicy(
            category=ErrorCategory.DATA,
            retryability=Retryability.RETRYABLE_AFTER_FIX,
            rationale="数据/产物内容错误；同一输入重跑会重复失败，必须先证明输入或前驱已变",
            source="策划书 §8.4（not evidence_valid / not disk_rehash_matches 分支）",
        ),
        ErrorCategory.CODE: CategoryPolicy(
            category=ErrorCategory.CODE,
            retryability=Retryability.RETRYABLE_AFTER_FIX,
            rationale="模板/注册表/代码契约问题；重跑前必须完成修复并重新登记",
            source="FR-004；M05 ExecutorFault；策划书 §8.4（not retryable → escalate）",
        ),
        ErrorCategory.RESOURCE: CategoryPolicy(
            category=ErrorCategory.RESOURCE,
            retryability=Retryability.RETRYABLE,
            rationale="资源压力可由 Governor 减压或加预算解除；同一输入重跑有机会成功",
            source="NFR-06；M03 limits；策划书 §8.6",
        ),
        ErrorCategory.PROTOCOL: CategoryPolicy(
            category=ErrorCategory.PROTOCOL,
            retryability=Retryability.NOT_RETRYABLE,
            rationale="证据链/事件序列/产物声明违约重跑不会修复，必须先排查事实源",
            source="05 §4.3/§13；M07 Collector；I-14",
        ),
        ErrorCategory.INPUT: CategoryPolicy(
            category=ErrorCategory.INPUT,
            retryability=Retryability.NOT_RETRYABLE,
            rationale="TaskSpec/参数/数据集登记错误；改输入属新任务或图变更，不是重跑",
            source="FR-001；05 §2.1；OQ-CT-08",
        ),
        ErrorCategory.UNKNOWN: CategoryPolicy(
            category=ErrorCategory.UNKNOWN,
            retryability=Retryability.UNKNOWN_CONSERVATIVE,
            rationale="未识别的失败不得自动重跑；保留事实并升级处理",
            source="AGENTS §8（不得用推测补齐）；05 §9.3（无授权边不得迁移）",
        ),
    }
)

# 判定顺序（写死；测试按此顺序断言“不误判”）。
CLASSIFICATION_ORDER: Final[tuple[ErrorCategory, ...]] = (
    ErrorCategory.RESOURCE,
    ErrorCategory.PROTOCOL,
    ErrorCategory.INPUT,
    ErrorCategory.DATA,
    ErrorCategory.CODE,
    ErrorCategory.UNKNOWN,
)

# 协议类：链/序列/包完整性错误码（M01 内部码）。
# `BUNDLE_TAMPERED` 归这里而不是 DATA：它表示“证据契约被破坏”（哈希/Merkle/清单不符），
# 不是“数据内容漂移”；重跑不会修复被改过的包。
_PROTOCOL_CODES: Final[frozenset[str]] = frozenset(
    {"EVIDENCE_CHAIN_BROKEN", "EVENT_SEQ_GAP", "EVENT_SEQ_REGRESSION", "BUNDLE_TAMPERED"}
)
# 输入类：契约/参数错误码
_INPUT_CODES: Final[frozenset[str]] = frozenset({"SCHEMA_INVALID"})
# 代码/权限类
_CODE_CODES: Final[frozenset[str]] = frozenset({"TOOL_NOT_ALLOWLISTED"})
# 资源类错误码
_RESOURCE_CODES: Final[frozenset[str]] = frozenset({"RESOURCE_BUDGET_EXCEEDED"})

_PROTOCOL_FAULTS: Final[frozenset[str]] = frozenset(
    {
        "ARTIFACT_UNDECLARED", "ARTIFACT_OUTSIDE_WORKSPACE", "ARTIFACT_TOO_MANY",
        "COLLECTOR_UNAVAILABLE",
    }
)
_CODE_FAULTS: Final[frozenset[str]] = frozenset(
    {
        "TEMPLATE_NOT_REGISTERED", "NODE_TYPE_MISMATCH", "ATTEMPT_ID_REUSED",
        "PROCESS_ISOLATION_UNAVAILABLE", "PROCESS_LAUNCH_FAILED", "PROCESS_WAIT_FAILED",
        "WORKSPACE_ESCAPE", "WORKSPACE_NOT_WRITABLE", "SAMPLING_FAILED",
    }
)
_RESOURCE_FAULTS: Final[frozenset[str]] = frozenset(
    {
        "WALL_CLOCK_EXCEEDED", "PROCESS_TREE_KILL_FAILED", "PROCESS_RESIDUAL_PROCESSES",
        "ARTIFACT_TOO_LARGE",
    }
)
_INPUT_FAULTS: Final[frozenset[str]] = frozenset(
    {"PARAM_SCHEMA_VIOLATION", "PARAMS_HASH_MISMATCH"}
)
_DATA_FAULTS: Final[frozenset[str]] = frozenset({"ARTIFACT_HASH_FAILED"})


# ---------------------------------------------------------------------------
# 4. 消息分桶（唯一允许把“文本”变成签名的通道）
# ---------------------------------------------------------------------------
# 关键字 → 桶。只做包含匹配，大小写不敏感；命中多个时按本表顺序（首个命中）。
_MESSAGE_RULES: Final[tuple[tuple[str, MessageClass], ...]] = (
    ("split", MessageClass.SPLIT_MANIFEST),
    ("manifest", MessageClass.SPLIT_MANIFEST),
    ("dataset", MessageClass.DATASET),
    ("data/", MessageClass.DATASET),
    ("parameter", MessageClass.PARAMS),
    ("params", MessageClass.PARAMS),
    ("seed", MessageClass.PARAMS),
    ("taskspec", MessageClass.TASK_SPEC),
    ("task_spec", MessageClass.TASK_SPEC),
    ("template", MessageClass.TEMPLATE),
    ("evidence", MessageClass.EVIDENCE),
    ("chain", MessageClass.EVIDENCE),
)


def classify_message(text: str) -> str:
    """把任意异常文本映射成 `MessageClass` 桶名。**永不返回原文**。

    输入：任意文本（可以为空、可以是路径或带时间戳）。
    输出：`MessageClass` 的 value（`OTHER` 兜底）。
    副作用：无。
    错误：非字符串 → `SignatureInputInvalid`。
    """
    if not isinstance(text, str):
        raise SignatureInputInvalid("message", "必须是字符串")
    lowered = text.lower()
    for needle, bucket in _MESSAGE_RULES:
        if needle in lowered:
            return bucket.value
    return MessageClass.OTHER.value


# 易变内容模式：用于自检“签名里不许出现这些”。
VOLATILE_PATTERNS: Final[tuple[str, ...]] = (
    r"[A-Za-z]:\\",                                  # Windows 绝对路径
    r"/(?:home|Users|tmp|var|workspace)/",           # POSIX 绝对路径
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",        # RFC3339 时间
    r"\bpid[=: ]\d+",                                # 进程号
    r"\b0x[0-9a-fA-F]{6,}\b",                        # 内存地址
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",  # 随机 UUID
)


# ---------------------------------------------------------------------------
# 5. 签名
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ErrorSignature:
    """一个失败的稳定签名。

    字段顺序固定（`key_material()` 按此顺序返回），不含时间/路径/pid。
    `signature_key` 不是字段：它必须由 M01 `canonical_bytes` 计算（避免自创规范化）。
    """

    category: ErrorCategory
    retryability: Retryability
    error_code: str | None
    disposition: str
    exit_code_class: ExitCodeClass
    limit_kind: str | None
    fault_code: str | None
    message_class: str

    def key_material(self) -> Mapping[str, object]:
        """签名前像：固定键序的 mapping（交给 M01 canonical_bytes → JCS）。

        键序即 `ErrorSignature` 的字段序；不含任何自由文本。
        """
        return MappingProxyType(
            {
                "category": self.category.value,
                "retryability": self.retryability.value,
                "error_code": self.error_code,
                "disposition": self.disposition,
                "exit_code_class": self.exit_code_class.value,
                "limit_kind": self.limit_kind,
                "fault_code": self.fault_code,
                "message_class": self.message_class,
            }
        )

    def signature_key(self, *, canonical_bytes: Callable[[object], bytes]) -> str:
        """`sha256(canonical_bytes(key_material()))`，64 位小写十六进制。

        输入：M01 `canonical_bytes`（JCS 规范化，RFC 8785）。
        输出：签名字符串。
        副作用：无。
        错误：`canonical_bytes` 抛出时原样上抛（不得回退到 `json.dumps`）。
        """
        # LIB: hashlib.sha256(canonical_bytes(self.key_material())).hexdigest()
        raise NotImplementedError("P7 伪代码：签名键由 M01 canonical_bytes + hashlib 落地")

    @property
    def plan_eligible_in_t0(self) -> bool:
        return CATEGORY_POLICY[self.category].plan_eligible_in_t0

    def as_detail(self) -> Mapping[str, object]:
        return self.key_material()


def signature_from_failure(failure: FailureInput) -> ErrorSignature:
    """把失败事实分类成签名（**唯一的分类入口**）。

    步骤（顺序固定，见 `CLASSIFICATION_ORDER`）：
      1. RESOURCE：有 `limit_kind`、处置为 `TIMED_OUT`/`RECLAIM_FAILED`、或资源类故障码；
      2. PROTOCOL：链/序列错误码、产物声明违约、Collector 不可用；
      3. INPUT：`SCHEMA_INVALID` 或参数类故障码；
      4. DATA：产物哈希与记录不符（`ARTIFACT_HASH_FAILED`）；
      5. CODE：模板/工作区/隔离类故障码、`TOOL_NOT_ALLOWLISTED`、模板非 0 退出；
      6. UNKNOWN：其余（不猜）。`CANCELLED` 也落在这里：取消不是失败，不得自动重跑。

    输入：`FailureInput`。
    输出：`ErrorSignature`。
    副作用：无。
    错误：处置/故障码不在已登记集合内 → `SignatureInputInvalid`（不猜成 UNKNOWN：
          “码拼错了”和“失败未知”是两件事，混在一起会掩盖配置错误）。
    """
    # 步骤 0：处置与故障码必须是已登记字面值
    if failure.disposition not in _DISPOSITIONS:
        raise SignatureInputInvalid("disposition", f"未登记处置：{failure.disposition!r}")
    if failure.fault_code is not None and failure.fault_code not in _FAULT_CODES:
        raise SignatureInputInvalid("fault_code", f"未登记故障码：{failure.fault_code!r}")
    code = failure.error_code
    fault = failure.fault_code

    # 步骤 1：RESOURCE
    if (
        failure.limit_kind is not None
        or code in _RESOURCE_CODES
        or failure.disposition in ("TIMED_OUT", "RECLAIM_FAILED")
        or fault in _RESOURCE_FAULTS
    ):
        return _signature(ErrorCategory.RESOURCE, failure)
    # 步骤 2：PROTOCOL
    if code in _PROTOCOL_CODES or fault in _PROTOCOL_FAULTS:
        return _signature(ErrorCategory.PROTOCOL, failure)
    # 步骤 3：INPUT
    if code in _INPUT_CODES or fault in _INPUT_FAULTS:
        return _signature(ErrorCategory.INPUT, failure)
    # 步骤 4：DATA
    if fault in _DATA_FAULTS:
        return _signature(ErrorCategory.DATA, failure)
    # 步骤 5：CODE
    if (
        code in _CODE_CODES
        or fault in _CODE_FAULTS
        or failure.disposition in ("TEMPLATE_ERROR", "LAUNCH_FAILED", "WORKSPACE_ERROR",
                                   "PRECHECK_FAILED")
    ):
        return _signature(ErrorCategory.CODE, failure)
    # 步骤 6：UNKNOWN（保守：不自动重跑）
    return _signature(ErrorCategory.UNKNOWN, failure)


def classify(failure: FailureInput) -> ErrorCategory:
    """只要类别时的便捷函数（语义与 `signature_from_failure().category` 完全一致）。"""
    return signature_from_failure(failure).category


def _signature(category: ErrorCategory, failure: FailureInput) -> ErrorSignature:
    policy = CATEGORY_POLICY[category]
    return ErrorSignature(
        category=category,
        retryability=policy.retryability,
        error_code=failure.error_code,
        disposition=failure.disposition,
        exit_code_class=ExitCodeClass.of(failure.exit_code),
        limit_kind=failure.limit_kind,
        fault_code=failure.fault_code,
        message_class=failure.message_class,
    )


# ---------------------------------------------------------------------------
# 6. 自检
# ---------------------------------------------------------------------------
def assert_no_volatile_fields(signature: ErrorSignature) -> list[str]:
    """自检：签名前像里不得出现路径、时间、pid、地址、随机 UUID。

    对每个字段的字符串值跑 `VOLATILE_PATTERNS`；命中即违反。
    这条检查是「同一输入两次生成同一 plan_hash」的必要条件之一。
    """
    problems: list[str] = []
    for key, value in signature.key_material().items():
        if value is None:
            continue
        text = str(value)
        for pattern in VOLATILE_PATTERNS:
            if re.search(pattern, text):
                problems.append(f"签名字段 {key} 命中易变模式 {pattern}：{text!r}")
    if len(signature.key_material()) != 8:
        problems.append("签名前像必须恰好 8 个字段（固定键序）")
    return problems


def assert_classification_total() -> list[str]:
    """自检：分类表完备、顺序固定、每个故障码都落到某个类别。

    检查项：
      1. `CATEGORY_POLICY` 覆盖 6 类，每类都有非空理由；
      2. `CLASSIFICATION_ORDER` 与六个类别一一对应（顺序固定）；
      3. 每个已登记故障码都能被某个集合命中，或由处置分支覆盖；
      4. 未知故障码/未知错误码落到 UNKNOWN 而不是抛错（但拼错已知码的形态要抛）。
    """
    problems: list[str] = []
    if set(CATEGORY_POLICY) != set(ErrorCategory):
        problems.append("类别策略未覆盖全部六类")
    if set(CLASSIFICATION_ORDER) != set(ErrorCategory):
        problems.append("判定顺序与六类不一致")
    if len(CLASSIFICATION_ORDER) != 6:
        problems.append("判定顺序必须恰好 6 项")
    for code in CATEGORY_POLICY.values():
        if not code.rationale.strip():
            problems.append(f"类别 {code.category} 缺少理由")
    covered = (
        _PROTOCOL_CODES | _INPUT_CODES | _CODE_CODES | _RESOURCE_CODES
        | _PROTOCOL_FAULTS | _CODE_FAULTS | _RESOURCE_FAULTS | _INPUT_FAULTS | _DATA_FAULTS
    )
    missing = [fault for fault in _FAULT_CODES if fault not in covered
               and fault not in {"EXECUTION_CANCELLED"}]
    if missing:
        problems.append(f"故障码未归类：{missing}")
    # 拼错的已知形态必须抛错，而不是静默 UNKNOWN
    try:
        signature_from_failure(FailureInput(error_code=None, disposition="NOT_A_DISPOSITION"))
    except SignatureInputInvalid:
        pass
    else:
        problems.append("未登记处置竟然被接受")
    return problems