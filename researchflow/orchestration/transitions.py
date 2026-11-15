"""Task/Node transition tables and role rules for WP-03.

This module is deliberately declarative: it contains no database access and no
transaction handling.  ``StateMachine`` is the only writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "ActorRole",
    "GuardId",
    "IllegalTransition",
    "NON_WRITER_ROLES",
    "NodeState",
    "ObjectType",
    "ReasonCode",
    "T1_RECOVERY_STATES",
    "TaskState",
    "Transition",
    "allowed_next_states",
    "assert_transition_contract",
    "lookup_transition",
]


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
    INVALIDATED = "INVALIDATED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DIAGNOSING = "DIAGNOSING"
    RECOVERING = "RECOVERING"


class ActorRole(StrEnum):
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

T1_RECOVERY_STATES: Final[frozenset[str]] = frozenset(
    {"PROPOSED", "VALIDATED", "APPROVED", "EXECUTING", "RECHECKED", "CLOSED", "ESCALATED"}
)


class GuardId(StrEnum):
    NONE = "NONE"
    DAG_VALID = "DAG_VALID"
    DAG_BLOCKING_GAP = "DAG_BLOCKING_GAP"
    FAILURE_EVIDENCE_PRESENT = "FAILURE_EVIDENCE_PRESENT"
    AT_LEAST_ONE_NODE_READY = "AT_LEAST_ONE_NODE_READY"
    EXECUTION_FINISHED = "EXECUTION_FINISHED"
    TASK_COMPLETION_PREREQUISITES = "TASK_COMPLETION_PREREQUISITES"
    DEPENDENCIES_SATISFIED = "DEPENDENCIES_SATISFIED"
    RESOURCES_AVAILABLE = "RESOURCES_AVAILABLE"
    ATTEMPT_ENDED = "ATTEMPT_ENDED"
    VERIFIED_PREREQUISITES = "VERIFIED_PREREQUISITES"
    STALE_CAUSE_PRESENT = "STALE_CAUSE_PRESENT"
    PLAN_THREE_GUARDS = "PLAN_THREE_GUARDS"
    RECOVERY_BUDGET_AVAILABLE = "RECOVERY_BUDGET_AVAILABLE"
    DIAGNOSIS_VALID = "DIAGNOSIS_VALID"
    RECOVERY_RECHECKED = "RECOVERY_RECHECKED"


class ReasonCode(StrEnum):
    # success
    TASK_PLANNING_STARTED = "TASK_PLANNING_STARTED"
    TASK_CANCELLED = "TASK_CANCELLED"
    DAG_VALIDATED = "DAG_VALIDATED"
    DAG_BLOCKING_GAP = "DAG_BLOCKING_GAP"
    TASK_FAILED = "TASK_FAILED"
    TASK_READY = "TASK_READY"
    TASK_RUNNING = "TASK_RUNNING"
    TASK_VERIFYING = "TASK_VERIFYING"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_BLOCKED = "TASK_BLOCKED"
    NODE_READY = "NODE_READY"
    NODE_RUNNING = "NODE_RUNNING"
    NODE_VERIFYING = "NODE_VERIFYING"
    NODE_VERIFIED = "NODE_VERIFIED"
    NODE_FAILED = "NODE_FAILED"
    NODE_BLOCKED = "NODE_BLOCKED"
    NODE_INVALIDATED = "NODE_INVALIDATED"
    NODE_DIAGNOSING = "NODE_DIAGNOSING"
    NODE_RECOVERING = "NODE_RECOVERING"
    TASK_CREATED = "TASK_CREATED"
    NODE_PLANNED = "NODE_PLANNED"
    RECOVERY_PLAN_FROZEN = "RECOVERY_PLAN_FROZEN"
    # denials
    ILLEGAL_EDGE = "ILLEGAL_EDGE"
    STALE_PREVIOUS_STATE = "STALE_PREVIOUS_STATE"
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    OBJECT_TYPE_NOT_MANAGED = "OBJECT_TYPE_NOT_MANAGED"
    OBJECT_ALREADY_EXISTS = "OBJECT_ALREADY_EXISTS"
    INITIAL_STATE_INVALID = "INITIAL_STATE_INVALID"
    PLAN_FIELDS_NOT_ALLOWED = "PLAN_FIELDS_NOT_ALLOWED"
    PORT_UNAVAILABLE = "PORT_UNAVAILABLE"
    DAG_INVALID = "DAG_INVALID"
    NO_READY_NODE = "NO_READY_NODE"
    EXECUTION_NOT_FINISHED = "EXECUTION_NOT_FINISHED"
    TASK_COMPLETION_PREREQUISITES = "TASK_COMPLETION_PREREQUISITES"
    REPORT_NOT_VERIFIED = "REPORT_NOT_VERIFIED"
    CERTIFICATE_INVALID = "CERTIFICATE_INVALID"
    DEPENDENCIES_NOT_SATISFIED = "DEPENDENCIES_NOT_SATISFIED"
    RESOURCES_UNAVAILABLE = "RESOURCES_UNAVAILABLE"
    ATTEMPT_NOT_ENDED = "ATTEMPT_NOT_ENDED"
    EXIT_CODE_NONZERO = "EXIT_CODE_NONZERO"
    GATE_NOT_PASS = "GATE_NOT_PASS"
    RECOVERY_BUDGET_EXHAUSTED = "RECOVERY_BUDGET_EXHAUSTED"
    DIAGNOSIS_INVALID = "DIAGNOSIS_INVALID"
    RECOVERY_RECHECK_FAILED = "RECOVERY_RECHECK_FAILED"
    GUARD_FAILED = "GUARD_FAILED"
    EVIDENCE_CHAIN_BROKEN = "EVIDENCE_CHAIN_BROKEN"
    STATE_WRITE_FAILED = "STATE_WRITE_FAILED"
    CAUSE_INVALID = "CAUSE_INVALID"
    NO_STALE_EVIDENCE = "NO_STALE_EVIDENCE"
    PLAN_FILE_MISSING = "PLAN_FILE_MISSING"
    PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
    PLAN_FREEZE_RECORD_MISSING = "PLAN_FREEZE_RECORD_MISSING"
    PLAN_ID_MISMATCH = "PLAN_ID_MISMATCH"
    PLAN_FROZEN_AFTER_RERUN = "PLAN_FROZEN_AFTER_RERUN"
    UNSAFE_PLAN_PATH = "UNSAFE_PLAN_PATH"
    WRITE_LOCK_TIMEOUT = "WRITE_LOCK_TIMEOUT"
    AUDIT_WRITE_FAILED = "AUDIT_WRITE_FAILED"


@dataclass(frozen=True, slots=True)
class Transition:
    obj_type: ObjectType
    from_state: str
    to_state: str
    allowed_roles: frozenset[ActorRole]
    guard_id: GuardId
    reason_code: ReasonCode
    basis: str


def _task(
    *,
    from_state: TaskState,
    to_state: TaskState,
    roles: tuple[ActorRole, ...],
    guard: GuardId,
    reason: ReasonCode,
    basis: str,
) -> Transition:
    return Transition(
        ObjectType.TASK,
        from_state.value,
        to_state.value,
        frozenset(roles),
        guard,
        reason,
        basis,
    )


def _node(
    *,
    from_state: NodeState,
    to_state: NodeState,
    roles: tuple[ActorRole, ...],
    guard: GuardId,
    reason: ReasonCode,
    basis: str,
) -> Transition:
    return Transition(
        ObjectType.NODE,
        from_state.value,
        to_state.value,
        frozenset(roles),
        guard,
        reason,
        basis,
    )


TASK_TRANSITIONS: Final[tuple[Transition, ...]] = (
    _task(
        from_state=TaskState.CREATED,
        to_state=TaskState.PLANNING,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.NONE,
        reason=ReasonCode.TASK_PLANNING_STARTED,
        basis="05 §9.2",
    ),
    _task(
        from_state=TaskState.CREATED,
        to_state=TaskState.CANCELLED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.OPERATOR),
        guard=GuardId.NONE,
        reason=ReasonCode.TASK_CANCELLED,
        basis="05 §9.2",
    ),
    _task(
        from_state=TaskState.PLANNING,
        to_state=TaskState.READY,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.DAG_VALID,
        reason=ReasonCode.TASK_READY,
        basis="05 §9.2 R03",
    ),
    _task(
        from_state=TaskState.PLANNING,
        to_state=TaskState.BLOCKED,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.DAG_BLOCKING_GAP,
        reason=ReasonCode.TASK_BLOCKED,
        basis="05 §9.2 R03",
    ),
    _task(
        from_state=TaskState.PLANNING,
        to_state=TaskState.FAILED,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.TASK_FAILED,
        basis="05 §9.2",
    ),
    _task(
        from_state=TaskState.READY,
        to_state=TaskState.RUNNING,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.AT_LEAST_ONE_NODE_READY,
        reason=ReasonCode.TASK_RUNNING,
        basis="05 §9.2 R04",
    ),
    _task(
        from_state=TaskState.READY,
        to_state=TaskState.CANCELLED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.OPERATOR),
        guard=GuardId.NONE,
        reason=ReasonCode.TASK_CANCELLED,
        basis="05 §9.2",
    ),
    _task(
        from_state=TaskState.RUNNING,
        to_state=TaskState.VERIFYING,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.EXECUTION_FINISHED,
        reason=ReasonCode.TASK_VERIFYING,
        basis="05 §9.2 R05",
    ),
    _task(
        from_state=TaskState.RUNNING,
        to_state=TaskState.FAILED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.TASK_FAILED,
        basis="05 §9.2",
    ),
    _task(
        from_state=TaskState.RUNNING,
        to_state=TaskState.BLOCKED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.TASK_BLOCKED,
        basis="05 §9.2",
    ),
    _task(
        from_state=TaskState.VERIFYING,
        to_state=TaskState.COMPLETED,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.TASK_COMPLETION_PREREQUISITES,
        reason=ReasonCode.TASK_COMPLETED,
        basis="05 §9.2 R06",
    ),
    _task(
        from_state=TaskState.VERIFYING,
        to_state=TaskState.FAILED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.TASK_FAILED,
        basis="05 §9.2",
    ),
    _task(
        from_state=TaskState.VERIFYING,
        to_state=TaskState.BLOCKED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.TASK_BLOCKED,
        basis="05 §9.2",
    ),
)

NODE_TRANSITIONS: Final[tuple[Transition, ...]] = (
    _node(
        from_state=NodeState.PLANNED,
        to_state=NodeState.READY,
        roles=(ActorRole.SCHEDULER,),
        guard=GuardId.DEPENDENCIES_SATISFIED,
        reason=ReasonCode.NODE_READY,
        basis="05 §9.3 R07",
    ),
    _node(
        from_state=NodeState.PLANNED,
        to_state=NodeState.BLOCKED,
        roles=(ActorRole.SCHEDULER, ActorRole.ORCHESTRATOR),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_BLOCKED,
        basis="05 §9.3",
    ),
    _node(
        from_state=NodeState.READY,
        to_state=NodeState.RUNNING,
        roles=(ActorRole.SCHEDULER,),
        guard=GuardId.RESOURCES_AVAILABLE,
        reason=ReasonCode.NODE_RUNNING,
        basis="05 §9.3 R08",
    ),
    _node(
        from_state=NodeState.READY,
        to_state=NodeState.BLOCKED,
        roles=(ActorRole.SCHEDULER, ActorRole.ORCHESTRATOR),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_BLOCKED,
        basis="05 §9.3",
    ),
    _node(
        from_state=NodeState.RUNNING,
        to_state=NodeState.VERIFYING,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.ATTEMPT_ENDED,
        reason=ReasonCode.NODE_VERIFYING,
        basis="05 §9.3 R09",
    ),
    _node(
        from_state=NodeState.RUNNING,
        to_state=NodeState.FAILED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_FAILED,
        basis="05 §9.3",
    ),
    _node(
        from_state=NodeState.VERIFYING,
        to_state=NodeState.VERIFIED,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.VERIFIED_PREREQUISITES,
        reason=ReasonCode.NODE_VERIFIED,
        basis="05 §9.3 R10",
    ),
    _node(
        from_state=NodeState.VERIFYING,
        to_state=NodeState.FAILED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_FAILED,
        basis="05 §9.3",
    ),
    _node(
        from_state=NodeState.VERIFYING,
        to_state=NodeState.BLOCKED,
        roles=(ActorRole.ORCHESTRATOR, ActorRole.BOOT_RECOVERY),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_BLOCKED,
        basis="05 §9.3",
    ),
    _node(
        from_state=NodeState.VERIFIED,
        to_state=NodeState.INVALIDATED,
        roles=(ActorRole.WP_R,),
        guard=GuardId.STALE_CAUSE_PRESENT,
        reason=ReasonCode.NODE_INVALIDATED,
        basis="ADR-001；05 §9.3",
    ),
    _node(
        from_state=NodeState.INVALIDATED,
        to_state=NodeState.READY,
        roles=(ActorRole.WP_R,),
        guard=GuardId.PLAN_THREE_GUARDS,
        reason=ReasonCode.NODE_READY,
        basis="ADR-004；05 §9.3",
    ),
    _node(
        from_state=NodeState.FAILED,
        to_state=NodeState.DIAGNOSING,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.RECOVERY_BUDGET_AVAILABLE,
        reason=ReasonCode.NODE_DIAGNOSING,
        basis="05 §9.3 R11",
    ),
    _node(
        from_state=NodeState.FAILED,
        to_state=NodeState.BLOCKED,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_BLOCKED,
        basis="05 §9.3",
    ),
    _node(
        from_state=NodeState.DIAGNOSING,
        to_state=NodeState.RECOVERING,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.DIAGNOSIS_VALID,
        reason=ReasonCode.NODE_RECOVERING,
        basis="05 §9.3 R12",
    ),
    _node(
        from_state=NodeState.DIAGNOSING,
        to_state=NodeState.BLOCKED,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_BLOCKED,
        basis="05 §9.3",
    ),
    _node(
        from_state=NodeState.RECOVERING,
        to_state=NodeState.READY,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.RECOVERY_RECHECKED,
        reason=ReasonCode.NODE_READY,
        basis="05 §9.3 R13",
    ),
    _node(
        from_state=NodeState.RECOVERING,
        to_state=NodeState.BLOCKED,
        roles=(ActorRole.ORCHESTRATOR,),
        guard=GuardId.FAILURE_EVIDENCE_PRESENT,
        reason=ReasonCode.NODE_BLOCKED,
        basis="05 §9.3",
    ),
)

_TASK_INDEX: Final[dict[tuple[str, str], Transition]] = {
    (edge.from_state, edge.to_state): edge for edge in TASK_TRANSITIONS
}
_NODE_INDEX: Final[dict[tuple[str, str], Transition]] = {
    (edge.from_state, edge.to_state): edge for edge in NODE_TRANSITIONS
}


class IllegalTransition(ValueError):
    def __init__(self, *, obj_type: ObjectType, from_state: str, to_state: str) -> None:
        self.obj_type = obj_type
        self.from_state = from_state
        self.to_state = to_state
        self.reason = ReasonCode.ILLEGAL_EDGE
        super().__init__(
            f"ILLEGAL_EDGE: {obj_type.value} {from_state} -> {to_state}"
        )


def allowed_next_states(obj_type: ObjectType, state: str) -> tuple[str, ...]:
    if obj_type is ObjectType.TASK:
        return tuple(
            edge.to_state for edge in TASK_TRANSITIONS if edge.from_state == state
        )
    if obj_type is ObjectType.NODE:
        return tuple(
            edge.to_state for edge in NODE_TRANSITIONS if edge.from_state == state
        )
    raise ValueError(f"unsupported object type: {obj_type}")


def lookup_transition(
    obj_type: ObjectType, from_state: str, to_state: str
) -> Transition:
    if obj_type is ObjectType.TASK:
        index = _TASK_INDEX
    elif obj_type is ObjectType.NODE:
        index = _NODE_INDEX
    else:
        raise ValueError(f"unsupported object type: {obj_type}")
    edge = index.get((from_state, to_state))
    if edge is None:
        raise IllegalTransition(
            obj_type=obj_type, from_state=from_state, to_state=to_state
        )
    return edge


def assert_transition_contract() -> list[str]:
    problems: list[str] = []
    if len(TASK_TRANSITIONS) != 13:
        problems.append(f"Task edges should be 13, got {len(TASK_TRANSITIONS)}")
    if len(NODE_TRANSITIONS) != 17:
        problems.append(f"Node edges should be 17, got {len(NODE_TRANSITIONS)}")
    for state in TaskState:
        if state.value in T1_RECOVERY_STATES:
            problems.append(f"T1 recovery state in Task: {state.value}")
    for state in NodeState:
        if state.value in T1_RECOVERY_STATES:
            problems.append(f"T1 recovery state in Node: {state.value}")
    if any(edge.from_state == "BLOCKED" for edge in TASK_TRANSITIONS + NODE_TRANSITIONS):
        problems.append("BLOCKED must have no outgoing edges in T0")
    if any(
        edge.from_state == "VERIFIED" and edge.to_state == "READY"
        for edge in NODE_TRANSITIONS
    ):
        problems.append("VERIFIED->READY is not authorised")
    if any(
        edge.from_state == "COMPLETED" for edge in TASK_TRANSITIONS
    ):
        problems.append("COMPLETED must be terminal in T0")
    return problems