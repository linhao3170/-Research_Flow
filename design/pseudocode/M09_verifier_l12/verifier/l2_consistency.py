"""MODULE: M09 · verifier/l2_consistency.py — L2 结果自洽复核（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-007、策划书 §9.1 L2/§9.2、05 §5/§13
FR/依赖: FR-007；依赖 M09 metric_recompute（指标口径）、M09 leakage_rules（R1–R5）、
        M09 l1_integrity（CheckStatus）、M06 Split Manifest/模板产物
不变量/错误码: L2 只读 predictions/metrics/split/dataset；指标必须由 predictions 重算；
             混淆矩阵必须交叉校验；五条泄漏规则任一 FAIL/NOT_EVALUABLE → L2 FAIL；
             **L2 PASS 只表示内部自洽，不表示真实执行**；L2 不得输出 VERIFIED。
             错误码：SCHEMA_INVALID（422）、REQUIRED_EVIDENCE_MISSING（409）、BUNDLE_TAMPERED（422）
写入者: **无**；Verifier 只读，不写证据/状态/报告
状态: 伪代码；不建环境、不跑测试、不写业务代码

## L2 能证明什么、不能证明什么（写死）

  **能证明**（以 predictions 为起点）：
  1. predictions 恰好覆盖 test 行、fold=1、y_true 与数据行标签一致；
  2. metrics 的五个指标能由 predictions + 标签重算并落在容差内；
  3. 混淆矩阵与 predictions 的逐行计数一致；
  4. R1–R5 五条泄漏规则在当前输入上可计算且未命中。

  **不能证明**：
  - predictions 是模型真实产生的（成套伪造可以让 predictions/metrics/混淆矩阵完全自洽）；
  - 模型真的被训练过、代码真的执行过；
  - 隐藏的/未声明的泄漏方式不存在。

  因此 L2 PASS 的唯一准确表述是“**结果自洽**”；把 L2 PASS 写成“已验证真实执行”
  是契约违反。真实执行只能由 L3 独立重跑支持（且仍只支持同环境独立重执行）。

## 检查顺序

  `L2-PREDICTIONS-COVERAGE` → `L2-FIELD-SEMANTICS` → `L2-METRICS-RECOMPUTE`
  → `L2-CONFUSION-CROSSCHECK` → `L2-LEAKAGE-R1..R5`。
  前一项失败不阻断后一项（便于一次收集全部缺口），但 L2 结论只有一个 FAIL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Mapping

from .l1_integrity import CheckStatus
from .leakage_rules import (
    DatasetTable,
    LeakageContext,
    LeakageReport,
    MetricsArtifactView,
    NearDuplicateSpec,
    PredictionsArtifactView,
    RuleStatus,
    SplitAssignment,
    SplitManifestView,
    evaluate_all,
)
from .metric_recompute import (
    METRIC_NAMES,
    MetricMismatch,
    MetricSet,
    PredictionError,
    compare_metrics,
    confusion_matrix,
    recompute_all,
)

__all__ = [
    "L2_DOES_NOT_PROVE",
    "L2_PROVES",
    "L2Check",
    "L2ConsistencyVerifier",
    "L2Gap",
    "L2Input",
    "L2Result",
    "assert_l2_boundary",
]

L2_PROVES: Final[tuple[str, ...]] = (
    "predictions 覆盖 test 行且字段语义一致",
    "metrics 可由 predictions 重算并落在容差内",
    "混淆矩阵与逐行预测一致",
    "R1–R5 泄漏规则在给定输入上可计算且未命中",
)
L2_DOES_NOT_PROVE: Final[tuple[str, ...]] = (
    "predictions 是模型真实产生",
    "模型被真实训练/执行",
    "不存在未声明的泄漏方式",
)
EXECUTION_CLAIM_SELF_CONSISTENT: Final[str] = "SELF_CONSISTENT_ONLY"


class L2Error(RuntimeError):
    """L2 程序性错误；常规缺口写 L2Gap/check，不抛异常。"""

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


@dataclass(frozen=True, slots=True)
class L2Input:
    """L2 的只读输入；`model_key` 指定本次评估的模型。"""

    task_id: str
    model_key: str
    predictions: PredictionsArtifactView
    metrics: MetricsArtifactView
    split: SplitAssignment
    manifest: SplitManifestView
    dataset: DatasetTable
    feature_whitelist: tuple[str, ...] | None = None
    feature_time_columns: tuple[str, ...] = ()
    near_duplicate: NearDuplicateSpec = NearDuplicateSpec()
    correlation_threshold: float = 0.999

    def __post_init__(self) -> None:
        if not self.task_id.startswith("task_"):
            raise L2Error("SCHEMA_INVALID", "TASK_ID_INVALID", "task_id 形态非法", field_path="task_id")
        if not self.model_key:
            raise L2Error("SCHEMA_INVALID", "MODEL_KEY_EMPTY", "model_key 不得为空", field_path="model_key")


@dataclass(frozen=True, slots=True)
class L2Gap:
    code: str
    error_code: str
    check_id: str
    message: str
    detail: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class L2Check:
    check_id: str
    status: CheckStatus
    message: str
    expected: str = ""
    actual: str = ""
    detail: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class L2Result:
    """L2 结论；`execution_claim` 固定为 SELF_CONSISTENT_ONLY。"""

    status: CheckStatus
    checks: tuple[L2Check, ...]
    gaps: tuple[L2Gap, ...]
    recomputed: MetricSet | None
    mismatches: tuple[MetricMismatch, ...]
    leakage: LeakageReport | None
    execution_claim: str = EXECUTION_CLAIM_SELF_CONSISTENT

    def failures(self) -> tuple[L2Check, ...]:
        return tuple(check for check in self.checks if check.status is CheckStatus.FAIL)

    @property
    def l2_status(self) -> str:
        """报告字段 `l2_status` 的投影；只允许 PASS/FAIL/SKIP/NOT_RUN。"""
        return self.status.value

    def assert_not_execution_proof(self) -> None:
        """L2 PASS 不能被当成“真实执行”。出现这种字段/声明即契约破坏。"""
        if self.execution_claim != EXECUTION_CLAIM_SELF_CONSISTENT:
            raise L2Error(
                "SCHEMA_INVALID", "L2_CLAIMS_EXECUTION",
                f"L2 只能声明 {EXECUTION_CLAIM_SELF_CONSISTENT!r}，实际 {self.execution_claim!r}",
                field_path="execution_claim",
            )
        if self.status is CheckStatus.PASS and self.execution_claim == "VERIFIED_EXECUTION":
            raise L2Error(
                "SCHEMA_INVALID", "L2_PASS_AS_EXECUTION",
                "L2 通过不等于真实执行", field_path="status",
            )


class L2ConsistencyVerifier:
    """L2 五项/多子项复核；纯只读、确定性。"""

    CHECK_COVERAGE: Final[str] = "L2-PREDICTIONS-COVERAGE"
    CHECK_SEMANTICS: Final[str] = "L2-FIELD-SEMANTICS"
    CHECK_METRICS: Final[str] = "L2-METRICS-RECOMPUTE"
    CHECK_CONFUSION: Final[str] = "L2-CONFUSION-CROSSCHECK"
    CHECK_LEAKAGE_PREFIX: Final[str] = "L2-LEAKAGE-"
    CHECK_ORDER: Final[tuple[str, ...]] = (
        CHECK_COVERAGE, CHECK_SEMANTICS, CHECK_METRICS, CHECK_CONFUSION,
    )

    def run(self, l2_input: L2Input) -> L2Result:
        """执行全部检查；FAIL 不早停，便于一次列出所有缺口。"""
        checks: list[L2Check] = []
        gaps: list[L2Gap] = []
        recomputed: MetricSet | None = None
        mismatches: tuple[MetricMismatch, ...] = ()
        leakage: LeakageReport | None = None

        coverage_check = self._check_predictions_coverage(l2_input)
        checks.append(coverage_check)
        if coverage_check.status is CheckStatus.FAIL:
            gaps.append(self._gap("PREDICTIONS_COVERAGE", "REQUIRED_EVIDENCE_MISSING",
                                  coverage_check.check_id, coverage_check.message,
                                  {"actual": coverage_check.actual}))

        semantics_check = self._check_field_semantics(l2_input)
        checks.append(semantics_check)
        if semantics_check.status is CheckStatus.FAIL:
            gaps.append(self._gap("FIELD_SEMANTICS", "SCHEMA_INVALID",
                                  semantics_check.check_id, semantics_check.message,
                                  {"actual": semantics_check.actual}))

        metrics_check, recomputed, mismatches = self._check_metrics_recompute(l2_input)
        checks.append(metrics_check)
        if metrics_check.status is CheckStatus.FAIL:
            gaps.append(self._gap("METRICS_NOT_RECOMPUTABLE", "REQUIRED_EVIDENCE_MISSING",
                                  metrics_check.check_id, metrics_check.message,
                                  {"mismatches": [m.reason + ":" + m.metric for m in mismatches]}))

        confusion_check = self._check_confusion(l2_input)
        checks.append(confusion_check)
        if confusion_check.status is CheckStatus.FAIL:
            gaps.append(self._gap("CONFUSION_MISMATCH", "REQUIRED_EVIDENCE_MISSING",
                                  confusion_check.check_id, confusion_check.message,
                                  {"actual": confusion_check.actual}))

        leakage_checks, leakage = self._check_leakage(l2_input)
        checks.extend(leakage_checks)
        for check in leakage_checks:
            if check.status is CheckStatus.FAIL:
                gaps.append(self._gap("LEAKAGE_RULE_FAILED", "REQUIRED_EVIDENCE_MISSING",
                                      check.check_id, check.message,
                                      dict(check.detail)))

        status = CheckStatus.FAIL if any(
            check.status is CheckStatus.FAIL for check in checks
        ) else CheckStatus.PASS
        result = L2Result(
            status=status,
            checks=tuple(checks),
            gaps=tuple(gaps),
            recomputed=recomputed,
            mismatches=mismatches,
            leakage=leakage,
        )
        result.assert_not_execution_proof()
        return result

    # -- 1. 覆盖 ----------------------------------------------------------
    def _check_predictions_coverage(self, l2_input: L2Input) -> L2Check:
        """predictions 行集 == test 行集；fold=1；y_true 与数据标签一致；n_test 一致。"""
        predictions = l2_input.predictions
        row_ids = tuple(row.row_id for row in predictions.rows)
        if len(set(row_ids)) != len(row_ids):
            return L2Check(
                self.CHECK_COVERAGE, CheckStatus.FAIL, "predictions 有重复 row_id",
                actual=f"{len(row_ids)} rows, {len(set(row_ids))} unique",
            )
        expected = set(l2_input.split.test_row_ids)
        actual = set(row_ids)
        if actual != expected:
            return L2Check(
                self.CHECK_COVERAGE, CheckStatus.FAIL,
                "predictions 行集与 test 行集不一致",
                expected=f"{len(expected)} test rows", actual=f"{len(actual)} prediction rows",
                detail={
                    "missing": sorted(expected - actual)[:10],
                    "extra": sorted(actual - expected)[:10],
                },
            )
        bad_fold = [row.row_id for row in predictions.rows if row.fold != 1]
        if bad_fold:
            return L2Check(
                self.CHECK_COVERAGE, CheckStatus.FAIL, "predictions 含非 test fold 行",
                actual=", ".join(bad_fold[:10]),
            )
        targets = [column.name for column in l2_input.dataset.columns if column.role == "target"]
        if len(targets) != 1:
            return L2Check(
                self.CHECK_COVERAGE, CheckStatus.FAIL, "数据集必须恰好一个 target 列",
                actual=str(targets),
            )
        target = targets[0]
        by_id = l2_input.dataset.by_id()
        bad_labels: list[str] = []
        for row in predictions.rows:
            dataset_row = by_id.get(row.row_id)
            if dataset_row is None:
                return L2Check(
                    self.CHECK_COVERAGE, CheckStatus.FAIL, "predictions 引用了数据集不存在的行",
                    actual=row.row_id,
                )
            if str(dataset_row[target]) != row.y_true:
                bad_labels.append(row.row_id)
        if bad_labels:
            return L2Check(
                self.CHECK_COVERAGE, CheckStatus.FAIL, "y_true 与数据集标签不一致",
                actual=", ".join(bad_labels[:10]),
            )
        if l2_input.metrics.n_test != len(expected):
            return L2Check(
                self.CHECK_COVERAGE, CheckStatus.FAIL, "metrics.n_test 与 test 行数不一致",
                expected=str(len(expected)), actual=str(l2_input.metrics.n_test),
            )
        return L2Check(
            self.CHECK_COVERAGE, CheckStatus.PASS,
            f"predictions 覆盖全部 {len(expected)} 条 test 行，fold=1，标签一致",
        )

    # -- 2. 字段语义 ------------------------------------------------------
    def _check_field_semantics(self, l2_input: L2Input) -> L2Check:
        """列白名单、模型列、预测标签与 metrics.labels 一致。"""
        columns = set(l2_input.predictions.columns)
        required = {"row_id", "fold", "y_true"}
        missing = required - columns
        if missing:
            return L2Check(
                self.CHECK_SEMANTICS, CheckStatus.FAIL, "predictions 缺少必需列",
                actual=str(sorted(missing)),
            )
        allowed_exact = {"row_id", "fold", "y_true"}
        unknown = [
            name for name in columns
            if name not in allowed_exact
            and not name.startswith("pred_")
            and not name.startswith("score_")
        ]
        if unknown:
            return L2Check(
                self.CHECK_SEMANTICS, CheckStatus.FAIL,
                "predictions 含未声明列（可能隐藏指标/标签）",
                actual=str(sorted(unknown)),
            )
        model_column = f"pred_{l2_input.model_key}"
        if model_column not in columns and "prediction" not in columns:
            return L2Check(
                self.CHECK_SEMANTICS, CheckStatus.FAIL, "缺少当前模型的预测列",
                expected=model_column, actual=str(sorted(columns)),
            )
        labels = set(l2_input.metrics.labels)
        bad = sorted({row.y_pred for row in l2_input.predictions.rows} - labels)
        if bad:
            return L2Check(
                self.CHECK_SEMANTICS, CheckStatus.FAIL,
                "predictions 含 metrics.labels 之外的预测标签",
                actual=str(bad),
            )
        for row in l2_input.predictions.rows:
            if row.scores is None:
                continue
            extra = sorted(set(row.scores) - labels)
            if extra:
                return L2Check(
                    self.CHECK_SEMANTICS, CheckStatus.FAIL,
                    "scores 含 metrics.labels 之外的标签",
                    actual=str(extra),
                )
        return L2Check(
            self.CHECK_SEMANTICS, CheckStatus.PASS, "字段语义与列白名单一致",
        )

    # -- 3. 指标重算 ------------------------------------------------------
    def _check_metrics_recompute(
        self, l2_input: L2Input,
    ) -> tuple[L2Check, MetricSet | None, tuple[MetricMismatch, ...]]:
        """从 predictions 重算五指标；与 metrics.values 逐项比较。"""
        try:
            # 不传 labels：让 recompute_all 用 sorted(observed) 自行解析标签集合。
            # 这样 metrics.labels 的顺序错误才会被下面的显式比较抓到，而不是被
            # “传入即同序”抵消。
            recomputed = recompute_all(l2_input.predictions.rows)
        except PredictionError as exc:
            return (
                L2Check(
                    self.CHECK_METRICS, CheckStatus.FAIL, f"指标无法重算：{exc}",
                    actual=exc.reason,
                ),
                None,
                (),
            )
        if tuple(recomputed.labels) != tuple(l2_input.metrics.labels):
            return (
                L2Check(
                    self.CHECK_METRICS, CheckStatus.FAIL, "重算标签顺序与 metrics.labels 不一致",
                    expected=str(l2_input.metrics.labels), actual=str(recomputed.labels),
                ),
                recomputed,
                (),
            )
        mismatches = compare_metrics(l2_input.metrics.values, recomputed)
        if mismatches:
            return (
                L2Check(
                    self.CHECK_METRICS, CheckStatus.FAIL,
                    f"metrics 与重算结果有 {len(mismatches)} 项不一致",
                    actual="; ".join(f"{m.metric}:{m.reason}" for m in mismatches[:10]),
                ),
                recomputed,
                mismatches,
            )
        return (
            L2Check(
                self.CHECK_METRICS, CheckStatus.PASS,
                "五个指标均可由 predictions 重算",
                detail={"n_test": recomputed.n_test},
            ),
            recomputed,
            (),
        )

    # -- 4. 混淆矩阵 ------------------------------------------------------
    def _check_confusion(self, l2_input: L2Input) -> L2Check:
        """混淆矩阵逐格比对；先查 reported 行列和，再比 recomputed 与 reported。"""
        reported = l2_input.metrics.confusion
        if reported is None:
            return L2Check(
                self.CHECK_CONFUSION, CheckStatus.FAIL,
                "metrics 缺少 confusion：无法完成混淆矩阵交叉校验",
            )
        try:
            recomputed = confusion_matrix(
                l2_input.predictions.rows, l2_input.metrics.labels,
            )
        except PredictionError as exc:
            return L2Check(
                self.CHECK_CONFUSION, CheckStatus.FAIL, f"混淆矩阵无法重算：{exc}",
                actual=exc.reason,
            )
        n_test = l2_input.metrics.n_test
        # 先按 reported 查行列和：行和错误给 detail.row，列和错误给 detail.column，
        # 不会被后面的“整矩阵不等”抢先捕获。
        for index, row in enumerate(reported):
            if sum(row) != n_test:
                return L2Check(
                    self.CHECK_CONFUSION, CheckStatus.FAIL, "混淆矩阵行和 != n_test",
                    expected=str(n_test), actual=str(sum(row)),
                    detail={"row": index},
                )
        for column in range(len(reported)):
            total = sum(reported[row][column] for row in range(len(reported)))
            if total != n_test:
                return L2Check(
                    self.CHECK_CONFUSION, CheckStatus.FAIL, "混淆矩阵列和 != n_test",
                    expected=str(n_test), actual=str(total),
                    detail={"column": column},
                )
        if recomputed != reported:
            return L2Check(
                self.CHECK_CONFUSION, CheckStatus.FAIL, "混淆矩阵与逐行预测不一致",
                expected=str(recomputed), actual=str(reported),
            )
        # 第二道：对重算矩阵再做行/列和检查。
        for index, row in enumerate(recomputed):
            if sum(row) != n_test:
                return L2Check(
                    self.CHECK_CONFUSION, CheckStatus.FAIL, "混淆矩阵行和 != n_test",
                    expected=str(n_test), actual=str(sum(row)),
                    detail={"row": index},
                )
        for column in range(len(recomputed)):
            total = sum(recomputed[row][column] for row in range(len(recomputed)))
            if total != n_test:
                return L2Check(
                    self.CHECK_CONFUSION, CheckStatus.FAIL, "混淆矩阵列和 != n_test",
                    expected=str(n_test), actual=str(total),
                    detail={"column": column},
                )
        return L2Check(
            self.CHECK_CONFUSION, CheckStatus.PASS, "混淆矩阵逐格一致，行列和 = n_test",
        )

    # -- 5. 泄漏五规则 ----------------------------------------------------
    def _check_leakage(self, l2_input: L2Input) -> tuple[tuple[L2Check, ...], LeakageReport | None]:
        """调用 R1–R5；NOT_EVALUABLE 按 FAIL 处理（fail-closed）。"""
        try:
            context = LeakageContext(
                dataset=l2_input.dataset,
                split=l2_input.split,
                manifest=l2_input.manifest,
                feature_whitelist=l2_input.feature_whitelist,
                feature_time_columns=l2_input.feature_time_columns,
                near_duplicate=l2_input.near_duplicate,
                correlation_threshold=l2_input.correlation_threshold,
                metrics=l2_input.metrics,
                predictions=l2_input.predictions,
            )
        except ValueError as exc:
            return (
                (
                    L2Check(
                        self.CHECK_LEAKAGE_PREFIX + "CONTEXT", CheckStatus.FAIL,
                        f"泄漏检测输入非法：{exc}", actual=str(exc),
                    ),
                ),
                None,
            )
        report = evaluate_all(context)
        checks: list[L2Check] = []
        for finding in report.findings:
            if finding.status is RuleStatus.PASS:
                status = CheckStatus.PASS
            elif finding.status is RuleStatus.NOT_APPLICABLE:
                status = CheckStatus.PASS
            else:
                status = CheckStatus.FAIL
            checks.append(L2Check(
                check_id=self.CHECK_LEAKAGE_PREFIX + finding.rule_id,
                status=status,
                message=f"{finding.code}: {finding.message}",
                expected=finding.criterion,
                actual=finding.status.value,
                detail={
                    "rule_status": finding.status.value,
                    "not_applicable": finding.status is RuleStatus.NOT_APPLICABLE,
                    **dict(finding.detail),
                },
            ))
        return tuple(checks), report

    @staticmethod
    def _gap(
        code: str,
        error_code: str,
        check_id: str,
        message: str,
        detail: Mapping[str, object],
    ) -> L2Gap:
        return L2Gap(
            code=code, error_code=error_code, check_id=check_id,
            message=message, detail=MappingProxyType(dict(detail)),
        )


def assert_l2_boundary() -> list[str]:
    """L2 不得训练模型、读原运行目录、把自洽写成执行证明。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("subprocess", "Popen", "fit", "predict", "Gate", "StateMachine"):
        if hasattr(module, attr):
            problems.append(f"l2_consistency 暴露禁用名 {attr!r}")
    if L2_PROVES == L2_DOES_NOT_PROVE:
        problems.append("L2 的能/不能证明声明被混同")
    if EXECUTION_CLAIM_SELF_CONSISTENT != "SELF_CONSISTENT_ONLY":
        problems.append("L2 execution_claim 被改动")
    if "VERIFIED" in CheckStatus.__members__:
        problems.append("L2 不得使用 VERIFIED 状态")
    return problems