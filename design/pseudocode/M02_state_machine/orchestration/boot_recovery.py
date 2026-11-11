"""M02 · orchestration/boot_recovery.py — 重启恢复顺序与 RUNNING 处置（P2 伪代码）。

阶段：P2｜状态：恢复阶段、阻断条件、RUNNING 分支、报告结构；**不执行恢复、不启动调度**。
规范来源：`docs/state/runtime_states.md` §6（重启先校验 DB/证据链/未完成 attempt）、
`docs/design/05_CONTRACTS_AND_STATES.md` §9.3、`docs/ADR/ADR-004`、
`docs/design/06_DATA_AND_API.md` §1.3/§2。

铁律：
  - **不得把 RUNNING 默认改成 COMPLETED**。重启后没有“进程还活着”的假设；
    单机 T0 重启即意味着旧进程已消失。
  - 只有 DB 完整性、schema 版本、证据链都通过，才处理未完成 attempt；
    只有 attempt 处理完且没有残留 RUNNING，才允许调度。
  - 发现 RUNNING 但**无活动 attempt** 时，明确走
    `RUNNING → FAILED`，reason `BOOT_NO_ACTIVE_ATTEMPT`；不是 COMPLETED、不是 VERIFYING。
  - `RUNNING → VERIFYING` 只允许在“有 launch + 有 exit + exit_code=0 + 证据链完整”时，
    且只表示“进入验证”，最终判定仍归 Gate/Verifier。
  - Task 状态在启动阶段不自动推进到 COMPLETED；本模块没有 Task→COMPLETED 分支。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

from ..persistence.migrations import MigrationError, MigrationRunner, assert_schema_current
from ..persistence.repositories import (
    AttemptView,
    NodeRow,
    PayloadReader,
    Repositories,
)
from .state_machine import (
    Actor,
    AuditWriteFailed,
    StateMachine,
    StateTransitionDenied,
    TransitionContext,
    format_utc,
)
from .transitions import ActorRole, ObjectType, ReasonCode

__all__ = [
    "BOOT_ALLOWED_NODE_TARGETS",
    "BOOT_DECISION_REASONS",
    "BOOT_FORBIDDEN_TARGETS",
    "BOOT_ORDER",
    "BootAction",
    "BootBlocker",
    "BootDecision",
    "BootLockPort",
    "BootPhase",
    "BootRecovery",
    "BootReport",
    "FileBootLock",
    "assert_boot_contract",
]

# 顺序不可交换：先锁 → DB → schema → 证据链 → attempt → 调度门。
BOOT_ORDER: Final[tuple[str, ...]] = (
    "LOCK",
    "DB_INTEGRITY",
    "SCHEMA_VERSION",
    "EVIDENCE_CHAIN",
    "UNFINISHED_ATTEMPTS",
    "SCHEDULER_GATE",
)

# 启动阶段只允许把 RUNNING 送到这两个目标；COMPLETED/VERIFIED 一律禁止。
BOOT_ALLOWED_NODE_TARGETS: Final[tuple[str, ...]] = ("VERIFYING", "FAILED")
BOOT_FORBIDDEN_TARGETS: Final[tuple[str, ...]] = ("COMPLETED", "VERIFIED")

BOOT_DECISION_REASONS: Final[dict[str, str]] = {
    "NO_ACTIVE_ATTEMPT": ReasonCode.BOOT_NO_ACTIVE_ATTEMPT.value,
    "UNFINISHED_ATTEMPT": ReasonCode.BOOT_UNFINISHED_ATTEMPT.value,
    "COMPLETED_ATTEMPT": ReasonCode.BOOT_ATTEMPT_COMPLETED.value,
    "FAILED_ATTEMPT": ReasonCode.BOOT_ATTEMPT_FAILED.value,
}


class BootPhase(StrEnum):
    LOCK = "LOCK"
    DB_INTEGRITY = "DB_INTEGRITY"
    SCHEMA_VERSION = "SCHEMA_VERSION"
    EVIDENCE_CHAIN = "EVIDENCE_CHAIN"
    UNFINISHED_ATTEMPTS = "UNFINISHED_ATTEMPTS"
    SCHEDULER_GATE = "SCHEDULER_GATE"
    DONE = "DONE"


class BootBlocker(StrEnum):
    BOOT_LOCK_HELD = "BOOT_LOCK_HELD"
    DB_INTEGRITY_FAILED = "DB_INTEGRITY_FAILED"
    FOREIGN_KEY_VIOLATION = "FOREIGN_KEY_VIOLATION"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    PENDING_MIGRATION = "PENDING_MIGRATION"
    EVIDENCE_CHAIN_BROKEN = "EVIDENCE_CHAIN_BROKEN"
    UNRESOLVED_RUNNING_NODE = "UNRESOLVED_RUNNING_NODE"
    UNKNOWN_STATE = "UNKNOWN_STATE"
    REPORT_WRITE_FAILED = "REPORT_WRITE_FAILED"


class BootDecision(StrEnum):
    NO_ACTIVE_ATTEMPT = "NO_ACTIVE_ATTEMPT"
    UNFINISHED_ATTEMPT = "UNFINISHED_ATTEMPT"
    COMPLETED_ATTEMPT = "COMPLETED_ATTEMPT"
    FAILED_ATTEMPT = "FAILED_ATTEMPT"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"


@dataclass(frozen=True, slots=True)
class BootAction:
    task_id: str
    node_id: str
    decision: BootDecision
    from_state: str
    to_state: str
    reason_code: str
    audit_id: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BootReport:
    run_id: str
    started_at: str
    finished_at: str
    phase_reached: BootPhase
    schedule_allowed: bool
    blockers: tuple[BootBlocker, ...]
    tasks_scanned: int
    running_nodes_scanned: int
    resolved: int
    already_terminal: int
    actions: tuple[BootAction, ...]
    report_path: str | None
    note: str = ""


class BootLockPort(Protocol):
    """单实例锁；拿不到锁时不得开始恢复/调度。"""

    def acquire(self) -> bool:
        ...

    def release(self) -> None:
        ...


class FileBootLock:
    """T0 单机文件锁（伪代码；实现用独占创建/删除）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._held = False

    def acquire(self) -> bool:
        try:
            fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        self._held = True
        return True

    def release(self) -> None:
        if self._held:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
            self._held = False


