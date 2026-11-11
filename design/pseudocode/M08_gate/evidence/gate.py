"""MODULE: M08 · evidence/gate.py — Gate 七步判定（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-006、I-02/I-04/I-10、策划书 §7.2、05 §10/§13
FR/依赖: FR-006；依赖 M08 ruleset（版本/必检项）、M08 coverage_matrix（七字段行/L3 物证）、
        M07 collector（等级门槛 helper）、M07 chain（链重算端口）、M01 冻结契约（schema/枚举）
不变量/错误码: Gate **只读**结构化证据与规则；七步顺序固定且不可交换；缺必检/哈希不符/规则版本不符/
             冲突未解释 = 一票否决；E0/E1 不满足执行类必检；报告指标来源节点必须有 PASS L3；
             Gate 永不返回 VERIFIED、不签发报告、不写证据/状态。
             错误码：REQUIRED_EVIDENCE_MISSING（409）、RULESET_VERSION_MISMATCH（409）、
             BUNDLE_TAMPERED（422）、EVIDENCE_REFERENCE_NOT_FOUND（422）、
             EVIDENCE_CHAIN_BROKEN/EVENT_SEQ_GAP/EVENT_SEQ_REGRESSION（500）
写入者: **无**；输出只是内存中的 GateResult，供 Verifier 组装报告
状态: 伪代码；不建环境、不跑测试、不写业务代码

## 七步与 7.2 的逐字对应（顺序不可换）

  1. `validate_schema_and_versions()`              —— schema 与版本
  2. `verify_event_sequence_and_hash_chain()`       —— 事件序列与链
  3. `verify_artifact_hashes_and_producers()`       —— 产物哈希与生产者
  4. `build_required_check_coverage_matrix()`       —— 覆盖矩阵
  5. `reject_unresolved_evidence_conflicts()`       —— 冲突拒绝
  6. `require_e2_e3_for_execution_critical_checks()`—— 执行类必检需 E2/E3
  7. `require_l3_irc_for_report_metric_source_nodes()`—— 报告指标来源节点需 L3/IRC
  8. `_conclude()`                                  —— PASS only if all pass，否则 GAP(list)

  第 1/2 步是**结构性前置**：schema/版本或链不成立时立即 BLOCKED，不继续造 coverage；
  第 3 步的哈希失败会继续走完 4–7 以收集全部缺口，但带 veto 的结果永远不能 PASS。

## 四类一票否决（必须全部机器可判）

  | veto code | 触发 | 注册错误码 |
  |---|---|---|
  | `REQUIRED_CHECK_MISSING` | 任一必检项没有合格证据 / 绑定不到节点 | `REQUIRED_EVIDENCE_MISSING`(409) |
  | `HASH_MISMATCH` | payload/产物哈希与记录或清单不符 | `BUNDLE_TAMPERED`(422) |
  | `RULESET_VERSION_MISMATCH` | task/规则集/证据 schema 版本或哈希不一致 | `RULESET_VERSION_MISMATCH`(409) |
  | `UNRESOLVED_EVIDENCE_CONFLICT` | 冲突日志有未解释项，或直接检测到重复执行事件 | `REQUIRED_EVIDENCE_MISSING`(409) |

  四类之外还有结构性 veto（如未知节点、节点要求了规则集没有的 check），
  它们同样 fail-closed，但不改变“四类必须否决”的口径。

## Gate 不做什么

  - 不调用 StateMachine、不写 Task/Node 状态、不签发 VerificationReport/Certificate。
  - 不计算 Merkle 根（L1 做）、不重算指标（L2 做）、不重跑模型（L3 做）。
  - 不“解释”冲突：冲突只能由 Collector 的拒绝日志说明来源，Gate 只负责拒绝放行。
  - 不把 E0/E1 当执行证据；不把“L2 自洽”当“真实执行”。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .coverage_matrix import (
    CoverageMatrix,
    CoverageRow,
    HashStatus,
    L3Attestation,
    L3RowStatus,
    RowResult,
    build_coverage_matrix,
    build_row,
)
from .ruleset import (
    KIND_LEVEL,
    LEVEL_RANK,
    Ruleset,
    RulesetError,
    assert_task_binding,
)

__all__ = [
    "EXECUTION_CRITICAL_LEVELS",
    "FOUR_VETO_CODES",
    "SEVEN_STEPS",
    "Gate",
    "GateError",
    "GateGap",
    "GateInput",
    "GateResult",
    "RecordView",
    "STEP_1",
    "STEP_2",
    "STEP_3",
    "STEP_4",
    "STEP_5",
    "STEP_6",
    "STEP_7",
    "assert_gate_boundary",
    "assert_step_order",
]

# 与 M07 collector 的 EXECUTION_CRITICAL_LEVELS 同源；Gate 不另造第四种等级。
EXECUTION_CRITICAL_LEVELS: Final[tuple[str, ...]] = ("E2", "E3")
PRODUCER_BY_LEVEL: Final[Mapping[str, str]] = MappingProxyType({
    "E0": "collector", "E1": "collector", "E2": "collector", "E3": "verifier",
})

STEP_1: Final[str] = "validate_schema_and_versions"
STEP_2: Final[str] = "verify_event_sequence_and_hash_chain"
STEP_3: Final[str] = "verify_artifact_hashes_and_producers"
STEP_4: Final[str] = "build_required_check_coverage_matrix"
STEP_5: Final[str] = "reject_unresolved_evidence_conflicts"
STEP_6: Final[str] = "require_e2_e3_for_execution_critical_checks"
STEP_7: Final[str] = "require_l3_irc_for_report_metric_source_nodes"

SEVEN_STEPS: Final[tuple[str, ...]] = (
    STEP_1, STEP_2, STEP_3, STEP_4, STEP_5, STEP_6, STEP_7,
)

FOUR_VETO_CODES: Final[tuple[str, ...]] = (
    "REQUIRED_CHECK_MISSING",
    "HASH_MISMATCH",
    "RULESET_VERSION_MISMATCH",
    "UNRESOLVED_EVIDENCE_CONFLICT",
)

# 具体缺口码 → 四类 veto 的映射。负例同时断言具体 code 与 veto_class，
# 避免“因为别的原因被拒”也算通过（AGENTS §8）。
VETO_CLASS_BY_CODE: Final[Mapping[str, str]] = MappingProxyType({
    "HASH_MISMATCH": "HASH_MISMATCH",
    "PAYLOAD_HASH_MISMATCH": "HASH_MISMATCH",
    "ARTIFACT_HASH_MISMATCH": "HASH_MISMATCH",
    "ARTIFACT_HASH_NOT_REGISTERED": "HASH_MISMATCH",
    "ARTIFACT_MISSING": "HASH_MISMATCH",
    "L3_EVIDENCE_HASH_MISMATCH": "HASH_MISMATCH",
    "TASK_RULESET_MISMATCH": "RULESET_VERSION_MISMATCH",
    "RULESET_HASH_UNSTABLE": "RULESET_VERSION_MISMATCH",
    "EVIDENCE_SCHEMA_VERSION_MISMATCH": "RULESET_VERSION_MISMATCH",
    "NODE_REQUIRES_UNKNOWN_CHECK": "RULESET_VERSION_MISMATCH",
    "L3_RULESET_MISMATCH": "RULESET_VERSION_MISMATCH",
    "REQUIRED_CHECK_MISSING": "REQUIRED_CHECK_MISSING",
    "CHECK_NOT_BOUND_TO_ANY_NODE": "REQUIRED_CHECK_MISSING",
    "REQUIRED_CHECK_L3_MISSING": "REQUIRED_CHECK_MISSING",
    "E0_E1_CANNOT_SATISFY_EXECUTION_CHECK": "REQUIRED_CHECK_MISSING",
    "EXECUTION_CHECK_LEVEL_UNSUPPORTED": "REQUIRED_CHECK_MISSING",
    "L3_ATTESTATION_MISSING": "REQUIRED_CHECK_MISSING",
    "L3_COVERAGE_INSUFFICIENT": "REQUIRED_CHECK_MISSING",
    "L3_CHECK_NOT_PASS": "REQUIRED_CHECK_MISSING",
    "L3_NOT_PASS": "REQUIRED_CHECK_MISSING",
    "L3_INSUFFICIENT_SEEDS": "REQUIRED_CHECK_MISSING",
    "L3_PLAN_HASH_MISSING": "REQUIRED_CHECK_MISSING",
    "UNRESOLVED_EVIDENCE_CONFLICT": "UNRESOLVED_EVIDENCE_CONFLICT",
    "DUPLICATE_ATTEMPT_EVENT": "UNRESOLVED_EVIDENCE_CONFLICT",
    "DUPLICATE_ARTIFACT_OBSERVATION": "UNRESOLVED_EVIDENCE_CONFLICT",
    "CONFLICT_JOURNAL_UNAVAILABLE": "UNRESOLVED_EVIDENCE_CONFLICT",
})

_HASH64 = re.compile(r"^[0-9a-f]{64}$")


class GateError(RuntimeError):
    """Gate 输入/端口/程序性错误；常规缺口走 GateGap，不抛异常。"""

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


# ---------------------------------------------------------------------------
# 1. 只读视图与端口
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RecordView:
    """Gate 看到的 EvidenceRecord（只读投影，不含 payload 内容）。

    字段与 `contracts/evidencerecord.schema.json` 一一对应；`payload` 只在
    `PayloadReaderPort` 里按 `payload_hash` 读取，Gate 不反序列化任意代码。
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
    prev_hash: str
    chain_hash: str
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence_id.startswith("ev_"):
            raise GateError("SCHEMA_INVALID", "EVIDENCE_ID_INVALID",
                            "evidence_id 形态非法", field_path="evidence_id")
        if not isinstance(self.event_seq, int) or isinstance(self.event_seq, bool) or self.event_seq < 1:
            raise GateError("SCHEMA_INVALID", "EVENT_SEQ_INVALID",
                            "event_seq 必须是 ≥1 的 integer", field_path="event_seq")
        if self.level not in LEVEL_RANK:
            raise GateError("SCHEMA_INVALID", "LEVEL_INVALID",
                            f"未知等级：{self.level!r}", field_path="level")
        if self.kind not in KIND_LEVEL:
            raise GateError("SCHEMA_INVALID", "KIND_INVALID",
                            f"未知 kind：{self.kind!r}", field_path="kind")
        if not isinstance(self.artifact_refs, tuple):
            raise GateError("SCHEMA_INVALID", "ARTIFACT_REFS_NOT_TUPLE",
                            "artifact_refs 必须是 tuple", field_path="artifact_refs")


