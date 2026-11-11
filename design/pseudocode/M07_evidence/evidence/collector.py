"""M07 · evidence/collector.py — 单写者在环：E0/E1/E2 投稿、入队、分配 seq、调链、落库（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-005（E2 唯一来源）、FR-006（Gate 输入）、05 §4.5
依赖：M07 store（写会话/许可）、M07 chain（前驱/链哈希）、M07 gaps（缺口日志）、M01 encoding（JCS 端口）
不变量：**只有 Collector 能拿写许可并打开 WriterSession**；event_seq 在单写队列内单调分配；
        E0 必须带 agent_claim 标记；E0/E1 永不满足执行类必检；重复 event_id 不产生第二条逻辑记录；
        payload_hash 与实际 payload 不符一律拒绝；Collector 不写任务/节点状态、不写审计、不签名
错误码：SCHEMA_INVALID（422，投稿形态/哈希不符）、EVIDENCE_REFERENCE_NOT_FOUND（422，产物引用不存在）、
        RESOURCE_BUDGET_EXCEEDED（429，队列/载荷超限）、EVENT_SEQ_* / EVIDENCE_CHAIN_BROKEN（500，链/序列）
写入者：**Collector 是 E0–E2 的唯一写入者**；E3（verifier_recheck）在 P4 不接受，留 P6（OQ-P4-01）
状态：伪代码；线程/队列/SQLite 事务属 WP-07；本文件不建库、不执行、不跑测试

## E0 的三道锁

  1. **标记**：E0 投稿必须带 `AgentClaim`，且 kind 必须是 `agent_claim`；
     payload 里写入 `agent_claim` 对象与 `claim_origin="agent"`。缺标记 → 拒绝。
  2. **等级**：level 由 kind 推导，**投稿方不能自报 level/producer**；
     E0 的 producer 永远是 `collector`（Collector 是记录者，不是声明者）。
  3. **门控**：`EXECUTION_CRITICAL_LEVELS=("E2","E3")`；`assert_can_satisfy_execution_check()`
     对 E0/E1 抛 `REQUIRED_EVIDENCE_MISSING`。P5 的 Gate 必须调用它，
     不得用 Agent 声明顶替执行类必检。

## 单写队列与 event_seq

  `submit()` 只把投稿放进有界队列；唯一的 writer 线程按入队顺序处理：
    - 先判重（event_id + payload_hash）；重复投递只增加 `ingestion_log.delivery_seq`；
    - 再开写事务（`BEGIN IMMEDIATE`），取链尾、`allocate_seq()`、算 chain_hash、
      `assert_appendable()`、INSERT evidence、INSERT ingestion_log，同一事务提交。
  并发投稿因此不会抢到同一个 seq；事务失败时 seq 不被占用（回滚），不会留下“空洞”。
  成功写入的 seq 连续 +1；读路径发现缺口按 gaps.py 处理，**不补造**。

## 重复 event_id 的三种结果

  | 情况 | 结果 |
  |---|---|
  | 同 event_id + 同 payload_hash | 幂等：返回既有 evidence_id，`duplicate=True`，delivery_seq+1 |
  | 同 event_id + 不同 payload_hash | CONFLICT：拒绝，写 rejection 日志，不写 evidence |
  | 不同 event_id + E2 同 attempt/kind 不同内容 | CONFLICT：拒绝（一个 attempt 只能有一次 launch/exit） |

## 为什么不在这里做 Gate/签名

  Gate 判定（P5）与签名（P6）是下游；Collector 只回答“这条投稿是否被接受、落在哪个 seq/hash”。
  它不能返回 `VERIFIED`，也不能把 `agent_claim` 当成“执行发生”。
"""

from __future__ import annotations

import hashlib
import queue
import re
import threading
import uuid
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol

from .chain import (
    ChainHasher,
    ChainRecord,
    StoredRecord,
    assert_appendable,
)
from .gaps import GapJournalPort, gate_view
from .store import (
    EvidenceStore,
    EvidenceStoreError,
    WritePermit,
    _issue_collector_permit,
)

