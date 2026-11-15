"""The single state-writing entry point for T0 WP-03.

Design rules:

* ``transition()`` is the only public method that changes an existing
  Task/Node state.
* ``create_initial()`` is the only creation entry point; it writes only
  ``CREATED``/``PLANNED`` rows plus an initial OK audit row.
* Successful transitions write state + ``audit_log(OK)`` in one transaction.
* Denied transitions roll back, then write ``audit_log(DENIED)`` in a new
  transaction.  A second audit failure is degraded to one structured stderr
  line and raises ``AuditWriteFailed`` — it is never swallowed.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from researchflow.contracts.encoding import hash_payload
from researchflow.contracts.errors import api_status
from researchflow.contracts.models import NodeSpec, TaskSpec
from researchflow.persistence.db import connect, format_utc, parse_utc, transaction, utc_now
from researchflow.persistence.repositories import (
    AuditRepository,
    AuditRow,
    Capability,
    EvidenceRepository,
    IdempotencyRepository,
    NodeRepository,
    NodeRow,
    STATE_MACHINE_WRITE,
    TASK_CREATION,
    TaskRepository,
    TaskRow,
)
from researchflow.orchestration.ports import (
    AttemptEnd,
    CertificateFacts,
    EvidenceFacts,
    PlanFileMissing,
    Ports,
    ReportFacts,
    UnsafePlanPath,
)
from researchflow.orchestration.transitions import (
    ActorRole,
    GuardId,
    IllegalTransition,
    NON_WRITER_ROLES,
    NodeState,
    ObjectType,
    ReasonCode,
    TaskState,
    Transition,
    lookup_transition,
)

__all__ = [
    "Actor",
    "AuditWriteFailed",
    "AUDIT_SENTINEL",
    "InitialResult",
    "InitializationDenied",
    "StateMachine",
    "StateTransitionDenied",
    "TransitionContext",
    "TransitionRequest",
    "TransitionResult",
    "assert_single_write_entrypoint",
]

AUDIT_SENTINEL = "<missing>"
_PLAN_HASH_RE = "0123456789abcdef"


class StateTransitionDenied(RuntimeError):
    """Public denial carrying both the API code and the internal domain code."""

    def __init__(
        self,
        *,
        api_error_code: str,
        error_code: str,
        reason: str,
        obj_type: str,
        obj_id: str | None,
        previous_state: str | None,
        next_state: str | None,
        correlation_id: str | None,
        audit_id: str | None = None,
        details: str = "",
        field_path: str | None = None,
        audit_degraded: bool = False,
    ) -> None:
        self.api_error_code = api_error_code
        self.error_code = error_code
        self.reason = reason
        self.obj_type = obj_type
        self.obj_id = obj_id
        self.previous_state = previous_state
        self.next_state = next_state
        self.correlation_id = correlation_id
        self.audit_id = audit_id
        self.details = details
        self.field_path = field_path
        self.audit_degraded = audit_degraded
        self.http_status = api_status(api_error_code, default=409)
        suffix = f"；{details}" if details else ""
        super().__init__(
            f"{api_error_code}/{error_code}: {obj_type} {obj_id} "
            f"{previous_state} -> {next_state} ({reason}){suffix}"
        )


class AuditWriteFailed(RuntimeError):
    error_code = "AUDIT_WRITE_FAILED"
    http_status = 500

    def __init__(
        self,
        *,
        original_error_code: str,
        correlation_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        self.original_error_code = original_error_code
        self.correlation_id = correlation_id
        self.audit_write_failed = True
        self.payload = payload
        super().__init__(
            "DENIED audit write failed; structured stderr emitted and the gap must be reported"
        )


class InitializationDenied(RuntimeError):
    def __init__(
        self,
        *,
        reason: ReasonCode | str,
        message: str,
        api_error_code: str = "STATE_TRANSITION_DENIED",
        field_path: str | None = None,
    ) -> None:
        self.reason = reason.value if isinstance(reason, ReasonCode) else str(reason)
        self.message = message
        self.api_error_code = api_error_code
        self.field_path = field_path
        self.http_status = api_status(api_error_code, default=409)
        super().__init__(message)


class _AuditInsertFailed(Exception):
    def __init__(self, payload: dict[str, Any], original: BaseException) -> None:
        self.payload = payload
        self.original = original


class _Denial(Exception):
    def __init__(
        self,
        reason: ReasonCode,
        *,
        api_error_code: str = "STATE_TRANSITION_DENIED",
        error_code: str = "STATE_TRANSITION_DENIED",
        details: str = "",
        field_path: str | None = None,
        previous_state: str | None = None,
        next_state: str | None = None,
    ) -> None:
        self.reason = reason
        self.api_error_code = api_error_code
        self.error_code = error_code
        self.details = details
        self.field_path = field_path
        self.previous_state = previous_state
        self.next_state = next_state
        super().__init__(f"{error_code}/{reason.value}: {details}")


@dataclass(frozen=True, slots=True)
class Actor:
    role: ActorRole
    identity: str

    def __post_init__(self) -> None:
        try:
            role = ActorRole(self.role)
        except ValueError as exc:
            raise ValueError(f"unknown actor role: {self.role!r}") from exc
        object.__setattr__(self, "role", role)
        if not isinstance(self.identity, str):
            raise TypeError("actor identity must be a string")
        if not 1 <= len(self.identity) <= 64:
            raise ValueError("actor identity must be 1–64 characters")
        if ":" in self.identity:
            raise ValueError("actor identity must not contain ':'")

    @property
    def audit_value(self) -> str:
        return f"{self.role.value}:{self.identity}"


@dataclass(frozen=True, slots=True)
class TransitionContext:
    graph_version: int | None = None
    failure_ref: str | None = None
    attempt_id: str | None = None
    recovery_ref: str | None = None
    diagnosis_ref: str | None = None
    recheck_ref: str | None = None
    evidence_ids: tuple[str, ...] = ()
    cause_type: str | None = None
    cause_ref: str | None = None
    plan_id: str | None = None
    plan_hash: str | None = None
    received_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    obj_type: ObjectType | str
    task_id: str | None
    next_state: str | None
    previous_state: str | None
    actor: Actor | None
    reason_code: str | None
    rule_version: str | None
    correlation_id: str | None
    node_id: str | None = None
    context: TransitionContext = field(default_factory=TransitionContext)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    ok: bool
    obj_type: str
    obj_id: str
    previous_state: str
    next_state: str
    audit_id: str
    applied_at: str
    correlation_id: str
    attempt_seq: int | None = None
    plan_id: str | None = None
    plan_hash: str | None = None


@dataclass(frozen=True, slots=True)
class InitialResult:
    ok: bool
    obj_type: str
    obj_id: str
    state: str
    audit_id: str
    created_at: str
    correlation_id: str


class _SystemClock:
    def now(self) -> datetime:
        return utc_now()


class StateMachine:
    def __init__(
        self,
        db_path: str | Path,
        *,
        task_repository: TaskRepository | None = None,
        node_repository: NodeRepository | None = None,
        audit_repository: AuditRepository | None = None,
        evidence_repository: EvidenceRepository | None = None,
        idempotency_repository: IdempotencyRepository | None = None,
        ports: Ports | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._tasks = task_repository or TaskRepository()
        self._nodes = node_repository or NodeRepository()
        self._audit = audit_repository or AuditRepository()
        self._evidence = evidence_repository or EvidenceRepository()
        self._idempotency = idempotency_repository or IdempotencyRepository()
        self._ports = ports or Ports()
        self._clock = self._ports.clock or _SystemClock()

    # ------------------------------------------------------------------ helpers
    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def _now(self) -> datetime:
        return self._clock.now()

    @staticmethod
    def _parse_obj_type(value: ObjectType | str) -> ObjectType:
        if isinstance(value, ObjectType):
            return value
        try:
            return ObjectType(str(value))
        except ValueError:
            return ObjectType.EVIDENCE

    def _require_port(self, name: str):
        port = getattr(self._ports, name)
        if port is None:
            raise _Denial(
                ReasonCode.PORT_UNAVAILABLE,
                details=f"{name} port is not configured",
            )
        return port

    def _load_object(
        self, connection: sqlite3.Connection, obj_type: ObjectType, task_id: str, node_id: str | None
    ) -> TaskRow | NodeRow | None:
        if obj_type is ObjectType.TASK:
            return self._tasks.get(connection, task_id)
        if obj_type is ObjectType.NODE:
            if node_id is None:
                return None
            return self._nodes.get(connection, task_id, node_id)
        return None

    # -------------------------------------------------------------- create_initial
    def create_initial(
        self,
        *,
        obj_type: ObjectType | str,
        task_id: str,
        actor: Actor,
        correlation_id: str,
        rule_version: str = "1.0",
        task_spec: TaskSpec | None = None,
        node_id: str | None = None,
        node_spec: NodeSpec | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> InitialResult:
        parsed_type = self._parse_obj_type(obj_type)
        if parsed_type is ObjectType.EVIDENCE:
            raise InitializationDenied(
                reason=ReasonCode.OBJECT_TYPE_NOT_MANAGED,
                message="StateMachine does not create Evidence rows",
            )
        if not isinstance(task_id, str) or not task_id:
            raise InitializationDenied(
                reason=ReasonCode.MISSING_PARAMETER,
                message="task_id is required",
                field_path="task_id",
            )
        if not isinstance(correlation_id, str) or not correlation_id:
            raise InitializationDenied(
                reason=ReasonCode.MISSING_PARAMETER,
                message="correlation_id is required",
                field_path="correlation_id",
            )
        if not isinstance(actor, Actor):
            raise InitializationDenied(
                reason=ReasonCode.MISSING_PARAMETER,
                message="actor is required",
                field_path="actor",
            )

        if parsed_type is ObjectType.TASK:
            if task_spec is None or not isinstance(task_spec, TaskSpec):
                raise InitializationDenied(
                    reason=ReasonCode.MISSING_PARAMETER,
                    message="task_spec is required",
                    field_path="task_spec",
                )
            if actor.role not in {ActorRole.API, ActorRole.ORCHESTRATOR}:
                raise InitializationDenied(
                    reason=ReasonCode.ROLE_NOT_ALLOWED,
                    message=f"role {actor.role.value!r} may not create tasks",
                )
            if task_spec.task_id != task_id:
                raise InitializationDenied(
                    reason=ReasonCode.MISSING_PARAMETER,
                    message="task_spec.task_id must match task_id",
                    field_path="task_id",
                )
        else:
            if node_spec is None or not isinstance(node_spec, NodeSpec):
                raise InitializationDenied(
                    reason=ReasonCode.MISSING_PARAMETER,
                    message="node_spec is required",
                    field_path="node_spec",
                )
            if not node_id or node_spec.node_id != node_id:
                raise InitializationDenied(
                    reason=ReasonCode.MISSING_PARAMETER,
                    message="node_id must match node_spec.node_id",
                    field_path="node_id",
                )
            if actor.role is not ActorRole.ORCHESTRATOR:
                raise InitializationDenied(
                    reason=ReasonCode.ROLE_NOT_ALLOWED,
                    message=f"role {actor.role.value!r} may not create nodes",
                )

        now = format_utc(self._now())

        def execute(connection_in_use: sqlite3.Connection) -> InitialResult:
            return self._create_initial_in_transaction(
                connection_in_use,
                parsed_type=parsed_type,
                task_id=task_id,
                node_id=node_id,
                task_spec=task_spec,
                node_spec=node_spec,
                actor=actor,
                correlation_id=correlation_id,
                rule_version=rule_version,
                now=now,
            )

        if connection is not None:
            try:
                return execute(connection)
            except sqlite3.IntegrityError as exc:
                raise self._initialization_denied_from_integrity(exc) from exc

        connection_in_use = self._connect()
        try:
            try:
                with transaction(connection_in_use):
                    return execute(connection_in_use)
            except sqlite3.IntegrityError as exc:
                raise self._initialization_denied_from_integrity(exc) from exc
        finally:
            connection_in_use.close()

    def _create_initial_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        parsed_type: ObjectType,
        task_id: str,
        node_id: str | None,
        task_spec: TaskSpec | None,
        node_spec: NodeSpec | None,
        actor: Actor,
        correlation_id: str,
        rule_version: str,
        now: str,
    ) -> InitialResult:
        audit_id = uuid.uuid4().hex
        if parsed_type is ObjectType.TASK:
            assert task_spec is not None
            task_spec_json = task_spec.model_dump_json()
            self._tasks._insert_initial(
                connection,
                task_id=task_id,
                schema_version=task_spec.schema_version,
                domain_pack=task_spec.domain_pack,
                goal=task_spec.goal,
                task_spec_hash=hash_payload(task_spec.model_dump(mode="json")),
                task_spec_json=task_spec_json,
                created_at=now,
                updated_at=now,
                capability=TASK_CREATION,
            )
            self._audit.append(
                connection,
                audit_id=audit_id,
                task_id=task_id,
                node_id=None,
                actor=actor.audit_value,
                action="TASK_CREATED",
                previous_state=None,
                next_state=TaskState.CREATED.value,
                reason_code=ReasonCode.TASK_CREATED.value,
                rule_version=rule_version,
                correlation_id=correlation_id,
                plan_id=None,
                plan_hash=None,
                result="OK",
                error_code=None,
                created_at=now,
                capability=STATE_MACHINE_WRITE,
            )
            return InitialResult(
                ok=True,
                obj_type=ObjectType.TASK.value,
                obj_id=task_id,
                state=TaskState.CREATED.value,
                audit_id=audit_id,
                created_at=now,
                correlation_id=correlation_id,
            )

        assert node_spec is not None and node_id is not None
        self._nodes._insert_initial(
            connection,
            task_id=task_id,
            node_id=node_id,
            schema_version=node_spec.schema_version,
            node_type=node_spec.node_type,
            template_id=node_spec.template_id,
            updated_at=now,
            capability=TASK_CREATION,
        )
        self._audit.append(
            connection,
            audit_id=audit_id,
            task_id=task_id,
            node_id=node_id,
            actor=actor.audit_value,
            action="NODE_PLANNED",
            previous_state=None,
            next_state=NodeState.PLANNED.value,
            reason_code=ReasonCode.NODE_PLANNED.value,
            rule_version=rule_version,
            correlation_id=correlation_id,
            plan_id=None,
            plan_hash=None,
            result="OK",
            error_code=None,
            created_at=now,
            capability=STATE_MACHINE_WRITE,
        )
        return InitialResult(
            ok=True,
            obj_type=ObjectType.NODE.value,
            obj_id=node_id,
            state=NodeState.PLANNED.value,
            audit_id=audit_id,
            created_at=now,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _initialization_denied_from_integrity(exc: sqlite3.IntegrityError) -> InitializationDenied:
        text = str(exc)
        if "UNIQUE" in text or "PRIMARY KEY" in text:
            reason = ReasonCode.OBJECT_ALREADY_EXISTS
        elif "MUST_BE_INSERTED" in text or "INITIAL_STATE" in text:
            reason = ReasonCode.INITIAL_STATE_INVALID
        else:
            reason = ReasonCode.STATE_WRITE_FAILED
        return InitializationDenied(reason=reason, message=text)

    # ----------------------------------------------------------------- transition
    def transition(self, request: TransitionRequest) -> TransitionResult:
        obj_type = self._parse_obj_type(request.obj_type)
        try:
            if obj_type is ObjectType.EVIDENCE:
                raise _Denial(
                    ReasonCode.OBJECT_TYPE_NOT_MANAGED,
                    details="StateMachine only manages Task/Node state",
                )
            self._validate_request(request, obj_type)
            connection = self._connect()
            try:
                obj = self._load_object(
                    connection, obj_type, request.task_id or "", request.node_id
                )
            finally:
                connection.close()
            if obj is None:
                raise _Denial(
                    ReasonCode.OBJECT_NOT_FOUND,
                    previous_state=request.previous_state,
                    next_state=request.next_state,
                )
            if request.previous_state != obj.state:
                raise _Denial(
                    ReasonCode.STALE_PREVIOUS_STATE,
                    previous_state=obj.state,
                    next_state=request.next_state,
                    details=f"persisted state is {obj.state}",
                )
            try:
                edge = lookup_transition(obj_type, obj.state, request.next_state or "")
            except IllegalTransition:
                raise _Denial(
                    ReasonCode.ILLEGAL_EDGE,
                    previous_state=obj.state,
                    next_state=request.next_state,
                ) from None
            self._check_role(request.actor, edge)
            self._evaluate_guard(request, obj, edge)
            return self._apply_success(request, obj, edge)
        except _Denial as denial:
            audit_id = self._deny(request, denial)
            raise StateTransitionDenied(
                api_error_code=denial.api_error_code,
                error_code=denial.error_code,
                reason=denial.reason.value,
                obj_type=obj_type.value,
                obj_id=request.node_id if obj_type is ObjectType.NODE else request.task_id,
                previous_state=denial.previous_state or request.previous_state,
                next_state=denial.next_state or request.next_state,
                correlation_id=request.correlation_id,
                audit_id=audit_id,
                details=denial.details,
                field_path=denial.field_path,
            ) from None
        except AuditWriteFailed:
            raise
        except StateTransitionDenied:
            raise
        except Exception as exc:  # defensive: never let an unexpected failure skip DENIED
            denial = _Denial(
                ReasonCode.STATE_WRITE_FAILED,
                details=f"{type(exc).__name__}: {exc}",
                previous_state=request.previous_state,
                next_state=request.next_state,
            )
            audit_id = self._deny(request, denial)
            raise StateTransitionDenied(
                api_error_code=denial.api_error_code,
                error_code=denial.error_code,
                reason=denial.reason.value,
                obj_type=obj_type.value,
                obj_id=request.node_id if obj_type is ObjectType.NODE else request.task_id,
                previous_state=denial.previous_state,
                next_state=denial.next_state,
                correlation_id=request.correlation_id,
                audit_id=audit_id,
                details=denial.details,
            ) from exc

    def _validate_request(self, request: TransitionRequest, obj_type: ObjectType) -> None:
        if not isinstance(request.task_id, str) or not request.task_id:
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="task_id",
                details="task_id is required",
            )
        if obj_type is ObjectType.NODE and (
            not isinstance(request.node_id, str) or not request.node_id
        ):
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="node_id",
                details="node_id is required for Node transitions",
            )
        if not isinstance(request.previous_state, str) or not request.previous_state:
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="previous_state",
                details="previous_state is required",
            )
        if not isinstance(request.next_state, str) or not request.next_state:
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="next_state",
                details="next_state is required",
            )
        if not isinstance(request.actor, Actor):
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="actor",
                details="actor is required",
            )
        if request.actor.role in NON_WRITER_ROLES:
            raise _Denial(
                ReasonCode.ROLE_NOT_ALLOWED,
                details=f"role {request.actor.role.value!r} is not a state writer",
            )
        for field_name in ("reason_code", "rule_version", "correlation_id"):
            if not isinstance(getattr(request, field_name), str) or not getattr(request, field_name):
                raise _Denial(
                    ReasonCode.MISSING_PARAMETER,
                    field_path=field_name,
                    details=f"{field_name} is required",
                )

        context = request.context
        has_plan_id = context.plan_id is not None
        has_plan_hash = context.plan_hash is not None
        if has_plan_id != has_plan_hash:
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="plan_id/plan_hash",
                details="plan_id and plan_hash must be supplied together",
            )
        plan_edge = (
            obj_type is ObjectType.NODE
            and request.previous_state == NodeState.INVALIDATED.value
            and request.next_state == NodeState.READY.value
        )
        if (has_plan_id or has_plan_hash) and not plan_edge:
            raise _Denial(
                ReasonCode.PLAN_FIELDS_NOT_ALLOWED,
                details="plan_id/plan_hash are only allowed on INVALIDATED -> READY",
            )
        if plan_edge and not (has_plan_id and has_plan_hash):
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="plan_hash",
                details="INVALIDATED -> READY requires plan_id and plan_hash",
            )

    @staticmethod
    def _check_role(actor: Actor | None, edge: Transition) -> None:
        assert actor is not None
        if actor.role not in edge.allowed_roles:
            raise _Denial(
                ReasonCode.ROLE_NOT_ALLOWED,
                details=f"role {actor.role.value!r} not allowed for this edge",
            )

    def _evaluate_guard(
        self, request: TransitionRequest, obj: TaskRow | NodeRow, edge: Transition
    ) -> None:
        context = request.context
        guard = edge.guard_id
        if guard is GuardId.NONE:
            return
        if guard is GuardId.DAG_VALID:
            graph = self._require_port("graph")
            if context.graph_version is None or not graph.dag_valid(
                request.task_id or "", context.graph_version
            ):
                raise _Denial(
                    ReasonCode.DAG_INVALID,
                    details="DAG validation failed or graph_version is missing",
                )
            return
        if guard is GuardId.DAG_BLOCKING_GAP:
            graph = self._require_port("graph")
            if not graph.blocking_gap(request.task_id or "", context.failure_ref or ""):
                raise _Denial(ReasonCode.DAG_INVALID, details="no blocking gap")
            return
        if guard is GuardId.FAILURE_EVIDENCE_PRESENT:
            if not context.failure_ref:
                raise _Denial(
                    ReasonCode.MISSING_PARAMETER,
                    field_path="failure_ref",
                    details="failure_ref is required",
                )
            return
        if guard is GuardId.AT_LEAST_ONE_NODE_READY:
            task_facts = self._require_port("task")
            if not task_facts.has_ready_node(request.task_id or ""):
                raise _Denial(ReasonCode.NO_READY_NODE)
            return
        if guard is GuardId.EXECUTION_FINISHED:
            task_facts = self._require_port("task")
            if not task_facts.execution_finished(request.task_id or ""):
                raise _Denial(
                    ReasonCode.ATTEMPT_NOT_ENDED,
                    details="execution still has unfinished nodes",
                )
            return
        if guard is GuardId.TASK_COMPLETION_PREREQUISITES:
            self._guard_task_completion(request)
            return
        if guard is GuardId.DEPENDENCIES_SATISFIED:
            node_facts = self._require_port("node")
            if not node_facts.dependencies_satisfied(
                request.task_id or "", request.node_id or ""
            ):
                raise _Denial(ReasonCode.DEPENDENCIES_NOT_SATISFIED)
            return
        if guard is GuardId.RESOURCES_AVAILABLE:
            node_facts = self._require_port("node")
            if not node_facts.resources_available(
                request.task_id or "", request.node_id or ""
            ):
                raise _Denial(ReasonCode.RESOURCES_UNAVAILABLE)
            return
        if guard is GuardId.ATTEMPT_ENDED:
            self._guard_attempt_ended(request)
            return
        if guard is GuardId.VERIFIED_PREREQUISITES:
            self._guard_verified_prerequisites(request)
            return
        if guard is GuardId.RECOVERY_BUDGET_AVAILABLE:
            node_facts = self._require_port("node")
            if not node_facts.recovery_budget_available(
                request.task_id or "", request.node_id or "", context.recovery_ref or ""
            ):
                raise _Denial(ReasonCode.RECOVERY_BUDGET_EXHAUSTED)
            return
        if guard is GuardId.DIAGNOSIS_VALID:
            node_facts = self._require_port("node")
            if not node_facts.diagnosis_valid(
                request.task_id or "", request.node_id or "", context.diagnosis_ref or ""
            ):
                raise _Denial(ReasonCode.DIAGNOSIS_INVALID)
            return
        if guard is GuardId.RECOVERY_RECHECKED:
            node_facts = self._require_port("node")
            if not node_facts.recovery_rechecked(
                request.task_id or "", request.node_id or "", context.recheck_ref or ""
            ):
                raise _Denial(ReasonCode.RECOVERY_RECHECK_FAILED)
            return
        if guard is GuardId.STALE_CAUSE_PRESENT:
            self._guard_stale_cause(request)
            return
        if guard is GuardId.PLAN_THREE_GUARDS:
            self._guard_plan_three(request)
            return
        raise _Denial(ReasonCode.GUARD_FAILED, details=f"unknown guard {guard!r}")

    def _guard_attempt_ended(self, request: TransitionRequest) -> None:
        node_facts = self._require_port("node")
        attempt: AttemptEnd = node_facts.attempt_end(
            request.task_id or "", request.node_id or "", request.context.attempt_id or ""
        )
        if not attempt.ended:
            raise _Denial(ReasonCode.ATTEMPT_NOT_ENDED)
        if not attempt.payload_readable:
            raise _Denial(ReasonCode.ATTEMPT_NOT_ENDED, details="attempt payload unreadable")
        if attempt.exit_code != 0:
            raise _Denial(ReasonCode.EXIT_CODE_NONZERO)

    def _guard_task_completion(self, request: TransitionRequest) -> None:
        report = self._require_port("report").get(request.task_id or "")
        if report.final_state != "VERIFIED" or not report.signature_valid:
            raise _Denial(ReasonCode.REPORT_NOT_VERIFIED)
        certificate = self._require_port("certificate").get(request.task_id or "")
        self._check_certificate(report, certificate, request.task_id or "")
        task_facts = self._require_port("task")
        if not task_facts.all_required_nodes_verified(request.task_id or ""):
            raise _Denial(ReasonCode.TASK_COMPLETION_PREREQUISITES)

    def _guard_verified_prerequisites(self, request: TransitionRequest) -> None:
        gate = self._require_port("gate").get(request.task_id or "", request.node_id or "")
        if not gate.passed:
            raise _Denial(ReasonCode.GATE_NOT_PASS)
        report = self._require_port("report").get(request.task_id or "")
        if report.final_state != "VERIFIED" or not report.signature_valid:
            raise _Denial(ReasonCode.REPORT_NOT_VERIFIED)
        certificate = self._require_port("certificate").get(request.task_id or "")
        self._check_certificate(report, certificate, request.task_id or "")

    def _check_certificate(
        self, report: ReportFacts, certificate: CertificateFacts, task_id: str
    ) -> None:
        if certificate.revoked:
            raise _Denial(ReasonCode.CERTIFICATE_INVALID, details="certificate revoked")
        if not certificate.signature_valid:
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                api_error_code="SIGNATURE_INVALID",
                error_code="SIGNATURE_INVALID",
                details="certificate signature invalid",
            )
        if certificate.final_state != "VERIFIED":
            raise _Denial(ReasonCode.CERTIFICATE_INVALID, details="certificate final_state")
        if report.report_id and certificate.report_id and certificate.report_id != report.report_id:
            raise _Denial(ReasonCode.CERTIFICATE_INVALID, details="report_id mismatch")
        if certificate.merkle_root != report.evidence_root:
            raise _Denial(ReasonCode.CERTIFICATE_INVALID, details="merkle_root mismatch")
        if certificate.ruleset_hash != report.ruleset_hash:
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                api_error_code="RULESET_VERSION_MISMATCH",
                error_code="RULESET_VERSION_MISMATCH",
                details="ruleset_hash mismatch",
            )
        evidence = self._require_port("evidence")
        if certificate.tree_size != evidence.count(task_id):
            raise _Denial(ReasonCode.CERTIFICATE_INVALID, details="tree_size mismatch")
        env = evidence.env_fingerprint(task_id)
        if env is None:
            raise _Denial(
                ReasonCode.PORT_UNAVAILABLE,
                details="evidence env_fingerprint is not available",
            )
        if certificate.env_fingerprint != env:
            raise _Denial(
                ReasonCode.CERTIFICATE_INVALID,
                error_code="ENV_FINGERPRINT_MISMATCH",
                details="env_fingerprint mismatch",
            )
        if not evidence.verify_chain(task_id):
            raise _Denial(
                ReasonCode.EVIDENCE_CHAIN_BROKEN,
                error_code="EVIDENCE_CHAIN_BROKEN",
                details="evidence chain verification failed",
            )

    def _guard_stale_cause(self, request: TransitionRequest) -> None:
        context = request.context
        if context.cause_type not in {
            "INPUT_CHANGE",
            "PREDECESSOR_CHANGE",
            "GRAPH_VERSION_CHANGE",
            "RULESET_CHANGE",
        }:
            raise _Denial(ReasonCode.CAUSE_INVALID, details="cause_type is invalid")
        if not context.evidence_ids:
            raise _Denial(ReasonCode.NO_STALE_EVIDENCE, details="evidence_ids is empty")
        evidence_facts = self._require_port("evidence")
        for evidence_id in context.evidence_ids:
            row: EvidenceFacts | None = evidence_facts.get(evidence_id)
            if row is None:
                raise _Denial(
                    ReasonCode.NO_STALE_EVIDENCE,
                    details=f"evidence not found: {evidence_id}",
                )
            if row.task_id != request.task_id or row.node_id != request.node_id:
                raise _Denial(
                    ReasonCode.NO_STALE_EVIDENCE,
                    details=f"evidence does not belong to node: {evidence_id}",
                )
            if evidence_facts.is_invalidated(evidence_id):
                raise _Denial(
                    ReasonCode.NO_STALE_EVIDENCE,
                    details=f"evidence already invalidated: {evidence_id}",
                )

    def _guard_plan_three(self, request: TransitionRequest) -> None:
        context = request.context
        plan_id = context.plan_id or ""
        plan_hash = context.plan_hash or ""
        if len(plan_hash) != 64 or any(ch not in _PLAN_HASH_RE for ch in plan_hash):
            raise _Denial(
                ReasonCode.PLAN_HASH_MISMATCH,
                error_code="PLAN_HASH_MISMATCH",
                details="plan_hash is not 64 lowercase hex characters",
            )
        if not plan_id or "/" in plan_id or "\\" in plan_id:
            raise _Denial(
                ReasonCode.UNSAFE_PLAN_PATH,
                error_code="PLAN_HASH_MISMATCH",
                details="plan_id is empty or contains a path separator",
            )
        plans = self._require_port("plans")
        try:
            path = plans.resolve(plan_hash)
        except UnsafePlanPath as exc:
            raise _Denial(
                ReasonCode.UNSAFE_PLAN_PATH,
                error_code="PLAN_HASH_MISMATCH",
                details=str(exc),
            ) from exc
        except PlanFileMissing as exc:
            raise _Denial(
                ReasonCode.PLAN_FILE_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details=str(exc),
            ) from exc
        try:
            data = plans.read_bytes(path)
        except OSError as exc:
            raise _Denial(
                ReasonCode.PLAN_FILE_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details="plan file is unreadable",
            ) from exc
        if hashlib.sha256(data).hexdigest() != plan_hash:
            raise _Denial(
                ReasonCode.PLAN_HASH_MISMATCH,
                error_code="PLAN_HASH_MISMATCH",
                details="sha256(file bytes) != plan_hash",
            )
        connection = self._connect()
        try:
            freeze = self._audit.latest_freeze(
                connection,
                task_id=request.task_id or "",
                node_id=request.node_id or "",
                plan_hash=plan_hash,
            )
        finally:
            connection.close()
        if freeze is None:
            raise _Denial(
                ReasonCode.PLAN_FREEZE_RECORD_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details="missing RECOVERY_PLAN_FROZEN(OK) audit row",
            )
        if freeze.plan_id != plan_id:
            raise _Denial(
                ReasonCode.PLAN_ID_MISMATCH,
                error_code="PLAN_HASH_MISMATCH",
                details="freeze record plan_id mismatch",
            )
        try:
            frozen_at = parse_utc(freeze.created_at)
        except ValueError as exc:
            raise _Denial(
                ReasonCode.PLAN_FREEZE_RECORD_MISSING,
                error_code="PLAN_HASH_MISMATCH",
                details="freeze record timestamp is invalid",
            ) from exc
        received_at = context.received_at or self._now()
        if received_at.tzinfo is None:
            raise _Denial(
                ReasonCode.MISSING_PARAMETER,
                field_path="received_at",
                details="received_at must be timezone-aware",
            )
        if not frozen_at < received_at:
            raise _Denial(
                ReasonCode.PLAN_FROZEN_AFTER_RERUN,
                error_code="PLAN_HASH_MISMATCH",
                details="freeze event is not strictly before the rerun",
            )

    # ------------------------------------------------------------- success write
    def _apply_success(
        self, request: TransitionRequest, obj: TaskRow | NodeRow, edge: Transition
    ) -> TransitionResult:
        connection = self._connect()
        try:
            try:
                with transaction(connection):
                    current = self._load_object(
                        connection,
                        edge.obj_type,
                        request.task_id or "",
                        request.node_id,
                    )
                    if current is None or current.state != request.previous_state:
                        raise _Denial(
                            ReasonCode.STALE_PREVIOUS_STATE,
                            previous_state=current.state if current is not None else None,
                            next_state=request.next_state,
                        )
                    updated_at = format_utc(self._now())
                    if (
                        edge.obj_type is ObjectType.NODE
                        and edge.from_state == NodeState.VERIFIED.value
                        and edge.to_state == NodeState.INVALIDATED.value
                    ):
                        for evidence_id in request.context.evidence_ids:
                            self._evidence.append_invalidation(
                                connection,
                                invalidation_id=uuid.uuid4().hex,
                                task_id=request.task_id or "",
                                node_id=request.node_id or "",
                                evidence_id=evidence_id,
                                reason_code=request.reason_code or AUDIT_SENTINEL,
                                cause_type=request.context.cause_type or "",
                                cause_ref=request.context.cause_ref,
                                plan_id=None,
                                plan_hash=None,
                                created_at=updated_at,
                                capability=STATE_MACHINE_WRITE,
                            )
                    audit_id = uuid.uuid4().hex
                    self._audit.append(
                        connection,
                        audit_id=audit_id,
                        task_id=request.task_id,
                        node_id=request.node_id,
                        actor=request.actor.audit_value if request.actor else "unknown:<missing>",
                        action="STATE_TRANSITION",
                        previous_state=current.state,
                        next_state=request.next_state,
                        reason_code=request.reason_code,
                        rule_version=request.rule_version,
                        correlation_id=request.correlation_id,
                        plan_id=request.context.plan_id,
                        plan_hash=request.context.plan_hash,
                        result="OK",
                        error_code=None,
                        created_at=updated_at,
                        capability=STATE_MACHINE_WRITE,
                    )
                    if edge.obj_type is ObjectType.TASK:
                        graph_version = (
                            request.context.graph_version
                            if edge.to_state == TaskState.READY.value
                            else getattr(obj, "graph_version", None)
                        )
                        rows = self._tasks._apply_transition(
                            connection,
                            task_id=request.task_id or "",
                            expected_from=current.state,
                            next_state=request.next_state or "",
                            graph_version=graph_version,
                            updated_at=updated_at,
                            capability=STATE_MACHINE_WRITE,
                        )
                        attempt_seq = None
                        plan_id = None
                        plan_hash = None
                    else:
                        attempt_seq = (
                            current.attempt_seq + 1
                            if edge.from_state == NodeState.READY.value
                            and edge.to_state == NodeState.RUNNING.value
                            else current.attempt_seq
                        )
                        plan_id = (
                            request.context.plan_id
                            if edge.from_state == NodeState.INVALIDATED.value
                            and edge.to_state == NodeState.READY.value
                            else current.plan_id
                        )
                        plan_hash = (
                            request.context.plan_hash
                            if edge.from_state == NodeState.INVALIDATED.value
                            and edge.to_state == NodeState.READY.value
                            else current.plan_hash
                        )
                        rows = self._nodes._apply_transition(
                            connection,
                            task_id=request.task_id or "",
                            node_id=request.node_id or "",
                            expected_from=current.state,
                            next_state=request.next_state or "",
                            attempt_seq=attempt_seq,
                            plan_id=plan_id,
                            plan_hash=plan_hash,
                            updated_at=updated_at,
                            capability=STATE_MACHINE_WRITE,
                        )
                    if rows != 1:
                        raise _Denial(
                            ReasonCode.STALE_PREVIOUS_STATE,
                            previous_state=current.state if current is not None else None,
                            next_state=request.next_state,
                        )
                    return TransitionResult(
                        ok=True,
                        obj_type=edge.obj_type.value,
                        obj_id=(
                            request.node_id
                            if edge.obj_type is ObjectType.NODE
                            else request.task_id or ""
                        ),
                        previous_state=current.state,
                        next_state=request.next_state or "",
                        audit_id=audit_id,
                        applied_at=updated_at,
                        correlation_id=request.correlation_id or AUDIT_SENTINEL,
                        attempt_seq=attempt_seq,
                        plan_id=plan_id,
                        plan_hash=plan_hash,
                    )
            except _Denial:
                raise
            except sqlite3.IntegrityError as exc:
                raise _Denial(
                    ReasonCode.STATE_WRITE_FAILED,
                    details=str(exc).splitlines()[0] if str(exc) else "state write failed",
                    previous_state=getattr(obj, "state", None),
                    next_state=request.next_state,
                ) from exc
        finally:
            connection.close()

    # ------------------------------------------------------------- denial audit
    def _deny(self, request: TransitionRequest, denial: _Denial) -> str:
        connection = self._connect()
        try:
            with transaction(connection):
                actual_state: str | None = None
                if request.task_id:
                    try:
                        actual = self._load_object(
                            connection,
                            self._parse_obj_type(request.obj_type),
                            request.task_id,
                            request.node_id,
                        )
                        actual_state = actual.state if actual is not None else None
                    except Exception:
                        actual_state = None
                audit_id = uuid.uuid4().hex
                payload = {
                    "audit_write_failed": True,
                    "error_code": "AUDIT_WRITE_FAILED",
                    "original_error_code": denial.error_code,
                    "task_id": request.task_id,
                    "node_id": request.node_id,
                    "previous_state": actual_state or request.previous_state,
                    "next_state": request.next_state,
                    "reason": denial.reason.value,
                    "correlation_id": request.correlation_id,
                    "actor": request.actor.audit_value if isinstance(request.actor, Actor) else None,
                    "field_path": denial.field_path,
                }
                try:
                    self._audit.append(
                        connection,
                        audit_id=audit_id,
                        task_id=request.task_id,
                        node_id=request.node_id,
                        actor=(
                            request.actor.audit_value
                            if isinstance(request.actor, Actor)
                            else "unknown:<missing>"
                        ),
                        action="STATE_TRANSITION",
                        previous_state=actual_state or request.previous_state,
                        next_state=request.next_state,
                        reason_code=request.reason_code or AUDIT_SENTINEL,
                        rule_version=request.rule_version or AUDIT_SENTINEL,
                        correlation_id=request.correlation_id or AUDIT_SENTINEL,
                        plan_id=request.context.plan_id,
                        plan_hash=request.context.plan_hash,
                        result="DENIED",
                        error_code=denial.error_code,
                        created_at=format_utc(self._now()),
                        capability=STATE_MACHINE_WRITE,
                    )
                except Exception as exc:
                    raise _AuditInsertFailed(payload, exc) from exc
                return audit_id
        except _AuditInsertFailed as failure:
            self._degrade_audit(failure.payload)
            raise AuditWriteFailed(
                original_error_code=denial.error_code,
                correlation_id=request.correlation_id,
                payload=failure.payload,
            ) from failure.original
        finally:
            connection.close()

    @staticmethod
    def _degrade_audit(payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        print(line, file=sys.stderr, flush=True)


def assert_single_write_entrypoint() -> list[str]:
    """Return contract violations for the public write-entry rule."""

    problems: list[str] = []
    expected = {"create_initial", "transition"}
    public = {
        name
        for name, member in inspect.getmembers(StateMachine, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    for name in sorted(public - expected):
        problems.append(f"unexpected public StateMachine method: {name}")
    for repository in (
        TaskRepository,
        NodeRepository,
        AuditRepository,
        EvidenceRepository,
        IdempotencyRepository,
    ):
        for name in ("update", "update_state", "set_state", "save", "delete"):
            if hasattr(repository, name):
                problems.append(f"{repository.__name__}.{name} must not exist")
    return problems