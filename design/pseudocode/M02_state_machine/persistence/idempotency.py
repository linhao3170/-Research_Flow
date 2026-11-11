"""M02 · persistence/idempotency.py — 幂等键、规范化请求哈希与冲突判定（P2 伪代码）。

阶段：P2｜状态：存储形态、哈希口径、冲突/重放判定与并发顺序；**不执行 SQL、不建库**。
规范来源：`docs/design/06_DATA_AND_API.md` §4.5、附录 E.4（P0626–P0630）；
`design/pseudocode/00_BASELINE/ENCODING_RULES.md` §5（JCS）；
`M01_contracts/contracts/errors.py`（`IDEMPOTENCY_CONFLICT` 409 / `SCHEMA_INVALID` 422）。

三条硬规则：
  1. **同键同体 → 重放**：返回原任务（HTTP 201），不新建任务、不新增幂等行。
  2. **同键异体 → 409 `IDEMPOTENCY_CONFLICT`**：不得覆盖旧哈希、不得返回旧任务。
  3. 幂等行与任务行**同事务**插入（06 §2）；任务插入失败 → 幂等行一起回滚，不留孤儿键。

哈希口径：
  - `request_hash = sha256(JCS(原始请求体))`，**不是** `json.dumps(..., sort_keys=True)`；
    JCS 只排对象键（UTF-16 码元序），不排数组（ENCODING_RULES §5）。
  - 哈希对象是“严格解析后、模型默认值注入前”的请求体；同一语义的不同键顺序必须同哈希。
  - 只哈希请求体，不哈希 `Idempotency-Key` 头、路径、查询串或认证信息。
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Mapping

__all__ = [
    "IDEMPOTENCY_KEY_MAX_LEN",
    "IDEMPOTENCY_KEY_PATTERN",
    "RETENTION_POLICY",
    "IdempotencyConflict",
    "IdempotencyDecision",
    "IdempotencyOutcome",
    "IdempotencyRecord",
    "IdempotencyRecordCorrupt",
    "IdempotencyStore",
    "InvalidIdempotencyKey",
    "assert_idempotency_contract",
    "canonical_request_hash",
    "validate_idempotency_key",
]

IDEMPOTENCY_KEY_MAX_LEN: Final[int] = 255
# 06 未冻结幂等键字符集；P2 取“可见 ASCII、无空白”。
IDEMPOTENCY_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[\x21-\x7E]{1,255}$")

RETENTION_POLICY: Final[tuple[str, ...]] = (
    "OQ-DB-2 开放：保留期与清理策略未定。",
    "T0 建议保留至任务进入终态（COMPLETED/FAILED/BLOCKED/CANCELLED）后再归档。",
    "归档不得复用旧键；不得把旧键指向新任务。",
    "M02 不实现 DELETE；清理走后续迁移/归档脚本，且需单独审批。",
)


class IdempotencyDecision(StrEnum):
    ABSENT = "ABSENT"        # 没有幂等键：每次创建新任务
    RESERVED = "RESERVED"    # 新建幂等行，任务可提交
    REPLAY = "REPLAY"        # 同键同体：返回原任务
    CONFLICT = "CONFLICT"    # 同键异体：409


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    idem_key: str
    request_hash: str
    task_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class IdempotencyOutcome:
    decision: IdempotencyDecision
    key: str | None
    request_hash: str
    task_id: str | None
    http_status: int
    error_code: str | None
    reason: str | None = None
    existing_task_id: str | None = None


class IdempotencyConflict(RuntimeError):
    """同键异体；HTTP 409。"""

    error_code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    reason = "SAME_KEY_DIFFERENT_BODY"

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            "相同 Idempotency-Key 对应了不同的规范化请求体；"
            "不得覆盖旧哈希，也不得返回旧任务"
        )


class InvalidIdempotencyKey(ValueError):
    """幂等键缺失以外的非法形态；HTTP 422。"""

    error_code = "SCHEMA_INVALID"
    http_status = 422
    field_path = "Idempotency-Key"

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            "Idempotency-Key 必须是 1–255 个可见 ASCII 字符且不含空白"
        )


class IdempotencyRecordCorrupt(RuntimeError):
    """幂等行存在但任务行不存在（不应发生；fail-closed）。"""

    error_code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    reason = "IDEMPOTENCY_TASK_MISSING"


# ---------------------------------------------------------------------------
# 1. 规范化请求哈希
# ---------------------------------------------------------------------------
def _contains_non_finite(value: Any) -> bool:
    """纵深防御：解析层已拒绝 NaN/Infinity；这里不替代解析层。"""
    if isinstance(value, float):
        return value != value or value in (float("inf"), float("-inf"))
    if isinstance(value, Mapping):
        return any(_contains_non_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite(v) for v in value)
    return False


def canonical_request_hash(payload: Mapping[str, Any]) -> str:
    """`sha256(JCS(payload))`，64 位小写十六进制。

    实现要求（P2 不执行）：
      - 调用 `contracts/encoding.canonical_bytes()`（RFC 8785 JCS）；
      - 再调用 `contracts/encoding.hash_bytes()`；不得自行 `json.dumps`；
      - 输入必须是严格解析后的 JSON 对象；数组保序；对象键重复在解析层已拒绝；
      - `payload` 不得含 NaN/Infinity；非有限数一律拒绝，不得静默转 null。
    """
    if not isinstance(payload, Mapping):
        raise ValueError("幂等哈希只接受 JSON 对象")
    if _contains_non_finite(payload):
        raise ValueError("请求体含非有限数，拒绝计算幂等哈希")
    raise NotImplementedError("P2 伪代码：canonical_request_hash 由 WP-02/WP-03 实现")


# ---------------------------------------------------------------------------
# 2. 键校验与判定
# ---------------------------------------------------------------------------
def validate_idempotency_key(key: str | None) -> str | None:
    """`None` 表示未提供；空串/空白/超长/不可见字符 → 422。"""
    if key is None:
        return None
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise InvalidIdempotencyKey(key)
    return key


def _replay(record: IdempotencyRecord) -> IdempotencyOutcome:
    return IdempotencyOutcome(
        decision=IdempotencyDecision.REPLAY,
        key=record.idem_key,
        request_hash=record.request_hash,
        task_id=record.task_id,
        existing_task_id=record.task_id,
        http_status=201,
        error_code=None,
        reason="SAME_KEY_SAME_BODY",
    )


def _conflict(key: str, request_hash: str) -> IdempotencyOutcome:
    return IdempotencyOutcome(
        decision=IdempotencyDecision.CONFLICT,
        key=key,
        request_hash=request_hash,
        task_id=None,
        http_status=409,
        error_code="IDEMPOTENCY_CONFLICT",
        reason="SAME_KEY_DIFFERENT_BODY",
    )


class IdempotencyStore:
    """`idempotency_keys` 的查询/插入；不提供 UPDATE/DELETE。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- 读 ---------------------------------------------------------------
    def lookup(self, key: str | None, request_hash: str) -> IdempotencyOutcome:
        """快速路径：ABSENT / REPLAY / CONFLICT。不插入。"""
        key = validate_idempotency_key(key)
        if key is None:
            return IdempotencyOutcome(
                decision=IdempotencyDecision.ABSENT,
                key=None,
                request_hash=request_hash,
                task_id=None,
                http_status=201,
                error_code=None,
                reason="NO_IDEMPOTENCY_KEY",
            )
        row = self._select(key)
        if row is None:
            return IdempotencyOutcome(
                decision=IdempotencyDecision.ABSENT,
                key=key,
                request_hash=request_hash,
                task_id=None,
                http_status=201,
                error_code=None,
                reason="KEY_NOT_SEEN",
            )
        if row.request_hash == request_hash:
            return _replay(row)
        return _conflict(key, request_hash)

    # -- 写（与任务创建同事务） -------------------------------------------
    def reserve(
        self,
        *,
        key: str,
        request_hash: str,
        task_id: str,
        created_at: str,
    ) -> IdempotencyOutcome:
        """在任务创建事务内插入幂等行。

        调用顺序（必须）：
          1. `BEGIN IMMEDIATE`；
          2. `INSERT INTO tasks (... state='CREATED')`；
          3. `reserve(...)`；
          4. RESERVED → COMMIT；REPLAY/CONFLICT → ROLLBACK（丢弃刚插入的任务行）。

        返回 REPLAY/CONFLICT 时，调用方必须回滚，**不得**提交新任务。
        """
        key = validate_idempotency_key(key)
        if key is None:
            raise ValueError("reserve 不接受 None key；无幂等键时不要调用")
        existing = self._select(key)
        if existing is not None:
            if existing.request_hash == request_hash:
                return _replay(existing)
            return _conflict(key, request_hash)
        try:
            self._insert(
                IdempotencyRecord(
                    idem_key=key,
                    request_hash=request_hash,
                    task_id=task_id,
                    created_at=created_at,
                )
            )
        except sqlite3.IntegrityError:
            # 并发：另一个事务已插入同键。不要覆盖；回读后按同体/异体判定。
            winner = self._select(key)
            if winner is None:
                raise IdempotencyRecordCorrupt(
                    "幂等键插入冲突后回读不到记录；拒绝继续"
                )
            if winner.request_hash == request_hash:
                return _replay(winner)
            return _conflict(key, request_hash)
        return IdempotencyOutcome(
            decision=IdempotencyDecision.RESERVED,
            key=key,
            request_hash=request_hash,
            task_id=task_id,
            http_status=201,
            error_code=None,
            reason="NEW_KEY",
        )

    # -- SQL 骨架（不实现） -----------------------------------------------
    def _select(self, key: str) -> IdempotencyRecord | None:
        raise NotImplementedError("P2 伪代码：IdempotencyStore._select")

    def _insert(self, record: IdempotencyRecord) -> None:
        raise NotImplementedError("P2 伪代码：IdempotencyStore._insert")


