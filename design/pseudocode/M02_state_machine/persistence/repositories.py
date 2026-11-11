"""M02 · persistence/repositories.py — 四类仓储与受控写入（P2 伪代码）。

阶段：P2｜状态：查询/写入入口的签名与边界；**不实现连接池、不执行 SQL、不建库**。

四类仓储：
  - `TaskRepository`：`tasks` 查询；写入口只有 `_apply_transition`（StateMachine 专用）
    与 `_insert_created`（创建专用，只 INSERT 初始 `CREATED`）。
  - `NodeRepository`：`nodes` 查询；写入口只有 `_apply_transition` 与 `_insert_planned`。
  - `EvidenceMetaRepository`：`evidence` 元数据与 `evidence_invalidations` 查询；
    追加入口 `_insert`（Collector/Verifier）与 `_append_invalidations`（StateMachine）。
  - `AuditRepository`：`audit_log` 查询；唯一写入口 `_append`（StateMachine）。

三条硬规则：
  1. **不提供裸 update**：不存在 `update` / `update_state` / `set_state` / `save` / `delete`
     之类的公开方法；状态写入只能由 `StateMachine` 以私有方法 + capability 调用。
  2. 只追加表（`evidence`、`evidence_invalidations`、`audit_log`）没有更新/删除入口；
     数据库触发器是第二道防线（schema_sql.py）。
  3. `_apply_transition` 返回受影响行数；`0` 表示乐观并发失败（调用方给
     `STATE_TRANSITION_DENIED / STALE_PREVIOUS_STATE`），**不得**改成“先读后写”或
     “最后写入者获胜”。

本文件不裁决状态迁移是否合法；合法性在 `orchestration/transitions.py` 与
`orchestration/state_machine.py`。仓储只负责“按期望前态写、写不中就返回 0”。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence

from .schema_sql import (
    EVIDENCE_LEVELS,
    NODE_STATES,
    TASK_STATES,
)

__all__ = [
    "AUDIT_APPEND_ONLY",
    "COLLECTOR_APPEND",
    "DAG_REGISTER",
    "STATE_MACHINE_WRITE",
    "TASK_CREATE",
    "VERIFIER_APPEND",
    "AppendOnlyViolation",
    "AttemptView",
    "AuditRepository",
    "AuditRow",
    "ChainReport",
    "DirectStateWriteDenied",
    "EvidenceMetaRepository",
    "EvidenceMetaRow",
    "InvalidationRow",
    "NodeRepository",
    "NodeRow",
    "ObjectNotFound",
    "PayloadReader",
    "Repositories",
    "RepositoryContractError",
    "TaskRepository",
    "TaskRow",
    "UnitOfWork",
    "assert_repository_contract",
    "connect",
]

AUDIT_APPEND_ONLY = True


# ---------------------------------------------------------------------------
# 0. capability：不是安全边界，是“调用点在 code review 中可见”的显式凭证
# ---------------------------------------------------------------------------
class _Capability:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"<capability {self.name}>"


STATE_MACHINE_WRITE = _Capability("state_machine")
COLLECTOR_APPEND = _Capability("collector")
VERIFIER_APPEND = _Capability("verifier")
TASK_CREATE = _Capability("task_create")
DAG_REGISTER = _Capability("dag_register")


class RepositoryContractError(RuntimeError):
    """仓储契约被破坏（例如公开了裸 update）。"""


class DirectStateWriteDenied(RepositoryContractError):
    """绕过 StateMachine 直接调用状态写入入口。"""

    error_code = "STATE_TRANSITION_DENIED"
    http_status = 409

    def __init__(self, repository: str, operation: str) -> None:
        self.repository = repository
        self.operation = operation
        super().__init__(
            f"{repository}.{operation} 只能由 StateMachine 调用；"
            "仓储层不提供裸 update，也不接受伪造 capability"
        )


class AppendOnlyViolation(RepositoryContractError):
    """试图更新/删除只追加表。"""

    error_code = "STATE_TRANSITION_DENIED"

    def __init__(self, table: str, operation: str) -> None:
        self.table = table
        self.operation = operation
        super().__init__(f"{table} 是只追加表，禁止 {operation}")


class ObjectNotFound(LookupError):
    """按主键查不到对象；API 可映射 404，状态机映射 DENIED。"""

    error_code = "STATE_TRANSITION_DENIED"
    http_status = 404

    def __init__(self, object_type: str, object_id: str) -> None:
        self.object_type = object_type
        self.object_id = object_id
        super().__init__(f"{object_type} 不存在：{object_id}")


# ---------------------------------------------------------------------------
# 1. 行对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TaskRow:
    task_id: str
    schema_version: str
    domain_pack: str
    goal: str
    task_spec_hash: str
    state: str
    graph_version: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class NodeRow:
    task_id: str
    node_id: str
    schema_version: str
    node_type: str
    template_id: str
    state: str
    attempt_seq: int
    plan_id: str | None
    plan_hash: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class EvidenceMetaRow:
    evidence_id: str
    task_id: str
    node_id: str
    attempt_id: str
    event_seq: int
    level: str
    kind: str
    producer: str
    timestamp: str
    payload_hash: str
    artifact_refs: str | None
    prev_hash: str
    chain_hash: str


@dataclass(frozen=True, slots=True)
class InvalidationRow:
    invalidation_id: str
    task_id: str
    node_id: str
    evidence_id: str
    reason_code: str
    cause_type: str
    cause_ref: str | None
    plan_id: str | None
    plan_hash: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class AuditRow:
    audit_id: str
    task_id: str | None
    node_id: str | None
    actor: str
    action: str
    previous_state: str | None
    next_state: str | None
    reason_code: str | None
    rule_version: str | None
    correlation_id: str | None
    plan_id: str | None
    plan_hash: str | None
    result: str
    error_code: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class AttemptView:
    """由 evidence 元数据投影出的 attempt 视图；不新增 attempts 表。"""

    attempt_id: str
    attempt_seq: int
    launch_seen: bool
    exit_seen: bool
    exit_code: int | None
    exit_payload_readable: bool
    evidence_ids: tuple[str, ...]
    last_event_seq: int | None


@dataclass(frozen=True, slots=True)
class ChainReport:
    """证据链只读校验结果；不修复、不重写。"""

    task_id: str
    ok: bool
    reason: str | None
    at_event_seq: int | None
    checked_count: int
    first_bad_evidence_id: str | None = None


class PayloadReader(Protocol):
    """读取证据 payload 的只读端口；M02 不实现，WP-07 提供。"""

    def read_exit_code(self, payload_hash: str) -> int:
        ...


# ---------------------------------------------------------------------------
# 2. 连接与事务
# ---------------------------------------------------------------------------
def connect(db_path: str) -> sqlite3.Connection:
    """打开连接并设置 06 §1.1 要求的 PRAGMA（伪代码，不执行）。"""
    raise NotImplementedError("P2 伪代码：连接与 PRAGMA 由 WP-03 实现")


class UnitOfWork:
    """短事务；写事务用 `BEGIN IMMEDIATE` 串行化，避免读后写竞态。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE → yield → COMMIT；异常回滚。

        嵌套调用必须显式拒绝（`RepositoryContractError`），不得静默复用外层事务。
        """
        if self._conn.in_transaction:
            raise RepositoryContractError("UnitOfWork.immediate 不允许嵌套")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise

    def rollback_if_needed(self) -> None:
        if self._conn.in_transaction:
            self._conn.rollback()


# ---------------------------------------------------------------------------
# 3. 仓储基类与校验
# ---------------------------------------------------------------------------
class _RepositoryBase:
    PUBLIC_METHODS: tuple[str, ...] = ()
    WRITE_METHODS: tuple[str, ...] = ()

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _require_capability(self, provided: object, expected: object, operation: str) -> None:
        if provided is not expected:
            raise DirectStateWriteDenied(type(self).__name__, operation)


class TaskRepository(_RepositoryBase):
    """`tasks` 仓储。

    公开方法只有查询。状态写入 `_apply_transition` 带 `WHERE state = :expected_from`，
    返回 0 即乐观并发失败；创建写入 `_insert_created` 只允许 `state='CREATED'`。
    """

    PUBLIC_METHODS = ("get", "get_state", "list_by_state", "list_all")
    WRITE_METHODS = ("_insert_created", "_apply_transition")

    def get(self, task_id: str) -> TaskRow | None:
        raise NotImplementedError("P2 伪代码：TaskRepository.get")

    def get_state(self, task_id: str) -> str:
        row = self.get(task_id)
        if row is None:
            raise ObjectNotFound("task", task_id)
        return row.state

    def list_by_state(self, state: str, *, limit: int = 100) -> tuple[TaskRow, ...]:
        if state not in TASK_STATES:
            raise ValueError(f"未知 Task 状态：{state!r}")
        raise NotImplementedError("P2 伪代码：TaskRepository.list_by_state")

    def list_all(self, *, limit: int = 1000) -> tuple[TaskRow, ...]:
        """启动恢复用：按 created_at 扫描任务；只读。"""
        raise NotImplementedError("P2 伪代码：TaskRepository.list_all")

    def _insert_created(
        self, task: TaskRow, *, capability: object
    ) -> None:
        """创建专用：只 INSERT，且 state 必须为 CREATED。"""
        self._require_capability(capability, TASK_CREATE, "_insert_created")
        if task.state != "CREATED":
            raise RepositoryContractError("任务创建只能写入初始状态 CREATED")
        raise NotImplementedError("P2 伪代码：TaskRepository._insert_created")

    def _apply_transition(
        self,
        *,
        task_id: str,
        expected_from: str,
        to_state: str,
        updated_at: str,
        graph_version: int | None,
        capability: object,
    ) -> int:
        """StateMachine 专用；返回受影响行数（0 = 前态已变）。"""
        self._require_capability(capability, STATE_MACHINE_WRITE, "_apply_transition")
        if to_state not in TASK_STATES:
            raise ValueError(f"未知 Task 状态：{to_state!r}")
        if graph_version is not None and to_state != "READY":
            raise RepositoryContractError("graph_version 只能在 PLANNING→READY 时写入")
        raise NotImplementedError("P2 伪代码：TaskRepository._apply_transition")


class NodeRepository(_RepositoryBase):
    """`nodes` 仓储；状态/attempt_seq/plan_* 的写入只走 `_apply_transition`。"""

    PUBLIC_METHODS = (
        "get", "get_state", "list_by_task", "list_by_state", "list_running",
        "project_attempt",
    )
    WRITE_METHODS = ("_insert_planned", "_apply_transition")

    def get(self, task_id: str, node_id: str) -> NodeRow | None:
        raise NotImplementedError("P2 伪代码：NodeRepository.get")

    def get_state(self, task_id: str, node_id: str) -> str:
        row = self.get(task_id, node_id)
        if row is None:
            raise ObjectNotFound("node", f"{task_id}/{node_id}")
        return row.state

    def list_by_task(self, task_id: str) -> tuple[NodeRow, ...]:
        raise NotImplementedError("P2 伪代码：NodeRepository.list_by_task")

    def list_by_state(self, task_id: str, state: str) -> tuple[NodeRow, ...]:
        if state not in NODE_STATES:
            raise ValueError(f"未知 Node 状态：{state!r}")
        raise NotImplementedError("P2 伪代码：NodeRepository.list_by_state")

    def list_running(self) -> tuple[NodeRow, ...]:
        """重启恢复扫描：所有 RUNNING 节点。"""
        raise NotImplementedError("P2 伪代码：NodeRepository.list_running")

    def project_attempt(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_seq: int,
        payload_reader: PayloadReader | None = None,
    ) -> AttemptView:
        """从 evidence 元数据投影 attempt；不新增 attempts 表。

        - `launch_seen`：存在 `kind='executor_launch'` 的 E2 记录；
        - `exit_seen`：存在 `kind='executor_process_exit'` 的 E2 记录；
        - `exit_code`：仅当传入 `payload_reader` 且 payload 可读时给出；
        - 任一步读取失败按“不可读”处理，由调用方 fail-closed（不得猜成功）。
        """
        raise NotImplementedError("P2 伪代码：NodeRepository.project_attempt")

    def _insert_planned(
        self, nodes: Sequence[NodeRow], *, capability: object
    ) -> None:
        """DAG 注册专用：只 INSERT，且 state 必须为 PLANNED。"""
        self._require_capability(capability, DAG_REGISTER, "_insert_planned")
        if any(n.state != "PLANNED" for n in nodes):
            raise RepositoryContractError("节点注册只能写入初始状态 PLANNED")
        raise NotImplementedError("P2 伪代码：NodeRepository._insert_planned")

    def _apply_transition(
        self,
        *,
        task_id: str,
        node_id: str,
        expected_from: str,
        to_state: str,
        updated_at: str,
        attempt_seq_delta: int = 0,
        plan_id: str | None = None,
        plan_hash: str | None = None,
        capability: object,
    ) -> int:
        """StateMachine 专用；返回受影响行数（0 = 前态已变/并发失败）。

        约束：
          - `attempt_seq_delta` 只能是 0 或 1；只有 READY→RUNNING 允许 +1；
          - `plan_id`/`plan_hash` 必须成对，且只允许 INVALIDATED→READY；
          - 不允许在别的边顺手改 plan 字段或 attempt_seq。
        """
        self._require_capability(capability, STATE_MACHINE_WRITE, "_apply_transition")
        if to_state not in NODE_STATES:
            raise ValueError(f"未知 Node 状态：{to_state!r}")
        if attempt_seq_delta not in (0, 1):
            raise RepositoryContractError("attempt_seq_delta 只能是 0 或 1")
        if (plan_id is None) != (plan_hash is None):
            raise RepositoryContractError("plan_id/plan_hash 必须成对")
        if plan_id is not None and not (expected_from == "INVALIDATED" and to_state == "READY"):
            raise RepositoryContractError("plan_id/plan_hash 只能在 INVALIDATED→READY 写入")
        if attempt_seq_delta and not (expected_from == "READY" and to_state == "RUNNING"):
            raise RepositoryContractError("attempt_seq 只能在 READY→RUNNING 递增")
        raise NotImplementedError("P2 伪代码：NodeRepository._apply_transition")


class EvidenceMetaRepository(_RepositoryBase):
    """`evidence` 元数据与 `evidence_invalidations`；只读 + 追加，无更新/删除。"""

    PUBLIC_METHODS = (
        "get", "list_by_task", "list_by_node_attempt", "latest_event_seq",
        "verify_chain", "count",
    )
    WRITE_METHODS = ("_insert", "_append_invalidations")

    def get(self, evidence_id: str) -> EvidenceMetaRow | None:
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository.get")

    def list_by_task(
        self, task_id: str, *, after_seq: int = 0, limit: int = 500
    ) -> tuple[EvidenceMetaRow, ...]:
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository.list_by_task")

    def list_by_node_attempt(
        self, task_id: str, node_id: str, attempt_id: str
    ) -> tuple[EvidenceMetaRow, ...]:
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository.list_by_node_attempt")

    def latest_event_seq(self, task_id: str) -> int:
        """返回该任务已见最大 event_seq；无记录返回 0。"""
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository.latest_event_seq")

    def count(self, task_id: str) -> int:
        """证书 tree_size 的唯一口径：证据条数。"""
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository.count")

    def verify_chain(self, task_id: str) -> ChainReport:
        """只读链校验：event_seq 从 1 连续、prev_hash == 上一条 chain_hash。

        `chain_hash` 前像未冻结（05 §13），本函数**不重算** chain_hash，只校验形态与链接；
        重算留给 WP-07 并以篡改负例锁定。
        """
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository.verify_chain")

    def _insert(self, row: EvidenceMetaRow, *, capability: object) -> None:
        """追加证据元数据；E0–E2 用 COLLECTOR_APPEND，E3 用 VERIFIER_APPEND。"""
        if capability not in (COLLECTOR_APPEND, VERIFIER_APPEND):
            raise DirectStateWriteDenied(type(self).__name__, "_insert")
        if row.level not in EVIDENCE_LEVELS:
            raise ValueError(f"未知证据等级：{row.level!r}")
        if row.level in ("E0", "E1", "E2") and capability is not COLLECTOR_APPEND:
            raise RepositoryContractError("E0–E2 只能由 Collector 追加")
        if row.level == "E3" and capability is not VERIFIER_APPEND:
            raise RepositoryContractError("E3 只能由 Verifier 追加")
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository._insert")

    def _append_invalidations(
        self, rows: Sequence[InvalidationRow], *, capability: object
    ) -> None:
        """StateMachine 在 VERIFIED→INVALIDATED 同事务追加；不得删除证据。"""
        self._require_capability(capability, STATE_MACHINE_WRITE, "_append_invalidations")
        if not rows:
            raise RepositoryContractError("失效迁移必须至少引用一条 stale 证据")
        raise NotImplementedError("P2 伪代码：EvidenceMetaRepository._append_invalidations")


class AuditRepository(_RepositoryBase):
    """`audit_log` 仓储；唯一写者是 StateMachine。"""

    PUBLIC_METHODS = (
        "query_by_task", "query_by_correlation", "latest_freeze",
        "latest_transition", "count_denied",
    )
    WRITE_METHODS = ("_append",)

    def query_by_task(
        self, task_id: str, *, limit: int = 200
    ) -> tuple[AuditRow, ...]:
        raise NotImplementedError("P2 伪代码：AuditRepository.query_by_task")

    def query_by_correlation(self, correlation_id: str) -> tuple[AuditRow, ...]:
        """同一迁移请求的成功 + 失败两条记录应能一起查到。"""
        raise NotImplementedError("P2 伪代码：AuditRepository.query_by_correlation")

    def latest_freeze(
        self, *, task_id: str, node_id: str, plan_hash: str
    ) -> AuditRow | None:
        """取该节点、该 plan_hash 最近一次 `RECOVERY_PLAN_FROZEN` 成功记录。"""
        raise NotImplementedError("P2 伪代码：AuditRepository.latest_freeze")

    def latest_transition(self, *, task_id: str, node_id: str | None) -> AuditRow | None:
        """取最近一次 STATE_TRANSITION 记录（OK 或 DENIED）。"""
        raise NotImplementedError("P2 伪代码：AuditRepository.latest_transition")

    def count_denied(self, task_id: str) -> int:
        raise NotImplementedError("P2 伪代码：AuditRepository.count_denied")

    def _append(self, row: AuditRow, *, capability: object) -> None:
        """StateMachine 唯一写入口；成功同事务、失败独立事务。"""
        self._require_capability(capability, STATE_MACHINE_WRITE, "_append")
        if row.result not in ("OK", "DENIED"):
            raise ValueError(f"未知审计结果：{row.result!r}")
        if row.result == "DENIED" and not row.error_code:
            raise RepositoryContractError("DENIED 审计必须携带 error_code")
        if row.result == "OK" and row.error_code:
            raise RepositoryContractError("OK 审计不得携带 error_code")
        raise NotImplementedError("P2 伪代码：AuditRepository._append")


# ---------------------------------------------------------------------------
# 4. 仓储集合
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Repositories:
    tasks: TaskRepository
    nodes: NodeRepository
    evidence: EvidenceMetaRepository
    audit: AuditRepository
    uow: UnitOfWork

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "Repositories":
        return cls(
            tasks=TaskRepository(conn),
            nodes=NodeRepository(conn),
            evidence=EvidenceMetaRepository(conn),
            audit=AuditRepository(conn),
            uow=UnitOfWork(conn),
        )


# ---------------------------------------------------------------------------
# 5. 契约自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
FORBIDDEN_PUBLIC_METHODS: tuple[str, ...] = (
    "update", "update_state", "set_state", "save", "delete", "remove",
    "execute", "raw_update", "force_state", "upsert",
)


def assert_repository_contract() -> list[str]:
    """检查仓储层没有裸 update / 公开写入口。返回违反项列表。"""
    problems: list[str] = []
    for cls in (TaskRepository, NodeRepository, EvidenceMetaRepository, AuditRepository):
        for name in FORBIDDEN_PUBLIC_METHODS:
            if hasattr(cls, name):
                problems.append(f"{cls.__name__} 不得有公开方法 {name}")
        for name in cls.WRITE_METHODS:
            if not name.startswith("_"):
                problems.append(f"{cls.__name__}.{name} 写入口必须以下划线开头")
            if name in cls.PUBLIC_METHODS:
                problems.append(f"{cls.__name__}.{name} 不能同时出现在 PUBLIC_METHODS")
        for name in cls.PUBLIC_METHODS:
            if name.startswith("_"):
                problems.append(f"{cls.__name__}.{name} 公开方法不应以下划线开头")
    return problems