class BootRecovery:
    """启动恢复器；只通过 StateMachine 改状态，不直接写 tasks/nodes。"""

    def __init__(
        self,
        *,
        repos: Repositories,
        state_machine: StateMachine,
        migrations: MigrationRunner,
        lock: BootLockPort,
        clock: object | None = None,
        payload_reader: PayloadReader | None = None,
        report_path: Path | None = None,
        rule_version: str = "1.0",
    ) -> None:
        self._repos = repos
        self._sm = state_machine
        self._migrations = migrations
        self._lock = lock
        self._clock = clock
        self._payload_reader = payload_reader
        self._report_path = report_path
        self._rule_version = rule_version

    # -- 主流程 -----------------------------------------------------------
    def run(self) -> BootReport:
        run_id = str(uuid.uuid4())
        started = self._now()
        blockers: set[BootBlocker] = set()
        actions: list[BootAction] = []
        tasks_scanned = 0
        running_scanned = 0

        if not self._lock.acquire():
            return self._report(
                run_id=run_id, started=started, phase=BootPhase.LOCK,
                schedule_allowed=False, blockers={BootBlocker.BOOT_LOCK_HELD},
                tasks_scanned=0, running_scanned=0, actions=(),
                note="另一个实例持有启动锁；不得并发恢复/调度",
            )
        try:
            # 1) DB 完整性（integrity_check + foreign_key_check）
            db_ok = self._check_db_integrity(blockers)
            if not db_ok:
                return self._report(
                    run_id=run_id, started=started, phase=BootPhase.DB_INTEGRITY,
                    schedule_allowed=False, blockers=blockers,
                    tasks_scanned=0, running_scanned=0, actions=(),
                    note="DB 完整性失败：只报告，不改任何状态",
                )

            # 2) schema 版本（必须正好是当前版本、无 pending）
            schema_ok = self._check_schema(blockers)
            if not schema_ok:
                return self._report(
                    run_id=run_id, started=started, phase=BootPhase.SCHEMA_VERSION,
                    schedule_allowed=False, blockers=blockers,
                    tasks_scanned=0, running_scanned=0, actions=(),
                    note="schema 不一致：拒绝恢复，不得先调度再迁移",
                )

            # 3) 证据链（逐任务；broken 时不处理 attempt、不改状态）
            tasks = self._repos.tasks.list_all()
            tasks_scanned = len(tasks)
            chain_ok = self._check_evidence_chains(tasks, blockers)
            if not chain_ok:
                return self._report(
                    run_id=run_id, started=started, phase=BootPhase.EVIDENCE_CHAIN,
                    schedule_allowed=False, blockers=blockers,
                    tasks_scanned=tasks_scanned, running_scanned=0, actions=(),
                    note="证据链断裂：不得修复/重写，不得据此恢复调度",
                )

            # 4) 未完成 attempt / RUNNING 节点
            running = self._repos.nodes.list_running()
            running_scanned = len(running)
            actions.extend(self._resolve_running_nodes(running, run_id, blockers))

            # 5) 调度门：仍有 RUNNING 或任何阻断 → 不允许调度
            residual = self._repos.nodes.list_running()
            if residual:
                blockers.add(BootBlocker.UNRESOLVED_RUNNING_NODE)
            schedule_allowed = not blockers and not residual
            return self._report(
                run_id=run_id, started=started, phase=BootPhase.SCHEDULER_GATE,
                schedule_allowed=schedule_allowed, blockers=blockers,
                tasks_scanned=tasks_scanned, running_scanned=running_scanned,
                actions=actions,
                note=(
                    "恢复完成；Task 状态不在启动阶段自动推进到 COMPLETED"
                    if schedule_allowed
                    else "存在阻断或残留 RUNNING；禁止调度"
                ),
            )
        finally:
            self._lock.release()

    # -- 阶段实现 ---------------------------------------------------------
    def _check_db_integrity(self, blockers: set[BootBlocker]) -> bool:
        conn = self._repos.uow.connection
        try:
            integrity = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
            if integrity != ["ok"]:
                blockers.add(BootBlocker.DB_INTEGRITY_FAILED)
                return False
            foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
            if foreign:
                blockers.add(BootBlocker.FOREIGN_KEY_VIOLATION)
                return False
            return True
        except Exception:  # noqa: BLE001 - 打不开/读不了都按失败
            blockers.add(BootBlocker.DB_INTEGRITY_FAILED)
            return False

    def _check_schema(self, blockers: set[BootBlocker]) -> bool:
        conn = self._repos.uow.connection
        try:
            assert_schema_current(conn, runner=self._migrations)
            return True
        except MigrationError:
            blockers.add(BootBlocker.SCHEMA_VERSION_MISMATCH)
            return False

    def _check_evidence_chains(self, tasks: tuple, blockers: set[BootBlocker]) -> bool:
        ok = True
        for task in tasks:
            try:
                report = self._repos.evidence.verify_chain(task.task_id)
            except Exception:  # noqa: BLE001 - 读不了链也按断裂处理
                ok = False
                blockers.add(BootBlocker.EVIDENCE_CHAIN_BROKEN)
                continue
            if not report.ok:
                ok = False
                blockers.add(BootBlocker.EVIDENCE_CHAIN_BROKEN)
        return ok

    def _resolve_running_nodes(
        self, running: tuple[NodeRow, ...], run_id: str, blockers: set[BootBlocker]
    ) -> list[BootAction]:
        actions: list[BootAction] = []
        for node in running:
            decision, target, reason = self._classify_running(node)
            ctx = TransitionContext(
                previous_state="RUNNING",
                rule_version=self._rule_version,
                correlation_id=f"boot:{run_id}:{node.task_id}:{node.node_id}",
                task_id=node.task_id,
                attempt_id=(
                    f"attempt_{node.attempt_seq:02d}" if node.attempt_seq > 0 else None
                ),
                failure_ref=(
                    f"boot:{decision.value}"
                    if target == "FAILED"
                    else None
                ),
            )
            try:
                result = self._sm.transition(
                    ObjectType.NODE,
                    node.node_id,
                    target,
                    Actor(ActorRole.BOOT_RECOVERY, "boot"),
                    reason,
                    ctx,
                )
                actions.append(
                    BootAction(
                        task_id=node.task_id,
                        node_id=node.node_id,
                        decision=decision,
                        from_state="RUNNING",
                        to_state=target,
                        reason_code=reason.value,
                        audit_id=result.audit_id,
                    )
                )
            except StateTransitionDenied as exc:
                blockers.add(BootBlocker.UNRESOLVED_RUNNING_NODE)
                actions.append(
                    BootAction(
                        task_id=node.task_id,
                        node_id=node.node_id,
                        decision=decision,
                        from_state="RUNNING",
                        to_state=target,
                        reason_code=reason.value,
                        audit_id=exc.audit_id,
                        error_code=exc.error_code,
                    )
                )
            except AuditWriteFailed as exc:
                # 状态已回滚但 DENIED 也失败：启动必须停在“不允许调度”，
                # 并把缺口留给 stderr/测试报告，不得静默继续。
                blockers.add(BootBlocker.UNRESOLVED_RUNNING_NODE)
                actions.append(
                    BootAction(
                        task_id=node.task_id,
                        node_id=node.node_id,
                        decision=decision,
                        from_state="RUNNING",
                        to_state=target,
                        reason_code=reason.value,
                        audit_id=None,
                        error_code=exc.error_code,
                    )
                )
        return actions

    def _classify_running(self, node: NodeRow) -> tuple[BootDecision, str, ReasonCode]:
        """RUNNING 的四个明确分支；**没有 COMPLETED 分支**。

        - attempt_seq=0 或无 launch 事件 → NO_ACTIVE_ATTEMPT → FAILED；
        - 有 launch、无 exit → UNFINISHED_ATTEMPT → FAILED；
        - launch+exit 且 exit_code=0 且 payload 可读 → COMPLETED_ATTEMPT → VERIFYING；
        - 其余（exit 非 0 / payload 不可读 / 读取异常） → FAILED_ATTEMPT → FAILED。
        """
        if node.attempt_seq <= 0:
            return BootDecision.NO_ACTIVE_ATTEMPT, "FAILED", ReasonCode.BOOT_NO_ACTIVE_ATTEMPT
        try:
            view: AttemptView = self._repos.nodes.project_attempt(
                task_id=node.task_id,
                node_id=node.node_id,
                attempt_seq=node.attempt_seq,
                payload_reader=self._payload_reader,
            )
        except Exception:  # noqa: BLE001 - 读取失败按失败处理
            return BootDecision.FAILED_ATTEMPT, "FAILED", ReasonCode.BOOT_ATTEMPT_FAILED
        if not view.launch_seen:
            return BootDecision.NO_ACTIVE_ATTEMPT, "FAILED", ReasonCode.BOOT_NO_ACTIVE_ATTEMPT
        if not view.exit_seen:
            return BootDecision.UNFINISHED_ATTEMPT, "FAILED", ReasonCode.BOOT_UNFINISHED_ATTEMPT
        if view.exit_payload_readable and view.exit_code == 0:
            return BootDecision.COMPLETED_ATTEMPT, "VERIFYING", ReasonCode.BOOT_ATTEMPT_COMPLETED
        return BootDecision.FAILED_ATTEMPT, "FAILED", ReasonCode.BOOT_ATTEMPT_FAILED

    # -- 报告 -------------------------------------------------------------
    def _report(
        self,
        *,
        run_id: str,
        started: datetime,
        phase: BootPhase,
        schedule_allowed: bool,
        blockers: set[BootBlocker],
        tasks_scanned: int,
        running_scanned: int,
        actions: list[BootAction] | tuple[BootAction, ...],
        note: str = "",
    ) -> BootReport:
        finished = self._now()
        report = BootReport(
            run_id=run_id,
            started_at=format_utc(started),
            finished_at=format_utc(finished),
            phase_reached=phase,
            schedule_allowed=schedule_allowed,
            blockers=tuple(sorted(blockers, key=lambda b: b.value)),
            tasks_scanned=tasks_scanned,
            running_nodes_scanned=running_scanned,
            resolved=sum(1 for a in actions if a.error_code is None and a.to_state != "RUNNING"),
            already_terminal=0,
            actions=tuple(actions),
            report_path=str(self._report_path) if self._report_path else None,
            note=note,
        )
        self._write_report(report)
        return report

    def _write_report(self, report: BootReport) -> None:
        if self._report_path is None:
            return
        payload = {
            "run_id": report.run_id,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "phase_reached": report.phase_reached.value,
            "schedule_allowed": report.schedule_allowed,
            "blockers": [b.value for b in report.blockers],
            "tasks_scanned": report.tasks_scanned,
            "running_nodes_scanned": report.running_nodes_scanned,
            "resolved": report.resolved,
            "actions": [
                {
                    "task_id": a.task_id,
                    "node_id": a.node_id,
                    "decision": a.decision.value,
                    "from_state": a.from_state,
                    "to_state": a.to_state,
                    "reason_code": a.reason_code,
                    "audit_id": a.audit_id,
                    "error_code": a.error_code,
                }
                for a in report.actions
            ],
            "note": report.note,
        }
        try:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            self._report_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            # 报告写失败不改变已发生的状态迁移；由调用方按 stderr/日志处理。
            pass

    def _now(self) -> datetime:
        clock = self._clock
        if clock is None:
            return datetime.now(timezone.utc)
        return clock.now()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
