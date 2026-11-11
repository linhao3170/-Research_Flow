"""M07 · evidence/gaps.py — 事件缺口标记、乱序缓冲与“不补造”路径（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-005（缺口可发现）、FR-006（Gate 读取缺口）、05 §4.3/§13
依赖：M07 store（只读查询/缺口日志端口）、M07 chain（seq 连续性）、M01 clock（端口注入）
不变量：event_seq 由 Collector 按入队顺序分配，成功追加不产生缺口；source_seq 乱序只缓冲有限窗口；
        缺口出现时写 `evidence_gap` 行（OPEN），**不生成占位证据、不推断缺失值**；
        迟到事件按正常追加，另写 FILLED 行引用真实 evidence_id；缺口历史不删不改
错误码：EVENT_SEQ_GAP（500，链缺口）、EVIDENCE_CHAIN_BROKEN（500，链不可续写）
写入者：**GapJournal** 由 Collector 调用的缺口日志写入；本文件不写 evidence 表
状态：伪代码；缓冲区只在内存，崩溃后靠 seq 与 store 重建缺口；不跑测试、不建表

## 两种 seq，不能混

  - `event_seq`：Collector 的证据链序号，单写队列内单调 +1；**成功写入不会跳号**。
    读路径发现跳号 = 数据缺失/被删/被篡改，记 `CHAIN_SEQ_GAP`，不可用推断补齐。
  - `source_seq`：生产方（Harness session、Executor attempt）自己的序号，可能乱序/丢失。
    只在声明了 `source_seq` 的流上做乱序缓冲；缺口是“生产方少发了”，不是“Collector 改号”。

## 缺口记录的字段（Gate 只读这些字段）

    gap_id, task_id, node_id, attempt_id, stream,
    first_missing_source_seq, last_missing_source_seq, missing_count,
    detection (REORDER_TIMEOUT / WINDOW_OVERFLOW / CHAIN_SEQ_JUMP / ATTEMPT_INCOMPLETE),
    detected_at, status (OPEN / FILLED), fill_evidence_ids, note

  `missing_count` 是**声明**的缺失条数，不是“推断出的内容”。
  `fill_evidence_ids` 只放真实追加的 evidence_id；没有真实事件就保持空。

## Gate 怎么读（P5 实现，这里只给视图）

  - 有任何 `OPEN` 缺口 → 该 task/node/attempt 的必检项不能 PASS；
  - 缺口范围内的值一律视为“未知”，不得用 0、默认值、相邻值或模型输出补齐；
  - `FILLED` 只说明“后来收到了真实事件”，不改变历史缺口存在过的事实；
  - 缺口不是证据：不能拿 `evidence_gap` 行去满足任何 required_check。

## 丢事件的处理路径（不补造）

  1. 事件没到 → 缓冲窗口到期/溢出 → 写 OPEN gap；
  2. 之后真实事件到达（同 event_id 幂等）→ 正常追加 → 写 FILLED 行引用该 evidence_id；
  3. 永远不到 → OPEN 保持；Gate 判 GAP/缺必检；任务不得 VERIFIED；
  4. 绝不生成 `placeholder`/`synthetic`/`inferred` 证据；静态检查禁止这些词进入写入路径。

## 接线边界（P4 只定义，不假装已接）

  - E2（launch/exit/artifact）不使用 source_seq 缓冲：一个 attempt 的完整性由
    “launch 与 exit 是否都存在”判定（ATTEMPT_INCOMPLETE），不是靠数字序号；
  - E1/Harness 的乱序缓冲在 P10/T2 的 ingress 适配器接线：`ReorderBuffer.submit()`
    返回可追加项，缓冲项不返回 receipt，避免调用方误以为已落库；
  - P4 的 Collector 只提供 `gate_gap_view()` 读缺口；不会把缺口当证据，也不会把
    缓冲项提前写成 evidence。未接线的部分必须在 MODULE 的“本阶段不做”中明说。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, Sequence

__all__ = [
    "EVIDENCE_GAP_FIELDS",
    "EVENT_GAP_MARKER",
    "GapDetection",
    "GapJournalPort",
    "GapPolicy",
    "GateGapView",
    "ReorderBuffer",
    "SubmitResult",
    "EvidenceGap",
    "assert_gap_boundary",
    "attempt_incomplete_gap",
    "detect_chain_seq_gap",
]

EVENT_GAP_MARKER: Final[str] = "evidence_gap"

EVIDENCE_GAP_FIELDS: Final[tuple[str, ...]] = (
    "marker",
    "gap_id",
    "task_id",
    "node_id",
    "attempt_id",
    "stream",
    "first_missing_source_seq",
    "last_missing_source_seq",
    "missing_count",
    "detection",
    "detected_at",
    "status",
    "fill_evidence_ids",
    "note",
)

_GAP_ID = re.compile(r"^gap_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class GapDetection(StrEnum):
    REORDER_TIMEOUT = "REORDER_TIMEOUT"
    WINDOW_OVERFLOW = "WINDOW_OVERFLOW"
    CHAIN_SEQ_JUMP = "CHAIN_SEQ_JUMP"
    ATTEMPT_INCOMPLETE = "ATTEMPT_INCOMPLETE"


class GapStatus(StrEnum):
    OPEN = "OPEN"
    FILLED = "FILLED"


class ClockPort(Protocol):
    def now_utc(self) -> str:
        ...


class GapJournalPort(Protocol):
    """缺口日志端口；只追加 OPEN/FILLED 行，不更新历史行。"""

    def append_open(self, gap: "EvidenceGap") -> None:
        ...

    def append_fill(self, gap_id: str, *, filled_at: str, evidence_ids: Sequence[str]) -> None:
        ...

    def open_gaps(
        self,
        *,
        task_id: str,
        node_id: str | None = None,
        attempt_id: str | None = None,
    ) -> tuple["EvidenceGap", ...]:
        ...


@dataclass(frozen=True, slots=True)
class GapPolicy:
    """非契约常量（OQ-P4-11）；不得写成验收阈值。"""

    max_reorder: int = 64
    max_wait_sec: int = 5
    max_gap_span: int = 1024
    first_expected_source_seq: int = 1

    def __post_init__(self) -> None:
        if self.max_reorder < 1 or self.max_wait_sec < 1 or self.max_gap_span < 1:
            raise ValueError("缓冲/等待/跨度上限必须 ≥1")
        if self.first_expected_source_seq < 0:
            raise ValueError("first_expected_source_seq 不得为负")


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    """一条缺口声明。`status` 是快照；FILLED 通过追加新行表达，不 UPDATE。"""

    gap_id: str
    task_id: str
    node_id: str
    attempt_id: str
    stream: str
    first_missing_source_seq: int
    last_missing_source_seq: int
    missing_count: int
    detection: GapDetection
    detected_at: str
    status: GapStatus = GapStatus.OPEN
    fill_evidence_ids: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if not _GAP_ID.match(self.gap_id):
            raise ValueError(f"gap_id 形态非法：{self.gap_id!r}")
        if self.first_missing_source_seq < 0 or self.last_missing_source_seq < self.first_missing_source_seq:
            raise ValueError("缺口范围非法")
        if self.missing_count != self.last_missing_source_seq - self.first_missing_source_seq + 1:
            raise ValueError("missing_count 必须等于范围长度（声明值，不得推断）")
        if self.status is GapStatus.OPEN and self.fill_evidence_ids:
            raise ValueError("OPEN 缺口不得带 fill_evidence_ids")
        if any(not eid.startswith("ev_") for eid in self.fill_evidence_ids):
            raise ValueError("fill_evidence_ids 必须是真实 evidence_id")

    @property
    def covers_source_seq(self) -> tuple[int, int]:
        return (self.first_missing_source_seq, self.last_missing_source_seq)

    def as_dict(self) -> dict[str, object]:
        return {
            "marker": EVENT_GAP_MARKER,
            "gap_id": self.gap_id,
            "task_id": self.task_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "stream": self.stream,
            "first_missing_source_seq": self.first_missing_source_seq,
            "last_missing_source_seq": self.last_missing_source_seq,
            "missing_count": self.missing_count,
            "detection": self.detection.value,
            "detected_at": self.detected_at,
            "status": self.status.value,
            "fill_evidence_ids": list(self.fill_evidence_ids),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class SubmitResult:
    """一次乱序提交的处理结果：哪些可以按序追加、哪些缺口被声明。"""

    emitted: tuple[object, ...]
    gaps: tuple[EvidenceGap, ...]
    duplicate: bool = False
    buffered: bool = False


class ReorderBuffer:
    """有限窗口的乱序缓冲；每个流一个实例（task/node/attempt/stream）。

    只接受 `source_seq` 非负整数的条目；`event_seq` 不在这里分配。
    `flush_expired(now_epoch)` 由 Collector 的定时器调用；`close()` 在 attempt 结束时调用。
    """

    def __init__(
        self,
        *,
        task_id: str,
        node_id: str,
        attempt_id: str,
        stream: str,
        journal: GapJournalPort,
        clock: ClockPort,
        policy: GapPolicy | None = None,
        gap_id_factory: "GapIdFactory | None" = None,
    ) -> None:
        self._task_id = task_id
        self._node_id = node_id
        self._attempt_id = attempt_id
        self._stream = stream
        self._journal = journal
        self._clock = clock
        self._policy = policy or GapPolicy()
        self._gap_id_factory = gap_id_factory or GapIdFactory()
        self._expected = self._policy.first_expected_source_seq
        self._buffer: dict[int, tuple[object, float]] = {}
        self._open_gaps: list[EvidenceGap] = []
        self._recent_gaps: list[EvidenceGap] = []

    @property
    def expected(self) -> int:
        return self._expected

    def submit(self, source_seq: int, item: object, *, now_epoch: float) -> SubmitResult:
        """提交一个源序号。

        - `seq == expected`：立即发出，并排空后续连续项；
        - `seq < expected`：重复（幂等），不产生第二条；
        - `seq > expected`：入缓冲；窗口满/等待超时 → 声明缺口并发出；
        - 不合法 seq（bool/负/非 int）→ `ValueError`，不静默丢弃。
        """
        if isinstance(source_seq, bool) or not isinstance(source_seq, int) or source_seq < 0:
            raise ValueError(f"source_seq 必须是非负 integer，实际 {source_seq!r}")
        if source_seq < self._expected:
            return SubmitResult(emitted=(), gaps=(), duplicate=True)

        if source_seq == self._expected:
            emitted: list[object] = [item]
            self._expected += 1
            emitted.extend(self._drain())
            return SubmitResult(emitted=tuple(emitted), gaps=tuple(self._take_gaps()))

        self._buffer[source_seq] = (item, now_epoch)
        if len(self._buffer) >= self._policy.max_reorder:
            gaps = self._declare_missing(
                self._expected, max(self._buffer), GapDetection.WINDOW_OVERFLOW
            )
            emitted = self._drain_all_buffered()
            return SubmitResult(emitted=tuple(emitted), gaps=tuple(gaps + self._take_gaps()))
        return SubmitResult(emitted=(), gaps=(), buffered=True)

    def flush_expired(self, *, now_epoch: float) -> SubmitResult:
        """等待超过 `max_wait_sec` 的缓冲项：声明缺口并发出，不无限等。"""
        if not self._buffer:
            return SubmitResult(emitted=(), gaps=())
        oldest_seq = min(self._buffer)
        oldest_at = self._buffer[oldest_seq][1]
        if now_epoch - oldest_at < self._policy.max_wait_sec:
            return SubmitResult(emitted=(), gaps=())
        gaps = self._declare_missing(
            self._expected, max(self._buffer), GapDetection.REORDER_TIMEOUT
        )
        emitted = self._drain_all_buffered()
        return SubmitResult(emitted=tuple(emitted), gaps=tuple(gaps + self._take_gaps()))

    def close(self, *, now_epoch: float) -> SubmitResult:
        """关闭流：缓冲里仍缺的序号全部声明为缺口；已到的项按序发出。"""
        if not self._buffer:
            return SubmitResult(emitted=(), gaps=())
        last = max(self._buffer)
        gaps = self._declare_missing(self._expected, last, GapDetection.REORDER_TIMEOUT)
        emitted = self._drain_all_buffered()
        return SubmitResult(emitted=tuple(emitted), gaps=tuple(gaps + self._take_gaps()))

    def fill_late(self, source_seq: int, evidence_id: str, *, filled_at: str) -> tuple[EvidenceGap, ...]:
        """迟到事件真实到达：对覆盖它的 OPEN 缺口追加 FILLED 行（引用真实 evidence_id）。"""
        if not evidence_id.startswith("ev_"):
            raise ValueError("迟到事件必须带真实 evidence_id")
        filled: list[EvidenceGap] = []
        remaining: list[EvidenceGap] = []
        for gap in self._open_gaps:
            if gap.first_missing_source_seq <= source_seq <= gap.last_missing_source_seq:
                self._journal.append_fill(gap.gap_id, filled_at=filled_at, evidence_ids=(evidence_id,))
                filled.append(EvidenceGap(
                    gap_id=gap.gap_id, task_id=gap.task_id, node_id=gap.node_id,
                    attempt_id=gap.attempt_id, stream=gap.stream,
                    first_missing_source_seq=gap.first_missing_source_seq,
                    last_missing_source_seq=gap.last_missing_source_seq,
                    missing_count=gap.missing_count, detection=gap.detection,
                    detected_at=gap.detected_at, status=GapStatus.FILLED,
                    fill_evidence_ids=(evidence_id,), note="late arrival",
                ))
            else:
                remaining.append(gap)
        self._open_gaps = remaining
        return tuple(filled)

    def open_gaps(self) -> tuple[EvidenceGap, ...]:
        return tuple(self._open_gaps)

    # -- 内部 -------------------------------------------------------------
    def _drain(self) -> list[object]:
        emitted: list[object] = []
        while self._expected in self._buffer:
            item, _ = self._buffer.pop(self._expected)
            emitted.append(item)
            self._expected += 1
        return emitted

    def _drain_all_buffered(self) -> list[object]:
        """按 seq 升序发出所有已缓冲项；缺失 seq 已由 `_declare_missing` 记录，不造占位项。"""
        emitted: list[object] = []
        for seq in sorted(self._buffer):
            if seq < self._expected:
                continue
            item, _ = self._buffer.pop(seq)
            emitted.append(item)
            self._expected = max(self._expected, seq + 1)
        return emitted

    def _declare_missing(
        self,
        first: int,
        last: int,
        detection: GapDetection,
    ) -> list[EvidenceGap]:
        """把 [first,last] 中**不在缓冲区**的序号按连续段声明为缺口。

        缓冲区里已有的序号不算缺口；这样“迟到但已到”的项不会被误记缺失。
        """
        if last < first:
            return []
        missing = [seq for seq in range(first, last + 1) if seq not in self._buffer]
        if not missing:
            return []
        runs: list[tuple[int, int]] = []
        start = prev = missing[0]
        for seq in missing[1:]:
            if seq == prev + 1:
                prev = seq
                continue
            runs.append((start, prev))
            start = prev = seq
        runs.append((start, prev))

        declared: list[EvidenceGap] = []
        for run_first, run_last in runs:
            if run_last - run_first + 1 > self._policy.max_gap_span:
                note = f"gap span exceeds max_gap_span={self._policy.max_gap_span}"
            else:
                note = ""
            gap = EvidenceGap(
                gap_id=self._gap_id_factory.new_gap_id(),
                task_id=self._task_id,
                node_id=self._node_id,
                attempt_id=self._attempt_id,
                stream=self._stream,
                first_missing_source_seq=run_first,
                last_missing_source_seq=run_last,
                missing_count=run_last - run_first + 1,
                detection=detection,
                detected_at=self._clock.now_utc(),
                note=note,
            )
            self._journal.append_open(gap)
            self._open_gaps.append(gap)
            self._recent_gaps.append(gap)
            declared.append(gap)
        return declared

    def _take_gaps(self) -> list[EvidenceGap]:
        gaps = self._recent_gaps
        self._recent_gaps = []
        return gaps


class GapIdFactory:
    """gap_id 生成器；形态 `gap_<uuid4>`。真实生成用 M01 `new_id` 的同形态。"""

    def new_gap_id(self) -> str:
        import uuid

        return f"gap_{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# 链缺口（不可填）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChainGapReport:
    ok: bool
    first_missing_seq: int = 0
    last_missing_seq: int = 0
    missing_count: int = 0
    reason: str = ""


def detect_chain_seq_gap(seqs: Sequence[int]) -> ChainGapReport:
    """检查已存 evidence 的 event_seq 是否从 1 连续；缺口不可推断、不可跳过。

    `seqs` 必须按存储/查询顺序（event_seq 升序）传入。重复/回退由 chain.verify 负责；
    本函数只找“缺哪几号”，供 Gate 读缺口。
    """
    if not seqs:
        return ChainGapReport(ok=True)
    if seqs[0] != 1:
        return ChainGapReport(
            ok=False, first_missing_seq=1, last_missing_seq=seqs[0] - 1,
            missing_count=seqs[0] - 1, reason="FIRST_SEQ_NOT_ONE",
        )
    for index in range(1, len(seqs)):
        expected = seqs[index - 1] + 1
        if seqs[index] != expected:
            return ChainGapReport(
                ok=False, first_missing_seq=expected, last_missing_seq=seqs[index] - 1,
                missing_count=seqs[index] - expected, reason="CHAIN_SEQ_JUMP",
            )
    return ChainGapReport(ok=True)


def attempt_incomplete_gap(
    *,
    task_id: str,
    node_id: str,
    attempt_id: str,
    launch_seen: bool,
    exit_seen: bool,
    detected_at: str,
    gap_id_factory: "GapIdFactory | None" = None,
) -> EvidenceGap | None:
    """attempt 结束仍只有 launch、没有 exit → `ATTEMPT_INCOMPLETE`。

    这不是 source_seq 缺口：`first/last_missing_source_seq=0` 是生命周期哨兵，
    `note` 明确写缺的事件类型。Gate 读到 OPEN 后不得把 exit 推断为 0/成功。
    """
    if exit_seen or not launch_seen:
        return None
    factory = gap_id_factory or GapIdFactory()
    return EvidenceGap(
        gap_id=factory.new_gap_id(),
        task_id=task_id,
        node_id=node_id,
        attempt_id=attempt_id,
        stream="executor",
        first_missing_source_seq=0,
        last_missing_source_seq=0,
        missing_count=1,
        detection=GapDetection.ATTEMPT_INCOMPLETE,
        detected_at=detected_at,
        note="executor_process_exit missing",
    )


# ---------------------------------------------------------------------------
# Gate 读取视图（P5 使用）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GateGapView:
    """Gate 只读视图：有 OPEN 缺口就不能把该 scope 的必检项判为 PASS。"""

    scope_task_id: str
    scope_node_id: str | None
    scope_attempt_id: str | None
    gaps: tuple[EvidenceGap, ...]

    @property
    def open_gaps(self) -> tuple[EvidenceGap, ...]:
        return tuple(g for g in self.gaps if g.status is GapStatus.OPEN)

    @property
    def blocked(self) -> bool:
        return bool(self.open_gaps)

    @property
    def missing_count(self) -> int:
        return sum(g.missing_count for g in self.open_gaps)

    def blocks_execution_check(self, check_id: str) -> bool:
        """执行类必检：任何 OPEN 缺口都阻断；缺口不是证据，不能顶替。"""
        if not check_id:
            raise ValueError("check_id 不得为空")
        return self.blocked

    def explain(self) -> tuple[str, ...]:
        """给报告用的短句；不包含推断值。"""
        return tuple(
            f"{g.stream}: missing source_seq [{g.first_missing_source_seq},"
            f"{g.last_missing_source_seq}] ({g.detection.value})"
            for g in self.open_gaps
        )


def gate_view(
    *,
    task_id: str,
    node_id: str | None,
    attempt_id: str | None,
    journal: GapJournalPort,
) -> GateGapView:
    """从缺口日志构造 Gate 视图；只读 OPEN 行。"""
    return GateGapView(
        scope_task_id=task_id,
        scope_node_id=node_id,
        scope_attempt_id=attempt_id,
        gaps=journal.open_gaps(task_id=task_id, node_id=node_id, attempt_id=attempt_id),
    )


# ---------------------------------------------------------------------------
# 静态边界
# ---------------------------------------------------------------------------
def assert_gap_boundary() -> list[str]:
    """检查本模块没有“造事件”入口，也没有把缺口当证据的字段。"""
    problems: list[str] = []
    forbidden = ("synthetic", "placeholder", "inferred_value", "backfill", "fabricate")
    import sys

    module = sys.modules[__name__]
    source_names = set(vars(module))
    for name in forbidden:
        if name in source_names:
            problems.append(f"模块暴露禁名 {name!r}（不得补造）")
    if "evidence_id" in EvidenceGap.__dataclass_fields__:
        problems.append("EvidenceGap 不得带 evidence_id（缺口不是证据）")
    if "value" in EvidenceGap.__dataclass_fields__:
        problems.append("EvidenceGap 不得带 value（不得推断缺失值）")
    return problems