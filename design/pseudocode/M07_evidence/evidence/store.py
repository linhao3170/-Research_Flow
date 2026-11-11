"""M07 · evidence/store.py — 追加写、按 task/node/attempt/level 查询、冲突保留（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-005（证据可追加/可查）、FR-006（Gate 读取）、06 §1.3
依赖：M02 schema（evidence/evidence_invalidations 只读口径）、M07 chain（StoredRecord/ChainRecord）、SQLite
不变量：evidence 只 INSERT；没有 UPDATE/DELETE/purge API；写入必须持 Collector 许可；
        payload 只存内容寻址 sidecar（DB 只存 payload_hash）；INVALID/CONFLICT 只进 rejection 日志；
        查询按 event_seq 排序，不按 timestamp；查询结果带 has_more，不静默截断
错误码：EVIDENCE_CHAIN_BROKEN / EVENT_SEQ_GAP / EVENT_SEQ_REGRESSION（500）；SCHEMA_INVALID（422）
写入者：**只有 `Collector` 能拿到 `WritePermit` 并打开 `WriterSession`**；Store 自身不主动写
状态：伪代码；DDL/事务属 WP-07；本文件不建库、不执行 SQL、不跑测试

## 单写者怎么在代码里体现

  1. `INSERT INTO evidence` 只出现在 `EVIDENCE_APPEND_SQL`，且只被 `WriterSession.insert()` 使用；
  2. `WriterSession` 不能直接构造；只能由 `EvidenceStore.writer_session(permit)` 在
     `permit.token is _COLLECTOR_TOKEN` 时返回；
  3. `_COLLECTOR_TOKEN` 只由 `collector.py` 通过 `_issue_collector_permit()` 取得；
     其他模块拿到 permit 也打不开写会话（token 不同即拒绝）；
  4. `EvidenceStore` 没有 `update`/`delete`/`purge`/`execute` 公开方法；
  5. `assert_store_boundary()` 做静态检查，负例表逐条断言。

  这是**代码结构 + 静态检查**的双保险，不是密码学边界：能改代码的人当然能改。
  它要防的是“某个组件顺手写证据”，不是防御主机被完全控制（哈希链也不声称做到这点）。

## 冲突记录保留策略

  - `INVALID`（投稿形态/哈希/等级不符）与 `CONFLICT`（同 event_id 不同 payload、
    attempt 级重复）**不进** evidence 表；进 `evidence_ingest_rejections`，只追加。
  - T0 保留策略 `KEEP_ALL`：`purge_after=NULL`，没有删除方法；删除需新 ADR + 审计迁移。
  - 冲突不是证据：Gate 不能把 rejection 行当作“已发生/未发生”的证据；
    它只能用来解释“为什么缺”。缺就是缺，不推断。
  - 重复投递（同 event_id 同 payload）不是冲突：`ingestion_log.delivery_seq += 1`，
    返回既有 evidence_id，不产生第二条逻辑记录。

## 为什么 payload 不入库

  06 §1.3 的 evidence 表只有 `payload_hash`。为了让 L1 能在事后重算 payload_hash，
  Collector 在写库前把规范化 payload 写进内容寻址 sidecar（`payloads/<hash>.json`），
  DB 只存哈希。sidecar 只增不删；读取时重算哈希，不符即 `BUNDLE_TAMPERED`。
  【OQ-P4-09】sidecar 目录布局与证据包导出规则需 WP-07/WP-12 确认。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Iterator, Mapping, Sequence

from .chain import ChainRecord, StoredRecord

__all__ = [
    "COLLECTOR_WRITER",
    "EVIDENCE_APPEND_SQL",
    "RETENTION_POLICY_T0",
    "EvidenceQueryPage",
    "EvidenceStore",
    "EvidenceStoreError",
    "IngestionRecord",
    "PayloadStore",
    "RejectionRecord",
    "WritePermit",
    "WriterSession",
    "assert_store_boundary",
]

COLLECTOR_WRITER: Final[str] = "collector"
RETENTION_POLICY_T0: Final[str] = "KEEP_ALL: evidence and rejections are append-only; purge_after=NULL"

_HASH64 = re.compile(r"^[0-9a-f]{64}$")
_LEVELS: Final[tuple[str, ...]] = ("E0", "E1", "E2", "E3")

EVIDENCE_APPEND_SQL: Final[str] = """
INSERT INTO evidence (
  evidence_id, task_id, node_id, attempt_id, event_seq, level, kind, producer,
  timestamp, payload_hash, artifact_refs, prev_hash, chain_hash
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INGESTION_LOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS ingestion_log (
  ingestion_id  TEXT PRIMARY KEY,
  evidence_id   TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE RESTRICT,
  delivery_seq  INTEGER NOT NULL CHECK (delivery_seq >= 1),
  received_at   TEXT NOT NULL,
  UNIQUE (ingestion_id, delivery_seq)
)
"""

REJECTION_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS evidence_ingest_rejections (
  rejection_id    TEXT PRIMARY KEY,
  event_id        TEXT NOT NULL,
  task_id         TEXT NOT NULL,
  node_id         TEXT NOT NULL,
  attempt_id      TEXT NOT NULL,
  kind            TEXT NOT NULL,
  reason          TEXT NOT NULL CHECK (reason IN ('INVALID','CONFLICT')),
  error_code      TEXT NOT NULL,
  field_path      TEXT NOT NULL,
  payload_hash    TEXT,
  detail          TEXT NOT NULL,
  received_at     TEXT NOT NULL,
  retention_class TEXT NOT NULL DEFAULT 'EVIDENCE_ADJACENT',
  purge_after     TEXT
)
"""

APPEND_ONLY_TRIGGERS: Final[tuple[str, ...]] = (
    "CREATE TRIGGER IF NOT EXISTS ingestion_log_no_update BEFORE UPDATE ON ingestion_log "
    "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: ingestion_log'); END",
    "CREATE TRIGGER IF NOT EXISTS ingestion_log_no_delete BEFORE DELETE ON ingestion_log "
    "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: ingestion_log'); END",
    "CREATE TRIGGER IF NOT EXISTS ingest_rejections_no_update "
    "BEFORE UPDATE ON evidence_ingest_rejections "
    "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence_ingest_rejections'); END",
    "CREATE TRIGGER IF NOT EXISTS ingest_rejections_no_delete "
    "BEFORE DELETE ON evidence_ingest_rejections "
    "BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_TABLE: evidence_ingest_rejections'); END",
)

# 写许可 token：只有 collector.py 通过 _issue_collector_permit 拿到同一对象。
_COLLECTOR_TOKEN: Final[object] = object()


class EvidenceStoreError(RuntimeError):
    """Store/链/序列拒绝；`error_code` 用已注册码，不新造码。"""

    def __init__(
        self,
        error_code: str,
        reason: str,
        message: str,
        *,
        field_path: str = "",
        http_status: int = 500,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.reason = reason
        self.field_path = field_path
        self.http_status = http_status
        self.detail = MappingProxyType(dict(detail or {}))
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


# ---------------------------------------------------------------------------
# 1. 写许可与 token
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WritePermit:
    """打开写会话的许可；`token` 必须是 `_COLLECTOR_TOKEN`。

    该类不导出构造入口；`_issue_collector_permit()` 只供 collector.py 调用。
    """

    writer: str
    token: object

    def __post_init__(self) -> None:
        if self.writer != COLLECTOR_WRITER:
            raise EvidenceStoreError(
                "EVIDENCE_CHAIN_BROKEN", "WRITER_NOT_COLLECTOR",
                f"证据表只允许 Collector 写，实际 writer={self.writer!r}",
                field_path="writer",
            )
        if self.token is not _COLLECTOR_TOKEN:
            raise EvidenceStoreError(
                "EVIDENCE_CHAIN_BROKEN", "WRITE_PERMIT_INVALID",
                "写许可 token 不是 Collector token",
                field_path="writer",
            )


def _issue_collector_permit() -> WritePermit:
    """仅供 collector.py 调用；其他模块调用会被静态检查与负例抓住。"""
    return WritePermit(writer=COLLECTOR_WRITER, token=_COLLECTOR_TOKEN)


# ---------------------------------------------------------------------------
# 2. Payload sidecar
# ---------------------------------------------------------------------------
class PayloadStore:
    """内容寻址 payload 文件库：`<root>/<hash>.json`，只增不删。

    写入：规范化字节 → SHA-256 → 临时文件 → fsync → `os.replace`（已存在则先比对）。
    读取：重算哈希；不符抛 `BUNDLE_TAMPERED`。不做反序列化执行（只 json.loads 数据）。
    """

    def __init__(self, root: Path, *, max_payload_bytes: int = 4 * 1024 * 1024) -> None:
        if not root.is_absolute():
            raise EvidenceStoreError("SCHEMA_INVALID", "PAYLOAD_ROOT_NOT_ABSOLUTE",
                                     "payload 根必须是绝对路径", field_path="payload_root", http_status=422)
        if max_payload_bytes < 1:
            raise ValueError("max_payload_bytes 必须 ≥1")
        self._root = root
        self._max = max_payload_bytes
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, payload_hash: str) -> Path:
        if not _HASH64.match(payload_hash):
            raise EvidenceStoreError("SCHEMA_INVALID", "PAYLOAD_HASH_INVALID",
                                     "payload_hash 必须是 64 位小写十六进制",
                                     field_path="payload_hash", http_status=422)
        return self._root / f"{payload_hash}.json"

    def put(self, canonical_bytes: bytes) -> str:
        if len(canonical_bytes) > self._max:
            raise EvidenceStoreError(
                "RESOURCE_BUDGET_EXCEEDED", "PAYLOAD_TOO_LARGE",
                f"payload {len(canonical_bytes)} > {self._max}",
                field_path="payload", http_status=429, detail={"limit_kind": "payload"},
            )
        digest = hashlib.sha256(canonical_bytes).hexdigest()
        target = self._path_for(digest)
        if target.exists():
            existing = target.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise EvidenceStoreError(
                    "BUNDLE_TAMPERED", "PAYLOAD_HASH_COLLISION",
                    "内容寻址文件已存在但哈希不符", field_path="payload_hash", http_status=422,
                )
            return digest
        fd, tmp_name = tempfile.mkstemp(prefix=".payload-", dir=self._root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(canonical_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return digest

    def get(self, payload_hash: str) -> bytes:
        target = self._path_for(payload_hash)
        if not target.is_file():
            raise EvidenceStoreError("EVIDENCE_REFERENCE_NOT_FOUND", "PAYLOAD_MISSING",
                                     "payload sidecar 不存在", field_path="payload_hash", http_status=422)
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != payload_hash:
            raise EvidenceStoreError("BUNDLE_TAMPERED", "PAYLOAD_HASH_MISMATCH",
                                     "payload sidecar 内容与哈希不符", field_path="payload_hash", http_status=422)
        return data

    def exists(self, payload_hash: str) -> bool:
        return self._path_for(payload_hash).is_file()


# ---------------------------------------------------------------------------
# 3. 行视图
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class IngestionRecord:
    ingestion_id: str
    evidence_id: str
    delivery_seq: int
    received_at: str


@dataclass(frozen=True, slots=True)
class RejectionRecord:
    rejection_id: str
    event_id: str
    task_id: str
    node_id: str
    attempt_id: str
    kind: str
    reason: str
    error_code: str
    field_path: str
    payload_hash: str | None
    detail: str
    received_at: str
    retention_class: str
    purge_after: str | None


@dataclass(frozen=True, slots=True)
class EvidenceQueryPage:
    records: tuple[StoredRecord, ...]
    has_more: bool
    next_after_seq: int


# ---------------------------------------------------------------------------
# 4. 写会话
# ---------------------------------------------------------------------------
class WriterSession:
    """一次写事务；只能由 `EvidenceStore.writer_session()` 构造。

    事务内顺序（Collector 负责）：
      1. `last_record()` 取链尾；
      2. `allocate_seq()` 取下一个 seq（若已有缺口则拒绝）；
      3. 计算 chain_hash、`assert_appendable()`；
      4. `insert()`；
      5. `record_ingestion()`（重复投递时只做这一步，由 Collector 在事务外先判重）。
    """

    def __init__(self, conn: sqlite3.Connection, *, permit: WritePermit) -> None:
        if permit.token is not _COLLECTOR_TOKEN:
            raise EvidenceStoreError("EVIDENCE_CHAIN_BROKEN", "WRITE_PERMIT_INVALID",
                                     "写会话必须持 Collector permit", field_path="writer")
        self._conn = conn
        self._closed = False

    # -- 4.1 读链尾 -------------------------------------------------------
    def last_record(self, task_id: str) -> StoredRecord | None:
        row = self._conn.execute(
            "SELECT evidence_id, task_id, node_id, attempt_id, event_seq, level, kind, producer, "
            "timestamp, payload_hash, artifact_refs, prev_hash, chain_hash "
            "FROM evidence WHERE task_id = ? ORDER BY event_seq DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return None if row is None else _row_to_stored(row)

    def count_and_max_seq(self, task_id: str) -> tuple[int, int]:
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(event_seq), 0) FROM evidence WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row[0]), int(row[1])

    def allocate_seq(self, task_id: str) -> int:
        """分配 `MAX(event_seq)+1`；若已有缺口（count != max）则拒绝续写。

        拒绝续写而不是“填洞”：填洞会让新事件占用历史序号，破坏链的可解释性；
        缺口只能由缺失的真实事件补发（同 event_id 幂等）或由 Gate 判 GAP。
        """
        count, max_seq = self.count_and_max_seq(task_id)
        if count != max_seq:
            raise EvidenceStoreError(
                "EVENT_SEQ_GAP", "SEQ_GAP_BEFORE_APPEND",
                f"task {task_id} 已有缺口：count={count}, max={max_seq}；拒绝在其后追加",
                field_path="event_seq",
                detail={"count": count, "max_seq": max_seq, "missing": max_seq - count},
            )
        return max_seq + 1

    # -- 4.2 写入 ---------------------------------------------------------
    def insert(self, stored: StoredRecord) -> None:
        record = stored.record
        artifacts = json.dumps(list(record.artifact_refs), ensure_ascii=False, separators=(",", ":"))
        try:
            self._conn.execute(
                EVIDENCE_APPEND_SQL,
                (
                    record.evidence_id, record.task_id, record.node_id, record.attempt_id,
                    record.event_seq, record.level, record.kind, record.producer,
                    record.timestamp, record.payload_hash, artifacts,
                    record.prev_hash, stored.chain_hash,
                ),
            )
        except sqlite3.IntegrityError as exc:
            message = str(exc)
            if "evidence.task_id, evidence.event_seq" in message:
                raise EvidenceStoreError(
                    "EVENT_SEQ_REGRESSION", "SEQ_DUPLICATED",
                    f"task {record.task_id} event_seq {record.event_seq} 已存在",
                    field_path="event_seq",
                ) from exc
            if "evidence.evidence_id" in message:
                raise EvidenceStoreError(
                    "EVENT_SEQ_REGRESSION", "EVIDENCE_ID_REUSED",
                    f"evidence_id {record.evidence_id!r} 已存在",
                    field_path="evidence_id",
                ) from exc
            raise EvidenceStoreError(
                "EVIDENCE_CHAIN_BROKEN", "INSERT_REJECTED", message,
                field_path="evidence",
            ) from exc

    def record_ingestion(self, *, ingestion_id: str, evidence_id: str, received_at: str) -> IngestionRecord:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(delivery_seq), 0) FROM ingestion_log WHERE ingestion_id = ?",
            (ingestion_id,),
        ).fetchone()
        next_seq = int(row[0]) + 1
        self._conn.execute(
            "INSERT INTO ingestion_log (ingestion_id, evidence_id, delivery_seq, received_at) "
            "VALUES (?, ?, ?, ?)",
            (ingestion_id, evidence_id, next_seq, received_at),
        )
        return IngestionRecord(ingestion_id, evidence_id, next_seq, received_at)

    def record_rejection(
        self,
        *,
        rejection_id: str,
        event_id: str,
        task_id: str,
        node_id: str,
        attempt_id: str,
        kind: str,
        reason: str,
        error_code: str,
        field_path: str,
        payload_hash: str | None,
        detail: str,
        received_at: str,
    ) -> RejectionRecord:
        if reason not in ("INVALID", "CONFLICT"):
            raise EvidenceStoreError("SCHEMA_INVALID", "REJECTION_REASON_INVALID",
                                     "reason 只允许 INVALID/CONFLICT", field_path="reason", http_status=422)
        self._conn.execute(
            "INSERT INTO evidence_ingest_rejections ("
            "rejection_id, event_id, task_id, node_id, attempt_id, kind, reason, error_code, "
            "field_path, payload_hash, detail, received_at, retention_class, purge_after"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EVIDENCE_ADJACENT', NULL)",
            (rejection_id, event_id, task_id, node_id, attempt_id, kind, reason, error_code,
             field_path, payload_hash, detail, received_at),
        )
        return RejectionRecord(
            rejection_id, event_id, task_id, node_id, attempt_id, kind, reason, error_code,
            field_path, payload_hash, detail, received_at, "EVIDENCE_ADJACENT", None,
        )

    def commit(self) -> None:
        if self._closed:
            raise RuntimeError("writer session 已关闭")
        self._conn.commit()
        self._closed = True

    def rollback(self) -> None:
        if not self._closed:
            self._conn.rollback()
            self._closed = True