def assert_boot_contract() -> list[str]:
    problems: list[str] = []
    if tuple(BOOT_ORDER) != (
        "LOCK", "DB_INTEGRITY", "SCHEMA_VERSION", "EVIDENCE_CHAIN",
        "UNFINISHED_ATTEMPTS", "SCHEDULER_GATE",
    ):
        problems.append("恢复顺序必须锁定为 LOCK→DB→SCHEMA→CHAIN→ATTEMPT→GATE")
    if set(BOOT_ALLOWED_NODE_TARGETS) != {"VERIFYING", "FAILED"}:
        problems.append("启动阶段只允许 RUNNING→VERIFYING/FAILED")
    for forbidden in BOOT_FORBIDDEN_TARGETS:
        if forbidden in BOOT_ALLOWED_NODE_TARGETS:
            problems.append(f"启动阶段不得以 {forbidden} 为目标")
    if "COMPLETED" in " ".join(BOOT_ALLOWED_NODE_TARGETS):
        problems.append("启动阶段不得把 RUNNING 改成 COMPLETED")
    if set(BOOT_DECISION_REASONS) != {d.value for d in BootDecision if d is not BootDecision.ALREADY_TERMINAL}:
        problems.append("四个 RUNNING 分支必须各有 reason_code")
    if BootDecision.NO_ACTIVE_ATTEMPT not in BootDecision:
        problems.append("缺少 RUNNING 无活动 attempt 分支")
    return problems