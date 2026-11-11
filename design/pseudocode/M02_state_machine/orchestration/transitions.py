"""M02 · orchestration/transitions.py — 四张迁移表（P2 伪代码）。

阶段：P2｜状态：状态枚举、允许边、守卫、角色、失败码；**不执行迁移**。
规范来源：
  - `docs/design/05_CONTRACTS_AND_STATES.md` §9.2（Task 9）、§9.3（Node 10）、
    §9.4（Evidence）、§9.5（T1 Recovery 边界）、§9.7（迁移必填参数）；
  - `docs/ADR/ADR-001`（INVALIDATED）、`ADR-004`（T0 恢复）、`ADR-005`（失败审计）；
  - `docs/design/06_DATA_AND_API.md` §3（表级写者）。

四张表：
  1. `TASK_TRANSITIONS`：9 个状态，13 条允许边，终态 4 个；
  2. `NODE_TRANSITIONS`：10 个状态，17 条允许边，终态 1 个（BLOCKED）+
     VERIFIED/INVALIDATED 各只有 1 条出边；
  3. `EVIDENCE_TRANSITIONS`：5 个状态，4 条允许边，3 个终态；
  4. `T0_RECOVERY_PATHS`：T0 的 `VERIFIED → INVALIDATED → READY` 两条路径，
     后者带三条 plan_hash 守卫。**T1 Recovery 状态（PROPOSED/APPROVED/…）不得出现**。

写法纪律：
  - 每个状态的“允许下一状态”必须逐条列在 `ALLOWED_NEXT`；终态写空元组，
    不允许用“其余拒绝”代替枚举；
  - 未列出的边一律 `ILLEGAL_EDGE`；05 §9.3 明令禁止的危险边在 `FORBIDDEN_EDGES`
    中单独列出，便于负例断言具体原因；
  - `ActorRole` 是角色，不是身份；审计的 `actor` 用 `role:identity`。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

from ..persistence.schema_sql import EVIDENCE_STATES, NODE_STATES, TASK_STATES

__all__ = [
    "ALLOWED_NEXT",
    "EVIDENCE_TRANSITIONS",
    "FORBIDDEN_EDGES",
    "FOUR_TRANSITION_TABLES",
    "NODE_TRANSITIONS",
    "NON_WRITER_ROLES",
    "PLAN_GUARD_ORDER",
    "RECOVERY_PATHS",
    "T0_RECOVERY_PATHS",
    "T1_RECOVERY_STATES",
    "TASK_TRANSITIONS",
    "TRANSITION_TABLES",
    "ActorRole",
    "EvidenceState",
    "ForbiddenEdge",
    "GuardId",
    "IllegalTransition",
    "NodeState",
    "ObjectType",
    "ReasonCode",
    "RecoveryPath",
    "RecoverySubguard",
    "TaskState",
    "Transition",
    "allowed_next_states",
    "assert_no_t1_recovery_state",
    "assert_transition_contract",
    "lookup_transition",
]


# ---------------------------------------------------------------------------
# 1. 枚举：状态 / 对象 / 角色 / 原因 / 守卫
# ---------------------------------------------------------------------------
class ObjectType(StrEnum):
    TASK = "task"
    NODE = "node"
    EVIDENCE = "evidence"


class TaskState(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class NodeState(StrEnum):
    PLANNED = "PLANNED"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DIAGNOSING = "DIAGNOSING"
    RECOVERING = "RECOVERING"
    INVALIDATED = "INVALIDATED"


class EvidenceState(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    APPENDED = "APPENDED"
    INVALID = "INVALID"
    CONFLICT = "CONFLICT"


# 状态字面值与 schema CHECK 必须一致（schema_sql 是 DB 侧唯一来源）
assert tuple(s.value for s in TaskState) == TASK_STATES
assert tuple(s.value for s in NodeState) == NODE_STATES
assert tuple(s.value for s in EvidenceState) == EVIDENCE_STATES


class ActorRole(StrEnum):
    """迁移请求的角色；身份另放 `actor` 的 identity 部分。"""

    ORCHESTRATOR = "orchestrator"
    SCHEDULER = "scheduler"
    WP_R = "wp_r"
    BOOT_RECOVERY = "boot_recovery"
    OPERATOR = "operator"
    VERIFIER = "verifier"
    COLLECTOR = "collector"
    EXECUTOR = "executor"
    GATE = "gate"
    AGENT = "agent"
    API = "api"


# 这些角色即使被伪造成调用者，也不允许写 Task/Node 状态。
NON_WRITER_ROLES: Final[frozenset[ActorRole]] = frozenset(
    {
        ActorRole.VERIFIER,
        ActorRole.COLLECTOR,
        ActorRole.EXECUTOR,
        ActorRole.GATE,
        ActorRole.AGENT,
        ActorRole.API,
    }
)


class ReasonCode(StrEnum):
    # 成功原因
    TASK_PLANNING_STARTED = "TASK_PLANNING_STARTED"
    TASK_CANCELLED = "TASK_CANCELLED"
    DAG_VALIDATED = "DAG_VALIDATED"
    DAG_BLOCKING_GAP = "DAG_BLOCKING_GAP"
    PLANNING_FAILED = "PLANNING_FAILED"
    TASK_STARTED = "TASK_STARTED"
    EXECUTION_FINISHED = "EXECUTION_FINISHED"
    TASK_EXECUTION_FAILED = "TASK_EXECUTION_FAILED"
    TASK_BLOCKED = "TASK_BLOCKED"
    REPORT_VERIFIED = "REPORT_VERIFIED"
    REPORT_FAILED = "REPORT_FAILED"
    REPORT_PARTIAL = "REPORT_PARTIAL"
    NODE_DEPS_SATISFIED = "NODE_DEPS_SATISFIED"
    NODE_STARTED = "NODE_STARTED"
    ATTEMPT_ENDED = "ATTEMPT_ENDED"
    ATTEMPT_FAILED = "ATTEMPT_FAILED"
    GATE_PASS_VERIFIER_VERIFIED_CERT_VALID = "GATE_PASS_VERIFIER_VERIFIED_CERT_VALID"
    GATE_FAILED = "GATE_FAILED"
    VERIFICATION_PARTIAL = "VERIFICATION_PARTIAL"
    RECOVERY_BUDGET_AVAILABLE = "RECOVERY_BUDGET_AVAILABLE"
    RECOVERY_BUDGET_EXHAUSTED = "RECOVERY_BUDGET_EXHAUSTED"
    DIAGNOSIS_VALID = "DIAGNOSIS_VALID"
    DIAGNOSIS_INVALID = "DIAGNOSIS_INVALID"
    RECOVERY_RECHECKED = "RECOVERY_RECHECKED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    STALE_CAUSE_DETECTED = "STALE_CAUSE_DETECTED"
    PLAN_FROZEN_BEFORE_RERUN = "PLAN_FROZEN_BEFORE_RERUN"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    EVIDENCE_APPENDED = "EVIDENCE_APPENDED"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    BOOT_NO_ACTIVE_ATTEMPT = "BOOT_NO_ACTIVE_ATTEMPT"
    BOOT_UNFINISHED_ATTEMPT = "BOOT_UNFINISHED_ATTEMPT"
    BOOT_ATTEMPT_COMPLETED = "BOOT_ATTEMPT_COMPLETED"
    BOOT_ATTEMPT_FAILED = "BOOT_ATTEMPT_FAILED"
    BOOT_EVIDENCE_CHAIN_BROKEN = "BOOT_EVIDENCE_CHAIN_BROKEN"
    BOOT_SCHEMA_MISMATCH = "BOOT_SCHEMA_MISMATCH"
    BOOT_DB_INTEGRITY_FAILED = "BOOT_DB_INTEGRITY_FAILED"
    # 拒绝原因
    MISSING_PARAMETER = "MISSING_PARAMETER"
    UNKNOWN_OBJECT_TYPE = "UNKNOWN_OBJECT_TYPE"
    OBJECT_TYPE_NOT_MANAGED = "OBJECT_TYPE_NOT_MANAGED"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    ILLEGAL_EDGE = "ILLEGAL_EDGE"
    STALE_PREVIOUS_STATE = "STALE_PREVIOUS_STATE"
    GUARD_FAILED = "GUARD_FAILED"
    DAG_INVALID = "DAG_INVALID"
    NO_READY_NODE = "NO_READY_NODE"
    DEPENDENCIES_UNSATISFIED = "DEPENDENCIES_UNSATISFIED"
    RESOURCE_NOT_AVAILABLE = "RESOURCE_NOT_AVAILABLE"
    ATTEMPT_NOT_ENDED = "ATTEMPT_NOT_ENDED"
    EXIT_CODE_NONZERO = "EXIT_CODE_NONZERO"
    GATE_NOT_PASS = "GATE_NOT_PASS"
    REPORT_NOT_VERIFIED = "REPORT_NOT_VERIFIED"
    CERTIFICATE_INVALID = "CERTIFICATE_INVALID"
    RULE_VERSION_MISMATCH = "RULE_VERSION_MISMATCH"
    ENV_FINGERPRINT_MISMATCH = "ENV_FINGERPRINT_MISMATCH"
    TASK_COMPLETION_PREREQUISITES = "TASK_COMPLETION_PREREQUISITES"
    RECOVERY_BUDGET_EXHAUSTED_DENIED = "RECOVERY_BUDGET_EXHAUSTED_DENIED"
    PLAN_FIELDS_NOT_ALLOWED = "PLAN_FIELDS_NOT_ALLOWED"
    PLAN_FILE_MISSING = "PLAN_FILE_MISSING"
    PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
    PLAN_FREEZE_RECORD_MISSING = "PLAN_FREEZE_RECORD_MISSING"
    PLAN_ID_MISMATCH = "PLAN_ID_MISMATCH"
    PLAN_FROZEN_AFTER_RERUN = "PLAN_FROZEN_AFTER_RERUN"
    UNSAFE_PLAN_PATH = "UNSAFE_PLAN_PATH"
    EVIDENCE_CHAIN_BROKEN = "EVIDENCE_CHAIN_BROKEN"
    EVENT_SEQ_GAP = "EVENT_SEQ_GAP"
    EVENT_SEQ_REGRESSION = "EVENT_SEQ_REGRESSION"
    NO_STALE_EVIDENCE = "NO_STALE_EVIDENCE"
    CAUSE_INVALID = "CAUSE_INVALID"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    WRITE_LOCK_TIMEOUT = "WRITE_LOCK_TIMEOUT"
    T1_RECOVERY_STATE_FORBIDDEN = "T1_RECOVERY_STATE_FORBIDDEN"
    AUDIT_WRITE_FAILED = "AUDIT_WRITE_FAILED"


class GuardId(StrEnum):
    NONE = "NONE"
    DAG_VALID = "DAG_VALID"
    DAG_BLOCKING_GAP = "DAG_BLOCKING_GAP"
    AT_LEAST_ONE_NODE_READY = "AT_LEAST_ONE_NODE_READY"
    EXECUTION_FINISHED = "EXECUTION_FINISHED"
    TASK_COMPLETION_PREREQUISITES = "TASK_COMPLETION_PREREQUISITES"
    DEPENDENCIES_SATISFIED = "DEPENDENCIES_SATISFIED"
    RESOURCES_AVAILABLE = "RESOURCES_AVAILABLE"
    ATTEMPT_ENDED_SUCCESS = "ATTEMPT_ENDED_SUCCESS"
    VERIFIED_PREREQUISITES = "VERIFIED_PREREQUISITES"
    RECOVERY_BUDGET_AVAILABLE = "RECOVERY_BUDGET_AVAILABLE"
    DIAGNOSIS_VALID = "DIAGNOSIS_VALID"
    RECOVERY_RECHECKED = "RECOVERY_RECHECKED"
    STALE_CAUSE_PRESENT = "STALE_CAUSE_PRESENT"
    PLAN_THREE_GUARDS = "PLAN_THREE_GUARDS"
    EVIDENCE_CHAIN_VALID = "EVIDENCE_CHAIN_VALID"
    FAILURE_EVIDENCE_PRESENT = "FAILURE_EVIDENCE_PRESENT"


# ---------------------------------------------------------------------------
# 2. 迁移边
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Transition:
    obj_type: ObjectType
    from_state: str
    to_state: str
    allowed_roles: frozenset[ActorRole]
    guard_id: GuardId
    guard: str
    denial_code: str
    guard_failure_codes: tuple[str, ...]
    side_effects: tuple[str, ...]
    requires: tuple[str, ...] = ()
    source: str = ""


def _t(
    *,
    obj_type: ObjectType,
    from_state: str,
    to_state: str,
    roles: tuple[ActorRole, ...],
    guard_id: GuardId,
    guard: str,
    side_effects: tuple[str, ...],
    requires: tuple[str, ...] = (),
    denial_code: str = "STATE_TRANSITION_DENIED",
    guard_failure_codes: tuple[str, ...] = ("STATE_TRANSITION_DENIED",),
    source: str,
) -> Transition:
    return Transition(
        obj_type=obj_type,
        from_state=from_state,
        to_state=to_state,
        allowed_roles=frozenset(roles),
        guard_id=guard_id,
        guard=guard,
        denial_code=denial_code,
        guard_failure_codes=guard_failure_codes,
        side_effects=side_effects,
        requires=requires,
        source=source,
    )


# -- Task：9 状态 / 13 条边 --------------------------------------------------
TASK_TRANSITIONS: Final[tuple[Transition, ...]] = (
    _t(
        obj_type=ObjectType.TASK, from_state="CREATED", to_state="PLANNING",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.NONE,
        guard="TaskSpec 已通过契约校验；无额外守卫",
        side_effects=("audit:OK", "tasks.updated_at"), source="05 §9.2 R02",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="CREATED", to_state="CANCELLED",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.OPERATOR), guard_id=GuardId.NONE,
        guard="创建后取消；不得先进入 PLANNING 再取消",
        side_effects=("audit:OK", "tasks.updated_at"), source="05 §9.2 R02",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="PLANNING", to_state="READY",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.DAG_VALID,
        guard="DAG 通过静态校验（拓扑/环/孤立/依赖/图版本）；写 graph_version",
        side_effects=("tasks.graph_version", "audit:OK"),
        requires=("graph_version",), source="05 §9.2 R03",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="PLANNING", to_state="BLOCKED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.DAG_BLOCKING_GAP,
        guard="DAG 校验产生阻塞缺口（结构化 gap_ref 必须存在）",
        side_effects=("audit:OK", "tasks.updated_at"),
        requires=("failure_ref",), source="05 §9.2 R03",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="PLANNING", to_state="FAILED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="规划阶段不可恢复失败；failure_ref 必须存在",
        side_effects=("audit:OK", "tasks.updated_at"),
        requires=("failure_ref",), source="05 §9.2 R03",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="READY", to_state="RUNNING",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.AT_LEAST_ONE_NODE_READY,
        guard="至少一个节点处于 READY；不得空任务启动",
        side_effects=("audit:OK", "tasks.updated_at"), source="05 §9.2 R04",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="READY", to_state="CANCELLED",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.OPERATOR), guard_id=GuardId.NONE,
        guard="启动前取消；不得有 RUNNING 节点",
        side_effects=("audit:OK", "tasks.updated_at"), source="05 §9.2 R04",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="RUNNING", to_state="VERIFYING",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.EXECUTION_FINISHED,
        guard="执行未结束不能进入最终验证；所有执行类节点已有 attempt 结束事件",
        side_effects=("audit:OK", "tasks.updated_at"), source="05 §9.2 R05",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="RUNNING", to_state="FAILED",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="不可恢复执行失败；failure_ref 必须存在",
        side_effects=("audit:OK", "tasks.updated_at"),
        requires=("failure_ref",), source="05 §9.2 R05",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="RUNNING", to_state="BLOCKED",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="资源/权限/缺口导致阻塞；failure_ref 必须存在",
        side_effects=("audit:OK", "tasks.updated_at"),
        requires=("failure_ref",), source="05 §9.2 R05",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="VERIFYING", to_state="COMPLETED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.TASK_COMPLETION_PREREQUISITES,
        guard="报告 VERIFIED + 有效 CompletionCertificate + 所有非跳过节点 VERIFIED（T0 无 SPA）",
        side_effects=("audit:OK", "tasks.updated_at"),
        requires=("report_id", "cert_id"),
        guard_failure_codes=(
            "STATE_TRANSITION_DENIED", "REQUIRED_EVIDENCE_MISSING",
            "RULESET_VERSION_MISMATCH", "SIGNATURE_INVALID",
            "ENV_FINGERPRINT_MISMATCH",
        ),
        source="05 §9.2 R06；§9.6；I-07",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="VERIFYING", to_state="FAILED",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="验证失败（报告 FAILED）；failure_ref 必须存在",
        side_effects=("audit:OK", "tasks.updated_at"),
        requires=("failure_ref",), source="05 §9.2 R06",
    ),
    _t(
        obj_type=ObjectType.TASK, from_state="VERIFYING", to_state="BLOCKED",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="验证受阻（报告 PARTIAL/BLOCKED）；failure_ref 必须存在",
        side_effects=("audit:OK", "tasks.updated_at"),
        requires=("failure_ref",), source="05 §9.2 R06；§9.6",
    ),
)

# -- Node：10 状态 / 17 条边 -------------------------------------------------
NODE_TRANSITIONS: Final[tuple[Transition, ...]] = (
    _t(
        obj_type=ObjectType.NODE, from_state="PLANNED", to_state="READY",
        roles=(ActorRole.SCHEDULER,), guard_id=GuardId.DEPENDENCIES_SATISFIED,
        guard="全部 depends_on 已 VERIFIED；input_refs 可解析；图版本一致",
        side_effects=("audit:OK", "nodes.updated_at"), source="05 §9.3 R07",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="PLANNED", to_state="BLOCKED",
        roles=(ActorRole.SCHEDULER, ActorRole.ORCHESTRATOR),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="依赖不可满足/输入缺失；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R07",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="READY", to_state="RUNNING",
        roles=(ActorRole.SCHEDULER,), guard_id=GuardId.RESOURCES_AVAILABLE,
        guard="资源/权限/并发槽检查通过；attempt_seq += 1",
        side_effects=("nodes.attempt_seq +1", "audit:OK"),
        requires=("attempt_id",), source="05 §9.3 R08",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="READY", to_state="BLOCKED",
        roles=(ActorRole.SCHEDULER, ActorRole.ORCHESTRATOR),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="资源/权限拒绝；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R08",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="RUNNING", to_state="VERIFYING",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard_id=GuardId.ATTEMPT_ENDED_SUCCESS,
        guard="必须有 attempt 结束事件且 exit_code=0；证据链完整；不得用进程存活猜测",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("attempt_id",),
        guard_failure_codes=(
            "STATE_TRANSITION_DENIED", "EVIDENCE_CHAIN_BROKEN",
            "EVENT_SEQ_GAP", "EVENT_SEQ_REGRESSION",
        ),
        source="05 §9.3 R09；PG-R09",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="RUNNING", to_state="FAILED",
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="attempt 失败/被终止/重启后发现无活动 attempt；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R09；ADR-004",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="VERIFYING", to_state="VERIFIED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.VERIFIED_PREREQUISITES,
        guard="Gate PASS + Verifier 报告 VERIFIED + 有效凭证 + 规则/环境一致；缺一不可",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("gate_result_ref", "report_id", "cert_id"),
        guard_failure_codes=(
            "STATE_TRANSITION_DENIED", "REQUIRED_EVIDENCE_MISSING",
            "RULESET_VERSION_MISMATCH", "SIGNATURE_INVALID",
            "ENV_FINGERPRINT_MISMATCH",
        ),
        source="05 §9.3 R10；P0133；I-02/I-04/I-07",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="VERIFYING", to_state="FAILED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="Gate/Verifier 判定 FAILED；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R10",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="VERIFYING", to_state="BLOCKED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="报告 PARTIAL 映射为节点 BLOCKED；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R10；§9.6",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="FAILED", to_state="DIAGNOSING",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.RECOVERY_BUDGET_AVAILABLE,
        guard="恢复次数未超限（retry_policy.max_attempts）；不得无限重试",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("recovery_ref",), source="05 §9.3 R11",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="FAILED", to_state="BLOCKED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="恢复次数耗尽/不可恢复；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R11",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="DIAGNOSING", to_state="RECOVERING",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.DIAGNOSIS_VALID,
        guard="根因/恢复计划结构有效（确定性计划，不含时间戳/随机序）",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("diagnosis_ref",), source="05 §9.3 R12；ADR-004",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="DIAGNOSING", to_state="BLOCKED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="无有效诊断/计划；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R12",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="RECOVERING", to_state="READY",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.RECOVERY_RECHECKED,
        guard="恢复计划执行完并复核；recheck_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("recheck_ref",), source="05 §9.3 R13",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="RECOVERING", to_state="BLOCKED",
        roles=(ActorRole.ORCHESTRATOR,), guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="恢复失败/复核不通过；failure_ref 必须存在",
        side_effects=("audit:OK", "nodes.updated_at"),
        requires=("failure_ref",), source="05 §9.3 R13",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="VERIFIED", to_state="INVALIDATED",
        roles=(ActorRole.WP_R,), guard_id=GuardId.STALE_CAUSE_PRESENT,
        guard="上游输入/前驱/图版本/规则版本变化；stale evidence_ids 非空；只追加失效，不删证据",
        side_effects=("evidence_invalidations:append", "audit:OK", "nodes.updated_at"),
        requires=("cause_type", "evidence_ids"),
        guard_failure_codes=("STATE_TRANSITION_DENIED", "NO_STALE_EVIDENCE", "CAUSE_INVALID"),
        source="05 §9.3；ADR-001；决议 4",
    ),
    _t(
        obj_type=ObjectType.NODE, from_state="INVALIDATED", to_state="READY",
        roles=(ActorRole.WP_R,), guard_id=GuardId.PLAN_THREE_GUARDS,
        guard="①计划文件存在且可读 ②sha256(文件)==plan_hash 且与 audit 冻结记录一致 "
              "③冻结事件早于本次重跑；三条全满足才放行",
        side_effects=("nodes.plan_id", "nodes.plan_hash", "audit:OK"),
        requires=("plan_id", "plan_hash"),
        denial_code="PLAN_HASH_MISMATCH",
        guard_failure_codes=(
            "PLAN_HASH_MISMATCH", "PLAN_FILE_MISSING",
            "PLAN_FREEZE_RECORD_MISSING", "PLAN_ID_MISMATCH",
            "PLAN_FROZEN_AFTER_RERUN", "UNSAFE_PLAN_PATH",
        ),
        source="05 §9.3；ADR-001/004；决议 5；OQ-CT-11",
    ),
)

# -- Evidence：5 状态 / 4 条边（写者是 Collector/Verifier，不是 StateMachine） --
EVIDENCE_TRANSITIONS: Final[tuple[Transition, ...]] = (
    _t(
        obj_type=ObjectType.EVIDENCE, from_state="RECEIVED", to_state="VALIDATED",
        roles=(ActorRole.COLLECTOR, ActorRole.VERIFIER),
        guard_id=GuardId.EVIDENCE_CHAIN_VALID,
        guard="链/哈希/等级-写入者校验通过；event_seq 连续且无回退",
        side_effects=("ingest:validated",),
        requires=("evidence_id",),
        guard_failure_codes=(
            "EVIDENCE_CHAIN_BROKEN", "EVENT_SEQ_GAP",
            "EVENT_SEQ_REGRESSION", "SCHEMA_INVALID",
        ),
        source="05 §9.4 R04",
    ),
    _t(
        obj_type=ObjectType.EVIDENCE, from_state="RECEIVED", to_state="INVALID",
        roles=(ActorRole.COLLECTOR, ActorRole.VERIFIER),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="校验失败；保留拒绝原因，不落 evidence 表（见 EVIDENCE_STATE_NOTE）",
        side_effects=("ingest:invalid",), requires=("failure_ref",),
        source="05 §9.4 R04",
    ),
    _t(
        obj_type=ObjectType.EVIDENCE, from_state="VALIDATED", to_state="APPENDED",
        roles=(ActorRole.COLLECTOR, ActorRole.VERIFIER),
        guard_id=GuardId.EVIDENCE_CHAIN_VALID,
        guard="只追加；插入后不得 UPDATE/DELETE；审计由 StateMachine 的审计服务写入",
        side_effects=("evidence:insert",), requires=("evidence_id",),
        source="05 §9.4 R04",
    ),
    _t(
        obj_type=ObjectType.EVIDENCE, from_state="VALIDATED", to_state="CONFLICT",
        roles=(ActorRole.COLLECTOR, ActorRole.VERIFIER),
        guard_id=GuardId.FAILURE_EVIDENCE_PRESENT,
        guard="链/哈希/等级冲突；保留冲突记录，不覆盖旧证据",
        side_effects=("ingest:conflict",), requires=("failure_ref",),
        source="05 §9.4 R04",
    ),
)

TRANSITION_TABLES: Final[Mapping[ObjectType, tuple[Transition, ...]]] = MappingProxyType(
    {
        ObjectType.TASK: TASK_TRANSITIONS,
        ObjectType.NODE: NODE_TRANSITIONS,
        ObjectType.EVIDENCE: EVIDENCE_TRANSITIONS,
    }
)


# ---------------------------------------------------------------------------
# 3. 每个状态的出边（逐条列全；终态为空元组）
# ---------------------------------------------------------------------------
def _build_allowed_next(
    obj_type: ObjectType, states: tuple[str, ...], edges: tuple[Transition, ...]
) -> Mapping[str, tuple[str, ...]]:
    table: dict[str, tuple[str, ...]] = {state: () for state in states}
    for edge in edges:
        table[edge.from_state] = (*table[edge.from_state], edge.to_state)
    return MappingProxyType(table)


ALLOWED_NEXT: Final[Mapping[ObjectType, Mapping[str, tuple[str, ...]]]] = MappingProxyType(
    {
        ObjectType.TASK: _build_allowed_next(ObjectType.TASK, TASK_STATES, TASK_TRANSITIONS),
        ObjectType.NODE: _build_allowed_next(ObjectType.NODE, NODE_STATES, NODE_TRANSITIONS),
        ObjectType.EVIDENCE: _build_allowed_next(
            ObjectType.EVIDENCE, EVIDENCE_STATES, EVIDENCE_TRANSITIONS
        ),
    }
)

TERMINAL_STATES: Final[Mapping[ObjectType, frozenset[str]]] = MappingProxyType(
    {
        ObjectType.TASK: frozenset({"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}),
        ObjectType.NODE: frozenset({"BLOCKED"}),
        ObjectType.EVIDENCE: frozenset({"APPENDED", "INVALID", "CONFLICT"}),
    }
)

FOUR_TRANSITION_TABLES: Final[tuple[str, ...]] = (
    "TASK_TRANSITIONS", "NODE_TRANSITIONS", "EVIDENCE_TRANSITIONS", "T0_RECOVERY_PATHS",
)


# ---------------------------------------------------------------------------
# 4. 05 §9.3 明令禁止/未授权的边（单独列出，便于负例断言）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ForbiddenEdge:
    obj_type: ObjectType
    from_state: str
    to_state: str
    reason: ReasonCode
    error_code: str
    source: str


FORBIDDEN_EDGES: Final[tuple[ForbiddenEdge, ...]] = (
    ForbiddenEdge(ObjectType.NODE, "VERIFIED", "READY", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.3：不得跳过 INVALIDATED"),
    ForbiddenEdge(ObjectType.NODE, "INVALIDATED", "VERIFYING", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.3：INVALIDATED 只能回 READY"),
    ForbiddenEdge(ObjectType.NODE, "INVALIDATED", "VERIFIED", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.3"),
    ForbiddenEdge(ObjectType.NODE, "INVALIDATED", "FAILED", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.3"),
    ForbiddenEdge(ObjectType.NODE, "READY", "PLANNED", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.3：任何状态不得直接回 PLANNED"),
    ForbiddenEdge(ObjectType.NODE, "RUNNING", "PLANNED", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.3：任何状态不得直接回 PLANNED"),
    ForbiddenEdge(ObjectType.NODE, "VERIFIED", "PLANNED", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.3：任何状态不得直接回 PLANNED"),
    ForbiddenEdge(ObjectType.TASK, "COMPLETED", "INVALIDATED", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "T1 revocation 未在 T0 授权（ADR-001）"),
    ForbiddenEdge(ObjectType.TASK, "COMPLETED", "READY", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "T1 revocation 未在 T0 授权（ADR-001）"),
    ForbiddenEdge(ObjectType.EVIDENCE, "APPENDED", "VALIDATED", ReasonCode.ILLEGAL_EDGE,
                  "STATE_TRANSITION_DENIED", "05 §9.4：APPENDED 是终态，只追加"),
)


# ---------------------------------------------------------------------------
# 5. T0 恢复路径与 plan_hash 三守卫
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RecoverySubguard:
    subguard_id: str
    description: str
    failure_reason: ReasonCode
    error_code: str


@dataclass(frozen=True, slots=True)
class RecoveryPath:
    from_state: str
    to_state: str
    subguards: tuple[RecoverySubguard, ...]
    denial_code: str
    source: str


PLAN_GUARD_ORDER: Final[tuple[str, ...]] = (
    "PLAN_FILE_EXISTS",
    "PLAN_HASH_MATCHES",
    "PLAN_FROZEN_BEFORE_RERUN",
)

RECOVERY_PATHS: Final[tuple[RecoveryPath, ...]] = (
    RecoveryPath(
        from_state="VERIFIED",
        to_state="INVALIDATED",
        subguards=(
            RecoverySubguard(
                "STALE_CAUSE_CLASSIFIED",
                "变更原因属于 INPUT_CHANGE/PREDECESSOR_CHANGE/GRAPH_VERSION_CHANGE/RULESET_CHANGE",
                ReasonCode.CAUSE_INVALID,
                "STATE_TRANSITION_DENIED",
            ),
            RecoverySubguard(
                "STALE_EVIDENCE_NONEMPTY",
                "至少一条 stale evidence_id 存在且属于本节点；只追加失效，不删除证据",
                ReasonCode.NO_STALE_EVIDENCE,
                "STATE_TRANSITION_DENIED",
            ),
            RecoverySubguard(
                "EVIDENCE_NOT_DELETED",
                "失效写入后 evidence 行数不变；不得 UPDATE/DELETE evidence",
                ReasonCode.ILLEGAL_EDGE,
                "STATE_TRANSITION_DENIED",
            ),
        ),
        denial_code="STATE_TRANSITION_DENIED",
        source="05 §9.3；ADR-001；决议 4",
    ),
    RecoveryPath(
        from_state="INVALIDATED",
        to_state="READY",
        subguards=(
            RecoverySubguard(
                "PLAN_FILE_EXISTS",
                "内容寻址文件 <plan_store_root>/<plan_hash>.json 存在、是普通文件、可读、"
                "解析后的路径仍在 plan_store_root 下（拒绝 ../ 与符号链接逃逸）",
                ReasonCode.PLAN_FILE_MISSING,
                "PLAN_HASH_MISMATCH",
            ),
            RecoverySubguard(
                "PLAN_HASH_MATCHES",
                "sha256(文件字节)==plan_hash（64 位小写十六进制），且该 plan_hash/plan_id "
                "与 audit_log 最近一条 RECOVERY_PLAN_FROZEN(result=OK) 记录一致；"
                "不得信任 nodes.plan_hash 或文件 mtime",
                ReasonCode.PLAN_HASH_MISMATCH,
                "PLAN_HASH_MISMATCH",
            ),
            RecoverySubguard(
                "PLAN_FROZEN_BEFORE_RERUN",
                "冻结事件的 created_at 严格早于本次重跑请求的 received_at；"
                "相等也拒绝（无法证明先冻结后重跑）",
                ReasonCode.PLAN_FROZEN_AFTER_RERUN,
                "PLAN_HASH_MISMATCH",
            ),
        ),
        denial_code="PLAN_HASH_MISMATCH",
        source="05 §9.3；ADR-004；决议 5；OQ-CT-11",
    ),
)

T0_RECOVERY_PATHS: Final[tuple[RecoveryPath, ...]] = RECOVERY_PATHS


# ---------------------------------------------------------------------------
# 6. T1 Recovery 状态禁令
# ---------------------------------------------------------------------------
# 05 §9.5：T0 不复用完整 Recovery 状态机；这些值不得出现在 T0 代码或 DB 枚举中。
# 注意：VALIDATED 同时是 Evidence 状态，不能做全局字符串禁用；它不得出现在 Task/Node。
T1_RECOVERY_STATES: Final[tuple[str, ...]] = (
    "PROPOSED", "APPROVED", "EXECUTING", "RECHECKED", "CLOSED", "ESCALATED",
)
T1_RECOVERY_STATE_NAMES_COLLIDING: Final[tuple[str, ...]] = ("VALIDATED",)


def assert_no_t1_recovery_state(obj_type: ObjectType, state: str) -> None:
    """T0 的 Task/Node 不得出现 T1 Recovery 状态；Evidence 的 VALIDATED 除外。"""
    if obj_type in (ObjectType.TASK, ObjectType.NODE) and state in T1_RECOVERY_STATES:
        raise ValueError(
            f"T0 不得引入 T1 Recovery 状态 {state!r}（05 §9.5 / 决议 6）"
        )
    if obj_type in (ObjectType.TASK, ObjectType.NODE) and state == "VALIDATED":
        raise ValueError("VALIDATED 是 Evidence 状态，不是 Task/Node 状态")


# ---------------------------------------------------------------------------
# 7. 查询与非法边
# ---------------------------------------------------------------------------
class IllegalTransition(ValueError):
    """边不在允许表内，或属于 05 §9.3 明令禁止的边。"""

    error_code = "STATE_TRANSITION_DENIED"
    http_status = 409

    def __init__(
        self,
        *,
        obj_type: ObjectType,
        from_state: str,
        to_state: str,
        reason: ReasonCode,
        detail: str = "",
    ) -> None:
        self.obj_type = obj_type
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        self.detail = detail
        suffix = f"（{detail}）" if detail else ""
        super().__init__(
            f"非法迁移 {obj_type.value}: {from_state} → {to_state}{suffix}"
        )


def _states_for(obj_type: ObjectType) -> tuple[str, ...]:
    if obj_type is ObjectType.TASK:
        return TASK_STATES
    if obj_type is ObjectType.NODE:
        return NODE_STATES
    if obj_type is ObjectType.EVIDENCE:
        return EVIDENCE_STATES
    raise ValueError(f"未知对象类型：{obj_type!r}")


def allowed_next_states(obj_type: ObjectType, from_state: str) -> tuple[str, ...]:
    """返回该状态的完整出边元组；终态返回空元组。"""
    if from_state not in _states_for(obj_type):
        raise ValueError(f"未知 {obj_type.value} 状态：{from_state!r}")
    return ALLOWED_NEXT[obj_type][from_state]


def lookup_transition(
    obj_type: ObjectType, from_state: str, to_state: str
) -> Transition:
    """查允许边；禁止边给专门 reason，其余未列出边给 ILLEGAL_EDGE。"""
    if from_state not in _states_for(obj_type):
        raise IllegalTransition(
            obj_type=obj_type, from_state=from_state, to_state=to_state,
            reason=ReasonCode.ILLEGAL_EDGE, detail="未知前态",
        )
    if to_state not in _states_for(obj_type):
        raise IllegalTransition(
            obj_type=obj_type, from_state=from_state, to_state=to_state,
            reason=ReasonCode.ILLEGAL_EDGE, detail="未知目标状态",
        )
    for edge in TRANSITION_TABLES[obj_type]:
        if edge.from_state == from_state and edge.to_state == to_state:
            return edge
    for forbidden in FORBIDDEN_EDGES:
        if (
            forbidden.obj_type is obj_type
            and forbidden.from_state == from_state
            and forbidden.to_state == to_state
        ):
            raise IllegalTransition(
                obj_type=obj_type, from_state=from_state, to_state=to_state,
                reason=forbidden.reason, detail=forbidden.source,
            )
    raise IllegalTransition(
        obj_type=obj_type, from_state=from_state, to_state=to_state,
        reason=ReasonCode.ILLEGAL_EDGE,
        detail="未在允许表中列出",
    )


# ---------------------------------------------------------------------------
# 8. 自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
def assert_transition_contract() -> list[str]:
    problems: list[str] = []
    expected_counts = {
        ObjectType.TASK: (9, 13),
        ObjectType.NODE: (10, 17),
        ObjectType.EVIDENCE: (5, 4),
    }
    for obj_type, edges in TRANSITION_TABLES.items():
        state_count, edge_count = expected_counts[obj_type]
        states = _states_for(obj_type)
        if len(states) != state_count:
            problems.append(f"{obj_type.value} 状态数应为 {state_count}，实际 {len(states)}")
        if len(edges) != edge_count:
            problems.append(f"{obj_type.value} 边数应为 {edge_count}，实际 {len(edges)}")
        seen: set[tuple[str, str]] = set()
        for edge in edges:
            if edge.from_state not in states or edge.to_state not in states:
                problems.append(f"{obj_type.value} 边引用了未知状态：{edge}")
            key = (edge.from_state, edge.to_state)
            if key in seen:
                problems.append(f"{obj_type.value} 重复边：{key}")
            seen.add(key)
            if not edge.allowed_roles:
                problems.append(f"{obj_type.value} {key} 没有允许角色")
            if not edge.denial_code:
                problems.append(f"{obj_type.value} {key} 没有失败错误码")
            assert_no_t1_recovery_state(obj_type, edge.from_state)
            assert_no_t1_recovery_state(obj_type, edge.to_state)

    # 终态必须真的没有出边；非终态必须有出边
    for obj_type, terminal in TERMINAL_STATES.items():
        for state, next_states in ALLOWED_NEXT[obj_type].items():
            if state in terminal and next_states:
                problems.append(f"{obj_type.value} 终态 {state} 不得有出边")
            if state not in terminal and not next_states:
                problems.append(f"{obj_type.value} 非终态 {state} 没有出边")

    # 05 §9.3 的两条窄边
    node_edges = {(e.from_state, e.to_state) for e in NODE_TRANSITIONS}
    if ("VERIFIED", "READY") in node_edges:
        problems.append("不得存在 VERIFIED→READY（必须经过 INVALIDATED）")
    if {(e.from_state, e.to_state) for e in NODE_TRANSITIONS if e.from_state == "VERIFIED"} != {
        ("VERIFIED", "INVALIDATED")
    }:
        problems.append("VERIFIED 只能有一条出边 INVALIDATED")
    if {(e.from_state, e.to_state) for e in NODE_TRANSITIONS if e.from_state == "INVALIDATED"} != {
        ("INVALIDATED", "READY")
    }:
        problems.append("INVALIDATED 只能有一条出边 READY")

    # T1 状态不得出现在 Task/Node 枚举
    for state in T1_RECOVERY_STATES:
        if state in TASK_STATES or state in NODE_STATES:
            problems.append(f"T1 Recovery 状态 {state} 混入 Task/Node")

    if len(T0_RECOVERY_PATHS) != 2:
        problems.append("T0_RECOVERY_PATHS 必须是 2 条")
    plan_path = next(
        (p for p in T0_RECOVERY_PATHS if p.to_state == "READY"), None
    )
    if plan_path is None:
        problems.append("缺少 INVALIDATED→READY 恢复路径")
    else:
        ids = tuple(g.subguard_id for g in plan_path.subguards)
        if ids != PLAN_GUARD_ORDER:
            problems.append(f"plan_hash 三守卫顺序/名称不符：{ids!r}")
        if plan_path.denial_code != "PLAN_HASH_MISMATCH":
            problems.append("INVALIDATED→READY 守卫失败码必须是 PLAN_HASH_MISMATCH")

    if NON_WRITER_ROLES & {
        role for e in (*TASK_TRANSITIONS, *NODE_TRANSITIONS) for role in e.allowed_roles
    }:
        problems.append("非写者角色不得出现在 Task/Node 的 allowed_roles")

    return problems