# ---------------------------------------------------------------------------
# 5. Store
# ---------------------------------------------------------------------------
class EvidenceStore:
    """证据只读查询 + Collector 专用写会话。

    构造只做 DDL 检查（M07 自有两表）；不创建 evidence 表（属 M02 迁移）。
    读连接 `PRAGMA query_only=ON`；写连接只在 `writer_session()` 内短暂存在。
    """

    def __init__(self, db_path: Path, payloads: PayloadStore) -> None:
        if not db_path.is_absolute():
            raise ValueError("db_path 必须是绝对路径")
        self._db_path = db_path
        self._payloads = payloads

    @property
    def payloads(self) -> PayloadStore:
        return self._payloads

    def install_m07_ddl(self, conn: sqlite3.Connection) -> None:
        """WP-07 迁移调用；只建 M07 自有两表与触发器，不碰 evidence 表结构。"""
        for ddl in (INGESTION_LOG_DDL, REJECTION_DDL, *APPEND_ONLY_TRIGGERS):
            conn.execute(ddl)
        conn.commit()

    @contextmanager
    def writer_session(self, permit: WritePermit) -> Iterator[WriterSession]:
        """打开写事务；permit 不是 Collector token 一律拒绝。"""
        if permit.token is not _COLLECTOR_TOKEN:
            raise EvidenceStoreError("EVIDENCE_CHAIN_BROKEN", "WRITE_PERMIT_INVALID",
                                     "只有 Collector 能打开证据写会话", field_path="writer")
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        session = WriterSession(conn, permit=permit)
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _read_conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        try:
            yield conn
        finally:
            conn.close()

    # -- 5.1 查询 ---------------------------------------------------------
    def get(self, evidence_id: str) -> StoredRecord:
        with self._read_conn() as conn:
            row = conn.execute(
                "SELECT evidence_id, task_id, node_id, attempt_id, event_seq, level, kind, producer, "
                "timestamp, payload_hash, artifact_refs, prev_hash, chain_hash "
                "FROM evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            raise EvidenceStoreError("EVIDENCE_REFERENCE_NOT_FOUND", "EVIDENCE_NOT_FOUND",
                                     f"evidence_id {evidence_id!r} 不存在",
                                     field_path="evidence_id", http_status=422)
        return _row_to_stored(row)

    def query(
        self,
        *,
        task_id: str | None = None,
        node_id: str | None = None,
        attempt_id: str | None = None,
        level: str | None = None,
        after_seq: int = 0,
        limit: int = 1000,
    ) -> EvidenceQueryPage:
        """按 task/node/attempt/level 过滤；按 event_seq 升序；不静默截断。"""
        if level is not None and level not in _LEVELS:
            raise EvidenceStoreError("SCHEMA_INVALID", "LEVEL_INVALID",
                                     f"level 必须是 {_LEVELS}", field_path="level", http_status=422)
        if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
            raise EvidenceStoreError("SCHEMA_INVALID", "AFTER_SEQ_INVALID",
                                     "after_seq 必须是 ≥0 的 integer", field_path="after_seq", http_status=422)
        if not (1 <= limit <= 1000):
            raise EvidenceStoreError("SCHEMA_INVALID", "LIMIT_INVALID",
                                     "limit 必须在 1–1000", field_path="limit", http_status=422)
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (("task_id", task_id), ("node_id", node_id),
                              ("attempt_id", attempt_id), ("level", level)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        clauses.append("event_seq > ?")
        params.append(after_seq)
        where = " AND ".join(clauses)
        sql = (
            "SELECT evidence_id, task_id, node_id, attempt_id, event_seq, level, kind, producer, "
            "timestamp, payload_hash, artifact_refs, prev_hash, chain_hash "
            f"FROM evidence WHERE {where} ORDER BY event_seq ASC LIMIT ?"
        )
        params.append(limit + 1)
        with self._read_conn() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        records = tuple(_row_to_stored(row) for row in page)
        next_seq = records[-1].event_seq if records else after_seq
        return EvidenceQueryPage(records=records, has_more=has_more, next_after_seq=next_seq)

    def iter_task(self, task_id: str) -> Iterator[StoredRecord]:
        """按 event_seq 升序迭代整条任务链；调用方负责验证链。"""
        after = 0
        while True:
            page = self.query(task_id=task_id, after_seq=after, limit=1000)
            yield from page.records
            if not page.has_more:
                break
            after = page.next_after_seq

    def last(self, task_id: str) -> StoredRecord | None:
        with self._read_conn() as conn:
            row = conn.execute(
                "SELECT evidence_id, task_id, node_id, attempt_id, event_seq, level, kind, producer, "
                "timestamp, payload_hash, artifact_refs, prev_hash, chain_hash "
                "FROM evidence WHERE task_id = ? ORDER BY event_seq DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return None if row is None else _row_to_stored(row)

    def count(self, task_id: str) -> int:
        with self._read_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM evidence WHERE task_id = ?", (task_id,)).fetchone()
        return int(row[0])

    def find_ingestion(self, ingestion_id: str) -> IngestionRecord | None:
        with self._read_conn() as conn:
            row = conn.execute(
                "SELECT ingestion_id, evidence_id, delivery_seq, received_at "
                "FROM ingestion_log WHERE ingestion_id = ? ORDER BY delivery_seq DESC LIMIT 1",
                (ingestion_id,),
            ).fetchone()
        if row is None:
            return None
        return IngestionRecord(row["ingestion_id"], row["evidence_id"], row["delivery_seq"], row["received_at"])

    def rejections(
        self,
        *,
        task_id: str | None = None,
        reason: str | None = None,
        limit: int = 1000,
    ) -> tuple[RejectionRecord, ...]:
        """只读冲突日志；T0 `KEEP_ALL`，没有 purge 参数。"""
        if reason is not None and reason not in ("INVALID", "CONFLICT"):
            raise EvidenceStoreError("SCHEMA_INVALID", "REJECTION_REASON_INVALID",
                                     "reason 只允许 INVALID/CONFLICT", field_path="reason", http_status=422)
        clauses: list[str] = []
        params: list[object] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if reason is not None:
            clauses.append("reason = ?")
            params.append(reason)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT rejection_id, event_id, task_id, node_id, attempt_id, kind, reason, error_code, "
            "field_path, payload_hash, detail, received_at, retention_class, purge_after "
            f"FROM evidence_ingest_rejections{where} ORDER BY received_at ASC, rejection_id ASC LIMIT ?"
        )
        params.append(limit)
        with self._read_conn() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return tuple(
            RejectionRecord(
                row["rejection_id"], row["event_id"], row["task_id"], row["node_id"],
                row["attempt_id"], row["kind"], row["reason"], row["error_code"],
                row["field_path"], row["payload_hash"], row["detail"], row["received_at"],
                row["retention_class"], row["purge_after"],
            )
            for row in rows
        )


def _row_to_stored(row: sqlite3.Row | Sequence[object]) -> StoredRecord:
    """DB 行 → StoredRecord；`artifact_refs` 的 NULL 映射为 `()`（前像稳定）。"""
    def get(name: str, index: int) -> object:
        return row[name] if isinstance(row, sqlite3.Row) else row[index]

    raw_artifacts = get("artifact_refs", 10)
    artifacts = tuple(json.loads(raw_artifacts)) if raw_artifacts else ()
    record = ChainRecord(
        schema_version="1.0",
        evidence_id=str(get("evidence_id", 0)),
        task_id=str(get("task_id", 1)),
        node_id=str(get("node_id", 2)),
        attempt_id=str(get("attempt_id", 3)),
        event_seq=int(get("event_seq", 4)),
        level=str(get("level", 5)),
        kind=str(get("kind", 6)),
        producer=str(get("producer", 7)),
        timestamp=str(get("timestamp", 8)),
        payload_hash=str(get("payload_hash", 9)),
        artifact_refs=artifacts,
        prev_hash=str(get("prev_hash", 11)),
    )
    return StoredRecord(record=record, chain_hash=str(get("chain_hash", 12)))


# ---------------------------------------------------------------------------
# 6. 静态边界
# ---------------------------------------------------------------------------
def assert_store_boundary() -> list[str]:
    """静态检查：证据表只有一条 INSERT，且只有 Collector token 能开写会话。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for name in ("update", "delete", "purge", "truncate"):
        if hasattr(EvidenceStore, name):
            problems.append(f"EvidenceStore 不得暴露 {name}()（只追加）")
    if EVIDENCE_APPEND_SQL.count("INSERT INTO evidence") != 1:
        problems.append("EVIDENCE_APPEND_SQL 必须恰好一条 INSERT")
    if "UPDATE evidence" in EVIDENCE_APPEND_SQL or "DELETE FROM evidence" in EVIDENCE_APPEND_SQL:
        problems.append("EVIDENCE_APPEND_SQL 不得包含 UPDATE/DELETE")
    if not RETENTION_POLICY_T0.startswith("KEEP_ALL"):
        problems.append("T0 保留策略必须是 KEEP_ALL")
    if "_issue_collector_permit" in __all__:
        problems.append("_issue_collector_permit 不得导出（只允许 collector.py 私有导入）")
    if "_COLLECTOR_TOKEN" in __all__:
        problems.append("_COLLECTOR_TOKEN 不得导出")
    return problems