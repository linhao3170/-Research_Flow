"""Shared helpers for the WP-03 tests.

These helpers use real SQLite files.  The fake ports only provide external
facts (Gate/Report/Certificate/attempt/graph) that later work packages will
own; they never stand in for SQLite, transactions or audit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from researchflow.contracts.models import NodeSpec, TaskSpec
from researchflow.orchestration.ports import (
    AttemptEnd,
    CertificateFacts,
    EvidenceFacts,
    FilePlanStore,
    GateFacts,
    Ports,
    ReportFacts,
)
from researchflow.orchestration.state_machine import (
    Actor,
    StateMachine,
    TransitionContext,
    TransitionRequest,
)
from researchflow.orchestration.transitions import ActorRole
from researchflow.persistence.db import connect
from researchflow.persistence.migrations import MigrationRunner
from researchflow.persistence.repositories import (
    COLLECTOR_APPEND,
    WP_R_FREEZE,
    AuditRepository,
    EvidenceRepository,
)

ROOT = Path(__file__).resolve().parents[1]
TASK_PAYLOAD: dict[str, Any] = json.loads(
    (ROOT / "contracts" / "examples" / "taskspec.positive.json").read_text(encoding="utf-8")
)
NODE_PAYLOAD: dict[str, Any] = json.loads(
    (ROOT / "contracts" / "examples" / "nodespec.positive.json").read_text(encoding="utf-8")
)
TASK_ID = str(TASK_PAYLOAD["task_id"])
NODE_ID = str(NODE_PAYLOAD["node_id"])
EVIDENCE_ID = "ev_00000000-0000-0000-0000-000000000001"


def make_db(path: Path) -> Path:
    connection = connect(path)
    try:
        MigrationRunner().upgrade(connection)
    finally:
        connection.close()
    return path


@dataclass
class FixedClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


class FakeTaskFacts:
    def __init__(
        self,
        *,
        has_ready: bool = True,
        finished: bool = True,
        all_verified: bool = True,
    ) -> None:
        self.has_ready = has_ready
        self.finished = finished
        self.all_verified = all_verified

    def has_ready_node(self, task_id: str) -> bool:
        return self.has_ready

    def execution_finished(self, task_id: str) -> bool:
        return self.finished

    def all_required_nodes_verified(self, task_id: str) -> bool:
        return self.all_verified


class FakeNodeFacts:
    def __init__(
        self,
        *,
        dependencies: bool = True,
        resources: bool = True,
        ended: bool = True,
        exit_code: int | None = 0,
        readable: bool = True,
    ) -> None:
        self.dependencies = dependencies
        self.resources = resources
        self.ended = ended
        self.exit_code = exit_code
        self.readable = readable

    def dependencies_satisfied(self, task_id: str, node_id: str) -> bool:
        return self.dependencies

    def resources_available(self, task_id: str, node_id: str) -> bool:
        return self.resources

    def attempt_end(self, task_id: str, node_id: str, attempt_id: str) -> AttemptEnd:
        return AttemptEnd(self.ended, self.exit_code, self.readable)

    def recovery_budget_available(self, *args: Any) -> bool:
        return True

    def diagnosis_valid(self, *args: Any) -> bool:
        return True

    def recovery_rechecked(self, *args: Any) -> bool:
        return True


class FakeGraphFacts:
    def __init__(self, *, valid: bool = True, gap: bool = False) -> None:
        self.valid = valid
        self.gap = gap

    def dag_valid(self, task_id: str, graph_version: int) -> bool:
        return self.valid

    def blocking_gap(self, task_id: str, failure_ref: str) -> bool:
        return self.gap


class FakeGateFacts:
    def __init__(self, *, passed: bool = True) -> None:
        self.passed = passed

    def get(self, task_id: str, node_id: str) -> GateFacts:
        return GateFacts(self.passed)


class FakeReportFacts:
    def __init__(
        self,
        *,
        final_state: str = "VERIFIED",
        report_id: str = "report_00000000-0000-0000-0000-000000000001",
        ruleset_hash: str = "b" * 64,
        evidence_root: str = "c" * 64,
        signature_valid: bool = True,
    ) -> None:
        self.final_state = final_state
        self.report_id = report_id
        self.ruleset_hash = ruleset_hash
        self.evidence_root = evidence_root
        self.signature_valid = signature_valid

    def get(self, task_id: str) -> ReportFacts:
        return ReportFacts(
            self.final_state,
            report_id=self.report_id,
            ruleset_hash=self.ruleset_hash,
            evidence_root=self.evidence_root,
            signature_valid=self.signature_valid,
        )


class FakeCertificateFacts:
    def __init__(
        self,
        *,
        report_id: str = "report_00000000-0000-0000-0000-000000000001",
        merkle_root: str = "c" * 64,
        tree_size: int = 1,
        ruleset_hash: str = "b" * 64,
        env_fingerprint: str = "a" * 64,
        signature_valid: bool = True,
        revoked: bool = False,
    ) -> None:
        self.report_id = report_id
        self.merkle_root = merkle_root
        self.tree_size = tree_size
        self.ruleset_hash = ruleset_hash
        self.env_fingerprint = env_fingerprint
        self.signature_valid = signature_valid
        self.revoked = revoked

    def get(self, task_id: str) -> CertificateFacts:
        return CertificateFacts(
            report_id=self.report_id,
            final_state="VERIFIED",
            merkle_root=self.merkle_root,
            tree_size=self.tree_size,
            ruleset_hash=self.ruleset_hash,
            env_fingerprint=self.env_fingerprint,
            signature_valid=self.signature_valid,
            revoked=self.revoked,
        )


class FakeEvidenceFacts:
    def __init__(
        self,
        evidence: EvidenceFacts,
        *,
        invalidated: bool = False,
        env: str | None = "a" * 64,
        chain_ok: bool = True,
    ) -> None:
        self.evidence = evidence
        self.invalidated = invalidated
        self.env = env
        self.chain_ok = chain_ok

    def get(self, evidence_id: str) -> EvidenceFacts | None:
        return self.evidence if evidence_id == self.evidence.evidence_id else None

    def count(self, task_id: str) -> int:
        return 1 if self.evidence.task_id == task_id else 0

    def is_invalidated(self, evidence_id: str) -> bool:
        return self.invalidated

    def verify_chain(self, task_id: str) -> bool:
        return self.chain_ok

    def env_fingerprint(self, task_id: str) -> str | None:
        return self.env


def default_evidence() -> EvidenceFacts:
    return EvidenceFacts(EVIDENCE_ID, TASK_ID, NODE_ID, "E2", "artifact_observed", "collector", 1)


def build_state_machine(
    db_path: Path,
    *,
    plan_root: Path | None = None,
    evidence: FakeEvidenceFacts | None = None,
    clock: FixedClock | None = None,
    task_facts: FakeTaskFacts | None = None,
    node_facts: FakeNodeFacts | None = None,
    graph_facts: FakeGraphFacts | None = None,
    gate_facts: FakeGateFacts | None = None,
    report_facts: FakeReportFacts | None = None,
    certificate_facts: FakeCertificateFacts | None = None,
) -> StateMachine:
    evidence = evidence or FakeEvidenceFacts(default_evidence())
    ports = Ports(
        task=task_facts or FakeTaskFacts(),
        node=node_facts or FakeNodeFacts(),
        graph=graph_facts or FakeGraphFacts(),
        gate=gate_facts or FakeGateFacts(),
        report=report_facts or FakeReportFacts(),
        certificate=certificate_facts or FakeCertificateFacts(),
        evidence=evidence,
        plans=FilePlanStore(plan_root) if plan_root is not None else None,
        clock=clock or FixedClock(datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)),
    )
    return StateMachine(db_path, ports=ports)


def create_task_and_node(sm: StateMachine) -> tuple[str, str]:
    task_spec = TaskSpec.model_validate(TASK_PAYLOAD)
    node_spec = NodeSpec.model_validate(NODE_PAYLOAD)
    sm.create_initial(
        obj_type="task",
        task_id=TASK_ID,
        actor=Actor(ActorRole.API, "create"),
        correlation_id="req-task",
        task_spec=task_spec,
    )
    sm.create_initial(
        obj_type="node",
        task_id=TASK_ID,
        node_id=NODE_ID,
        actor=Actor(ActorRole.ORCHESTRATOR, "test"),
        correlation_id="req-node",
        node_spec=node_spec,
    )
    return TASK_ID, NODE_ID


def seed_evidence(db_path: Path, evidence_id: str = EVIDENCE_ID) -> None:
    connection = connect(db_path)
    try:
        EvidenceRepository().append(
            connection,
            evidence_id=evidence_id,
            task_id=TASK_ID,
            node_id=NODE_ID,
            attempt_id="attempt_01",
            event_seq=1,
            level="E2",
            kind="artifact_observed",
            producer="collector",
            timestamp="2026-11-12T00:00:00.000000Z",
            payload_hash="d" * 64,
            artifact_refs=None,
            prev_hash="0" * 64,
            chain_hash="d" * 64,
            capability=COLLECTOR_APPEND,
        )
    finally:
        connection.close()


def seed_freeze(
    db_path: Path,
    *,
    plan_id: str,
    plan_hash: str,
    created_at: str = "2026-11-12T00:00:00.000000Z",
    task_id: str = TASK_ID,
    node_id: str = NODE_ID,
) -> str:
    audit_id = "freeze-" + plan_hash[:12]
    connection = connect(db_path)
    try:
        AuditRepository().append(
            connection,
            audit_id=audit_id,
            task_id=task_id,
            node_id=node_id,
            actor="wp_r:test",
            action="RECOVERY_PLAN_FROZEN",
            previous_state=None,
            next_state=None,
            reason_code="RECOVERY_PLAN_FROZEN",
            rule_version="1.0",
            correlation_id="freeze-c",
            plan_id=plan_id,
            plan_hash=plan_hash,
            result="OK",
            error_code=None,
            created_at=created_at,
            capability=WP_R_FREEZE,
        )
    finally:
        connection.close()
    return audit_id


def write_plan(plan_root: Path, content: bytes = b'{"plan":"fixed"}') -> tuple[str, str]:
    plan_root.mkdir(parents=True, exist_ok=True)
    plan_hash = hashlib.sha256(content).hexdigest()
    (plan_root / f"{plan_hash}.json").write_bytes(content)
    return "plan-1", plan_hash


def node_transition(
    sm: StateMachine,
    *,
    previous_state: str,
    next_state: str,
    role: ActorRole,
    reason_code: str,
    context: TransitionContext | None = None,
    task_id: str = TASK_ID,
    node_id: str = NODE_ID,
):
    return sm.transition(
        TransitionRequest(
            obj_type="node",
            task_id=task_id,
            node_id=node_id,
            previous_state=previous_state,
            next_state=next_state,
            actor=Actor(role, "test"),
            reason_code=reason_code,
            rule_version="1.0",
            correlation_id=f"req-{next_state}",
            context=context or TransitionContext(),
        )
    )


def walk_node_to_verified(sm: StateMachine) -> None:
    node_transition(
        sm,
        previous_state="PLANNED",
        next_state="READY",
        role=ActorRole.SCHEDULER,
        reason_code="NODE_READY",
    )
    node_transition(
        sm,
        previous_state="READY",
        next_state="RUNNING",
        role=ActorRole.SCHEDULER,
        reason_code="NODE_RUNNING",
    )
    node_transition(
        sm,
        previous_state="RUNNING",
        next_state="VERIFYING",
        role=ActorRole.ORCHESTRATOR,
        reason_code="NODE_VERIFYING",
        context=TransitionContext(attempt_id="attempt_01"),
    )
    node_transition(
        sm,
        previous_state="VERIFYING",
        next_state="VERIFIED",
        role=ActorRole.ORCHESTRATOR,
        reason_code="NODE_VERIFIED",
    )


def count_audit(db_path: Path, result: str | None = None) -> int:
    connection = connect(db_path)
    try:
        return AuditRepository().count(connection, result)
    finally:
        connection.close()