__all__ = [
    "E0_MARKER",
    "EXECUTION_CRITICAL_LEVELS",
    "LEVEL_BY_KIND",
    "AgentClaim",
    "Collector",
    "CollectorError",
    "CollectorPolicy",
    "EvidenceReceipt",
    "EvidenceSubmission",
    "RejectedSubmission",
    "assert_can_satisfy_execution_check",
    "assert_collector_boundary",
    "can_satisfy_execution_check",
]

E0_MARKER: Final[str] = "agent_claim"
EXECUTION_CRITICAL_LEVELS: Final[tuple[str, ...]] = ("E2", "E3")

LEVEL_BY_KIND: Final[Mapping[str, str]] = MappingProxyType({
    "agent_claim": "E0",
    "tool_invocation": "E1",
    "harness_trace": "E1",
    "executor_launch": "E2",
    "executor_process_exit": "E2",
    "artifact_observed": "E2",
    "verifier_recheck": "E3",
})

PRODUCER_BY_LEVEL: Final[Mapping[str, str]] = MappingProxyType({
    "E0": "collector", "E1": "collector", "E2": "collector", "E3": "verifier",
})

SOURCE_BY_KIND: Final[Mapping[str, str]] = MappingProxyType({
    "agent_claim": "agent",
    "tool_invocation": "harness",
    "harness_trace": "harness",
    "executor_launch": "executor",
    "executor_process_exit": "executor",
    "artifact_observed": "executor",
    "verifier_recheck": "verifier",
})