class RecordSchemaPort(Protocol):
    """冻结 schema 的独立复核（M01 严格模型/validate_contracts 端口）。"""

    def validate(self, record: RecordView) -> None: ...


class PayloadReaderPort(Protocol):
    """按 payload_hash 读取规范化 payload 字节；不存在返回 None。"""

    def read(self, payload_hash: str) -> bytes | None: ...


class ArtifactHasherPort(Protocol):
    """按 attempt + artifact:// 引用读取产物并重算 SHA-256；不存在返回 None。"""

    def sha256(self, *, task_id: str, attempt_id: str, ref: str) -> str | None: ...


class ChainHashPort(Protocol):
    """M07 ChainHasher 的只读端口：按同一前像重算 chain_hash。"""

    def recompute(self, record: RecordView) -> str: ...


class ConflictView(Protocol):
    """冲突日志的只读视图（M07 evidence_ingest_rejections / 后续 conflicts 表）。"""

    @property
    def conflict_id(self) -> str: ...
    @property
    def reason(self) -> str: ...
    @property
    def resolved(self) -> bool: ...
    @property
    def resolution_ref(self) -> str: ...


class ConflictJournalPort(Protocol):
    """读取任务内冲突；不可用必须抛错，Gate 按 fail-closed 处理。"""

    def unresolved(self, task_id: str) -> Sequence[ConflictView]: ...


class CanonicalizerPort(Protocol):
    def canonical_bytes(self, value: object) -> bytes: ...


@dataclass(frozen=True, slots=True)
class GateInput:
    """Gate 的完整只读输入。

    `records` 必须是**存储顺序**（按 event_seq 升序）；Gate 不排序——
    排序会掩盖存储顺序错误，也会让“链尾篡改”更难发现。
    `artifact_manifest` 的键是 `"<attempt_id>:<artifact://...>"`，值是 E2 观测到的哈希。
    """

    task_id: str
    task_ruleset_hash: str
    ruleset: Ruleset
    records: tuple[RecordView, ...]
    known_nodes: tuple[str, ...]
    node_required_checks: Mapping[str, tuple[str, ...]]
    metric_source_nodes: tuple[str, ...]
    l3_attestations: Mapping[str, L3Attestation]
    artifact_manifest: Mapping[str, str]
    record_schema: RecordSchemaPort
    payload_reader: PayloadReaderPort
    artifact_hasher: ArtifactHasherPort
    chain_hasher: ChainHashPort
    conflict_journal: ConflictJournalPort
    canonicalizer: CanonicalizerPort

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.startswith("task_"):
            raise GateError("SCHEMA_INVALID", "TASK_ID_INVALID",
                            "task_id 形态非法", field_path="task_id")
        if not isinstance(self.records, tuple):
            raise GateError("SCHEMA_INVALID", "RECORDS_NOT_TUPLE",
                            "records 必须是 tuple（存储顺序）", field_path="records")
        if len(set(self.known_nodes)) != len(self.known_nodes):
            raise GateError("SCHEMA_INVALID", "KNOWN_NODES_DUPLICATED",
                            "known_nodes 不得重复", field_path="known_nodes")
        if len(set(self.metric_source_nodes)) != len(self.metric_source_nodes):
            raise GateError("SCHEMA_INVALID", "METRIC_NODES_DUPLICATED",
                            "metric_source_nodes 不得重复", field_path="metric_source_nodes")


