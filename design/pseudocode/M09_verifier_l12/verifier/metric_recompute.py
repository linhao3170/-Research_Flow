"""MODULE: M09 · verifier/metric_recompute.py — 指标重算算法与边界（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-004/FR-007、策划书 §9.1/§9.2 R5、05 §5
FR/依赖: FR-007（L2/L3 指标重算）；依赖 M06 模板的 predictions 五列口径、M01 数值规则
不变量/错误码: 只接受 test fold 的逐行预测；指标定义固定为 5 个；macro 平均标签集合固定；
             AUC 单类/缺分数 = UNDEFINED（不得写 0.0 冒充）；禁用 NaN/Infinity；重复 row_id 拒绝。
             错误码：SCHEMA_INVALID（422，输入形态/标签/数值非法）、REQUIRED_EVIDENCE_MISSING（409，指标不可重算）
写入者: **无**；纯计算，不读文件、不写证据、不判 PASS/FAIL
状态: 伪代码；sklearn 调用只标 `# LIB:`，本文件不 import sklearn、不执行

## 五个指标的口径（与 M06 模板逐字对齐）

  | 指标 | 定义 | 边界 |
  |---|---|---|
  | `accuracy` | 正确行 / n_test | n_test=0 → 拒绝，不写 0 |
  | `precision_macro` | 对标签集合 L 逐类 P，再取算术平均 | 分母 0 → P=0（零除策略固定为 0） |
  | `recall_macro` | 对 L 逐类 R，再平均 | 同上 |
  | `f1_macro` | 对 L 逐类 F1=2PR/(P+R)，再平均 | P+R=0 → F1=0 |
  | `roc_auc_ovr` | 对 L 逐类 one-vs-rest AUC，再 macro 平均 | 任一类只有正/负样本 → 整体 UNDEFINED |

  L 的默认取值是 `sorted(set(y_true) ∪ set(y_pred))`；调用方可传入显式 labels，
  但必须是二者并集的超集。排序是为了跨实现稳定；数组顺序不参与指标语义。

## 为什么 AUC 不能“缺了就写 0”

  0.0 表示“比随机猜还差”，是一个有信息的值；`UNDEFINED` 表示“这个指标在此数据上
  没有定义”。把二者混同会让 L2/Gate 把“没算出来”当成“算出来且很差”，
  也会让伪造者用 0.0 通过“数值有限”的检查。因此本文件用 `MetricSet.undefined`
  单独记录不可计算项，比较函数对它一律报 `METRIC_UNDEFINED`。

## AUC 的 tie 处理

  `roc_auc_binary` 用 Mann–Whitney 秩和：同分记平均秩。全部分数相同 → AUC=0.5（不是 1.0）；
  单类标签 → UNDEFINED。`roc_auc_ovr` 对每一类调用同一实现，任一类 UNDEFINED 则整体 UNDEFINED。
  这与 sklearn `roc_auc_score(..., multi_class="ovr", average="macro")` 的宏观口径一致；
  但本文件不 import sklearn，P5 只钉算法与边界，落地时用标准库实现并与 sklearn 对拍。

## 比较容差

  L2 重算与产物指标来自同一批 predictions，理论上应相同；浮点求和顺序可能不同，
  因此允许 `abs_tol=1e-12`、`rel_tol=1e-9`。L3 的确定性模式**不使用**这个容差：
  L3 用 bit-exact 比较（见 M10），本文件只提供 `bit_identical()` 供其调用。
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

__all__ = [
    "FOLD_TEST",
    "FOLD_TRAIN",
    "METRIC_ABS_TOL",
    "METRIC_NAMES",
    "METRIC_REL_TOL",
    "MetricDefinition",
    "MetricMismatch",
    "MetricName",
    "MetricSet",
    "PredictionError",
    "PredictionRow",
    "accuracy",
    "assert_metric_boundary",
    "bit_identical",
    "compare_metrics",
    "confusion_matrix",
    "precision_recall_f1_macro",
    "recompute_all",
    "roc_auc_binary",
    "roc_auc_ovr",
]

FOLD_TRAIN: Final[int] = 0
FOLD_TEST: Final[int] = 1
METRIC_ABS_TOL: Final[float] = 1e-12
METRIC_REL_TOL: Final[float] = 1e-9
METRIC_NAMES: Final[tuple[str, ...]] = (
    "accuracy",
    "precision_macro",
    "recall_macro",
    "f1_macro",
    "roc_auc_ovr",
)


class MetricName(StrEnum):
    ACCURACY = "accuracy"
    PRECISION_MACRO = "precision_macro"
    RECALL_MACRO = "recall_macro"
    F1_MACRO = "f1_macro"
    ROC_AUC_OVR = "roc_auc_ovr"


class PredictionError(RuntimeError):
    """predictions 不满足重算前提；对外码按语义选 SCHEMA_INVALID 或 REQUIRED_EVIDENCE_MISSING。"""

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
# 1. 输入与输出
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PredictionRow:
    """一行测试折预测。

    `scores` 是 `label -> score`；AUC 需要它。`y_pred` 是硬标签。
    `fold` 只允许 0/1；L2 只接受 1（test），训练折预测不得进入指标。
    """

    row_id: str
    fold: int
    y_true: str
    y_pred: str
    scores: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.row_id, str) or not self.row_id:
            raise PredictionError(
                "SCHEMA_INVALID", "ROW_ID_EMPTY", "row_id 不得为空", field_path="row_id",
            )
        if isinstance(self.fold, bool) or self.fold not in (FOLD_TRAIN, FOLD_TEST):
            raise PredictionError(
                "SCHEMA_INVALID", "FOLD_INVALID", "fold 只允许 0/1", field_path="fold",
            )
        if not isinstance(self.y_true, str) or not self.y_true:
            raise PredictionError(
                "SCHEMA_INVALID", "Y_TRUE_EMPTY", "y_true 不得为空", field_path="y_true",
            )
        if not isinstance(self.y_pred, str) or not self.y_pred:
            raise PredictionError(
                "SCHEMA_INVALID", "Y_PRED_EMPTY", "y_pred 不得为空", field_path="y_pred",
            )
        if self.scores is not None:
            for label, value in self.scores.items():
                if not isinstance(label, str) or not label:
                    raise PredictionError(
                        "SCHEMA_INVALID", "SCORE_LABEL_INVALID",
                        "score 的标签必须是非空字符串", field_path="scores",
                    )
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise PredictionError(
                        "SCHEMA_INVALID", "SCORE_TYPE",
                        f"score[{label}] 必须是 number", field_path=f"scores.{label}",
                    )
                if not math.isfinite(float(value)):
                    raise PredictionError(
                        "SCHEMA_INVALID", "SCORE_NON_FINITE",
                        f"score[{label}] 不得为 NaN/Infinity", field_path=f"scores.{label}",
                    )


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """指标定义；`requires_scores` 的项在没有 scores 时记为 UNDEFINED。"""

    name: str
    requires_scores: bool
    average: str = "macro"
    zero_division: int = 0

    def __post_init__(self) -> None:
        if self.name not in METRIC_NAMES:
            raise PredictionError(
                "SCHEMA_INVALID", "METRIC_NAME_UNKNOWN", f"未知指标 {self.name!r}", field_path="metric",
            )
        if self.average not in ("macro",):
            raise PredictionError(
                "SCHEMA_INVALID", "METRIC_AVERAGE_UNSUPPORTED",
                "T0 只支持 macro 平均", field_path="metric.average",
            )
        if self.zero_division not in (0, 1):
            raise PredictionError(
                "SCHEMA_INVALID", "ZERO_DIVISION_UNSUPPORTED",
                "zero_division 只允许 0/1（0 表示记 0 并计数）", field_path="metric.zero_division",
            )


@dataclass(frozen=True, slots=True)
class MetricSet:
    """一次重算的完整结果；不可计算项放 `undefined`，不放 0.0。"""

    values: Mapping[str, float]
    undefined: Mapping[str, str]
    n_test: int
    labels: tuple[str, ...]
    confusion: tuple[tuple[int, ...], ...]
    zero_division_hits: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.n_test, bool) or not isinstance(self.n_test, int) or self.n_test < 1:
            raise PredictionError(
                "SCHEMA_INVALID", "N_TEST_INVALID", "n_test 必须 ≥1", field_path="n_test",
            )
        if len(set(self.labels)) != len(self.labels) or not self.labels:
            raise PredictionError(
                "SCHEMA_INVALID", "LABELS_INVALID", "labels 必须非空且唯一", field_path="labels",
            )
        for name, value in self.values.items():
            if name not in METRIC_NAMES:
                raise PredictionError(
                    "SCHEMA_INVALID", "METRIC_NAME_UNKNOWN", f"未知指标 {name!r}", field_path="values",
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise PredictionError(
                    "SCHEMA_INVALID", "METRIC_VALUE_INVALID", f"{name} 必须是有限数", field_path=f"values.{name}",
                )
        for name in self.undefined:
            if name not in METRIC_NAMES:
                raise PredictionError(
                    "SCHEMA_INVALID", "METRIC_NAME_UNKNOWN", f"未知指标 {name!r}", field_path="undefined",
                )
        if set(self.values) & set(self.undefined):
            raise PredictionError(
                "SCHEMA_INVALID", "METRIC_BOTH_DEFINED_AND_UNDEFINED",
                "同一指标不得同时出现在 values 与 undefined", field_path="values",
            )
        size = len(self.labels)
        if len(self.confusion) != size or any(len(row) != size for row in self.confusion):
            raise PredictionError(
                "SCHEMA_INVALID", "CONFUSION_SHAPE", "混淆矩阵必须是 |labels|×|labels|",
                field_path="confusion",
            )


@dataclass(frozen=True, slots=True)
class MetricMismatch:
    metric: str
    expected: float | None
    actual: float | None
    reason: str
    delta: float | None = None


# ---------------------------------------------------------------------------
# 2. 基础量
# ---------------------------------------------------------------------------
def _float64_bits(value: float) -> bytes:
    """float64 的 IEEE-754 大端字节；L3 的 bit-exact 比较复用。"""
    return struct.pack(">d", float(value))


def bit_identical(left: float, right: float) -> bool:
    """两个 float 是否逐位相同（含 -0.0 与 +0.0 不等、NaN 不相等）。"""
    if math.isnan(left) or math.isnan(right):
        return False
    return _float64_bits(left) == _float64_bits(right)


def _require_rows(rows: Sequence[PredictionRow]) -> tuple[PredictionRow, ...]:
    if not rows:
        raise PredictionError(
            "REQUIRED_EVIDENCE_MISSING", "NO_PREDICTION_ROWS",
            "没有预测行可重算", field_path="predictions", http_status=409,
        )
    seen: set[str] = set()
    for row in rows:
        if row.fold != FOLD_TEST:
            raise PredictionError(
                "SCHEMA_INVALID", "NON_TEST_FOLD_ROW",
                f"指标只能从 test fold 重算；{row.row_id} 的 fold={row.fold}",
                field_path="fold",
            )
        if row.row_id in seen:
            raise PredictionError(
                "SCHEMA_INVALID", "ROW_ID_DUPLICATED",
                f"row_id 重复：{row.row_id}", field_path="row_id",
            )
        seen.add(row.row_id)
    return tuple(rows)


def _resolve_labels(
    rows: Sequence[PredictionRow],
    labels: Sequence[str] | None,
) -> tuple[str, ...]:
    observed = {row.y_true for row in rows} | {row.y_pred for row in rows}
    if labels is None:
        return tuple(sorted(observed))
    resolved = tuple(labels)
    if len(set(resolved)) != len(resolved):
        raise PredictionError(
            "SCHEMA_INVALID", "LABELS_DUPLICATED", "labels 不得重复", field_path="labels",
        )
    missing = sorted(observed - set(resolved))
    if missing:
        raise PredictionError(
            "SCHEMA_INVALID", "LABELS_INCOMPLETE",
            f"labels 未覆盖观测到的类别：{missing}", field_path="labels",
        )
    return resolved


def accuracy(rows: Sequence[PredictionRow]) -> float:
    """正确行 / 总行；调用前已保证非空。"""
    return sum(1 for row in rows if row.y_true == row.y_pred) / len(rows)


def confusion_matrix(
    rows: Sequence[PredictionRow],
    labels: Sequence[str],
) -> tuple[tuple[int, ...], ...]:
    """按 labels 顺序的混淆矩阵：行=y_true，列=y_pred。"""
    index = {label: i for i, label in enumerate(labels)}
    size = len(labels)
    matrix = [[0 for _ in range(size)] for _ in range(size)]
    for row in rows:
        if row.y_true not in index or row.y_pred not in index:
            raise PredictionError(
                "SCHEMA_INVALID", "LABEL_UNKNOWN",
                f"标签不在 labels 内：y_true={row.y_true!r}, y_pred={row.y_pred!r}",
                field_path="labels",
            )
        matrix[index[row.y_true]][index[row.y_pred]] += 1
    return tuple(tuple(row) for row in matrix)


def precision_recall_f1_macro(
    rows: Sequence[PredictionRow],
    labels: Sequence[str],
) -> tuple[float, float, float, tuple[str, ...]]:
    """逐类 P/R/F1 后 macro 平均；零除记 0 并返回命中项，便于 L2 记录。"""
    hits: list[str] = []
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    for label in labels:
        tp = sum(1 for row in rows if row.y_true == label and row.y_pred == label)
        fp = sum(1 for row in rows if row.y_true != label and row.y_pred == label)
        fn = sum(1 for row in rows if row.y_true == label and row.y_pred != label)
        if tp + fp == 0:
            precision = 0.0
            hits.append(f"precision:{label}")
        else:
            precision = tp / (tp + fp)
        if tp + fn == 0:
            recall = 0.0
            hits.append(f"recall:{label}")
        else:
            recall = tp / (tp + fn)
        if precision + recall == 0:
            f1 = 0.0
            hits.append(f"f1:{label}")
        else:
            f1 = 2 * precision * recall / (precision + recall)
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    return (
        sum(precisions) / len(labels),
        sum(recalls) / len(labels),
        sum(f1s) / len(labels),
        tuple(hits),
    )


def _average_ranks(values: Sequence[float]) -> tuple[float, ...]:
    """1-based 平均秩；同分取平均。用于 Mann–Whitney AUC。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average_rank = (position + 1 + end + 1) / 2.0
        for index in range(position, end + 1):
            ranks[order[index]] = average_rank
        position = end + 1
    return tuple(ranks)


