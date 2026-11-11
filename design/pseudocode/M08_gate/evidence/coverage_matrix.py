"""MODULE: M08 · evidence/coverage_matrix.py — coverage row 七字段与报告计数（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-006、SEM-VR-01/02、策划书 §7.2
FR/依赖: FR-006；依赖 M08 ruleset（RequiredCheck/Ruleset）、M01 冻结枚举（level/kind/producer）
不变量/错误码: 每行恰好七字段；每行由证据事实**计算**出 result，调用方不得自报 PASS；
             空证据 → GAP；执行类 E0/E1 → GAP；要求 L3 而 l3_status≠PASS → GAP；
             规则集每个必检项恰好一行；没有绑定节点的必检项按 GAP 处理（反空转）。
             错误码：SCHEMA_INVALID（422，行/事实形态非法）、REQUIRED_EVIDENCE_MISSING（409，行被判 GAP）
写入者: **无**；本文件只构造内存值对象，不写证据/报告/状态
状态: 伪代码；不建环境、不跑测试、不写业务代码

## 七字段（逐字对应策划书 §7.2）

  | 字段 | 含义 | 机器口径 |
  |---|---|---|
  | `required_check_id` | 规则集里的必检项 ID | `^[a-z][a-z0-9_]*$`，且必须在规则集中 |
  | `evidence_ids` | 支撑该项的 evidence_id 列表 | 空 → 必然 GAP；不得放缺口行/推断值 |
  | `level` | 支撑证据中的最高等级 | 空证据时为 `None`；E0/E1 不能过执行类 |
  | `producer` | 最高等级证据的实际写入者 | E0–E2=`collector`，E3=`verifier` |
  | `hash_status` | payload/产物哈希复核结果 | `MATCH` / `MISMATCH` / `NOT_CHECKED` |
  | `l3_status` | L3/IRC 对该项的结论 | `PASS/FAIL/SKIP/NOT_RUN`；不要求 L3 时必须 `SKIP` |
  | `result` | 本项判定 | 只允许 `PASS` / `GAP`；PASS 由前六列**计算**得出 |

## 为什么 result 不能由调用方传入

  如果 Gate 可以先写 `result=PASS` 再补证据，覆盖矩阵就退化成展示表。这里把
  `build_row()` 设计成只接收事实（evidence_ids/level/producer/hash/l3），`result`
  由纯函数计算；任何“缺证据但想通过”的调用都只能得到 GAP。

## 聚合口径（一个 check 绑定多个节点时）

  coverage row 没有 node_id 字段（七字段固定）。Gate 对“同一 check 的多个适用节点”
  做**全称聚合**：所有适用节点都满足才算 PASS；任一处缺证据，整行 GAP，
  但 Gate 的 `GateGap.node_id` 会指出具体缺口。这样不会因为某个节点通过就掩盖另一个节点。

## 报告计数

  `required` = 规则集必检项数；`passed` = result=PASS 的项数；`missing = required - passed`。
  这个口径直接满足 SEM-VR-01；`VERIFIED ⇒ missing==0` 由 Gate/Verifier 入口再判（SEM-VR-02）。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from .ruleset import LEVEL_RANK, RequiredCheck, Ruleset

__all__ = [
    "CHECK_STATUS_VALUES",
    "CoverageError",
    "CoverageMatrix",
    "CoverageRow",
    "HashStatus",
    "L3Attestation",
    "L3RowStatus",
    "RowResult",
    "assert_coverage_boundary",
    "assert_seven_fields",
    "build_coverage_matrix",
    "build_row",
]

CHECK_STATUS_VALUES: Final[tuple[str, ...]] = ("PASS", "FAIL", "SKIP", "NOT_RUN")
PRODUCER_BY_LEVEL: Final[Mapping[str, str]] = MappingProxyType({
    "E0": "collector", "E1": "collector", "E2": "collector", "E3": "verifier",
})


class HashStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_CHECKED = "NOT_CHECKED"


class L3RowStatus(StrEnum):
    """与 05 §5 的 l1/l2/l3_status 四值同名；这里是 row 级视图。"""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    NOT_RUN = "NOT_RUN"


class RowResult(StrEnum):
    PASS = "PASS"
    GAP = "GAP"


class CoverageError(RuntimeError):
    """行/矩阵不变量被破坏（**不是** Gate 的常规缺口；常规缺口走 GAP 行）。"""

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
# 1. 七字段行
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CoverageRow:
    """恰好七个字段；顺序与策划书 §7.2 一致。"""

    required_check_id: str
    evidence_ids: tuple[str, ...]
    level: str | None
    producer: str | None
    hash_status: HashStatus
    l3_status: L3RowStatus
    result: RowResult

    def __post_init__(self) -> None:
        if not self.required_check_id:
            raise CoverageError(
                "SCHEMA_INVALID", "CHECK_ID_EMPTY", "required_check_id 不得为空",
                field_path="required_check_id",
            )
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise CoverageError(
                "SCHEMA_INVALID", "EVIDENCE_ID_DUPLICATED",
                "evidence_ids 不得重复", field_path="evidence_ids",
            )
        for evidence_id in self.evidence_ids:
            if not isinstance(evidence_id, str) or not evidence_id.startswith("ev_"):
                raise CoverageError(
                    "SCHEMA_INVALID", "EVIDENCE_ID_INVALID",
                    f"evidence_id 形态非法：{evidence_id!r}", field_path="evidence_ids",
                )
        if self.level is not None and self.level not in LEVEL_RANK:
            raise CoverageError(
                "SCHEMA_INVALID", "ROW_LEVEL_INVALID",
                f"level 必须是 E0–E3 或 None：{self.level!r}", field_path="level",
            )
        if (self.level is None) != (self.producer is None):
            raise CoverageError(
                "SCHEMA_INVALID", "ROW_LEVEL_PRODUCER_MISMATCH",
                "level 与 producer 必须同时为空或同时非空", field_path="producer",
            )
        if self.level is not None and self.producer != PRODUCER_BY_LEVEL[self.level]:
            raise CoverageError(
                "SCHEMA_INVALID", "ROW_PRODUCER_MISMATCH",
                f"level={self.level} 只允许 producer={PRODUCER_BY_LEVEL[self.level]!r}，"
                f"实际 {self.producer!r}",
                field_path="producer",
            )
        if self.result is RowResult.PASS:
            if not self.evidence_ids:
                raise CoverageError(
                    "REQUIRED_EVIDENCE_MISSING", "PASS_WITHOUT_EVIDENCE",
                    "没有 evidence_ids 的行不得 PASS", field_path="evidence_ids", http_status=409,
                )
            if self.hash_status is not HashStatus.MATCH:
                raise CoverageError(
                    "REQUIRED_EVIDENCE_MISSING", "PASS_WITHOUT_HASH_MATCH",
                    "hash_status 不是 MATCH 的行不得 PASS", field_path="hash_status", http_status=409,
                )
        if self.l3_status not in (L3RowStatus.PASS, L3RowStatus.FAIL, L3RowStatus.SKIP, L3RowStatus.NOT_RUN):
            raise CoverageError(
                "SCHEMA_INVALID", "L3_STATUS_INVALID",
                f"l3_status 非法：{self.l3_status!r}", field_path="l3_status",
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "required_check_id": self.required_check_id,
            "evidence_ids": list(self.evidence_ids),
            "level": self.level,
            "producer": self.producer,
            "hash_status": self.hash_status.value,
            "l3_status": self.l3_status.value,
            "result": self.result.value,
        }


def assert_seven_fields() -> list[str]:
    """结构自检：字段名/顺序必须恰好七项，且与 §7.2 一致。"""
    expected = (
        "required_check_id",
        "evidence_ids",
        "level",
        "producer",
        "hash_status",
        "l3_status",
        "result",
    )
    actual = tuple(f.name for f in fields(CoverageRow))
    return [] if actual == expected else [f"CoverageRow 字段为 {actual}，期望 {expected}"]


def build_row(
    check: RequiredCheck,
    *,
    evidence_ids: Sequence[str],
    level: str | None,
    producer: str | None,
    hash_status: HashStatus,
    l3_status: L3RowStatus,
    force_gap_reason: str | None = None,
) -> CoverageRow:
    """由**事实**计算一行；`result` 不接受调用方输入。

    判定顺序（每一步都可能得到 GAP，且不会把 GAP 改回 PASS）：
      1. 没有证据 → GAP（hash=NOT_CHECKED；L3 要求时 NOT_RUN，否则 SKIP）；
      2. 等级不足 min_level → GAP；
      3. 执行类必检遇到 E0/E1 → GAP（一票否决，Gate 第 6 步会再查）；
      4. 哈希不是 MATCH → GAP；
      5. 要求 L3 而 l3_status≠PASS → GAP；
      6. 不要求 L3 但调用方声称 PASS/FAIL/NOT_RUN → 拒绝，避免语义混淆；
      7. 以上全过 → PASS。

    `force_gap_reason` 只能把结果**降级**为 GAP（用于“多节点聚合时某节点缺证据”），
    不能把 GAP 提升为 PASS；这是本函数唯一的“外部原因”入口。
    """
    ids = tuple(evidence_ids)
    if not ids:
        if level is not None or producer is not None:
            raise CoverageError(
                "SCHEMA_INVALID", "ROW_FACT_INCONSISTENT",
                "没有 evidence_ids 时 level/producer 必须为 None", field_path="evidence_ids",
            )
        if hash_status is not HashStatus.NOT_CHECKED:
            raise CoverageError(
                "SCHEMA_INVALID", "ROW_HASH_INCONSISTENT",
                "没有证据时 hash_status 必须是 NOT_CHECKED", field_path="hash_status",
            )
        l3_value = L3RowStatus.NOT_RUN if check.l3_required else L3RowStatus.SKIP
        return CoverageRow(
            required_check_id=check.check_id,
            evidence_ids=(),
            level=None,
            producer=None,
            hash_status=HashStatus.NOT_CHECKED,
            l3_status=l3_value,
            result=RowResult.GAP,
        )

    if level is None or producer is None:
        raise CoverageError(
            "SCHEMA_INVALID", "ROW_FACT_INCONSISTENT",
            "有 evidence_ids 时必须给出 level/producer", field_path="level",
        )
    if level not in LEVEL_RANK:
        raise CoverageError(
            "SCHEMA_INVALID", "ROW_LEVEL_INVALID", f"未知等级：{level!r}", field_path="level",
        )
    if producer != PRODUCER_BY_LEVEL[level]:
        raise CoverageError(
            "SCHEMA_INVALID", "ROW_PRODUCER_MISMATCH",
            f"level={level} 的 producer 必须是 {PRODUCER_BY_LEVEL[level]!r}",
            field_path="producer",
        )
    if not check.l3_required and l3_status is not L3RowStatus.SKIP:
        raise CoverageError(
            "SCHEMA_INVALID", "L3_STATUS_NOT_APPLICABLE",
            f"{check.check_id!r} 不要求 L3，l3_status 必须是 SKIP",
            field_path="l3_status",
        )

    passed = True
    if LEVEL_RANK[level] < LEVEL_RANK[check.min_level]:
        passed = False
    if check.execution_critical and level in ("E0", "E1"):
        passed = False
    if hash_status is not HashStatus.MATCH:
        passed = False
    if check.l3_required and l3_status is not L3RowStatus.PASS:
        passed = False
    if force_gap_reason:
        passed = False

    return CoverageRow(
        required_check_id=check.check_id,
        evidence_ids=ids,
        level=level,
        producer=producer,
        hash_status=hash_status,
        l3_status=l3_status,
        result=RowResult.PASS if passed else RowResult.GAP,
    )


# ---------------------------------------------------------------------------
# 2. L3 结构化物证（Gate 第 4/7 步消费）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class L3Attestation:
    """L3/IRC 的结构化结论；由 M10 `l3_replay.py` 产出，Gate 只读。

    `check_statuses` 逐项给出该节点上每个 check 的 L3 结论；`coverage` 是该节点的
    L3 覆盖（0–1）。`evidence_id` 必须对应一条真实 E3 `verifier_recheck` 记录；
    Gate 会回查该记录，不信任孤立的 attestation 对象。
    """

    node_id: str
    l3_status: L3RowStatus
    coverage: float
    evidence_id: str
    ruleset_hash: str
    execution_mode: str          # RETRAIN / REINFER
    equivalence_mode: str        # DETERMINISTIC / STOCHASTIC
    seed_count: int
    plan_hash: str               # 等价性计划哈希；确定性模式也必须预冻结
    check_statuses: Mapping[str, L3RowStatus]
    produced_at: str

    def __post_init__(self) -> None:
        if not self.node_id:
            raise CoverageError("SCHEMA_INVALID", "L3_NODE_EMPTY", "node_id 不得为空", field_path="node_id")
        # 允许构造方传字符串（JSON/物证），但内部统一归一为枚举；否则 `is` 比较会失效。
        try:
            normalized_status = self.l3_status if isinstance(self.l3_status, L3RowStatus) \
                else L3RowStatus(str(self.l3_status))
            normalized_checks = MappingProxyType({
                check_id: (status if isinstance(status, L3RowStatus) else L3RowStatus(str(status)))
                for check_id, status in self.check_statuses.items()
            })
        except ValueError as exc:
            raise CoverageError(
                "SCHEMA_INVALID", "L3_STATUS_INVALID", f"非法 L3 状态：{exc}", field_path="l3_status",
            ) from exc
        object.__setattr__(self, "l3_status", normalized_status)
        object.__setattr__(self, "check_statuses", normalized_checks)
        if normalized_status not in (L3RowStatus.PASS, L3RowStatus.FAIL, L3RowStatus.SKIP, L3RowStatus.NOT_RUN):
            raise CoverageError("SCHEMA_INVALID", "L3_STATUS_INVALID", "l3_status 非法", field_path="l3_status")
        if not (0.0 <= float(self.coverage) <= 1.0):
            raise CoverageError("SCHEMA_INVALID", "L3_COVERAGE_RANGE", "coverage 必须在 [0,1]", field_path="coverage")
        if not self.evidence_id.startswith("ev_"):
            raise CoverageError("SCHEMA_INVALID", "L3_EVIDENCE_ID_INVALID", "evidence_id 形态非法", field_path="evidence_id")
        if len(self.ruleset_hash) != 64:
            raise CoverageError("SCHEMA_INVALID", "L3_RULESET_HASH_INVALID", "ruleset_hash 形态非法", field_path="ruleset_hash")
        if self.execution_mode not in ("RETRAIN", "REINFER"):
            raise CoverageError("SCHEMA_INVALID", "L3_EXECUTION_MODE_INVALID", "execution_mode 非法", field_path="execution_mode")
        if self.equivalence_mode not in ("DETERMINISTIC", "STOCHASTIC"):
            raise CoverageError("SCHEMA_INVALID", "L3_EQUIVALENCE_MODE_INVALID", "equivalence_mode 非法", field_path="equivalence_mode")
        if isinstance(self.seed_count, bool) or not isinstance(self.seed_count, int) or self.seed_count < 0:
            raise CoverageError("SCHEMA_INVALID", "L3_SEED_COUNT_INVALID", "seed_count 必须是非负 integer", field_path="seed_count")
        if len(self.plan_hash) != 64:
            raise CoverageError("SCHEMA_INVALID", "L3_PLAN_HASH_INVALID", "plan_hash 形态非法", field_path="plan_hash")
        for check_id, status in normalized_checks.items():
            if status not in (L3RowStatus.PASS, L3RowStatus.FAIL, L3RowStatus.SKIP, L3RowStatus.NOT_RUN):
                raise CoverageError(
                    "SCHEMA_INVALID", "L3_CHECK_STATUS_INVALID",
                    f"{check_id}: 非法状态 {status!r}", field_path=f"check_statuses.{check_id}",
                )

    def status_for(self, check_id: str) -> L3RowStatus:
        value = self.check_statuses.get(check_id, L3RowStatus.NOT_RUN)
        return value if isinstance(value, L3RowStatus) else L3RowStatus(str(value))


# ---------------------------------------------------------------------------
# 3. 覆盖矩阵
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CoverageMatrix:
    """按规则集顺序排列的行；每个必检项恰好一行。"""

    ruleset_hash: str
    rows: tuple[CoverageRow, ...]

    def __post_init__(self) -> None:
        ids = [row.required_check_id for row in self.rows]
        if len(set(ids)) != len(ids):
            raise CoverageError(
                "SCHEMA_INVALID", "MATRIX_ROW_DUPLICATED",
                "同一必检项不得有两行", field_path="rows",
            )
        for row in self.rows:
            problem = assert_seven_fields()
            if problem:
                raise CoverageError(
                    "SCHEMA_INVALID", "MATRIX_SHAPE_INVALID", problem[0], field_path="rows",
                )

    def row_for(self, check_id: str) -> CoverageRow | None:
        for row in self.rows:
            if row.required_check_id == check_id:
                return row
        return None

    def gaps(self) -> tuple[CoverageRow, ...]:
        return tuple(row for row in self.rows if row.result is RowResult.GAP)

    def passed_check_ids(self) -> tuple[str, ...]:
        return tuple(row.required_check_id for row in self.rows if row.result is RowResult.PASS)

    def missing_check_ids(self) -> tuple[str, ...]:
        return tuple(row.required_check_id for row in self.rows if row.result is RowResult.GAP)

    def report_counts(self) -> tuple[int, int, int]:
        """返回 (required, passed, missing)；算术满足 SEM-VR-01。"""
        required = len(self.rows)
        passed = len(self.passed_check_ids())
        return required, passed, required - passed

    def assert_report_counts_consistent(self, *, verified: bool) -> None:
        """SEM-VR-01/02 的本地断言；Verifier 组装报告前调用。"""
        required, passed, missing = self.report_counts()
        if passed > required or missing != required - passed:
            raise CoverageError(
                "SCHEMA_INVALID", "SEM_VR_01_VIOLATED",
                f"覆盖率算术不成立：required={required}, passed={passed}, missing={missing}",
                field_path="required_check_coverage",
            )
        if verified and missing != 0:
            raise CoverageError(
                "REQUIRED_EVIDENCE_MISSING", "SEM_VR_02_VIOLATED",
                "VERIFIED 报告不得有缺失必检项", field_path="required_check_coverage", http_status=409,
            )


def build_coverage_matrix(ruleset: Ruleset, rows: Sequence[CoverageRow]) -> CoverageMatrix:
    """按规则集顺序装配矩阵；缺行/多行/错 ID 都拒绝。

    - 多出的行（规则集里没有的 check_id）→ `SCHEMA_INVALID/MATRIX_UNKNOWN_CHECK`；
    - 缺少的行 → 补一行空证据 GAP（`CHECK_NOT_EVALUATED`），**不得**视为通过；
    - 顺序以规则集声明为准，不按调用方传入顺序重排。
    """
    by_id: dict[str, CoverageRow] = {}
    for row in rows:
        if row.required_check_id in by_id:
            raise CoverageError(
                "SCHEMA_INVALID", "MATRIX_ROW_DUPLICATED",
                f"重复行：{row.required_check_id}", field_path="rows",
            )
        by_id[row.required_check_id] = row
    known = set(ruleset.check_ids())
    extra = sorted(set(by_id) - known)
    if extra:
        raise CoverageError(
            "SCHEMA_INVALID", "MATRIX_UNKNOWN_CHECK",
            f"矩阵包含规则集未声明的必检项：{extra}", field_path="rows",
        )
    ordered: list[CoverageRow] = []
    for check in ruleset.required_checks:
        row = by_id.get(check.check_id)
        if row is None:
            ordered.append(CoverageRow(
                required_check_id=check.check_id,
                evidence_ids=(),
                level=None,
                producer=None,
                hash_status=HashStatus.NOT_CHECKED,
                l3_status=L3RowStatus.NOT_RUN if check.l3_required else L3RowStatus.SKIP,
                result=RowResult.GAP,
            ))
        else:
            ordered.append(row)
    return CoverageMatrix(ruleset_hash=ruleset.ruleset_hash, rows=tuple(ordered))


# ---------------------------------------------------------------------------
# 4. 静态边界自检
# ---------------------------------------------------------------------------
def assert_coverage_boundary() -> list[str]:
    """coverage 层不得自己做 Gate 判定、不得写证据/状态。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("Gate", "evaluate", "transition", "sign", "issue_report", "write", "store"):
        if hasattr(module, attr):
            problems.append(f"coverage_matrix 暴露禁用名 {attr!r}")
    if PRODUCER_BY_LEVEL["E2"] != "collector" or PRODUCER_BY_LEVEL["E3"] != "verifier":
        problems.append("等级-写入者映射被改动")
    problems.extend(assert_seven_fields())
    return problems