@dataclass(frozen=True, slots=True)
class GateGap:
    """一个结构化缺口；`veto=True` 表示属于一票否决类。"""

    code: str
    error_code: str
    step: str
    message: str
    check_id: str | None = None
    node_id: str | None = None
    evidence_id: str | None = None
    veto: bool = False
    detail: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def key(self) -> tuple[str, str | None, str | None, str | None, str]:
        return (self.code, self.check_id, self.node_id, self.evidence_id, self.step)

    def veto_class(self) -> str | None:
        """四类 veto 归类；结构性 veto 返回 None（仍因 veto=True 阻塞）。"""
        return VETO_CLASS_BY_CODE.get(self.code)


@dataclass(frozen=True, slots=True)
class GateResult:
    """Gate 的唯一输出；没有 `final_state`，也没有 `signature`。"""

    verdict: str
    task_id: str
    ruleset_hash: str
    coverage: CoverageMatrix | None
    gaps: tuple[GateGap, ...]
    vetoes: tuple[GateGap, ...]
    executed_steps: tuple[str, ...]
    l3_coverage: float
    required_check_total: int

    def passed(self) -> bool:
        if self.verdict != "PASS":
            return False
        if self.vetoes or self.gaps:
            return False
        if self.coverage is None:
            return False
        required, passed, missing = self.coverage.report_counts()
        return required == self.required_check_total and missing == 0 and passed == required

    def report_counts(self) -> tuple[int, int, int]:
        if self.coverage is None:
            return (self.required_check_total, 0, self.required_check_total)
        return self.coverage.report_counts()

    def veto_classes(self) -> tuple[str, ...]:
        """命中的四类 veto（去重、保序）；结构性 veto 不在其中但仍会阻塞。"""
        found: list[str] = []
        for gap in self.vetoes:
            name = gap.veto_class()
            if name and name not in found:
                found.append(name)
        return tuple(found)

    def assert_no_verified_claim(self) -> None:
        """Gate 不得冒充 Verifier：出现 VERIFIED 字样即契约破坏。"""
        if self.verdict == "VERIFIED":
            raise GateError("SCHEMA_INVALID", "GATE_RETURNED_VERIFIED",
                            "Gate 不得返回 VERIFIED；VERIFIED 只能由 Verifier 签发报告",
                            field_path="verdict")


# ---------------------------------------------------------------------------
# 2. 内部上下文
# ---------------------------------------------------------------------------
class _GateContext:
    """一次判定的可变工作区；只在 `evaluate()` 栈内存在。"""

    def __init__(self, gate_input: GateInput) -> None:
        self.input = gate_input
        self.gaps: list[GateGap] = []
        self.executed_steps: list[str] = []
        self.hash_status: dict[str, HashStatus] = {}
        self.matrix: CoverageMatrix | None = None
        self.l3_coverage: float = 0.0
        self.record_index: dict[str, RecordView] = {
            record.evidence_id: record for record in gate_input.records
        }
        self.node_checks: dict[str, tuple[str, ...]] = {
            node: tuple(checks) for node, checks in gate_input.node_required_checks.items()
        }

    def add(self, gap: GateGap) -> None:
        for index, existing in enumerate(self.gaps):
            if existing.key() == gap.key():
                if gap.veto and not existing.veto:
                    self.gaps[index] = replace(existing, veto=True)
                return
        self.gaps.append(gap)

    def deduped_gaps(self) -> tuple[GateGap, ...]:
        merged: dict[tuple[str, str | None, str | None, str | None, str], GateGap] = {}
        for gap in self.gaps:
            key = gap.key()
            current = merged.get(key)
            if current is None or (gap.veto and not current.veto):
                merged[key] = gap
        return tuple(merged.values())