def roc_auc_binary(
    y_true: Sequence[str],
    scores: Sequence[float],
    *,
    positive_label: str,
) -> float:
    """二分类 AUC；单类或空输入 → 抛 `AUC_UNDEFINED`。"""
    if len(y_true) != len(scores):
        raise PredictionError(
            "SCHEMA_INVALID", "AUC_SHAPE", "y_true 与 scores 长度不一致", field_path="scores",
        )
    if not y_true:
        raise PredictionError(
            "REQUIRED_EVIDENCE_MISSING", "AUC_UNDEFINED", "空输入无法计算 AUC",
            field_path="scores", http_status=409,
        )
    labels = set(y_true)
    if len(labels) != 2 or positive_label not in labels:
        raise PredictionError(
            "REQUIRED_EVIDENCE_MISSING", "AUC_UNDEFINED",
            f"二分类 AUC 需要恰好两个类别且包含正类 {positive_label!r}；实际 {sorted(labels)}",
            field_path="y_true", http_status=409,
        )
    ranks = _average_ranks(scores)
    positive = [ranks[i] for i, label in enumerate(y_true) if label == positive_label]
    negative_count = len(y_true) - len(positive)
    if not positive or negative_count == 0:
        raise PredictionError(
            "REQUIRED_EVIDENCE_MISSING", "AUC_UNDEFINED",
            "正类或负类为空，AUC 无定义", field_path="y_true", http_status=409,
        )
    rank_sum = sum(positive)
    n_pos = len(positive)
    auc = (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * negative_count)
    # 全同分时 rank_sum 恰为 n_pos*(n+1)/2，AUC=0.5；不做 0/1 截断，交给浮点误差范围。
    return min(1.0, max(0.0, auc))


