"""M03 · observability/audit_events.py — 审计事件类型表（P1 伪代码）。

阶段：P1｜状态：事件名、触发点、必填字段、写入者；不实现审计写入。

来源：06 §1.3 `audit_log` DDL、06 §3 表级写入权限（`audit_log` 唯一写者 = StateMachine）、
06 §4.6 启动审计、05 §9.3/§9.7（失效、计划冻结、DENIED 审计与降级）、决议 7。

两条硬约束：
  1. **只有 StateMachine 写 `audit_log`**；其他组件只能“请求审计”，不得直连。
     启动阶段尚无 DB，启动拒绝走结构化 stderr（`sink=STARTUP_STDERR`），
     这不是例外，而是启动审计的指定通道（06 §4.6）。
  2. **审计不是日志、日志不是审计**：日志可以截断/采样；`audit_log` 只追加、
     不得 UPDATE/DELETE，且不得用自由文本替代 `reason_code`/`error_code`。

禁止写入审计的内容：token、私钥、计划正文（决议 3：计划正文不入库）、
原始数据、请求/响应正文、工具参数原文。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "AUDIT_COLUMNS",
    "AUDIT_EVENTS",
    "AUDIT_EVENTS_BY_NAME",
    "FORBIDDEN_AUDIT_CONTENT",
    "MIGRATION_REQUIRED_PARAMS",
    "RESULT_VALUES",
    "AuditEventSpec",
    "Sink",
    "by_action",
]


class Sink(StrEnum):
    AUDIT_LOG = "audit_log"              # SQLite，只追加，唯一写者 StateMachine
    STARTUP_STDERR = "startup_stderr"    # 启动拒绝：单行 JSON 到 stderr（无 DB）
    STDERR_FALLBACK = "stderr_fallback"  # 审计写失败降级：单行 JSON，含 audit_write_failed=true


RESULT_VALUES: Final[tuple[str, ...]] = ("OK", "DENIED")  # 对应 DDL CHECK

AUDIT_COLUMNS: Final[tuple[str, ...]] = (
    "audit_id",
    "task_id",
    "node_id",
    "actor",
    "action",
    "previous_state",
    "next_state",
    "reason_code",
    "rule_version",
    "correlation_id",
    "plan_id",
    "plan_hash",
    "result",
    "error_code",
    "created_at",
)

MIGRATION_REQUIRED_PARAMS: Final[tuple[str, ...]] = (
    "previous_state",
    "next_state",
    "actor",
    "reason_code",
    "rule_version",
    "correlation_id",
)  # 05 §9.7；INVALIDATED→READY 另加 plan_id/plan_hash


@dataclass(frozen=True, slots=True)
class AuditEventSpec:
    name: str
    action: str
    trigger: str
    trigger_owner: str
    writer: str
    sink: Sink
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    result_values: tuple[str, ...]
    error_code: str | None
    forbidden: tuple[str, ...]
    source: str


AUDIT_EVENTS: Final[tuple[AuditEventSpec, ...]] = (
    AuditEventSpec(
        name="STATE_TRANSITION_APPLIED",
        action="STATE_TRANSITION",
        trigger="StateMachine 完成一次合法迁移（状态与审计在同一事务）",
        trigger_owner="state_machine",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "actor", "action", "previous_state", "next_state",
            "reason_code", "rule_version", "correlation_id", "result", "created_at",
        ),
        optional_fields=("task_id", "node_id", "plan_id", "plan_hash", "error_code"),
        result_values=("OK",),
        error_code=None,
        forbidden=("自由文本替代 reason_code", "完整请求体", "token/私钥"),
        source="06 §1.3；05 §9.7",
    ),
    AuditEventSpec(
        name="STATE_TRANSITION_DENIED",
        action="STATE_TRANSITION",
        trigger=(
            "迁移被拒（非法边、守卫失败、previous_state 过期、必填参数缺失）："
            "状态事务回滚后，在**独立事务**写 DENIED；该记录必须在回滚后仍存在（I-14）"
        ),
        trigger_owner="state_machine",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "actor", "action", "previous_state", "next_state",
            "reason_code", "rule_version", "correlation_id", "result", "error_code", "created_at",
        ),
        optional_fields=("task_id", "node_id", "plan_id", "plan_hash"),
        result_values=("DENIED",),
        error_code="STATE_TRANSITION_DENIED",
        forbidden=("只记录“失败”而不写 error_code", "把审计写在状态事务内（会一起回滚）"),
        source="05 §9.7 决议 7；I-14；06 §3",
    ),
    AuditEventSpec(
        name="NODE_INVALIDATED",
        action="NODE_INVALIDATED",
        trigger=(
            "VERIFIED 节点因输入/前驱/图版本/规则版本变化而失效："
            "写 nodes 状态 + evidence_invalidations（stale 证据 ID 与原因）+ 本审计"
        ),
        trigger_owner="state_machine",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "task_id", "node_id", "actor", "action", "previous_state",
            "next_state", "reason_code", "rule_version", "correlation_id", "result", "created_at",
        ),
        optional_fields=("plan_id", "plan_hash", "error_code"),
        result_values=("OK",),
        error_code=None,
        forbidden=("在审计里删除/覆盖证据", "把 stale 证据 ID 塞进自由文本而不进 evidence_invalidations"),
        source="05 §9.3；决议 4；06 §1.3",
    ),
    AuditEventSpec(
        name="RECOVERY_PLAN_FROZEN",
        action="RECOVERY_PLAN_FROZEN",
        trigger="WP-R 生成确定性计划文件（内容寻址，文件名 = plan_hash）后登记冻结事件",
        trigger_owner="wp_r",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "task_id", "node_id", "actor", "action", "plan_id",
            "plan_hash", "correlation_id", "result", "created_at",
        ),
        optional_fields=("reason_code", "rule_version", "error_code"),
        result_values=("OK",),
        error_code=None,
        forbidden=("把计划正文写入 audit_log（决议 3：正文只存文件）", "plan_id 或 plan_hash 缺失"),
        source="05 §9.3 决议 5；06 §1.2 规则 4；06 §3 规则 4",
    ),
    AuditEventSpec(
        name="RECOVERY_PLAN_REUSE_DENIED",
        action="RECOVERY_PLAN_REUSE",
        trigger=(
            "INVALIDATED→READY 守卫三条件任一失败：文件缺失/不可读、"
            "sha256(文件)≠plan_hash 或与冻结记录不符、冻结晚于本次重跑"
        ),
        trigger_owner="state_machine",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "task_id", "node_id", "actor", "action", "plan_id",
            "plan_hash", "correlation_id", "result", "error_code", "created_at",
        ),
        optional_fields=("reason_code", "rule_version", "previous_state", "next_state"),
        result_values=("DENIED",),
        error_code="PLAN_HASH_MISMATCH",
        forbidden=("“计划缺失但放行”且不留审计", "用 mtime 代替内容哈希"),
        source="05 §9.3/§13；决议 5；07 WP-R",
    ),
    AuditEventSpec(
        name="TOOL_REQUEST_DENIED",
        action="TOOL_REQUEST",
        trigger="工具未注册或角色无权限；必须在启动子进程前拒绝（TOOL_NOT_ALLOWLISTED）",
        trigger_owner="tool_registry/executor",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "actor", "action", "correlation_id", "result", "error_code", "created_at",
        ),
        optional_fields=("task_id", "node_id", "reason_code", "rule_version"),
        result_values=("DENIED",),
        error_code="TOOL_NOT_ALLOWLISTED",
        forbidden=("记录工具参数原文（可能含数据/密钥）", "记录完整命令行"),
        source="附录 E.3；06 §3；AGENTS §4",
    ),
    AuditEventSpec(
        name="KEY_OPERATION",
        action="SIGN",
        trigger="签发报告/凭证或验签时记录受控密钥操作的结果（成功与失败都记）",
        trigger_owner="verifier/signing",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "actor", "action", "correlation_id", "result", "created_at",
        ),
        optional_fields=("task_id", "reason_code", "rule_version", "error_code"),
        result_values=("OK", "DENIED"),
        error_code="SIGNATURE_INVALID",  # 失败时；成功时为 None
        forbidden=("私钥、PEM、密钥派生材料", "签名原文以外的密钥句柄细节"),
        source="04 §L6；NFR-05；06 §3（密钥操作审计）",
    ),
    AuditEventSpec(
        name="ENV_FINGERPRINT_CHECK_FAILED",
        action="ENV_FINGERPRINT_CHECK",
        trigger=(
            "Verifier 签发前或 E2 绑定校验时：环境指纹不一致/缺项/哈希种子随机化 → 拒绝签发"
        ),
        trigger_owner="verifier",
        writer="state_machine",
        sink=Sink.AUDIT_LOG,
        required_fields=(
            "audit_id", "actor", "action", "correlation_id", "result", "error_code", "created_at",
        ),
        optional_fields=("task_id", "node_id", "reason_code", "rule_version"),
        result_values=("DENIED",),
        error_code="ENV_FINGERPRINT_MISMATCH",
        forbidden=("记录环境变量原文中的敏感值", "只记 digest 不一致而不记原因分类"),
        source="05 §6；策划书 §8.4；M03 env_fingerprint",
    ),
    AuditEventSpec(
        name="STARTUP_REFUSED",
        action="STARTUP_GUARD",
        trigger=(
            "启动守卫拒绝：配置缺键/未知键/类型错/越界、feature flag 越权、"
            "非回环绑定且无 token；进程以非 0 退出且不监听端口"
        ),
        trigger_owner="startup_guard",
        writer="startup_guard",
        sink=Sink.STARTUP_STDERR,
        required_fields=("actor", "action", "correlation_id", "result", "error_code", "created_at"),
        optional_fields=("reason_code"),
        result_values=("DENIED",),
        error_code="CONFIG_MISSING_KEY / CONFIG_UNKNOWN_KEY / CONFIG_TYPE_INVALID / "
                   "CONFIG_VALUE_OUT_OF_RANGE / FEATURE_FLAG_NOT_PERMITTED",
        forbidden=("回显配置值或 token", "回显完整文件路径中的用户名", "监听端口后再退出"),
        source="06 §4.6 决议 8；M03 schemas/feature_flags",
    ),
    AuditEventSpec(
        name="AUDIT_WRITE_DEGRADED",
        action="AUDIT_WRITE_FAILED",
        trigger=(
            "状态已回滚、独立事务写 DENIED 仍失败：降级写单行 JSON 到 stderr，"
            "含 audit_write_failed=true；在测试报告计为测试缺口"
        ),
        trigger_owner="state_machine",
        writer="state_machine",
        sink=Sink.STDERR_FALLBACK,
        required_fields=(
            "actor", "action", "correlation_id", "result", "error_code", "created_at",
            "audit_write_failed",
        ),
        optional_fields=("task_id", "node_id", "reason_code", "rule_version"),
        result_values=("DENIED",),
        error_code="AUDIT_WRITE_FAILED",
        forbidden=("静默吞掉", "把缺口写成通过", "在 stderr 里回显 SQL/DSN"),
        source="05 §9.7 决议 7 第 3–4 条；06 §3",
    ),
)

AUDIT_EVENTS_BY_NAME: Final[Mapping[str, AuditEventSpec]] = MappingProxyType(
    {e.name: e for e in AUDIT_EVENTS}
)

FORBIDDEN_AUDIT_CONTENT: Final[tuple[str, ...]] = (
    "token / 私钥 / 会话凭据 / API key",
    "计划正文（决议 3：只在内容寻址文件里）",
    "原始数据、请求/响应正文、工具参数原文",
    "完整 SQL、DSN、数据库连接串",
    "用自由文本替代 reason_code / error_code",
    "UPDATE/DELETE 历史审计（只追加）",
)


def by_action(action: str) -> tuple[AuditEventSpec, ...]:
    """按 action 取事件；同一 action 可对应多个事件（如 STATE_TRANSITION 的成功/拒绝）。"""
    return tuple(e for e in AUDIT_EVENTS if e.action == action)


# 自检（实现阶段用，P1 不执行）：
#   {e.writer for e in AUDIT_EVENTS if e.sink is Sink.AUDIT_LOG} == {"state_machine"}
#   all(e.result_values and set(e.result_values) <= set(RESULT_VALUES) for e in AUDIT_EVENTS)
#   STARTUP_REFUSED / AUDIT_WRITE_DEGRADED 的 sink 不是 AUDIT_LOG
#   每条事件的 required_fields ⊆ AUDIT_COLUMNS ∪ {"audit_write_failed"}