# ---------------------------------------------------------------------------
# 3. Gate
# ---------------------------------------------------------------------------
class Gate:
    """七步判定器；构造无状态，所有输入经 `evaluate(GateInput)` 传入。"""

    SEVEN_STEPS: Final[tuple[str, ...]] = SEVEN_STEPS

    # -- 3.0 入口 ---------------------------------------------------------
    def evaluate(self, gate_input: GateInput) -> GateResult:
        """按 7.2 顺序执行七步；返回 PASS / GAP / BLOCKED。

        顺序不可交换：版本 → 链 → 产物 → 覆盖 → 冲突 → 执行类 → L3。
        第 1/2 步出现 veto 立即 BLOCKED；第 3 步起继续收集缺口。
        """
        ctx = _GateContext(gate_input)

        # 第 1 步
        ctx.executed_steps.append(STEP_1)
        for gap in self.validate_schema_and_versions(ctx):
            ctx.add(gap)
        if any(gap.veto for gap in ctx.gaps):
            return self._blocked(ctx)

        # 第 2 步
        ctx.executed_steps.append(STEP_2)
        for gap in self.verify_event_sequence_and_hash_chain(ctx):
            ctx.add(gap)
        if any(gap.veto for gap in ctx.gaps):
            return self._blocked(ctx)

        # 第 3 步（哈希失败继续走完，但最终 BLOCKED）
        ctx.executed_steps.append(STEP_3)
        for gap in self.verify_artifact_hashes_and_producers(ctx):
            ctx.add(gap)

        # 第 4 步
        ctx.executed_steps.append(STEP_4)
        matrix, coverage_gaps = self.build_required_check_coverage_matrix(ctx)
        ctx.matrix = matrix
        for gap in coverage_gaps:
            ctx.add(gap)

        # 第 5 步
        ctx.executed_steps.append(STEP_5)
        for gap in self.reject_unresolved_evidence_conflicts(ctx):
            ctx.add(gap)

        # 第 6 步
        ctx.executed_steps.append(STEP_6)
        for gap in self.require_e2_e3_for_execution_critical_checks(ctx):
            ctx.add(gap)

        # 第 7 步
        ctx.executed_steps.append(STEP_7)
        for gap in self.require_l3_irc_for_report_metric_source_nodes(ctx):
            ctx.add(gap)

        # 第 8 步：结论
        return self._conclude(ctx)

    # -- 3.1 第 1 步：schema 与版本 --------------------------------------
    def validate_schema_and_versions(self, ctx: _GateContext) -> tuple[GateGap, ...]:
        """校验证据 schema、规则集哈希、任务绑定、节点/必检项/指标节点引用。

        失败即 veto（版本/结构不可信时继续判 coverage 没有意义）。
        """
        gaps: list[GateGap] = []
        gate_input = ctx.input

        # 1) 规则集自身哈希可重算，且与任务绑定一致
        try:
            recomputed = gate_input.ruleset.verify_hash(gate_input.canonicalizer)
            if recomputed != gate_input.ruleset.ruleset_hash:
                gaps.append(self._gap(
                    "RULESET_HASH_UNSTABLE", "RULESET_VERSION_MISMATCH", STEP_1,
                    "规则集内容与 ruleset_hash 不一致", veto=True,
                    detail={"expected": gate_input.ruleset.ruleset_hash, "actual": recomputed},
                ))
            assert_task_binding(gate_input.task_ruleset_hash, gate_input.ruleset)
        except RulesetError as exc:
            gaps.append(self._gap(
                exc.reason, exc.error_code, STEP_1, str(exc), veto=True,
                detail={"field_path": exc.field_path, **dict(exc.detail)},
            ))

        # 2) 每条证据的 schema/版本/任务/节点
        known = set(gate_input.known_nodes)
        for record in gate_input.records:
            if record.schema_version != "1.0":
                gaps.append(self._gap(
                    "EVIDENCE_SCHEMA_VERSION_MISMATCH", "RULESET_VERSION_MISMATCH", STEP_1,
                    "证据 schema_version 不是 1.0", veto=True, evidence_id=record.evidence_id,
                    detail={"actual": record.schema_version},
                ))
            if record.task_id != gate_input.task_id:
                gaps.append(self._gap(
                    "EVIDENCE_TASK_MISMATCH", "SCHEMA_INVALID", STEP_1,
                    "证据 task_id 与本次任务不一致", veto=True, evidence_id=record.evidence_id,
                ))
            if record.node_id not in known:
                gaps.append(self._gap(
                    "EVIDENCE_NODE_UNKNOWN", "SCHEMA_INVALID", STEP_1,
                    "证据引用了任务图里不存在的节点", veto=True,
                    node_id=record.node_id, evidence_id=record.evidence_id,
                ))
            try:
                gate_input.record_schema.validate(record)
            except Exception as exc:  # 端口必须 fail-closed；不把异常类型当契约
                gaps.append(self._gap(
                    "EVIDENCE_SCHEMA_INVALID", "SCHEMA_INVALID", STEP_1,
                    f"冻结 schema 复核失败：{exc}", veto=True, evidence_id=record.evidence_id,
                ))

        # 3) 节点声明的必检项必须在规则集里
        check_ids = set(gate_input.ruleset.check_ids())
        for node, node_checks in ctx.node_checks.items():
            if node not in known:
                gaps.append(self._gap(
                    "NODE_REQUIRED_CHECKS_UNKNOWN_NODE", "SCHEMA_INVALID", STEP_1,
                    "node_required_checks 引用了未知节点", veto=True, node_id=node,
                ))
            for check_id in node_checks:
                if check_id not in check_ids:
                    gaps.append(self._gap(
                        "NODE_REQUIRES_UNKNOWN_CHECK", "RULESET_VERSION_MISMATCH", STEP_1,
                        "节点声明的必检项不在规则集里", veto=True,
                        node_id=node, check_id=check_id,
                    ))
        for node in gate_input.metric_source_nodes:
            if node not in known:
                gaps.append(self._gap(
                    "METRIC_SOURCE_NODE_UNKNOWN", "SCHEMA_INVALID", STEP_1,
                    "指标来源节点不在任务图里", veto=True, node_id=node,
                ))
        for node in gate_input.l3_attestations:
            if node not in known:
                gaps.append(self._gap(
                    "L3_ATTESTATION_NODE_UNKNOWN", "SCHEMA_INVALID", STEP_1,
                    "L3 物证引用了未知节点", veto=True, node_id=node,
                ))
        return tuple(gaps)

    # -- 3.2 第 2 步：事件序列与链 --------------------------------------
    def verify_event_sequence_and_hash_chain(self, ctx: _GateContext) -> tuple[GateGap, ...]:
        """event_seq 从 1 起严格 +1；prev_hash 接链；chain_hash 可重算；evidence_id 唯一。"""
        gaps: list[GateGap] = []
        records = ctx.input.records
        if not records:
            gaps.append(self._gap(
                "NO_EVIDENCE_RECORDS", "REQUIRED_EVIDENCE_MISSING", STEP_2,
                "任务没有任何证据记录", veto=True,
            ))
            return tuple(gaps)

        seen_ids: set[str] = set()
        for index, record in enumerate(records):
            if record.evidence_id in seen_ids:
                gaps.append(self._gap(
                    "EVIDENCE_ID_REUSED", "EVIDENCE_CHAIN_BROKEN", STEP_2,
                    "evidence_id 重复", veto=True, evidence_id=record.evidence_id,
                ))
            seen_ids.add(record.evidence_id)

            expected_seq = 1 if index == 0 else records[index - 1].event_seq + 1
            if record.event_seq != expected_seq:
                if index == 0:
                    code, error_code = "FIRST_SEQ_NOT_ONE", "EVENT_SEQ_GAP"
                elif record.event_seq == records[index - 1].event_seq:
                    code, error_code = "SEQ_DUPLICATED", "EVENT_SEQ_REGRESSION"
                elif record.event_seq < records[index - 1].event_seq:
                    code, error_code = "SEQ_REGRESSION", "EVENT_SEQ_REGRESSION"
                else:
                    code, error_code = "SEQ_GAP", "EVENT_SEQ_GAP"
                gaps.append(self._gap(
                    code, error_code, STEP_2, "event_seq 不连续",
                    veto=True, evidence_id=record.evidence_id,
                    detail={"expected": expected_seq, "actual": record.event_seq},
                ))

            if index == 0:
                if not _HASH64.match(record.prev_hash):
                    gaps.append(self._gap(
                        "FIRST_PREV_HASH_INVALID", "EVIDENCE_CHAIN_BROKEN", STEP_2,
                        "首条 prev_hash 形态非法", veto=True, evidence_id=record.evidence_id,
                    ))
                # OQ-CT-10：不比较创世值，只校形态。
            else:
                if record.prev_hash != records[index - 1].chain_hash:
                    gaps.append(self._gap(
                        "PREV_HASH_MISMATCH", "EVIDENCE_CHAIN_BROKEN", STEP_2,
                        "prev_hash 不等于上一条 chain_hash", veto=True,
                        evidence_id=record.evidence_id,
                        detail={"expected": records[index - 1].chain_hash, "actual": record.prev_hash},
                    ))

            try:
                recomputed = ctx.input.chain_hasher.recompute(record)
            except Exception as exc:
                gaps.append(self._gap(
                    "CHAIN_HASH_UNAVAILABLE", "EVIDENCE_CHAIN_BROKEN", STEP_2,
                    f"chain_hash 重算失败：{exc}", veto=True, evidence_id=record.evidence_id,
                ))
                continue
            if recomputed != record.chain_hash:
                gaps.append(self._gap(
                    "CHAIN_HASH_MISMATCH", "EVIDENCE_CHAIN_BROKEN", STEP_2,
                    "chain_hash 与重算值不符", veto=True, evidence_id=record.evidence_id,
                    detail={"expected": recomputed, "actual": record.chain_hash},
                ))
        return tuple(gaps)

    # -- 3.3 第 3 步：产物哈希与生产者 ----------------------------------
    def verify_artifact_hashes_and_producers(self, ctx: _GateContext) -> tuple[GateGap, ...]:
        """逐条复核 level/kind/producer、payload_hash、artifact_refs 哈希。

        `ctx.hash_status` 给第 4 步用：MISMATCH 的证据不得进入 coverage。
        """
        gaps: list[GateGap] = []
        gate_input = ctx.input
        for record in gate_input.records:
            ctx.hash_status.setdefault(record.evidence_id, HashStatus.MATCH)

            expected_level = KIND_LEVEL[record.kind]
            if record.level != expected_level:
                gaps.append(self._gap(
                    "LEVEL_KIND_MISMATCH", "SCHEMA_INVALID", STEP_3,
                    f"{record.kind} 只能是 {expected_level}", veto=True,
                    evidence_id=record.evidence_id,
                    detail={"expected": expected_level, "actual": record.level},
                ))
                ctx.hash_status[record.evidence_id] = HashStatus.MISMATCH
            expected_producer = PRODUCER_BY_LEVEL[record.level]
            if record.producer != expected_producer:
                gaps.append(self._gap(
                    "PRODUCER_MISMATCH", "SCHEMA_INVALID", STEP_3,
                    f"{record.level} 只能由 {expected_producer} 写入", veto=True,
                    evidence_id=record.evidence_id,
                    detail={"expected": expected_producer, "actual": record.producer},
                ))
                ctx.hash_status[record.evidence_id] = HashStatus.MISMATCH

            payload = gate_input.payload_reader.read(record.payload_hash)
            if payload is None:
                gaps.append(self._gap(
                    "PAYLOAD_MISSING", "EVIDENCE_REFERENCE_NOT_FOUND", STEP_3,
                    "payload sidecar 不存在", veto=True, evidence_id=record.evidence_id,
                ))
                ctx.hash_status[record.evidence_id] = HashStatus.MISMATCH
            else:
                actual = hashlib.sha256(payload).hexdigest()
                if actual != record.payload_hash:
                    gaps.append(self._gap(
                        "PAYLOAD_HASH_MISMATCH", "BUNDLE_TAMPERED", STEP_3,
                        "payload 重算哈希与记录不符", veto=True, evidence_id=record.evidence_id,
                        detail={"expected": record.payload_hash, "actual": actual},
                    ))
                    ctx.hash_status[record.evidence_id] = HashStatus.MISMATCH

            for ref in record.artifact_refs:
                key = f"{record.attempt_id}:{ref}"
                expected = gate_input.artifact_manifest.get(key)
                if expected is None:
                    gaps.append(self._gap(
                        "ARTIFACT_HASH_NOT_REGISTERED", "SCHEMA_INVALID", STEP_3,
                        "产物引用了未登记的哈希（E2 未观测到）", veto=True,
                        evidence_id=record.evidence_id,
                        detail={"artifact": ref},
                    ))
                    ctx.hash_status[record.evidence_id] = HashStatus.MISMATCH
                    continue
                actual = gate_input.artifact_hasher.sha256(
                    task_id=record.task_id, attempt_id=record.attempt_id, ref=ref,
                )
                if actual is None:
                    gaps.append(self._gap(
                        "ARTIFACT_MISSING", "EVIDENCE_REFERENCE_NOT_FOUND", STEP_3,
                        "证据引用的产物不存在", veto=True, evidence_id=record.evidence_id,
                        detail={"artifact": ref},
                    ))
                    ctx.hash_status[record.evidence_id] = HashStatus.MISMATCH
                elif actual != expected:
                    gaps.append(self._gap(
                        "ARTIFACT_HASH_MISMATCH", "BUNDLE_TAMPERED", STEP_3,
                        "产物重算哈希与 E2 观测值不符", veto=True,
                        evidence_id=record.evidence_id,
                        detail={"artifact": ref, "expected": expected, "actual": actual},
                    ))
                    ctx.hash_status[record.evidence_id] = HashStatus.MISMATCH
        return tuple(gaps)

    # -- 3.4 第 4 步：覆盖矩阵 ------------------------------------------
    def build_required_check_coverage_matrix(
        self, ctx: _GateContext,
    ) -> tuple[CoverageMatrix, tuple[GateGap, ...]]:
        """为每个必检项生成七字段行；空绑定/缺节点证据都按 GAP + veto 处理。"""
        gaps: list[GateGap] = []
        rows: list[CoverageRow] = []
        gate_input = ctx.input

        for check in gate_input.ruleset.required_checks:
            applicable = tuple(
                node for node, checks in ctx.node_checks.items() if check.check_id in checks
            )
            if not applicable:
                rows.append(build_row(
                    check, evidence_ids=(), level=None, producer=None,
                    hash_status=HashStatus.NOT_CHECKED,
                    l3_status=L3RowStatus.NOT_RUN if check.l3_required else L3RowStatus.SKIP,
                    force_gap_reason="CHECK_NOT_BOUND_TO_ANY_NODE",
                ))
                gaps.append(self._gap(
                    "CHECK_NOT_BOUND_TO_ANY_NODE", "REQUIRED_EVIDENCE_MISSING", STEP_4,
                    "必检项没有绑定任何节点：不能按通过处理", veto=True,
                    check_id=check.check_id,
                ))
                continue

            selected: list[RecordView] = []
            missing_nodes: list[str] = []
            l3_statuses: list[L3RowStatus] = []
            for node in applicable:
                candidates = [
                    record for record in gate_input.records
                    if record.node_id == node
                    and check.evidence_rule.matches_kind(record.kind)
                    and LEVEL_RANK[record.level] >= LEVEL_RANK[check.min_level]
                    and check.evidence_rule.matches_artifact(record.artifact_refs)
                    and ctx.hash_status.get(record.evidence_id) is HashStatus.MATCH
                ]
                if not candidates:
                    missing_nodes.append(node)
                else:
                    selected.extend(candidates)
                if check.l3_required:
                    attestation = gate_input.l3_attestations.get(node)
                    if attestation is None:
                        l3_statuses.append(L3RowStatus.NOT_RUN)
                    else:
                        l3_statuses.append(attestation.status_for(check.check_id))

            if not selected:
                rows.append(build_row(
                    check, evidence_ids=(), level=None, producer=None,
                    hash_status=HashStatus.NOT_CHECKED,
                    l3_status=L3RowStatus.NOT_RUN if check.l3_required else L3RowStatus.SKIP,
                    force_gap_reason="NODE_EVIDENCE_MISSING",
                ))
                gaps.append(self._gap(
                    "REQUIRED_CHECK_MISSING", "REQUIRED_EVIDENCE_MISSING", STEP_4,
                    "必检项没有任何合格证据（等级不足或哈希未通过）", veto=True,
                    check_id=check.check_id, node_id=missing_nodes[0] if missing_nodes else None,
                    detail={"missing_nodes": missing_nodes},
                ))
                continue

            # 最高等级与对应 producer；同一最高等级出现多个 producer 时判歧义
            highest_rank = max(LEVEL_RANK[record.level] for record in selected)
            highest = [record for record in selected if LEVEL_RANK[record.level] == highest_rank]
            producers = {record.producer for record in highest}
            level = highest[0].level
            producer = highest[0].producer
            ambiguous = len(producers) > 1

            l3_value = L3RowStatus.SKIP
            force_reason: str | None = None
            if check.l3_required:
                if L3RowStatus.FAIL in l3_statuses:
                    l3_value = L3RowStatus.FAIL
                elif L3RowStatus.SKIP in l3_statuses:
                    l3_value = L3RowStatus.SKIP
                elif L3RowStatus.NOT_RUN in l3_statuses:
                    l3_value = L3RowStatus.NOT_RUN
                else:
                    l3_value = L3RowStatus.PASS

            if missing_nodes:
                force_reason = "NODE_EVIDENCE_MISSING"
            elif ambiguous:
                force_reason = "AMBIGUOUS_PRODUCER"
            elif check.l3_required and l3_value is not L3RowStatus.PASS:
                force_reason = "NODE_L3_NOT_PASS"

            rows.append(build_row(
                check,
                evidence_ids=tuple(record.evidence_id for record in selected),
                level=level,
                producer=producer,
                hash_status=HashStatus.MATCH,
                l3_status=l3_value,
                force_gap_reason=force_reason,
            ))

            if missing_nodes:
                gaps.append(self._gap(
                    "REQUIRED_CHECK_MISSING", "REQUIRED_EVIDENCE_MISSING", STEP_4,
                    "必检项在部分节点上没有合格证据", veto=True,
                    check_id=check.check_id, node_id=missing_nodes[0],
                    detail={"missing_nodes": missing_nodes},
                ))
            if ambiguous:
                gaps.append(self._gap(
                    "AMBIGUOUS_PRODUCER", "SCHEMA_INVALID", STEP_4,
                    "同一最高等级出现多个 producer", veto=True, check_id=check.check_id,
                    detail={"producers": sorted(producers)},
                ))
            if check.l3_required and l3_value is not L3RowStatus.PASS:
                gaps.append(self._gap(
                    "REQUIRED_CHECK_L3_MISSING", "REQUIRED_EVIDENCE_MISSING", STEP_4,
                    "要求 L3 的必检项没有 PASS 的 L3 结论", veto=True,
                    check_id=check.check_id, detail={"l3_status": l3_value.value},
                ))

        matrix = build_coverage_matrix(gate_input.ruleset, rows)
        return matrix, tuple(gaps)

    # -- 3.5 第 5 步：冲突拒绝 ------------------------------------------
    def reject_unresolved_evidence_conflicts(self, ctx: _GateContext) -> tuple[GateGap, ...]:
        """未解释冲突一律 veto；另外直接检测重复执行事件/重复产物观测。

        "未解释"不是"无法解释"：冲突必须有 Collector 的拒绝日志或 StateMachine 的
        审计记录作为 resolution_ref；Gate 不自行补解释。
        """
        gaps: list[GateGap] = []
        try:
            conflicts = ctx.input.conflict_journal.unresolved(ctx.input.task_id)
        except Exception as exc:
            gaps.append(self._gap(
                "CONFLICT_JOURNAL_UNAVAILABLE", "EVIDENCE_CHAIN_BROKEN", STEP_5,
                f"冲突日志不可读：{exc}", veto=True,
            ))
            conflicts = ()

        for conflict in conflicts:
            if conflict.resolved and conflict.resolution_ref:
                continue
            gaps.append(self._gap(
                "UNRESOLVED_EVIDENCE_CONFLICT", "REQUIRED_EVIDENCE_MISSING", STEP_5,
                "存在未解释的证据冲突", veto=True,
                detail={
                    "conflict_id": conflict.conflict_id,
                    "reason": conflict.reason,
                },
            ))

        # 直接检测：同一 attempt 的 launch/exit 只能各一条；同组 artifact 只能观测一次。
        attempt_kinds: dict[tuple[str, str, str], int] = {}
        artifact_sets: dict[tuple[str, str, frozenset[str]], int] = {}
        for record in ctx.input.records:
            if record.kind in ("executor_launch", "executor_process_exit"):
                key = (record.node_id, record.attempt_id, record.kind)
                attempt_kinds[key] = attempt_kinds.get(key, 0) + 1
            if record.kind == "artifact_observed" and record.artifact_refs:
                key2 = (record.node_id, record.attempt_id, frozenset(record.artifact_refs))
                artifact_sets[key2] = artifact_sets.get(key2, 0) + 1

        for (node, attempt, kind), count in attempt_kinds.items():
            if count > 1:
                gaps.append(self._gap(
                    "DUPLICATE_ATTEMPT_EVENT", "SCHEMA_INVALID", STEP_5,
                    f"同一 attempt 出现 {count} 条 {kind}", veto=True,
                    node_id=node,
                    detail={"attempt_id": attempt, "kind": kind},
                ))
        for (node, attempt, refs), count in artifact_sets.items():
            if count > 1:
                gaps.append(self._gap(
                    "DUPLICATE_ARTIFACT_OBSERVATION", "SCHEMA_INVALID", STEP_5,
                    "同一组产物被重复观测", veto=True, node_id=node,
                    detail={"attempt_id": attempt, "artifact_refs": sorted(refs)},
                ))
        return tuple(gaps)

    # -- 3.6 第 6 步：执行类必检需 E2/E3 --------------------------------
    def require_e2_e3_for_execution_critical_checks(self, ctx: _GateContext) -> tuple[GateGap, ...]:
        """执行类必检的 level 必须是 E2/E3；E0/E1 一律降级为 GAP 并 veto。"""
        gaps: list[GateGap] = []
        if ctx.matrix is None:
            gaps.append(self._gap(
                "COVERAGE_MATRIX_MISSING", "REQUIRED_EVIDENCE_MISSING", STEP_6,
                "覆盖矩阵不存在，无法判定执行类必检", veto=True,
            ))
            return tuple(gaps)

        new_rows: list[CoverageRow] = []
        for row in ctx.matrix.rows:
            check = ctx.input.ruleset.check(row.required_check_id)
            if not check.execution_critical:
                new_rows.append(row)
                continue
            if row.level in ("E0", "E1"):
                gaps.append(self._gap(
                    "E0_E1_CANNOT_SATISFY_EXECUTION_CHECK", "REQUIRED_EVIDENCE_MISSING", STEP_6,
                    f"{row.level} 不能顶替执行类必检 {check.check_id}", veto=True,
                    check_id=check.check_id, detail={"level": row.level, "min_level": "E2"},
                ))
                new_rows.append(replace(row, result=RowResult.GAP))
            elif row.level is not None and not self._can_satisfy_execution_check(row.level):
                gaps.append(self._gap(
                    "EXECUTION_CHECK_LEVEL_UNSUPPORTED", "REQUIRED_EVIDENCE_MISSING", STEP_6,
                    f"等级 {row.level} 不在 E2/E3 内", veto=True, check_id=check.check_id,
                ))
                new_rows.append(replace(row, result=RowResult.GAP))
            else:
                if row.result is RowResult.GAP:
                    gaps.append(self._gap(
                        "REQUIRED_CHECK_MISSING", "REQUIRED_EVIDENCE_MISSING", STEP_6,
                        "执行类必检未通过", veto=True, check_id=check.check_id,
                    ))
                new_rows.append(row)
        ctx.matrix = build_coverage_matrix(ctx.input.ruleset, new_rows)
        return tuple(gaps)

    # -- 3.7 第 7 步：报告指标来源节点需 L3/IRC -------------------------
    def require_l3_irc_for_report_metric_source_nodes(
        self, ctx: _GateContext,
    ) -> tuple[GateGap, ...]:
        """每个报告指标来源节点都必须有可回查的 PASS L3 物证；不足即缺口 + veto。"""
        gaps: list[GateGap] = []
        gate_input = ctx.input
        metric_nodes = gate_input.metric_source_nodes
        if not metric_nodes:
            gaps.append(self._gap(
                "NO_METRIC_SOURCE_NODES", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                "任务没有声明指标来源节点：不能证明报告指标来自 L3 覆盖节点", veto=True,
            ))
            ctx.l3_coverage = 0.0
            return tuple(gaps)

        covered = 0
        for node in metric_nodes:
            attestation = gate_input.l3_attestations.get(node)
            if attestation is None:
                gaps.append(self._gap(
                    "L3_ATTESTATION_MISSING", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                    "指标来源节点没有 L3 物证", veto=True, node_id=node,
                ))
                continue

            if attestation.l3_status is not L3RowStatus.PASS:
                gaps.append(self._gap(
                    "L3_NOT_PASS", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                    f"L3 结论不是 PASS：{attestation.l3_status.value}", veto=True, node_id=node,
                ))
                continue
            if attestation.coverage < gate_input.ruleset.l3_policy.required_coverage:
                gaps.append(self._gap(
                    "L3_COVERAGE_INSUFFICIENT", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                    "单节点 L3 覆盖低于规则集要求", veto=True, node_id=node,
                    detail={
                        "required": gate_input.ruleset.l3_policy.required_coverage,
                        "actual": attestation.coverage,
                    },
                ))
                continue
            if attestation.ruleset_hash != gate_input.ruleset.ruleset_hash:
                gaps.append(self._gap(
                    "L3_RULESET_MISMATCH", "RULESET_VERSION_MISMATCH", STEP_7,
                    "L3 物证绑定的规则版本与本次不一致", veto=True, node_id=node,
                    detail={
                        "expected": gate_input.ruleset.ruleset_hash,
                        "actual": attestation.ruleset_hash,
                    },
                ))
                continue

            evidence = ctx.record_index.get(attestation.evidence_id)
            if evidence is None:
                gaps.append(self._gap(
                    "L3_EVIDENCE_NOT_FOUND", "EVIDENCE_REFERENCE_NOT_FOUND", STEP_7,
                    "L3 物证引用的 E3 记录不存在", veto=True, node_id=node,
                    evidence_id=attestation.evidence_id,
                ))
                continue
            if not (
                evidence.node_id == node
                and evidence.level == "E3"
                and evidence.kind == "verifier_recheck"
                and evidence.producer == "verifier"
            ):
                gaps.append(self._gap(
                    "L3_EVIDENCE_NOT_E3", "SCHEMA_INVALID", STEP_7,
                    "L3 物证必须回指同节点的 E3 verifier_recheck", veto=True,
                    node_id=node, evidence_id=evidence.evidence_id,
                ))
                continue
            if ctx.hash_status.get(evidence.evidence_id) is not HashStatus.MATCH:
                gaps.append(self._gap(
                    "L3_EVIDENCE_HASH_MISMATCH", "BUNDLE_TAMPERED", STEP_7,
                    "L3 物证引用的 E3 记录哈希未通过", veto=True,
                    node_id=node, evidence_id=evidence.evidence_id,
                ))
                continue
            if attestation.execution_mode not in ("RETRAIN", "REINFER"):
                gaps.append(self._gap(
                    "L3_EXECUTION_MODE_INVALID", "SCHEMA_INVALID", STEP_7,
                    "L3 执行模式必须是 RETRAIN/REINFER", veto=True, node_id=node,
                ))
                continue
            if attestation.equivalence_mode == "STOCHASTIC" and attestation.seed_count < 5:
                gaps.append(self._gap(
                    "L3_INSUFFICIENT_SEEDS", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                    "随机性模式至少需要 5 个预注册种子", veto=True, node_id=node,
                    detail={"seed_count": attestation.seed_count},
                ))
                continue
            if len(attestation.plan_hash) != 64:
                gaps.append(self._gap(
                    "L3_PLAN_HASH_MISSING", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                    "等价性计划哈希缺失：不能证明边界预冻结", veto=True, node_id=node,
                ))
                continue

            node_checks = ctx.node_checks.get(node, ())
            failed_checks = [
                check_id for check_id in node_checks
                if gate_input.ruleset.check(check_id).l3_required
                and attestation.status_for(check_id) is not L3RowStatus.PASS
            ]
            if failed_checks:
                gaps.append(self._gap(
                    "L3_CHECK_NOT_PASS", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                    "指标来源节点上有要求 L3 的必检项未 PASS", veto=True, node_id=node,
                    detail={"failed_checks": failed_checks},
                ))
                continue
            covered += 1

        ctx.l3_coverage = covered / len(metric_nodes)
        if ctx.l3_coverage < gate_input.ruleset.l3_policy.required_coverage:
            gaps.append(self._gap(
                "L3_COVERAGE_INSUFFICIENT", "REQUIRED_EVIDENCE_MISSING", STEP_7,
                "L3 覆盖率低于规则集阈值", veto=True,
                detail={
                    "required": gate_input.ruleset.l3_policy.required_coverage,
                    "actual": ctx.l3_coverage,
                    "covered": covered,
                    "total": len(metric_nodes),
                },
            ))
        return tuple(gaps)

    # -- 3.8 第 8 步：结论 ----------------------------------------------
    def _conclude(self, ctx: _GateContext) -> GateResult:
        """PASS only if 无缺口、无 veto、覆盖完整、L3 达标；否则 GAP/BLOCKED。"""
        gaps = ctx.deduped_gaps()
        vetoes = tuple(gap for gap in gaps if gap.veto)
        matrix = ctx.matrix
        required_total = len(ctx.input.ruleset.required_checks)
        coverage_ok = matrix is not None and matrix.report_counts()[2] == 0
        l3_ok = ctx.l3_coverage >= ctx.input.ruleset.l3_policy.required_coverage
        passed = not gaps and not vetoes and coverage_ok and l3_ok and matrix is not None
        if passed:
            verdict = "PASS"
        elif vetoes:
            verdict = "BLOCKED"
        else:
            verdict = "GAP"
        result = GateResult(
            verdict=verdict,
            task_id=ctx.input.task_id,
            ruleset_hash=ctx.input.ruleset.ruleset_hash,
            coverage=matrix,
            gaps=gaps,
            vetoes=vetoes,
            executed_steps=tuple(ctx.executed_steps),
            l3_coverage=ctx.l3_coverage,
            required_check_total=required_total,
        )
        result.assert_no_verified_claim()
        return result

    def _blocked(self, ctx: _GateContext) -> GateResult:
        gaps = ctx.deduped_gaps()
        result = GateResult(
            verdict="BLOCKED",
            task_id=ctx.input.task_id,
            ruleset_hash=ctx.input.ruleset.ruleset_hash,
            coverage=ctx.matrix,
            gaps=gaps,
            vetoes=tuple(gap for gap in gaps if gap.veto),
            executed_steps=tuple(ctx.executed_steps),
            l3_coverage=0.0,
            required_check_total=len(ctx.input.ruleset.required_checks),
        )
        result.assert_no_verified_claim()
        return result

    # -- 3.9 工具 --------------------------------------------------------
    @staticmethod
    def _can_satisfy_execution_check(level: str) -> bool:
        """与 M07 `collector.can_satisfy_execution_check()` 同口径。

        真实实现必须直接调用 M07 的 helper（单一口径）；这里保留同构函数是为了
        让 P5 伪代码可独立审阅，且负例可以断言“E0/E1 返回 False”。
        """
        return level in EXECUTION_CRITICAL_LEVELS

    @staticmethod
    def _gap(
        code: str,
        error_code: str,
        step: str,
        message: str,
        *,
        veto: bool = False,
        check_id: str | None = None,
        node_id: str | None = None,
        evidence_id: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> GateGap:
        return GateGap(
            code=code,
            error_code=error_code,
            step=step,
            message=message,
            check_id=check_id,
            node_id=node_id,
            evidence_id=evidence_id,
            veto=veto,
            detail=MappingProxyType(dict(detail or {})),
        )


# ---------------------------------------------------------------------------
# 4. 顺序与边界自检
# ---------------------------------------------------------------------------
def assert_step_order() -> list[str]:
    """七步必须与策划书 §7.2 一一对应且顺序一致。"""
    expected = (
        "validate_schema_and_versions",
        "verify_event_sequence_and_hash_chain",
        "verify_artifact_hashes_and_producers",
        "build_required_check_coverage_matrix",
        "reject_unresolved_evidence_conflicts",
        "require_e2_e3_for_execution_critical_checks",
        "require_l3_irc_for_report_metric_source_nodes",
    )
    problems: list[str] = []
    if SEVEN_STEPS != expected:
        problems.append(f"SEVEN_STEPS 顺序不符：{SEVEN_STEPS}")
    for name in expected:
        if not hasattr(Gate, name):
            problems.append(f"Gate 缺少步骤方法 {name!r}")
    if len(set(SEVEN_STEPS)) != 7:
        problems.append("SEVEN_STEPS 有重复项")
    return problems


def assert_gate_boundary() -> list[str]:
    """静态检查：Gate 不写状态/证据、不签名、不签发报告。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("StateMachine", "transition", "sign", "issue_report", "EvidenceStore",
                 "WriterSession", "CompletionCertificate"):
        if hasattr(module, attr):
            problems.append(f"gate 暴露禁用名 {attr!r}（写入/状态/签名不属于 Gate）")
    if GateResult.__dataclass_fields__.get("final_state") is not None:
        problems.append("GateResult 不得有 final_state 字段（VERIFIED 只能由 Verifier 给）")
    if "signature" in GateResult.__dataclass_fields__:
        problems.append("GateResult 不得有 signature 字段")
    problems.extend(assert_step_order())
    return problems