# ---------------------------------------------------------------------------
# 3. 并发语义（写进常量，供测试逐条断言）
# ---------------------------------------------------------------------------
CONCURRENCY_RULES: Final[tuple[str, ...]] = (
    "同键同体并发：两个请求都 ABSENT；各自插任务；先 reserve 成功者提交，"
    "后 reserve 冲突者回滚并回读 → REPLAY，返回同一 task_id；tasks 只多一行。",
    "同键异体并发：先提交者 201；后者 reserve 冲突 → 回滚并回读 → 409 "
    "IDEMPOTENCY_CONFLICT；tasks 只多一行。",
    "不得用 INSERT OR REPLACE 覆盖 request_hash；不得把旧 task_id 返回给新请求体。",
    "任务插入失败：幂等行与任务行同事务回滚，键可被下一次请求重新占用（同体/异体按当时哈希判定）。",
    "hash 冲突（SHA-256 碰撞）不在 T0 处理范围；比较必须用完整 64 位十六进制，不得截断。",
)


# ---------------------------------------------------------------------------
# 4. 自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
def assert_idempotency_contract() -> list[str]:
    problems: list[str] = []
    if IDEMPOTENCY_KEY_PATTERN.pattern != r"^[\x21-\x7E]{1,255}$":
        problems.append("幂等键正则被改动；需先更新 06 §4.5 口径")
    if not RETENTION_POLICY:
        problems.append("保留期策略不能为空（即使未决也要写明）")
    if not CONCURRENCY_RULES:
        problems.append("并发规则不能为空")
    if "JCS" not in " ".join(CONCURRENCY_RULES) and "JCS" not in canonical_request_hash.__doc__:
        problems.append("幂等哈希口径必须写明 JCS")
    if IdempotencyConflict.http_status != 409:
        problems.append("IDEMPOTENCY_CONFLICT 必须是 409")
    if IdempotencyConflict.error_code != "IDEMPOTENCY_CONFLICT":
        problems.append("IDEMPOTENCY_CONFLICT 错误码名不得改写")
    return problems