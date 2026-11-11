"""M07 · evidence/chain.py — 哈希链公式、前驱传递与断链检测（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-005（E2 可校验）、FR-006（Gate 可判定）、策划书 §7.3
依赖：M01 encoding（JCS canonical_bytes 端口）、M01 errors（EVIDENCE_CHAIN_BROKEN / EVENT_SEQ_GAP / EVENT_SEQ_REGRESSION）
不变量：chain_hash 覆盖除自身外的全部规范化字段；prev_hash == 上一条 chain_hash；event_seq 严格 +1；
        首条 prev_hash 只校形态（OQ-CT-10 未决，不比较全零）；链只提高“可发现篡改”，不声称不可篡改
错误码：EVIDENCE_CHAIN_BROKEN（500）、EVENT_SEQ_GAP（500）、EVENT_SEQ_REGRESSION（500）
写入者：**只读/纯计算**；Collector 调 `compute`/`assert_appendable`，Verifier 调 `verify`
状态：伪代码；链前像为 P4 提案（OQ-P4-02），落地前需 ADR/WP-07 冻结

## 前像（P4 提案，必须逐字节实现）

    projection = {
      schema_version, evidence_id, task_id, node_id, attempt_id, event_seq,
      level, kind, producer, timestamp, payload_hash, artifact_refs, prev_hash
    }
    preimage  = b"RF-EVIDENCE-CHAIN\\x00v1\\x00" || JCS(projection)
    chain_hash = lowercase_hex(SHA-256(preimage))

  - `chain_hash` 自身不进入前像（否则自指）。
  - `artifact_refs` 缺失时规范化为 `[]`，不写 `null`；否则 DB 的 NULL 与内存的 [] 会算出两个哈希。
  - 域分离前缀与 Merkle 的 `0x00/0x01`、签名载荷的域前缀都不同；
    同一个 32 字节不能同时被解释为链哈希与 Merkle 内部节点。
  - `task_id` 在前像里：跨任务重放会改变哈希，不能把 A 任务的链尾接到 B 任务。

## 为什么首条不比较全零

  OQ-CT-10 未决。P1 的 `GENESIS_PREV_HASH_PROPOSED = "0"*64` 只是建议值；
  校验器只校验 `[0-9a-f]{64}` 形态，**不得**因首条不是全零而拒绝。
  第二条及以后必须 `prev_hash == 上一条 chain_hash`，这条与 OQ-CT-10 无关。

## 边界（不得声称“不可篡改”）

  链能发现：中间记录被改、被删、被重排、prev 被改、seq 跳号/回退。
  链**不能**发现：只改最后一条并把它自己的 chain_hash 一起重算——没有后继 prev_hash
  会暴露它。这种情况必须由报告 `evidence_root` / Merkle 根 / 外部锚定发现。
  因此本模块只声明“提高可发现性”，不声明“绝对不可篡改”；负例必须同时覆盖
  “链发现”和“链尾 + 重算后由 Merkle/报告根发现”两种路径。

## 断链检测（读路径）

  `verify()` 按传入顺序检查，不排序：排序会把“存储顺序错乱”掩盖成“正常”。
  检查顺序固定：seq 起点 → seq 严格 +1 → prev 形态/相等 → chain_hash 重算。
  任何一项失败都返回 `ChainVerification(ok=False, reason=...)`，不抛异常；
  追加路径用 `assert_appendable()` 抛 `EvidenceChainError`（fail-closed）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

__all__ = [
    "CHAIN_DOMAIN",
    "CHAIN_HASH_FIELDS",
    "ChainHasher",
    "ChainRecord",
    "ChainVerification",
    "ChainVerifier",
    "EvidenceChainError",
    "StoredRecord",
    "assert_appendable",
    "compute_chain_hash",
    "accept_first_prev_hash",
]

# 域分离：换前缀 = 换协议版本，旧哈希不再通过新校验器（这是有意的）。
CHAIN_DOMAIN: Final[bytes] = b"RF-EVIDENCE-CHAIN\x00v1\x00"

CHAIN_HASH_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "evidence_id",
    "task_id",
    "node_id",
    "attempt_id",
    "event_seq",
    "level",
    "kind",
    "producer",
    "timestamp",
    "payload_hash",
    "artifact_refs",
    "prev_hash",
)

_LEVEL_KINDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    "E0": ("agent_claim",),
    "E1": ("tool_invocation", "harness_trace"),
    "E2": ("executor_launch", "executor_process_exit", "artifact_observed"),
    "E3": ("verifier_recheck",),
})
_PRODUCER_BY_LEVEL: Final[Mapping[str, str]] = MappingProxyType({
    "E0": "collector", "E1": "collector", "E2": "collector", "E3": "verifier",
})

_EVIDENCE_ID = re.compile(r"^ev_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_TASK_ID = re.compile(r"^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ATTEMPT_ID = re.compile(r"^attempt_[0-9]{2,}$")
_HASH64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$")


class CanonicalizerPort(Protocol):
    """M01 `canonical_bytes` 端口；不得用 `json.dumps(sort_keys=True)` 冒名。"""

    def canonical_bytes(self, value: object) -> bytes:
        ...


# ---------------------------------------------------------------------------
# 1. 记录视图
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChainRecord:
    """写入前/写入后的证据字段（不含 chain_hash）。

    `artifact_refs` 用 tuple；DB 里的 NULL 在读回时映射为 `()`，保证前像稳定。
    """

    schema_version: str
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
    artifact_refs: tuple[str, ...]
    prev_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError("schema_version 必须是 1.0")
        for name, pattern in (
            ("evidence_id", _EVIDENCE_ID),
            ("task_id", _TASK_ID),
            ("node_id", _NODE_ID),
            ("attempt_id", _ATTEMPT_ID),
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not pattern.match(value):
                raise ValueError(f"{name} 形态非法：{value!r}")
        if isinstance(self.event_seq, bool) or not isinstance(self.event_seq, int) or self.event_seq < 1:
            raise ValueError("event_seq 必须是 ≥1 的 integer")
        if self.level not in _LEVEL_KINDS:
            raise ValueError(f"level 不在 E0–E3：{self.level!r}")
        if self.kind not in _LEVEL_KINDS[self.level]:
            raise ValueError(f"level={self.level} 不允许 kind={self.kind!r}")
        if self.producer != _PRODUCER_BY_LEVEL[self.level]:
            raise ValueError(
                f"producer 必须是 {_PRODUCER_BY_LEVEL[self.level]!r}（level={self.level}）"
            )
        if not _UTC.match(self.timestamp):
            raise ValueError("timestamp 必须是 UTC RFC 3339（Z 或 +00:00）")
        for name in ("payload_hash", "prev_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HASH64.match(value):
                raise ValueError(f"{name} 必须是 64 位小写十六进制")
        if len(set(self.artifact_refs)) != len(self.artifact_refs):
            raise ValueError("artifact_refs 不得重复")
        for ref in self.artifact_refs:
            if not isinstance(ref, str) or not ref.startswith("artifact://") or len(ref) <= len("artifact://"):
                raise ValueError(f"artifact_ref 形态非法：{ref!r}")

    def projection(self) -> dict[str, object]:
        """前像字段；顺序由 JCS 决定，不依赖本 dict 的插入顺序。"""
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "task_id": self.task_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "event_seq": self.event_seq,
            "level": self.level,
            "kind": self.kind,
            "producer": self.producer,
            "timestamp": self.timestamp,
            "payload_hash": self.payload_hash,
            "artifact_refs": list(self.artifact_refs),
            "prev_hash": self.prev_hash,
        }


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """链上的一条完整记录（ChainRecord + chain_hash）。"""

    record: ChainRecord
    chain_hash: str

    def __post_init__(self) -> None:
        if not _HASH64.match(self.chain_hash):
            raise ValueError("chain_hash 必须是 64 位小写十六进制")

    @property
    def event_seq(self) -> int:
        return self.record.event_seq

    def projection(self) -> dict[str, object]:
        payload = self.record.projection()
        payload["chain_hash"] = self.chain_hash
        return payload


# ---------------------------------------------------------------------------
# 2. 异常与错误码
# ---------------------------------------------------------------------------
class EvidenceChainError(RuntimeError):
    """追加路径的 fail-closed 异常；对外 500（内部码，不进 API 文档）。"""

    def __init__(
        self,
        error_code: str,
        reason: str,
        message: str,
        *,
        field_path: str = "",
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.reason = reason
        self.field_path = field_path
        self.detail = MappingProxyType(dict(detail or {}))
        self.http_status = 500
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


def _chain_error(reason: str, message: str, *, field_path: str, **detail: object) -> EvidenceChainError:
    return EvidenceChainError(
        "EVIDENCE_CHAIN_BROKEN", reason, message, field_path=field_path, detail=detail
    )


# ---------------------------------------------------------------------------
# 3. 哈希计算
# ---------------------------------------------------------------------------
def accept_first_prev_hash(value: str) -> bool:
    """首条 prev_hash 的唯一判定：形态合法即可（OQ-CT-10 未决）。"""
    return isinstance(value, str) and bool(_HASH64.match(value))


def compute_chain_hash(record: ChainRecord, canonicalizer: CanonicalizerPort) -> str:
    """按 §前像 计算 chain_hash。

    规范化只走注入的 M01 实现；本文件不复制 JCS，也不对字段做二次排序/补默认值。
    """
    projection = record.projection()
    if set(projection) != set(CHAIN_HASH_FIELDS):
        raise ValueError(
            f"chain 前像字段漂移：{sorted(set(projection) ^ set(CHAIN_HASH_FIELDS))}"
        )
    canonical = canonicalizer.canonical_bytes(projection)
    return hashlib.sha256(CHAIN_DOMAIN + canonical).hexdigest()


class ChainHasher:
    """有状态的薄包装：只持有 canonicalizer；不缓存、不续写。"""

    def __init__(self, canonicalizer: CanonicalizerPort) -> None:
        self._canonicalizer = canonicalizer

    def hash(self, record: ChainRecord) -> str:
        return compute_chain_hash(record, self._canonicalizer)


# ---------------------------------------------------------------------------
# 4. 追加守卫
# ---------------------------------------------------------------------------
def assert_appendable(
    prev: StoredRecord | None,
    new: ChainRecord,
    *,
    expected_seq: int | None = None,
) -> None:
    """追加前校验：seq、任务、prev_hash、evidence_id 不复用。

    调用方（Collector）必须在同一写事务里持有链尾；本函数不查库、不加锁。
    错误码：
      - seq 不是 1 / 不连续 → `EVENT_SEQ_GAP`
      - seq 回退/重复 → `EVENT_SEQ_REGRESSION`
      - prev_hash 不匹配 → `EVIDENCE_CHAIN_BROKEN`
    """
    if prev is None:
        if new.event_seq != 1:
            raise EvidenceChainError(
                "EVENT_SEQ_GAP", "FIRST_SEQ_NOT_ONE",
                f"首条 event_seq 必须是 1，实际 {new.event_seq}",
                field_path="event_seq", detail={"expected": 1, "actual": new.event_seq},
            )
        if not accept_first_prev_hash(new.prev_hash):
            raise _chain_error(
                "PREV_HASH_INVALID", "首条 prev_hash 形态非法", field_path="prev_hash"
            )
        return

    if new.event_seq == prev.event_seq:
        raise EvidenceChainError(
            "EVENT_SEQ_REGRESSION", "SEQ_DUPLICATED",
            f"event_seq {new.event_seq} 已被占用",
            field_path="event_seq", detail={"previous": prev.event_seq, "actual": new.event_seq},
        )
    if new.event_seq < prev.event_seq:
        raise EvidenceChainError(
            "EVENT_SEQ_REGRESSION", "SEQ_REGRESSION",
            f"event_seq 回退：{prev.event_seq} → {new.event_seq}",
            field_path="event_seq", detail={"previous": prev.event_seq, "actual": new.event_seq},
        )
    if new.event_seq != prev.event_seq + 1:
        raise EvidenceChainError(
            "EVENT_SEQ_GAP", "SEQ_GAP",
            f"event_seq 跳号：期望 {prev.event_seq + 1}，实际 {new.event_seq}",
            field_path="event_seq",
            detail={"expected": prev.event_seq + 1, "actual": new.event_seq,
                    "missing": new.event_seq - prev.event_seq - 1},
        )
    if expected_seq is not None and new.event_seq != expected_seq:
        raise EvidenceChainError(
            "EVENT_SEQ_GAP", "SEQ_NOT_ALLOCATED",
            f"event_seq {new.event_seq} 与分配器期望 {expected_seq} 不一致",
            field_path="event_seq", detail={"expected": expected_seq, "actual": new.event_seq},
        )
    if new.task_id != prev.record.task_id:
        raise _chain_error(
            "TASK_MISMATCH", "同一条链不得跨 task", field_path="task_id",
            expected=prev.record.task_id, actual=new.task_id,
        )
    if new.evidence_id == prev.record.evidence_id:
        raise EvidenceChainError(
            "EVENT_SEQ_REGRESSION", "EVIDENCE_ID_REUSED",
            f"evidence_id {new.evidence_id!r} 已存在",
            field_path="evidence_id",
        )
    if new.prev_hash != prev.chain_hash:
        raise _chain_error(
            "PREV_HASH_MISMATCH",
            "prev_hash 不等于上一条 chain_hash",
            field_path="prev_hash",
            expected=prev.chain_hash, actual=new.prev_hash,
        )


# ---------------------------------------------------------------------------
# 5. 读路径校验
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChainVerification:
    """校验结果；`ok=False` 时 reason 必须可断言。"""

    ok: bool
    checked: int
    first_seq: int
    last_seq: int
    broken_at_seq: int | None = None
    reason: str = ""
    expected: str = ""
    actual: str = ""
    detail: Mapping[str, object] = MappingProxyType({})


class ChainVerifier:
    """按存储顺序重算整条链；不排序、不跳过、不“修复”。"""

    def __init__(self, canonicalizer: CanonicalizerPort) -> None:
        self._canonicalizer = canonicalizer

    def verify(self, records: Sequence[StoredRecord]) -> ChainVerification:
        """逐条重算；第一条的 prev 只校形态（OQ-CT-10）。"""
        if not records:
            return ChainVerification(True, 0, 0, 0)

        first = records[0]
        if first.event_seq != 1:
            return ChainVerification(
                False, 0, first.event_seq, first.event_seq, first.event_seq,
                "FIRST_SEQ_NOT_ONE", "1", str(first.event_seq),
            )
        if not accept_first_prev_hash(first.record.prev_hash):
            return ChainVerification(
                False, 0, 1, 1, 1, "PREV_HASH_INVALID", "64-hex", first.record.prev_hash,
            )
        expected_prev = first.record.prev_hash
        checked = 0
        for index, stored in enumerate(records):
            seq = stored.event_seq
            expected_seq = index + 1
            if seq != expected_seq:
                reason = "SEQ_REGRESSION" if seq < expected_seq else "SEQ_GAP"
                code = "EVENT_SEQ_REGRESSION" if seq < expected_seq else "EVENT_SEQ_GAP"
                return ChainVerification(
                    False, checked, 1, records[-1].event_seq, seq, reason,
                    str(expected_seq), str(seq),
                    MappingProxyType({"error_code": code, "missing": max(0, seq - expected_seq)}),
                )
            if stored.record.prev_hash != expected_prev:
                return ChainVerification(
                    False, checked, 1, records[-1].event_seq, seq, "PREV_HASH_MISMATCH",
                    expected_prev, stored.record.prev_hash,
                    MappingProxyType({"error_code": "EVIDENCE_CHAIN_BROKEN"}),
                )
            recomputed = compute_chain_hash(stored.record, self._canonicalizer)
            if recomputed != stored.chain_hash:
                return ChainVerification(
                    False, checked, 1, records[-1].event_seq, seq, "CHAIN_HASH_MISMATCH",
                    recomputed, stored.chain_hash,
                    MappingProxyType({"error_code": "EVIDENCE_CHAIN_BROKEN"}),
                )
            expected_prev = stored.chain_hash
            checked += 1
        return ChainVerification(True, checked, 1, records[-1].event_seq)


def verify_chain(records: Sequence[StoredRecord], canonicalizer: CanonicalizerPort) -> ChainVerification:
    """模块级便捷函数；行为与 `ChainVerifier.verify` 完全一致。"""
    return ChainVerifier(canonicalizer).verify(records)