def roc_auc_ovr(
    rows: Sequence[PredictionRow],
    labels: Sequence[str],
) -> tuple[float | None, str]:
    """macro OvR AUC；多分类先逐类二值化（one-vs-rest）。

    每个 label 都把 y_true 转成 ``pos``/``neg`` 后调用 `roc_auc_binary`；
    不改变 `roc_auc_binary` 的“恰好二类”语义。任一类 AUC 不可定义 → (None, 原因)。
    """
    if any(row.scores is None for row in rows):
        return None, "SCORES_MISSING"
    values: list[float] = []
    for label in labels:
        scores: list[float] = []
        y_true: list[str] = []
        for row in rows:
            assert row.scores is not None
            if label not in row.scores:
                return None, f"SCORE_LABEL_MISSING:{label}"
            scores.append(float(row.scores[label]))
            y_true.append(row.y_true)
        y_bin = ["pos" if actual == label else "neg" for actual in y_true]
        try:
            values.append(roc_auc_binary(y_bin, scores, positive_label="pos"))
        except PredictionError as exc:
            return None, f"{exc.reason}:{label}"
    return sum(values) / len(values), ""


# ---------------------------------------------------------------------------
# 3. 全量重算
# ---------------------------------------------------------------------------
def recompute_all(
    rows: Sequence[PredictionRow],
    *,
    labels: Sequence[str] | None = None,
    metric_defs: Sequence[MetricDefinition] | None = None,
) -> MetricSet:
    """从 predictions 重算五指标；不可计算项写入 `undefined`。

    步骤：
      1. 行非空、无重复 row_id、全部 fold=TEST；
      2. 解析标签集合 L（并集，排序）；
      3. 混淆矩阵；
      4. accuracy / P / R / F1；
      5. roc_auc_ovr（缺 scores 或单类 → UNDEFINED）；
      6. 返回 MetricSet；缺失指标由 `metric_defs` 决定是否允许（默认全部五项）。
    """
    resolved_rows = _require_rows(rows)
    resolved_labels = _resolve_labels(resolved_rows, labels)
    defs = tuple(metric_defs) if metric_defs is not None else tuple(
        MetricDefinition(name=name, requires_scores=(name == "roc_auc_ovr")) for name in METRIC_NAMES
    )
    requested = {definition.name for definition in defs}
    if len(requested) != len(defs):
        raise PredictionError(
            "SCHEMA_INVALID", "METRIC_DEFINITION_DUPLICATED",
            "metric_defs 不得包含重复指标", field_path="metric_defs",
        )

    matrix = confusion_matrix(resolved_rows, resolved_labels)
    precision, recall, f1, hits = precision_recall_f1_macro(resolved_rows, resolved_labels)
    values: dict[str, float] = {}
    undefined: dict[str, str] = {}

    if "accuracy" in requested:
        values["accuracy"] = accuracy(resolved_rows)
    if "precision_macro" in requested:
        values["precision_macro"] = precision
    if "recall_macro" in requested:
        values["recall_macro"] = recall
    if "f1_macro" in requested:
        values["f1_macro"] = f1
    if "roc_auc_ovr" in requested:
        auc, reason = roc_auc_ovr(resolved_rows, resolved_labels)
        if auc is None:
            undefined["roc_auc_ovr"] = reason
        else:
            values["roc_auc_ovr"] = auc

    return MetricSet(
        values=MappingProxyType(values),
        undefined=MappingProxyType(undefined),
        n_test=len(resolved_rows),
        labels=resolved_labels,
        confusion=matrix,
        zero_division_hits=hits,
    )


