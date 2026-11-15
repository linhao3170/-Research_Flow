"""M15 · orchestration/determinism/prr_ledger.py — 剪枝-重跑逐节点台账（P9 伪代码）。
MODULE: M15 DC/SPA ｜ 阶段：P9「DC/SPA 与 VAS」
追踪：FR-015（T2 / G4）、策划书 §4.2 R08（PRR）、§4.3（统计口径）、附录 D.6
FR+依赖：M14 恢复计划（plan_id）、`spa_judge.SpaRecord`（spa_id）、`dc_issuer`（dc_id）、
        scipy `beta.ppf`（精确二项区间，不自行实现近似）
不变量：剪枝登记必须带 `spa_id + dc_id + recovery_plan_id`；重跑必须先有 `RERUN_STARTED`；
        `changed` 逐项精确比较，不做「差不多一样」；随机节点一律保守记 `changed=True` 并标违规；
        分母只含 `RERUN_COMPLETED`；覆盖率不足不给点估计；零错误给 Clopper–Pearson 上界
错误码：SCHEMA_INVALID（事件字段不符，422）、PRR_LEDGER_APPEND_ONLY（改写/回退，409）、
        PRR_AUTHORIZATION_MISSING（剪枝缺授权，409）、PRR_RERUN_WITHOUT_START（409）
写入者：无。台账只在内存里追加；落库由 T2 存储层负责
状态：伪代码；不执行统计、不合并、不产生实验结论

## 为什么「没有分母就不报 0」

  「剪了 12 个节点，0 个结果变化」这句话只有在 12 个都真的重跑过时才有意义。若只重跑了 3 个，
  正确的说法是「3/12 已复核，0 变化，覆盖率 0.25，未复核部分未知」。因此：

  - 分母 = `RERUN_COMPLETED` 数，分子 = 其中 `changed=True` 数；
  - `coverage = 分母 / 剪枝数`；`coverage < 1` 时 `point_estimate = None`；
  - 分子为 0 时不得只写「PRR=0」，必须同时给 Clopper–Pearson 上界（0/72 ≈ 4.99%）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

__all__ = [
    "CP_CONFIDENCE",
    "DEFAULT_ALPHA",
    "ComparisonBasis",
    "EpisodeStatus",
    "PrrEntry",
    "PrrEvent",
    "PrrEventType",
    "PrrLedger",
    "PrrRefused",
    "PrrReport",
    "PruningAuthorization",
    "ResultFingerprint",
    "assert_denominator_policy",
    "assert_no_cross_task_merge",
    "assert_no_zero_without_denominator",
    "assert_prr_records_raw",
    "clopper_pearson_upper",
]

STAGE: Final[str] = "P9"

#: 双侧 95%（与 0/72 ≈ 4.99% 的口径一致）。
DEFAULT_ALPHA: Final[float] = 0.05
CP_CONFIDENCE: Final[float] = 1.0 - DEFAULT_ALPHA


# ---------------------------------------------------------------------------
# 1. 错误与形态校验
# ---------------------------------------------------------------------------
class PrrRefused(RuntimeError):
    """台账拒绝：字段不符、授权缺失、顺序错乱、试图改写历史。"""

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{self.error_code}/{reason}：{detail}")


def _require_at(moment: datetime, field_path: str) -> None:
    """台账时间必须是带时区的 UTC（不猜本地时区）。"""
    if not isinstance(moment, datetime):
        raise PrrRefused("TIME_INVALID", f"{field_path} 必须是 datetime")
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise PrrRefused("TIME_NOT_UTC", f"{field_path} 必须是带时区的 UTC")


def _utc_z(moment: datetime) -> str:
    _require_at(moment, "moment")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_id(value: str, field_path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PrrRefused("ID_MISSING", f"{field_path} 不得为空")


# ---------------------------------------------------------------------------
# 2. 结果指纹与授权
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ResultFingerprint:
    """结果指纹：状态、产物哈希集、指标哈希、退出码。

    `changed` 只能由 `diff()` 产出——逐项精确比较，不做归一化、不忽略顺序以外的差异。
    """

    state: str
    artifact_hashes: tuple[str, ...]
    metric_hash: str
    exit_code: int

    def __post_init__(self) -> None:
        if not self.state.strip():
            raise PrrRefused("STATE_MISSING", "state 不得为空")
        if not self.artifact_hashes:
            raise PrrRefused("ARTIFACTS_MISSING", "产物哈希集不得为空")
        if len(set(self.artifact_hashes)) != len(self.artifact_hashes):
            raise PrrRefused("ARTIFACTS_DUPLICATE", "产物哈希集必须去重")
        if not self.metric_hash.strip():
            raise PrrRefused("METRIC_MISSING", "metric_hash 不得为空")

    def diff(self, other: "ResultFingerprint") -> tuple[str, ...]:
        """返回不同的字段名（空元组表示完全相同）。"""
        differences: list[str] = []
        if self.state != other.state:
            differences.append("state")
        if tuple(sorted(self.artifact_hashes)) != tuple(sorted(other.artifact_hashes)):
            differences.append("artifact_hashes")
        if self.metric_hash != other.metric_hash:
            differences.append("metric_hash")
        if self.exit_code != other.exit_code:
            differences.append("exit_code")
        return tuple(differences)

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "state": self.state,
                "artifact_hashes": list(self.artifact_hashes),
                "metric_hash": self.metric_hash,
                "exit_code": self.exit_code,
            }
        )


@dataclass(frozen=True, slots=True)
class PruningAuthorization:
    """剪枝三元授权。少一个就不是「有授权的剪枝」，而是「无凭据的跳过」。"""

    spa_id: str
    dc_id: str
    recovery_plan_id: str

    def __post_init__(self) -> None:
        for name in ("spa_id", "dc_id", "recovery_plan_id"):
            _require_id(getattr(self, name), f"authorization.{name}")


# ---------------------------------------------------------------------------
# 3. 事件模型
# ---------------------------------------------------------------------------
class PrrEventType(StrEnum):
    """台账事件。顺序即允许发生的顺序。"""

    PRUNED = "PRUNED"
    RERUN_STARTED = "RERUN_STARTED"
    RERUN_COMPLETED = "RERUN_COMPLETED"
    RERUN_FAILED = "RERUN_FAILED"
    RESULT_COMPARED = "RESULT_COMPARED"
    CORRECTION = "CORRECTION"


class EpisodeStatus(StrEnum):
    """单个被剪节点的状态。仅 `RERUN_COMPLETED` 计入分母。"""

    PRUNED = "PRUNED"
    RERUNNING = "RERUNNING"
    RERUN_COMPLETED = "RERUN_COMPLETED"
    RERUN_FAILED = "RERUN_FAILED"
    NOT_RERUN = "NOT_RERUN"


class ComparisonBasis(StrEnum):
    """`changed` 的比较依据。随机节点按保守方向处理，单列一档。"""

    EXACT_FINGERPRINT = "EXACT_FINGERPRINT"
    STOCHASTIC_CONSERVATIVE = "STOCHASTIC_CONSERVATIVE"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class PrrEvent:
    """追加事件。`seq` 由台账分配，调用方不得自填（防重排）。"""

    seq: int
    task_id: str
    plan_id: str
    node_id: str
    event_type: PrrEventType
    at: str
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seq < 1:
            raise PrrRefused("SEQ_INVALID", f"seq={self.seq} 必须从 1 开始")
        _require_id(self.task_id, "event.task_id")
        _require_id(self.plan_id, "event.plan_id")
        _require_id(self.node_id, "event.node_id")
        _require_at_text(self.at)

    def as_detail(self) -> Mapping[str, object]:
        body = dict(self.detail)
        body.update(
            {
                "seq": self.seq,
                "task_id": self.task_id,
                "plan_id": self.plan_id,
                "node_id": self.node_id,
                "event_type": self.event_type.value,
                "at": self.at,
            }
        )
        return MappingProxyType(body)


def _require_at_text(text: str) -> None:
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as exc:
        raise PrrRefused("TIME_INVALID", f"不是 RFC3339 UTC：{text!r}") from exc


@dataclass(frozen=True, slots=True)
class PrrEntry:
    """单个被剪节点的台账行（对外只读快照）。"""

    node_id: str
    status: EpisodeStatus
    authorization: PruningAuthorization
    pruned_at: str
    rerun_started_at: str | None
    rerun_completed_at: str | None
    changed: bool
    comparison_basis: ComparisonBasis
    differences: tuple[str, ...] = ()
    is_stochastic: bool = False
    violations: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status in (EpisodeStatus.RERUN_COMPLETED, EpisodeStatus.RERUN_FAILED, EpisodeStatus.RERUNNING):
            if self.rerun_started_at is None:
                raise PrrRefused(
                    "RERUN_WITHOUT_START",
                    f"{self.node_id} 进入 {self.status.value} 却没有 RERUN_STARTED",
                )
        if self.status is EpisodeStatus.RERUN_COMPLETED and self.rerun_completed_at is None:
            raise PrrRefused("COMPLETION_WITHOUT_TIME", f"{self.node_id} 缺完成时间")
        if self.changed and self.comparison_basis is ComparisonBasis.NONE:
            raise PrrRefused("CHANGED_WITHOUT_BASIS", f"{self.node_id} 记了 changed 但没写比较依据")
        if self.is_stochastic and self.status is EpisodeStatus.RERUN_COMPLETED and not self.changed:
            raise PrrRefused(
                "STOCHASTIC_RECORDED_UNCHANGED",
                f"{self.node_id} 是随机节点，不得记 changed=False（方差不是「没变化」）",
            )

    @property
    def counted_in_denominator(self) -> bool:
        return self.status is EpisodeStatus.RERUN_COMPLETED

    @property
    def resolved(self) -> bool:
        return self.status in (
            EpisodeStatus.RERUN_COMPLETED,
            EpisodeStatus.RERUN_FAILED,
        )

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "status": self.status.value,
                "spa_id": self.authorization.spa_id,
                "dc_id": self.authorization.dc_id,
                "recovery_plan_id": self.authorization.recovery_plan_id,
                "pruned_at": self.pruned_at,
                "rerun_started_at": self.rerun_started_at,
                "rerun_completed_at": self.rerun_completed_at,
                "changed": self.changed,
                "comparison_basis": self.comparison_basis.value,
                "differences": list(self.differences),
                "is_stochastic": self.is_stochastic,
                "violations": list(self.violations),
                "evidence_ids": list(self.evidence_ids),
            }
        )


# ---------------------------------------------------------------------------
# 4. 统计
# ---------------------------------------------------------------------------
def clopper_pearson_upper(k: int, n: int, alpha: float = DEFAULT_ALPHA) -> float:
    """精确二项（Clopper–Pearson）**双侧** 95% 上界。

    参数：k 变化数，n 分母（必须 ≥1），alpha 显著性水平。
    返回：[0,1] 内的上界；n=0 时抛错（无分母不得报数）。
    依据：策划书 §4.3；`0/72 ≈ 4.99%` 即 `beta.ppf(0.975, 1, 72)`。
    """
    if n <= 0:
        raise PrrRefused("NO_DENOMINATOR", "分母为 0 时不得计算上界")
    if k < 0 or k > n:
        raise PrrRefused("K_OUT_OF_RANGE", f"k={k} 不在 [0, {n}]")
    if not 0.0 < alpha < 1.0:
        raise PrrRefused("ALPHA_INVALID", f"alpha={alpha}")
    from scipy.stats import beta  # LIB: scipy 已在 requirements.lock（1.17.1）

    if k == n:
        return 1.0
    return float(beta.ppf(1.0 - alpha / 2.0, k + 1, n - k))


@dataclass(frozen=True, slots=True)
class PrrReport:
    """单任务、单计划的台账报告。**不含**跨任务合并字段。"""

    task_id: str
    plan_id: str
    rows: tuple[PrrEntry, ...]
    pruned: int
    rerun_completed: int
    changed: int
    unresolved: int
    stochastic_rows: int
    violations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.pruned != len(self.rows):
            raise PrrRefused("PRUNED_ROW_MISMATCH", f"pruned={self.pruned} 但 rows={len(self.rows)}")
        if self.rerun_completed > self.pruned:
            raise PrrRefused("DENOMINATOR_EXCEEDS_NUMERATOR_SPACE", "分母大于剪枝数")
        if self.changed > self.rerun_completed:
            raise PrrRefused("CHANGED_EXCEEDS_DENOMINATOR", "分子大于分母")

    @property
    def coverage(self) -> float:
        """覆盖率 = 已完成重跑 / 剪枝数；无剪枝时为 0.0（不是 1.0）。"""
        return self.rerun_completed / self.pruned if self.pruned else 0.0

    @property
    def point_estimate(self) -> float | None:
        """只有覆盖率 1.0 才给点估计；否则 None（不得把部分复核写成总体比例）。"""
        if self.pruned == 0 or self.coverage != 1.0:
            return None
        return self.changed / self.rerun_completed

    @property
    def cp_upper(self) -> float | None:
        """零错误时也必须给上界；无分母时 None（不写 0）。"""
        if self.rerun_completed == 0:
            return None
        return clopper_pearson_upper(self.changed, self.rerun_completed)

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "task_id": self.task_id,
                "plan_id": self.plan_id,
                "pruned": self.pruned,
                "rerun_completed": self.rerun_completed,
                "changed": self.changed,
                "unresolved": self.unresolved,
                "coverage": self.coverage,
                "point_estimate": self.point_estimate,
                "cp_upper_95": self.cp_upper,
                "stochastic_rows": self.stochastic_rows,
                "violations": list(self.violations),
                "rows": [row.as_detail() for row in self.rows],
            }
        )


# ---------------------------------------------------------------------------
# 5. 台账
# ---------------------------------------------------------------------------
class _EpisodeState:
    """内部可变状态：一个节点从剪枝到复核的全过程。"""

    __slots__ = (
        "node_id",
        "authorization",
        "pruned_at",
        "rerun_started_at",
        "rerun_completed_at",
        "status",
        "changed",
        "basis",
        "differences",
        "is_stochastic",
        "violations",
        "evidence_ids",
        "baseline",
    )

    def __init__(
        self,
        node_id: str,
        authorization: PruningAuthorization,
        pruned_at: str,
        *,
        is_stochastic: bool,
        evidence_ids: tuple[str, ...],
    ) -> None:
        self.node_id = node_id
        self.authorization = authorization
        self.pruned_at = pruned_at
        self.rerun_started_at: str | None = None
        self.rerun_completed_at: str | None = None
        self.status = EpisodeStatus.PRUNED
        self.changed = False
        self.basis = ComparisonBasis.NONE
        self.differences: tuple[str, ...] = ()
        self.is_stochastic = is_stochastic
        self.violations: list[str] = []
        self.evidence_ids = evidence_ids
        self.baseline: ResultFingerprint | None = None

    def snapshot(self) -> PrrEntry:
        return PrrEntry(
            node_id=self.node_id,
            status=self.status,
            authorization=self.authorization,
            pruned_at=self.pruned_at,
            rerun_started_at=self.rerun_started_at,
            rerun_completed_at=self.rerun_completed_at,
            changed=self.changed,
            comparison_basis=self.basis,
            differences=self.differences,
            is_stochastic=self.is_stochastic,
            violations=tuple(self.violations),
            evidence_ids=self.evidence_ids,
        )


class PrrLedger:
    """单任务台账。只追加；没有 `merge` / `aggregate` / `combine`。"""

    def __init__(self, *, task_id: str) -> None:
        _require_id(task_id, "task_id")
        self._task_id = task_id
        self._episodes: dict[tuple[str, str], _EpisodeState] = {}
        self._events: list[PrrEvent] = []
        self._seq = 0

    # -- 事件 ---------------------------------------------------------------
    def _append(
        self,
        *,
        plan_id: str,
        node_id: str,
        event_type: PrrEventType,
        at: datetime,
        detail: Mapping[str, object] | None = None,
    ) -> PrrEvent:
        """追加一条事件并返回；`seq` 单调递增。"""
        _require_at(at, "at")
        self._seq += 1
        event = PrrEvent(
            seq=self._seq,
            task_id=self._task_id,
            plan_id=plan_id,
            node_id=node_id,
            event_type=event_type,
            at=_utc_z(at),
            detail=MappingProxyType(dict(detail or {})),
        )
        self._events.append(event)
        return event

    # -- 剪枝 ---------------------------------------------------------------
    def record_pruning(
        self,
        *,
        plan_id: str,
        node_id: str,
        authorization: PruningAuthorization,
        at: datetime,
        is_stochastic: bool = False,
        baseline: ResultFingerprint | None = None,
        evidence_ids: tuple[str, ...] = (),
    ) -> PrrEntry:
        """登记一次剪枝。必须带 SPA + DC + 计划三元授权。

        错误：`PrrRefused`（缺授权、计划不一致、同一节点重复剪枝）。
        """
        _require_id(plan_id, "plan_id")
        _require_id(node_id, "node_id")
        if authorization.recovery_plan_id != plan_id:
            raise PrrRefused(
                "PLAN_MISMATCH",
                f"授权里的 plan={authorization.recovery_plan_id}，登记 plan={plan_id}",
            )
        key = (plan_id, node_id)
        if key in self._episodes:
            raise PrrRefused("DUPLICATE_PRUNING", f"{node_id} 在同一计划内重复剪枝")
        state = _EpisodeState(
            node_id,
            authorization,
            _utc_z(at),
            is_stochastic=is_stochastic,
            evidence_ids=evidence_ids,
        )
        state.baseline = baseline
        self._episodes[key] = state
        self._append(
            plan_id=plan_id,
            node_id=node_id,
            event_type=PrrEventType.PRUNED,
            at=at,
            detail={
                "spa_id": authorization.spa_id,
                "dc_id": authorization.dc_id,
                "recovery_plan_id": authorization.recovery_plan_id,
                "is_stochastic": is_stochastic,
            },
        )
        return state.snapshot()

    # -- 重跑 ---------------------------------------------------------------
    def record_rerun_started(
        self,
        *,
        plan_id: str,
        node_id: str,
        at: datetime,
        run_id: str,
    ) -> PrrEntry:
        """登记「真的开始重跑」。没有这条，后续完成事件一律拒绝。

        这一步存在的理由：只有完成事件时，无法区分「跑了」和「抄了一份旧结果」。
        """
        _require_id(run_id, "run_id")
        state = self._require_episode(plan_id, node_id)
        if state.rerun_started_at is not None:
            raise PrrRefused("RERUN_ALREADY_STARTED", f"{node_id} 已登记过重跑开始")
        state.rerun_started_at = _utc_z(at)
        state.status = EpisodeStatus.RERUNNING
        self._append(
            plan_id=plan_id,
            node_id=node_id,
            event_type=PrrEventType.RERUN_STARTED,
            at=at,
            detail={"run_id": run_id},
        )
        return state.snapshot()

    def record_rerun_completed(
        self,
        *,
        plan_id: str,
        node_id: str,
        at: datetime,
        rerun: ResultFingerprint,
        run_id: str,
    ) -> PrrEntry:
        """登记重跑完成并立即比较结果。缺 `RERUN_STARTED` 直接拒绝。"""
        state = self._require_episode(plan_id, node_id)
        if state.rerun_started_at is None:
            raise PrrRefused(
                "RERUN_WITHOUT_START",
                f"{node_id} 没有 RERUN_STARTED：无法证明真的重跑过",
            )
        if state.rerun_completed_at is not None:
            raise PrrRefused("RERUN_ALREADY_COMPLETED", f"{node_id} 已完成重跑")
        state.rerun_completed_at = _utc_z(at)
        state.status = EpisodeStatus.RERUN_COMPLETED
        self._append(
            plan_id=plan_id,
            node_id=node_id,
            event_type=PrrEventType.RERUN_COMPLETED,
            at=at,
            detail={"run_id": run_id, "rerun": dict(rerun.as_detail())},
        )
        # 完成后立即比较；随机节点按保守方向记 changed=True。
        self._compare(state, rerun, at, plan_id)
        return state.snapshot()

    def record_rerun_failed(
        self,
        *,
        plan_id: str,
        node_id: str,
        at: datetime,
        reason: str,
    ) -> PrrEntry:
        """重跑失败：进 `unresolved`，不进分母。"""
        state = self._require_episode(plan_id, node_id)
        if state.rerun_started_at is None:
            raise PrrRefused("RERUN_WITHOUT_START", f"{node_id} 没有 RERUN_STARTED")
        state.status = EpisodeStatus.RERUN_FAILED
        self._append(
            plan_id=plan_id,
            node_id=node_id,
            event_type=PrrEventType.RERUN_FAILED,
            at=at,
            detail={"reason": reason},
        )
        return state.snapshot()

    def _compare(
        self,
        state: _EpisodeState,
        rerun: ResultFingerprint,
        at: datetime,
        plan_id: str,
    ) -> None:
        """逐项比较并写入 changed / basis / differences。"""
        if state.is_stochastic:
            # 随机节点的方差不是「没变化」：一律按保守方向记 changed=True，并标违规。
            state.changed = True
            state.basis = ComparisonBasis.STOCHASTIC_CONSERVATIVE
            state.differences = ("stochastic_node",)
            state.violations.append("PRUNED_STOCHASTIC_NODE")
            self._append(
                plan_id=plan_id,
                node_id=state.node_id,
                event_type=PrrEventType.RESULT_COMPARED,
                at=at,
                detail={"changed": True, "basis": state.basis.value, "violation": "PRUNED_STOCHASTIC_NODE"},
            )
            return
        if state.baseline is None:
            raise PrrRefused(
                "BASELINE_MISSING",
                f"{state.node_id} 没有剪枝前的结果指纹，无法判断是否变化",
            )
        differences = state.baseline.diff(rerun)
        state.changed = bool(differences)
        state.basis = ComparisonBasis.EXACT_FINGERPRINT
        state.differences = differences
        self._append(
            plan_id=plan_id,
            node_id=state.node_id,
            event_type=PrrEventType.RESULT_COMPARED,
            at=at,
            detail={"changed": state.changed, "differences": list(differences)},
        )

    def record_correction(
        self,
        *,
        plan_id: str,
        node_id: str,
        at: datetime,
        note: str,
        evidence_ids: tuple[str, ...] = (),
    ) -> PrrEntry:
        """纠错：只追加说明，**不改**历史行的 changed。"""
        state = self._require_episode(plan_id, node_id)
        if not note.strip():
            raise PrrRefused("CORRECTION_NOTE_MISSING", "纠错必须写明原因")
        self._append(
            plan_id=plan_id,
            node_id=node_id,
            event_type=PrrEventType.CORRECTION,
            at=at,
            detail={"note": note, "evidence_ids": list(evidence_ids)},
        )
        return state.snapshot()

    # -- 查询 ---------------------------------------------------------------
    def _require_episode(self, plan_id: str, node_id: str) -> _EpisodeState:
        state = self._episodes.get((plan_id, node_id))
        if state is None:
            raise PrrRefused("PRUNING_RECORD_MISSING", f"未登记 {plan_id}/{node_id}")
        return state

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def events(self) -> tuple[PrrEvent, ...]:
        return tuple(self._events)

    def episodes(self, plan_id: str) -> tuple[PrrEntry, ...]:
        """按计划取全部行（保持登记顺序，便于与 DAG 对照）。"""
        return tuple(
            state.snapshot() for (pid, _), state in self._episodes.items() if pid == plan_id
        )

    def report(self, plan_id: str) -> PrrReport:
        """产出单计划报告。不做跨计划合并。"""
        rows = self.episodes(plan_id)
        if not rows:
            raise PrrRefused("EMPTY_PLAN", f"计划 {plan_id} 没有剪枝记录，不能出报告")
        completed = sum(1 for row in rows if row.counted_in_denominator)
        changed = sum(1 for row in rows if row.counted_in_denominator and row.changed)
        unresolved = sum(1 for row in rows if not row.resolved)
        stochastic = sum(1 for row in rows if row.is_stochastic)
        violations: list[str] = []
        for row in rows:
            violations.extend(row.violations)
        return PrrReport(
            task_id=self._task_id,
            plan_id=plan_id,
            rows=rows,
            pruned=len(rows),
            rerun_completed=completed,
            changed=changed,
            unresolved=unresolved,
            stochastic_rows=stochastic,
            violations=tuple(sorted(set(violations))),
        )


# ---------------------------------------------------------------------------
# 6. 静态守卫（实现阶段用；P9 不执行）
# ---------------------------------------------------------------------------
def _probe_entry(node_id: str, status: EpisodeStatus, *, changed: bool) -> PrrEntry:
    """构造一行合法的探针台账，供守卫函数使用（不写台账、不产事件）。"""
    authorization = PruningAuthorization(spa_id="spa_probe", dc_id="dc_probe", recovery_plan_id="plan_probe")
    started = "2026-11-11T00:10:00Z" if status is not EpisodeStatus.PRUNED else None
    completed = "2026-11-11T00:20:00Z" if status is EpisodeStatus.RERUN_COMPLETED else None
    basis = (
        ComparisonBasis.EXACT_FINGERPRINT
        if status is EpisodeStatus.RERUN_COMPLETED
        else ComparisonBasis.NONE
    )
    return PrrEntry(
        node_id=node_id,
        status=status,
        authorization=authorization,
        pruned_at="2026-11-11T00:00:00Z",
        rerun_started_at=started,
        rerun_completed_at=completed,
        changed=changed,
        comparison_basis=basis,
        differences=("state",) if changed else (),
    )


def assert_denominator_policy() -> tuple[str, ...]:
    """分母只含已完成重跑；覆盖率不足不给点估计；0/72 上界对齐 4.99%。"""
    problems: list[str] = []
    upper = clopper_pearson_upper(0, 72)
    if not (0.0490 <= upper <= 0.0510):
        problems.append(f"0/72 上界={upper:.4f}，期望 ≈0.0499")
    if clopper_pearson_upper(0, 10) <= clopper_pearson_upper(0, 72):
        problems.append("样本越少上界应越大")
    report = PrrReport(
        task_id="task_1",
        plan_id="plan_1",
        rows=(),
        pruned=0,
        rerun_completed=0,
        changed=0,
        unresolved=0,
        stochastic_rows=0,
    )
    if report.coverage != 0.0:
        problems.append("无剪枝时覆盖率应为 0.0")
    if report.point_estimate is not None:
        problems.append("无剪枝时不得给点估计")
    if report.cp_upper is not None:
        problems.append("无分母时不得给上界")
    return tuple(problems)


def assert_no_zero_without_denominator() -> tuple[str, ...]:
    """没有分母时不得报 0；报告必须区分「0/0」与「0/n」。"""
    problems: list[str] = []
    try:
        clopper_pearson_upper(0, 0)
    except PrrRefused:
        pass
    else:
        problems.append("n=0 时未拒绝计算上界")
    partial = PrrReport(
        task_id="task_1",
        plan_id="plan_1",
        rows=(
            _probe_entry("n1", EpisodeStatus.RERUN_COMPLETED, changed=False),
            _probe_entry("n2", EpisodeStatus.PRUNED, changed=False),
            _probe_entry("n3", EpisodeStatus.PRUNED, changed=False),
            _probe_entry("n4", EpisodeStatus.PRUNED, changed=False),
        ),
        pruned=4,
        rerun_completed=1,
        changed=0,
        unresolved=3,
        stochastic_rows=0,
    )
    if partial.point_estimate is not None:
        problems.append("覆盖率 0.25 时仍给了点估计")
    if partial.coverage != 0.25:
        problems.append(f"覆盖率={partial.coverage}，期望 0.25")
    return tuple(problems)


def assert_no_cross_task_merge() -> tuple[str, ...]:
    """台账不得提供跨任务合并/聚合入口。"""
    problems: list[str] = []
    for forbidden in ("merge", "aggregate", "combine", "union", "concat"):
        if hasattr(PrrLedger, forbidden):
            problems.append(f"PrrLedger 暴露了 {forbidden}")
    if hasattr(PrrReport, "merge"):
        problems.append("PrrReport 暴露了 merge")
    return tuple(problems)


def assert_prr_records_raw() -> tuple[str, ...]:
    """逐节点原始行必须完整：授权、时间、比较依据、差异都不许缺。"""
    problems: list[str] = []
    required = {
        "node_id",
        "status",
        "authorization",
        "pruned_at",
        "rerun_started_at",
        "rerun_completed_at",
        "changed",
        "comparison_basis",
        "differences",
        "is_stochastic",
        "violations",
        "evidence_ids",
    }
    missing = required - set(PrrEntry.__dataclass_fields__)
    if missing:
        problems.append(f"PrrEntry 缺字段：{sorted(missing)}")
    if "spa_id" not in PruningAuthorization.__dataclass_fields__:
        problems.append("授权缺 spa_id")
    if "dc_id" not in PruningAuthorization.__dataclass_fields__:
        problems.append("授权缺 dc_id")
    return tuple(problems)