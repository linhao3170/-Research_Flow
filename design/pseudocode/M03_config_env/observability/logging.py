"""M03 · observability/logging.py — 日志字段、级别与脱敏（P1 伪代码）。

阶段：P1｜状态：字段表、级别语义、脱敏规则与检查点；不实现 logger。

来源：05 §9.7（审计二次失败降级单行 JSON stderr）、06 §4.4（不得回显堆栈/SQL/路径/密钥）、
06 §4.6（启动失败只说明原因，不回显配置值）、NFR-05/NFR-08、AGENTS §4（私钥不进日志）。

**不可协商的三条**：
  1. 私钥、token、密码、Cookie、Authorization 头**任何级别都不得落日志**（不是“默认关闭”，是没有该通路）。
  2. 原始数据集内容、请求/响应正文、模型原始输出**任何级别都不得落日志**；只允许哈希、行数、
     字节数和字段名。
  3. 绝对路径默认不落；必须落时先归一（项目根 → `<project>`，用户目录 → `<home>`）。

脱敏是**丢弃**而不是“打码后保留”：命中禁写键的字段整键删除，并在 `redactions` 计数；
命中值模式的字符串用 `<redacted>` 替换并置 `redaction_applied=true`。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Mapping

__all__ = [
    "ALLOWED_EXTRA_KEYS",
    "DENY_KEY_TOKENS",
    "DENY_VALUE_PATTERNS",
    "FORBIDDEN_CONTENT",
    "LOG_FIELDS",
    "LOG_LEVELS",
    "REDACTED",
    "Level",
    "LogField",
    "PathScope",
    "assert_log_safe",
    "normalize_path",
    "redact_event",
]


class Level(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


LOG_LEVELS: Final[tuple[Level, ...]] = (
    Level.DEBUG, Level.INFO, Level.WARNING, Level.ERROR, Level.CRITICAL,
)

LEVEL_SEMANTICS: Final[Mapping[Level, str]] = {
    Level.DEBUG: "开发定位；默认不开启；仍受全部脱敏规则约束（不得借 DEBUG 输出原始数据）",
    Level.INFO: "正常运行里程碑：启动、加载配置、状态迁移摘要、任务/节点状态变化",
    Level.WARNING: "可继续但已降级：重试、水位接近上限、缺项告警、缺口受理",
    Level.ERROR: "单次操作失败：校验失败、签发失败、启动被拒（拒绝启动也要留一条）",
    Level.CRITICAL: "完整性/安全事件：链断裂、指纹不一致、审计写入降级、信任锚缺失",
}


@dataclass(frozen=True, slots=True)
class LogField:
    name: str
    type_expr: str
    required: bool
    note: str


LOG_FIELDS: Final[tuple[LogField, ...]] = (
    LogField("ts", "str (UTC RFC3339, 微秒 + Z)", True, "写入时刻；不得用本地时间"),
    LogField("level", 'str (enum: DEBUG/INFO/WARNING/ERROR/CRITICAL)', True, "级别；不得自定义级别"),
    LogField("component", "str (snake_case)", True, "产生日志的组件：api/state_machine/collector/gate/verifier/config…"),
    LogField("event", "str (UPPER_SNAKE)", True, "事件名；与 audit_events.py 的动作名可对齐但不等同（日志不是审计）"),
    LogField("correlation_id", "str", True, "请求/迁移/attempt 关联 ID；无关联时用 trace_id，不得留空"),
    LogField("message", "str (已脱敏)", True, "人类可读摘要；不得含密钥、原始数据、绝对路径"),
    LogField("task_id", "str (task_<uuid>)", False, "有任务上下文时必填"),
    LogField("node_id", "str", False, "有节点上下文时必填"),
    LogField("attempt_id", "str (attempt_NN)", False, "有执行上下文时必填"),
    LogField("evidence_id", "str (ev_<uuid>)", False, "涉及具体证据时填写"),
    LogField("code", "str (errors.py 已注册)", False, "失败时必须是注册表里的码，不得自造"),
    LogField("field_path", "str (JSON Pointer 风格)", False, "SCHEMA_INVALID/CONFIG_* 时填写"),
    LogField("limit_kind", 'str (token/wall_clock/concurrency/memory/disk/retry)', False, "RESOURCE_BUDGET_EXCEEDED 的子类"),
    LogField("redactions", "int (>=0)", False, "本次丢弃/替换的敏感字段数；>0 时必须有"),
    LogField("redaction_applied", "bool", False, "是否发生替换"),
    LogField("exc_type", "str", False, "异常类名；不含异常消息中的敏感值"),
)

ALLOWED_EXTRA_KEYS: Final[frozenset[str]] = frozenset(
    {"duration_ms", "status", "http_status", "route", "ruleset_hash", "env_digest", "queue_depth"}
)

REDACTED: Final[str] = "<redacted>"

# 命中任一 token（大小写不敏感、按子串）即整键丢弃。
DENY_KEY_TOKENS: Final[tuple[str, ...]] = (
    "token",
    "secret",
    "password",
    "passwd",
    "private_key",
    "privatekey",
    "private_bytes",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "credential",
    "session_key",
    "seed_phrase",
    "raw_data",
    "rawdata",
    "dataset_content",
    "file_content",
    "request_body",
    "response_body",
    "payload",
    "rows",
    "dataframe",
)

# 命中值模式即替换；这些模式覆盖“键名无害但值敏感”的情况。
DENY_VALUE_PATTERNS: Final[tuple[str, ...]] = (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}",
    r"(?i)\bsk-[A-Za-z0-9]{16,}",
    r"(?i)\bghp_[A-Za-z0-9]{20,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",  # JWT
)

FORBIDDEN_CONTENT: Final[tuple[str, ...]] = (
    "私钥/PEM/助记词/密钥材料（任何级别）",
    "访问 token、API key、Authorization/Cookie 头（任何级别）",
    "原始数据集内容、请求/响应正文、模型原始输出（任何级别）",
    "完整 SQL 语句、数据库连接串、DSN",
    "未归一化的绝对路径（尤其含用户名）",
    "证书/报告签名原文以外的密钥派生材料",
)


class PathScope(StrEnum):
    PROJECT = "<project>"
    HOME = "<home>"
    EXTERNAL = "<external>"


def normalize_path(path: str) -> str:
    """绝对路径归一：项目根 → `<project>/...`，用户目录 → `<home>/...`，其他 → `<external>/<basename>`。

    规则：
      - 先 `Path.resolve()`（消解 `..` 与符号链接），再判断前缀；
      - 只保留相对部分，分隔符统一为 `/`；
      - 无法判定时只留 basename，不留父目录（父目录常含用户名/项目名）。
    """
    raise NotImplementedError("P1 伪代码：路径归一是日志落地的一部分")


def redact_event(event: Mapping[str, Any]) -> Mapping[str, Any]:
    """返回可安全写出的新 mapping（不修改入参）。

    规则：
      1. 键名（小写）含 DENY_KEY_TOKENS 任一 token → 整键删除，`redactions += 1`。
      2. 字符串值命中 DENY_VALUE_PATTERNS → 替换为 REDACTED，`redaction_applied=True`。
      3. 未在 LOG_FIELDS 且不在 ALLOWED_EXTRA_KEYS 的键 → 丢弃（白名单，不是黑名单）。
      4. `message` 长度截断（建议 500 字符），避免把大对象塞进日志。
      5. 不得递归展开 list/dict 值；只接受标量（复杂结构先转摘要/哈希）。
      6. 任何异常都按“丢字段”处理，不得把原值落盘。
    """
    raise NotImplementedError("P1 伪代码：脱敏属 M03 落地阶段")


def assert_log_safe(record: Mapping[str, Any]) -> None:
    """写出前的最后一道断言（P1 只定义，不实现）。

    失败条件：仍存在禁写键、仍匹配敏感值模式、出现绝对路径、出现非白名单键、
    `message` 含换行（单行 JSON 约束）。
    失败必须抛异常并阻止写出——不得“尽力脱敏后照写”。
    """
    raise NotImplementedError("P1 伪代码：写前断言属 M03 落地阶段")