# ---------------------------------------------------------------------------
# 4. 比较
# ---------------------------------------------------------------------------
def compare_metrics(
    reported: Mapping[str, float],
    recomputed: MetricSet,
    *,
    expected_metrics: Sequence[str] = METRIC_NAMES,
    abs_tol: float = METRIC_ABS_TOL,
    rel_tol: float = METRIC_REL_TOL,
) -> tuple[MetricMismatch, ...]:
    """逐指标比较；返回所有不一致，不在第一个错误处停止（便于一次修完）。

    规则：
      - reported 缺指标 → `METRIC_MISSING`；
      - reported 多出未定义指标 → `METRIC_UNKNOWN`；
      - 重算 UNDEFINED 但 reported 有值 → `METRIC_UNDEFINED`；
      - 数值不在容差内 → `METRIC_MISMATCH`；
      - NaN/Infinity → `METRIC_NON_FINITE`。
    """
    mismatches: list[MetricMismatch] = []
    for name in expected_metrics:
        if name not in reported:
            mismatches.append(MetricMismatch(name, None, None, "METRIC_MISSING"))
            continue
        actual = reported[name]
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(float(actual)):
            mismatches.append(MetricMismatch(name, None, None, "METRIC_NON_FINITE"))
            continue
        if name in recomputed.undefined:
            mismatches.append(MetricMismatch(
                name, float(actual), None, f"METRIC_UNDEFINED:{recomputed.undefined[name]}",
            ))
            continue
        expected = recomputed.values.get(name)
        if expected is None:
            mismatches.append(MetricMismatch(name, None, float(actual), "METRIC_NOT_RECOMPUTED"))
            continue
        if not math.isclose(float(actual), float(expected), abs_tol=abs_tol, rel_tol=rel_tol):
            mismatches.append(MetricMismatch(
                name, float(expected), float(actual), "METRIC_MISMATCH",
                delta=float(actual) - float(expected),
            ))
    for name in reported:
        if name not in expected_metrics:
            mismatches.append(MetricMismatch(name, None, float(reported[name]), "METRIC_UNKNOWN"))
    return tuple(mismatches)


# ---------------------------------------------------------------------------
# 5. 静态边界自检
# ---------------------------------------------------------------------------
def assert_metric_boundary() -> list[str]:
    """指标重算不得读文件、连网络、做裁决。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("open", "Path", "requests", "socket", "subprocess", "Gate", "Verifier"):
        if hasattr(module, attr):
            problems.append(f"metric_recompute 暴露禁用名 {attr!r}")
    if METRIC_NAMES != (
        "accuracy", "precision_macro", "recall_macro", "f1_macro", "roc_auc_ovr"
    ):
        problems.append("METRIC_NAMES 被改动（必须与 M06 模板一致）")
    if not bit_identical(0.5, 0.5) or bit_identical(-0.0, 0.0):
        problems.append("bit_identical 语义错误（-0.0/+0.0 必须不等）")
    return problems