_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$")
_ATTEMPT_ID = re.compile(r"^attempt_[0-9]{2,}$")
_TASK_ID = re.compile(r"^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class CollectorError(RuntimeError):
    """投稿/写入拒绝；对外码用已注册码。"""

    def __init__(
        self,
        error_code: str,
        reason: str,
        message: str,
        *,
        field_path: str = "",
        http_status: int = 422,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.reason = reason
        self.field_path = field_path
        self.http_status = http_status
        self.detail = MappingProxyType(dict(detail or {}))
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


class ClaimType(StrEnum):
    FINDING = "finding"
    EXPLANATION = "explanation"
    COMPLETION_CLAIM = "completion_claim"
    RISK = "risk"


@dataclass(frozen=True, slots=True)
class AgentClaim:
    """E0 声明的最小标记；没有它就不是 E0，也不该进证据表。"""

    claim_id: str
    agent_id: str
    claim_type: str
    claim_text: str
    session_ref: str
    asserted_at: str

    def __post_init__(self) -> None:
        if not self.claim_id or len(self.claim_id) > 128:
            raise ValueError("claim_id 必须非空且 ≤128")
        if not self.agent_id or len(self.agent_id) > 128:
            raise ValueError("agent_id 必须非空且 ≤128")
        if self.claim_type not in {c.value for c in ClaimType}:
            raise ValueError(f"claim_type 非法：{self.claim_type!r}")
        if not self.claim_text or len(self.claim_text) > 8192:
            raise ValueError("claim_text 必须非空且 ≤8192")
        if not self.session_ref or len(self.session_ref) > 256:
            raise ValueError("session_ref 必须非空且 ≤256")
        if not _UTC.match(self.asserted_at):
            raise ValueError("asserted_at 必须是 UTC RFC 3339")

    def as_payload(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "agent_id": self.agent_id,
            "claim_type": self.claim_type,
            "claim_text": self.claim_text,
            "session_ref": self.session_ref,
            "asserted_at": self.asserted_at,
        }


@dataclass(frozen=True, slots=True)
class EvidenceSubmission:
    """生产方交给 Collector 的投稿。

    **刻意没有** `level`/`producer`/`event_seq`/`prev_hash`/`chain_hash`：
    这些由 Collector 推导/分配。投稿方自报 level 会被结构挡掉（字段不存在）。
    """

    event_id: str | None
    kind: str
    task_id: str
    node_id: str
    attempt_id: str
    observed_at: str
    payload: Mapping[str, object]
    source: str
    artifact_refs: tuple[str, ...] = ()
    agent_claim: AgentClaim | None = None
    source_seq: int | None = None
    correlation_id: str = ""
    declared_payload_hash: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in LEVEL_BY_KIND:
            raise CollectorError("SCHEMA_INVALID", "KIND_INVALID",
                                 f"kind 不在冻结集合：{self.kind!r}", field_path="kind")
        if self.event_id is not None and not _EVENT_ID.match(self.event_id):
            raise CollectorError("SCHEMA_INVALID", "EVENT_ID_INVALID",
                                 f"event_id 形态非法：{self.event_id!r}", field_path="event_id")
        for name in ("task_id", "node_id", "attempt_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise CollectorError("SCHEMA_INVALID", "ID_EMPTY",
                                     f"{name} 必须非空", field_path=name)
        if not _TASK_ID.match(self.task_id):
            raise CollectorError("SCHEMA_INVALID", "TASK_ID_INVALID",
                                 f"task_id 形态非法：{self.task_id!r}", field_path="task_id")
        if not _NODE_ID.match(self.node_id):
            raise CollectorError("SCHEMA_INVALID", "NODE_ID_INVALID",
                                 f"node_id 形态非法：{self.node_id!r}", field_path="node_id")
        if not _ATTEMPT_ID.match(self.attempt_id):
            raise CollectorError("SCHEMA_INVALID", "ATTEMPT_ID_INVALID",
                                 f"attempt_id 形态非法：{self.attempt_id!r}", field_path="attempt_id")
        if not _UTC.match(self.observed_at):
            raise CollectorError("SCHEMA_INVALID", "TIMESTAMP_INVALID",
                                 "observed_at 必须是 UTC RFC 3339", field_path="timestamp")
        if not isinstance(self.payload, Mapping):
            raise CollectorError("SCHEMA_INVALID", "PAYLOAD_NOT_OBJECT",
                                 "payload 必须是对象", field_path="payload")
        expected_source = SOURCE_BY_KIND[self.kind]
        if self.source != expected_source:
            raise CollectorError(
                "SCHEMA_INVALID", "SOURCE_MISMATCH",
                f"kind={self.kind} 的 source 必须是 {expected_source!r}，实际 {self.source!r}",
                field_path="source",
            )
        if self.source_seq is not None and (
            isinstance(self.source_seq, bool) or not isinstance(self.source_seq, int) or self.source_seq < 0
        ):
            raise CollectorError("SCHEMA_INVALID", "SOURCE_SEQ_INVALID",
                                 "source_seq 必须是非负 integer", field_path="source_seq")
        for ref in self.artifact_refs:
            if not isinstance(ref, str) or not ref.startswith("artifact://") or len(ref) <= len("artifact://"):
                raise CollectorError("SCHEMA_INVALID", "ARTIFACT_REF_INVALID",
                                     f"artifact_ref 形态非法：{ref!r}", field_path="artifact_refs")
        if len(set(self.artifact_refs)) != len(self.artifact_refs):
            raise CollectorError("SCHEMA_INVALID", "ARTIFACT_REF_DUPLICATED",
                                 "artifact_refs 不得重复", field_path="artifact_refs")
        if self.kind == E0_MARKER:
            if self.agent_claim is None:
                raise CollectorError(
                    "SCHEMA_INVALID", "AGENT_CLAIM_MISSING",
                    "E0 必须带 agent_claim 标记", field_path="agent_claim",
                )
            if self.artifact_refs:
                raise CollectorError(
                    "SCHEMA_INVALID", "E0_ARTIFACT_CLAIM",
                    "E0 不得引用 artifact（声明不是执行产物）", field_path="artifact_refs",
                )
        elif self.agent_claim is not None:
            raise CollectorError(
                "SCHEMA_INVALID", "AGENT_CLAIM_ON_NON_E0",
                "只有 kind=agent_claim 可以带 agent_claim", field_path="agent_claim",
            )

    @property
    def level(self) -> str:
        return LEVEL_BY_KIND[self.kind]

    @property
    def producer(self) -> str:
        return PRODUCER_BY_LEVEL[self.level]

    def payload_for_storage(self) -> dict[str, object]:
        """写进 payload sidecar 的对象；E0 强制加 marker/origin。"""
        payload = dict(self.payload)
        if self.kind == E0_MARKER:
            if self.agent_claim is None:
                raise CollectorError("SCHEMA_INVALID", "AGENT_CLAIM_MISSING",
                                     "E0 必须带 agent_claim", field_path="agent_claim")
            payload["agent_claim"] = self.agent_claim.as_payload()
            payload["claim_origin"] = "agent"
        return payload


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    evidence_id: str
    event_seq: int
    chain_hash: str
    level: str
    kind: str
    ingestion_id: str
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class RejectedSubmission:
    reason: str
    error_code: str
    field_path: str
    detail: str
    rejection_id: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class CollectorPolicy:
    queue_size: int = 1024
    submit_timeout_sec: float = 10.0
    max_payload_bytes: int = 4 * 1024 * 1024
    max_artifact_refs: int = 64
    require_artifact_resolution: bool = True

    def __post_init__(self) -> None:
        if self.queue_size < 1 or self.submit_timeout_sec <= 0:
            raise ValueError("队列/超时配置非法")
        if self.max_payload_bytes < 1 or self.max_artifact_refs < 1:
            raise ValueError("载荷/引用上限必须 ≥1")


class ClockPort(Protocol):
    def now_utc(self) -> str: ...
    def monotonic(self) -> float: ...


class CanonicalizerPort(Protocol):
    def canonical_bytes(self, value: object) -> bytes: ...


class EvidenceIdFactory(Protocol):
    def new_evidence_id(self) -> str: ...
    def new_rejection_id(self) -> str: ...


class ArtifactResolverPort(Protocol):
    def exists(self, *, task_id: str, attempt_id: str, ref: str) -> bool: ...


class _Envelope:
    __slots__ = ("submission", "done", "result", "error")

    def __init__(self, submission: EvidenceSubmission) -> None:
        self.submission = submission
        self.done = threading.Event()
        self.result: EvidenceReceipt | RejectedSubmission | None = None
        self.error: BaseException | None = None


class IdFactory:
    """默认 ID 工厂：形态与 M01 `new_id("ev")` 一致；落地替换为 M01 实现。"""

    def new_evidence_id(self) -> str:
        return f"ev_{uuid.uuid4()}"

    def new_rejection_id(self) -> str:
        return f"rej_{uuid.uuid4()}"


class Collector:
    """E0/E1/E2 的唯一写入者。

    生命周期：`start()` → `submit()`* → `stop()`。未 `start()` 调用 `submit()` 会拒绝，
    避免“以为在写、其实只在内存排队”。
    """

    def __init__(
        self,
        *,
        store: EvidenceStore,
        hasher: ChainHasher,
        clock: ClockPort,
        canonicalizer: CanonicalizerPort,
        gap_journal: GapJournalPort,
        id_factory: EvidenceIdFactory | None = None,
        artifact_resolver: ArtifactResolverPort | None = None,
        policy: CollectorPolicy | None = None,
    ) -> None:
        self._store = store
        self._hasher = hasher
        self._clock = clock
        self._canonicalizer = canonicalizer
        self._gaps = gap_journal
        self._ids = id_factory or IdFactory()
        self._resolver = artifact_resolver
        self._policy = policy or CollectorPolicy()
        self._permit: WritePermit = _issue_collector_permit()
        self._queue: queue.Queue[_Envelope] = queue.Queue(maxsize=self._policy.queue_size)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._stop = threading.Event()
        self._unavailable: str = ""

    # -- 生命周期 ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._running.set()
        self._thread = threading.Thread(target=self._writer_loop, name="evidence-collector", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_sec: float = 5.0) -> None:
        self._stop.set()
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=timeout_sec)

    @property
    def running(self) -> bool:
        return self._running.is_set() and not self._unavailable

    # -- 投稿入口 ---------------------------------------------------------
    def submit(self, submission: EvidenceSubmission, *, timeout_sec: float | None = None) -> EvidenceReceipt:
        """入队并等待结果；拒绝/超时都抛 `CollectorError`，不静默丢。"""
        if not self.running:
            raise CollectorError("EVIDENCE_CHAIN_BROKEN", "COLLECTOR_NOT_RUNNING",
                                 "Collector 未启动或已不可用", http_status=500)
        if len(submission.artifact_refs) > self._policy.max_artifact_refs:
            raise CollectorError("RESOURCE_BUDGET_EXCEEDED", "TOO_MANY_ARTIFACT_REFS",
                                 "artifact_refs 超过上限", field_path="artifact_refs", http_status=429,
                                 detail={"limit_kind": "artifact_refs"})
        envelope = _Envelope(submission)
        try:
            self._queue.put_nowait(envelope)
        except queue.Full as exc:
            raise CollectorError("RESOURCE_BUDGET_EXCEEDED", "COLLECTOR_QUEUE_FULL",
                                 "Collector 单写队列已满", http_status=429,
                                 detail={"limit_kind": "queue"}) from exc
        wait = self._policy.submit_timeout_sec if timeout_sec is None else timeout_sec
        if not envelope.done.wait(timeout=wait):
            raise CollectorError("RESOURCE_BUDGET_EXCEEDED", "COLLECTOR_TIMEOUT",
                                 "等待 Collector 写入超时", http_status=429,
                                 detail={"limit_kind": "wall_clock"})
        if envelope.error is not None:
            raise envelope.error
        if isinstance(envelope.result, RejectedSubmission):
            status = 422
            if envelope.result.error_code == "RESOURCE_BUDGET_EXCEEDED":
                status = 429
            elif envelope.result.error_code in ("EVIDENCE_CHAIN_BROKEN", "EVENT_SEQ_GAP",
                                                "EVENT_SEQ_REGRESSION"):
                status = 500
            raise CollectorError(
                envelope.result.error_code, envelope.result.reason, envelope.result.detail,
                field_path=envelope.result.field_path,
                http_status=status,
                detail={"rejection_id": envelope.result.rejection_id},
            )
        if envelope.result is None:
            raise CollectorError("EVIDENCE_CHAIN_BROKEN", "COLLECTOR_NO_RESULT",
                                 "Collector 未返回结果", http_status=500)
        return envelope.result

    # -- M05 适配器 -------------------------------------------------------
    def record(self, draft: object) -> str:
        """`CollectorPort.record(EventDraft)` 适配：返回 evidence_id；失败即抛。

        M05 的 EventDraft 没有 event_id/level；E2 的 event_id 由内容派生，
        同一 attempt/kind 的重复投递由 attempt 级唯一性兜底。
        """
        kind = getattr(draft, "kind")
        payload = getattr(draft, "payload")
        refs = _artifact_refs_from_payload(payload)
        submission = EvidenceSubmission(
            event_id=None,
            kind=kind,
            task_id=getattr(draft, "task_id"),
            node_id=getattr(draft, "node_id"),
            attempt_id=getattr(draft, "attempt_id"),
            observed_at=getattr(draft, "observed_at"),
            payload=payload,
            source=SOURCE_BY_KIND[kind],
            artifact_refs=refs,
        )
        receipt = self.submit(submission)
        return receipt.evidence_id

    def has_launch(self, *, task_id: str, node_id: str, attempt_id: str) -> bool:
        page = self._store.query(task_id=task_id, node_id=node_id, attempt_id=attempt_id, limit=1000)
        return any(r.record.kind == "executor_launch" for r in page.records)

    def has_exit(self, *, task_id: str, node_id: str, attempt_id: str) -> bool:
        page = self._store.query(task_id=task_id, node_id=node_id, attempt_id=attempt_id, limit=1000)
        return any(r.record.kind == "executor_process_exit" for r in page.records)

    # -- 单写线程 ---------------------------------------------------------
    def _writer_loop(self) -> None:
        while not self._stop.is_set():
            try:
                envelope = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                envelope.result = self._process(envelope.submission)
            except BaseException as exc:  # fail-closed：把异常交回投稿方
                envelope.error = exc
                if isinstance(exc, (EvidenceStoreError, CollectorError)) and getattr(
                    exc, "error_code", ""
                ) in ("EVIDENCE_CHAIN_BROKEN", "EVENT_SEQ_GAP"):
                    self._unavailable = f"{getattr(exc, 'error_code', '')}/{getattr(exc, 'reason', '')}"
                    self._running.clear()
            finally:
                envelope.done.set()
                self._queue.task_done()

    # -- 核心处理 ---------------------------------------------------------
    def _process(self, submission: EvidenceSubmission) -> EvidenceReceipt | RejectedSubmission:
        # 1) 等级/来源/标记
        level = submission.level
        if level == "E3":
            return self._reject(submission, "INVALID", "SCHEMA_INVALID",
                                "verifier_recheck 在 P4 不接受（P6/OQ-P4-01）", "kind")
        # 2) payload 规范化 + 哈希
        payload = submission.payload_for_storage()
        canonical = self._canonicalizer.canonical_bytes(payload)
        if len(canonical) > self._policy.max_payload_bytes:
            return self._reject(submission, "INVALID", "RESOURCE_BUDGET_EXCEEDED",
                                "payload 超过上限", "payload")
        payload_hash = hashlib.sha256(canonical).hexdigest()
        if submission.declared_payload_hash is not None and submission.declared_payload_hash != payload_hash:
            return self._reject(submission, "INVALID", "SCHEMA_INVALID",
                                "投稿自报 payload_hash 与实际不一致", "payload_hash")
        # 3) event_id：E0/E1 必填；E2 允许由内容派生（稳定）
        event_id = submission.event_id or self._derive_e2_event_id(submission, payload_hash)
        # ingestion_id 加 task 前缀：生产方 event_id 只保证任务内唯一，跨任务可能撞车。
        ingestion_id = f"{submission.task_id}:{event_id}"
        # 4) 幂等/冲突（event_id 级）
        existing = self._store.find_ingestion(ingestion_id)
        if existing is not None:
            try:
                stored = self._store.get(existing.evidence_id)
            except EvidenceStoreError:
                return self._reject(submission, "INVALID", "SCHEMA_INVALID",
                                    "ingestion_log 指向不存在的 evidence", "event_id")
            if stored.record.payload_hash == payload_hash:
                self._record_delivery(ingestion_id, existing.evidence_id)
                return EvidenceReceipt(
                    evidence_id=existing.evidence_id,
                    event_seq=stored.event_seq,
                    chain_hash=stored.chain_hash,
                    level=stored.record.level,
                    kind=stored.record.kind,
                    ingestion_id=ingestion_id,
                    duplicate=True,
                )
            return self._reject(submission, "CONFLICT", "SCHEMA_INVALID",
                                "同 event_id 对应不同 payload_hash", "event_id",
                                payload_hash=payload_hash)
        # 5) attempt 级唯一性（E2）
        conflict = self._attempt_conflict(submission, payload_hash)
        if conflict is not None:
            return conflict
        # 6) 产物引用存在性
        if submission.artifact_refs and self._policy.require_artifact_resolution:
            if self._resolver is None:
                return self._reject(submission, "INVALID", "EVIDENCE_CHAIN_BROKEN",
                                    "需要校验 artifact_refs 但未注入 resolver", "artifact_refs")
            missing = [ref for ref in submission.artifact_refs
                       if not self._resolver.exists(task_id=submission.task_id,
                                                    attempt_id=submission.attempt_id, ref=ref)]
            if missing:
                return self._reject(submission, "INVALID", "EVIDENCE_REFERENCE_NOT_FOUND",
                                    f"artifact 引用不存在：{missing}", "artifact_refs")
        # 7) 写 payload sidecar（内容寻址；DB 只存哈希）
        stored_hash = self._store.payloads.put(canonical)
        if stored_hash != payload_hash:
            return self._reject(submission, "INVALID", "SCHEMA_INVALID",
                                "sidecar 哈希与计算值不一致", "payload_hash")
        # 8) 单写事务：seq → chain_hash → append → ingestion
        try:
            with self._store.writer_session(self._permit) as session:
                prev = session.last_record(submission.task_id)
                seq = session.allocate_seq(submission.task_id)
                prev_hash = prev.chain_hash if prev is not None else _genesis_prev_hash()
                record = ChainRecord(
                    schema_version="1.0",
                    evidence_id=self._ids.new_evidence_id(),
                    task_id=submission.task_id,
                    node_id=submission.node_id,
                    attempt_id=submission.attempt_id,
                    event_seq=seq,
                    level=level,
                    kind=submission.kind,
                    producer=submission.producer,
                    timestamp=submission.observed_at,
                    payload_hash=payload_hash,
                    artifact_refs=submission.artifact_refs,
                    prev_hash=prev_hash,
                )
                chain_hash = self._hasher.hash(record)
                assert_appendable(prev, record, expected_seq=seq)
                stored = StoredRecord(record=record, chain_hash=chain_hash)
                session.insert(stored)
                session.record_ingestion(
                    ingestion_id=ingestion_id,
                    evidence_id=record.evidence_id,
                    received_at=self._clock.now_utc(),
                )
                session.commit()
        except EvidenceStoreError:
            raise
        return EvidenceReceipt(
            evidence_id=record.evidence_id,
            event_seq=seq,
            chain_hash=chain_hash,
            level=level,
            kind=submission.kind,
            ingestion_id=ingestion_id,
            duplicate=False,
        )

    # -- 冲突/拒绝 --------------------------------------------------------
    def _attempt_conflict(
        self,
        submission: EvidenceSubmission,
        payload_hash: str,
    ) -> RejectedSubmission | None:
        """E2 launch/exit 一个 attempt 只能一条；artifact_observed 按 ref 去重。"""
        if submission.level != "E2":
            return None
        page = self._store.query(
            task_id=submission.task_id, node_id=submission.node_id,
            attempt_id=submission.attempt_id, limit=1000,
        )
        same_kind = [r for r in page.records if r.record.kind == submission.kind]
        if submission.kind in ("executor_launch", "executor_process_exit") and same_kind:
            first = same_kind[0]
            if first.record.payload_hash == payload_hash:
                return self._reject(submission, "CONFLICT", "SCHEMA_INVALID",
                                    f"{submission.kind} 已存在且内容相同，但没有同 event_id",
                                    "kind", payload_hash=payload_hash)
            return self._reject(submission, "CONFLICT", "SCHEMA_INVALID",
                                f"{submission.kind} 在一个 attempt 内只能有一条", "kind",
                                payload_hash=payload_hash)
        if submission.kind == "artifact_observed":
            wanted = set(submission.artifact_refs)
            for record in same_kind:
                if set(record.record.artifact_refs) == wanted and wanted:
                    return self._reject(submission, "CONFLICT", "SCHEMA_INVALID",
                                        "同一组 artifact_refs 已观测，但 event_id 不同",
                                        "artifact_refs", payload_hash=payload_hash)
        return None

    def _reject(
        self,
        submission: EvidenceSubmission,
        reason: str,
        error_code: str,
        detail: str,
        field_path: str,
        *,
        payload_hash: str | None = None,
    ) -> RejectedSubmission:
        rejection_id = self._ids.new_rejection_id()
        try:
            with self._store.writer_session(self._permit) as session:
                session.record_rejection(
                    rejection_id=rejection_id,
                    event_id=submission.event_id or "derived",
                    task_id=submission.task_id,
                    node_id=submission.node_id,
                    attempt_id=submission.attempt_id,
                    kind=submission.kind,
                    reason=reason,
                    error_code=error_code,
                    field_path=field_path,
                    payload_hash=payload_hash,
                    detail=detail,
                    received_at=self._clock.now_utc(),
                )
                session.commit()
        except EvidenceStoreError:
            # 拒绝日志写不进去时，仍把拒绝返回给调用方；日志缺口由审计通道处理。
            pass
        return RejectedSubmission(
            reason=reason, error_code=error_code, field_path=field_path,
            detail=detail, rejection_id=rejection_id, retryable=False,
        )

    def _record_delivery(self, ingestion_id: str, evidence_id: str) -> None:
        with self._store.writer_session(self._permit) as session:
            session.record_ingestion(
                ingestion_id=ingestion_id,
                evidence_id=evidence_id,
                received_at=self._clock.now_utc(),
            )
            session.commit()

    def _derive_e2_event_id(self, submission: EvidenceSubmission, payload_hash: str) -> str:
        """E2 内容派生 event_id：同一 attempt/kind/payload 的重复投递稳定同 ID。"""
        seed = {
            "kind": submission.kind,
            "task_id": submission.task_id,
            "node_id": submission.node_id,
            "attempt_id": submission.attempt_id,
            "payload_hash": payload_hash,
        }
        digest = hashlib.sha256(self._canonicalizer.canonical_bytes(seed)).hexdigest()
        return f"e2:{digest}"

    # -- Gate 规则 helper（P5 调用） --------------------------------------
    def gate_gap_view(self, *, task_id: str, node_id: str | None, attempt_id: str | None):
        return gate_view(task_id=task_id, node_id=node_id, attempt_id=attempt_id, journal=self._gaps)


def _artifact_refs_from_payload(payload: Mapping[str, object]) -> tuple[str, ...]:
    """从 M05 的 artifact_observed payload 提取 refs（`artifact://<declared_name>`）。"""
    explicit = payload.get("artifact_refs")
    if isinstance(explicit, list) and all(isinstance(x, str) for x in explicit):
        return tuple(explicit)
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        refs: list[str] = []
        for item in artifacts:
            if isinstance(item, Mapping):
                name = item.get("declared_name")
                if isinstance(name, str) and name:
                    refs.append(f"artifact://{name}")
        return tuple(refs)
    return ()


def _genesis_prev_hash() -> str:
    """OQ-CT-10 未决：只作为**建议值**使用；首条只校形态，不比较全零。"""
    return "0" * 64


def can_satisfy_execution_check(level: str) -> bool:
    """E0/E1 永不满足执行类必检；E2/E3 才有资格（仍要过 Gate 的其他条件）。"""
    if level not in PRODUCER_BY_LEVEL:
        raise ValueError(f"未知证据等级：{level!r}")
    return level in EXECUTION_CRITICAL_LEVELS


def assert_can_satisfy_execution_check(level: str, *, check_id: str) -> None:
    """Gate 必调：E0/E1 顶替执行类必检 → `REQUIRED_EVIDENCE_MISSING`(409)。"""
    if not check_id:
        raise ValueError("check_id 不得为空")
    if not can_satisfy_execution_check(level):
        raise CollectorError(
            "REQUIRED_EVIDENCE_MISSING", "E0_E1_CANNOT_SATISFY_EXECUTION_CHECK",
            f"{level} 不能顶替执行类必检 {check_id!r}", field_path="level", http_status=409,
            detail={"check_id": check_id, "level": level, "min_level": "E2"},
        )


def assert_collector_boundary() -> list[str]:
    """静态检查：Collector 不写状态/审计、不签名、不接收 E3。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("StateMachine", "transition", "audit_log", "sign", "issue_report"):
        if hasattr(module, attr):
            problems.append(f"Collector 暴露禁用名 {attr!r}")
    if hasattr(Collector, "update") or hasattr(Collector, "delete"):
        problems.append("Collector 不得暴露 update/delete")
    if not can_satisfy_execution_check("E2") or can_satisfy_execution_check("E0"):
        problems.append("执行类必检等级集合必须恰为 E2/E3")
    if E0_MARKER not in LEVEL_BY_KIND:
        problems.append("E0 marker 必须是 agent_claim")
    return problems