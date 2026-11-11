r"""MODULE: M09 · verifier/leakage_rules.py — L2 数据泄漏五规则（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-007、策划书 §9.2（R1–R5）、05 §13
FR/依赖: FR-007；依赖 M06 Split Manifest 六字段/语义、M09 metric_recompute（R5 重算）
不变量/错误码: 五条规则各自有**机器判据**，不得以“人工判断”代替；NOT_APPLICABLE 必须显式记录理由；
             NOT_EVALUABLE（缺输入/无法计算）按 fail-closed 处理，不得当成 PASS；
             规则不得修改数据、不得重抽样、不得读原运行产物。
             错误码：SCHEMA_INVALID（422，输入形态非法）、REQUIRED_EVIDENCE_MISSING（409，规则不可评估）
写入者: **无**；纯只读分析，不写证据/报告/状态
状态: 伪代码；不建环境、不跑测试、不写业务代码

## 五条规则的机器判据（逐字对应 §9.2）

  | 规则 | 判据（可执行） | 通过条件 |
  |---|---|---|
  | R1 重复样本 | 特征向量规范化 token 的 SHA-256 在 train/test 相同；或数值行 L∞ 距离 ≤ 阈值；或文本 3-gram Jaccard ≥ 阈值 | 无同哈希/无近重复对 |
  | R2 分组泄漏 | `manifest.group_key` 非空时 `set(group(train)) ∩ set(group(test)) == ∅` | 交集为空 |
  | R3 时序泄漏 | `max(time(train)) ≤ min(time(test))`；每个 feature_time 列逐行 `≤ label_time` | 两条都成立 |
  | R4 标签/后验字段 | 特征列必须等于白名单；target/ID/time/group/score 角色不得作特征；特征列哈希不得等于 target 列哈希；数值特征 \|Pearson r\| < 0.999；不得存在“每个特征值唯一映射一个标签”的列 | 全部成立 |
  | R5 指标来源 | `metrics.split == "test"`、`metrics.split_manifest_hash == manifest.manifest_hash`、predictions 行集 == test 行集、指标可由 predictions 重算且一致 | 全部成立 |

## 状态语义（不要把三种“没失败”混为一谈）

  - `PASS`：判据被真实计算且成立。
  - `NOT_APPLICABLE`：规则在声明语义下不适用（如 `group_key=None`），必须带 `reason`；
    L2 允许它不阻塞，但报告必须列出。
  - `NOT_EVALUABLE`：缺输入/无法计算（如特征白名单缺失、时间列无法解析）。
    **fail-closed**：L2 视为失败，不得写成 PASS。

## 边界声明

  五规则能发现“明显的/可计算的”泄漏；不能证明不存在未知泄漏方式。规则版本必须进入
  ruleset_hash；规则阈值（近重复、相关系数）是策略值，不是 G0 契约，改动必须升规则版本。
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from .metric_recompute import (
    METRIC_NAMES,
    MetricMismatch,
    PredictionRow,
    compare_metrics,
    recompute_all,
)

__all__ = [
    "DEFAULT_FORBIDDEN_FEATURE_NAMES",
    "ID_NAME_PATTERN",
    "ColumnSpec",
    "DatasetTable",
    "LeakageContext",
    "LeakageFinding",
    "LeakageReport",
    "MetricsArtifactView",
    "NearDuplicateSpec",
    "PredictionsArtifactView",
    "RuleStatus",
    "SplitAssignment",
    "SplitManifestView",
    "assert_leakage_boundary",
    "evaluate_all",
    "r1_duplicate_samples",
    "r2_group_leakage",
    "r3_temporal_leakage",
    "r4_label_or_posterior_fields",
    "r5_metric_source",
]

DEFAULT_FORBIDDEN_FEATURE_NAMES: Final[tuple[str, ...]] = (
    "target", "label", "labels", "y", "y_true", "outcome", "result",
    "prediction", "pred", "score", "probability", "posterior", "residual",
)
ID_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(^id$|_id$|^id_|uuid|guid|patient|subject|user|school|batch|session|row_number)",
    re.IGNORECASE,
)


class RuleStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUABLE = "NOT_EVALUABLE"


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """一列的语义角色；角色决定它能否作为特征。"""

    name: str
    role: str          # feature / target / id / time / group / score / meta
    dtype: str         # number / string / datetime / category

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("列名不得为空")
        if self.role not in ("feature", "target", "id", "time", "group", "score", "meta"):
            raise ValueError(f"未知列角色：{self.role!r}")
        if self.dtype not in ("number", "string", "datetime", "category"):
            raise ValueError(f"未知列类型：{self.dtype!r}")


@dataclass(frozen=True, slots=True)
class DatasetTable:
    """只读数据表；行是 `列名 -> 值` 的映射，行序保持原始数据行序。"""

    row_id_column: str
    columns: tuple[ColumnSpec, ...]
    rows: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        names = [column.name for column in self.columns]
        if len(set(names)) != len(names):
            raise ValueError("列名不得重复")
        if self.row_id_column not in names:
            raise ValueError(f"row_id_column {self.row_id_column!r} 不在列中")
        if len(self.rows) < 2:
            raise ValueError("数据表至少需要 2 行")
        for index, row in enumerate(self.rows):
            if set(row) != set(names):
                raise ValueError(f"第 {index} 行的列集合与表头不一致")
            row_id = row[self.row_id_column]
            if not isinstance(row_id, str) or not row_id:
                raise ValueError(f"第 {index} 行 row_id 非法")
        row_ids = [str(row[self.row_id_column]) for row in self.rows]
        if len(set(row_ids)) != len(row_ids):
            raise ValueError("row_id 不得重复")

    def column(self, name: str) -> ColumnSpec:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"列不存在：{name!r}")

    def row_ids(self) -> tuple[str, ...]:
        return tuple(str(row[self.row_id_column]) for row in self.rows)

    def by_id(self) -> Mapping[str, Mapping[str, object]]:
        return MappingProxyType({
            str(row[self.row_id_column]): row for row in self.rows
        })


@dataclass(frozen=True, slots=True)
class SplitManifestView:
    """Split Manifest 的只读视图（六字段 + 信封）；字段语义见 M06。"""

    dataset_hash: str
    algorithm: str
    version: str
    seed: int
    row_id_hash: str
    fold_assignment_hash: str
    group_key: str | None
    time_key: str | None
    ordering: str
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class SplitAssignment:
    """train/test 行 ID 与 fold 分配；必须覆盖全表且不重叠。"""

    train_row_ids: tuple[str, ...]
    test_row_ids: tuple[str, ...]
    folds: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.train_row_ids or not self.test_row_ids:
            raise ValueError("train/test 均不得为空")
        if set(self.train_row_ids) & set(self.test_row_ids):
            raise ValueError("train/test 行不得重叠")
        if len(set(self.train_row_ids)) != len(self.train_row_ids):
            raise ValueError("train 行 ID 重复")
        if len(set(self.test_row_ids)) != len(self.test_row_ids):
            raise ValueError("test 行 ID 重复")
        for row_id, fold in self.folds.items():
            if fold not in (0, 1):
                raise ValueError(f"{row_id}: fold 必须是 0/1")


@dataclass(frozen=True, slots=True)
class NearDuplicateSpec:
    """近重复判据；阈值是策略值，改动必须升规则版本。"""

    enabled: bool = True
    l_inf_threshold: float = 1e-9
    jaccard_threshold: float = 0.95
    shingle_size: int = 3
    max_pairs: int = 20

    def __post_init__(self) -> None:
        if not (0.0 <= self.l_inf_threshold <= 1.0):
            raise ValueError("l_inf_threshold 必须在 [0,1]")
        if not (0.0 <= self.jaccard_threshold <= 1.0):
            raise ValueError("jaccard_threshold 必须在 [0,1]")
        if self.shingle_size < 1 or self.max_pairs < 1:
            raise ValueError("shingle_size/max_pairs 必须 ≥1")


@dataclass(frozen=True, slots=True)
class MetricsArtifactView:
    """metrics.json 的只读视图；`split` 必须是 test。

    `confusion` 是 L2 交叉校验的输入；M06 的 metrics.json 可以没有该字段，
    但 L2 的“混淆矩阵交叉校验”要求它存在——缺失按 `CONFUSION_MISSING` 处理，
    不得因为“文件里没写”就跳过。
    """

    split: str
    split_manifest_hash: str
    n_test: int
    labels: tuple[str, ...]
    values: Mapping[str, float]
    confusion: tuple[tuple[int, ...], ...] | None = None
    per_fold_values: Mapping[int, Mapping[str, float]] = MappingProxyType({})

    def __post_init__(self) -> None:
        if self.split not in ("test", "train", "all"):
            raise ValueError(f"未知 split：{self.split!r}")
        if self.n_test < 1:
            raise ValueError("n_test 必须 ≥1")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("labels 不得重复")
        for name in self.values:
            if name not in METRIC_NAMES:
                raise ValueError(f"未知指标：{name!r}")
        if self.confusion is not None:
            size = len(self.labels)
            if len(self.confusion) != size or any(len(row) != size for row in self.confusion):
                raise ValueError("confusion 必须是 |labels|×|labels|")
            for row in self.confusion:
                for value in row:
                    if isinstance(value, bool) or not isinstance(value, int):
                        raise ValueError("confusion 单元格必须是 int")
            # JSON 读入是 list-of-lists；归一为 tuple-of-tuples，便于与
            # confusion_matrix() 的返回值直接比较。None 保持 None。
            normalized = tuple(tuple(int(value) for value in row) for row in self.confusion)
            object.__setattr__(self, "confusion", normalized)


@dataclass(frozen=True, slots=True)
class PredictionsArtifactView:
    """predictions.csv 的只读视图；行顺序保持文件顺序。"""

    columns: tuple[str, ...]
    rows: tuple[PredictionRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("predictions 不得为空")
        required = {"row_id", "fold", "y_true"}
        if not required.issubset(set(self.columns)):
            raise ValueError(f"predictions 缺列：{sorted(required - set(self.columns))}")


@dataclass(frozen=True, slots=True)
class LeakageContext:
    """五规则的完整只读输入；缺项由对应规则判 NOT_EVALUABLE。"""

    dataset: DatasetTable
    split: SplitAssignment
    manifest: SplitManifestView
    feature_whitelist: tuple[str, ...] | None = None
    feature_time_columns: tuple[str, ...] = ()
    id_columns: tuple[str, ...] = ()
    near_duplicate: NearDuplicateSpec = NearDuplicateSpec()
    correlation_threshold: float = 0.999
    metrics: MetricsArtifactView | None = None
    predictions: PredictionsArtifactView | None = None

    def __post_init__(self) -> None:
        if not (0.0 < self.correlation_threshold <= 1.0):
            raise ValueError("correlation_threshold 必须在 (0,1]")
        dataset_ids = set(self.dataset.row_ids())
        train_ids = set(self.split.train_row_ids)
        test_ids = set(self.split.test_row_ids)
        if not (train_ids | test_ids) <= dataset_ids:
            raise ValueError("split 引用了数据表里不存在的行")
        if train_ids | test_ids != dataset_ids:
            raise ValueError("split 未覆盖全部数据行")
        for row_id in dataset_ids:
            expected = 0 if row_id in train_ids else 1
            if self.split.folds.get(row_id) != expected:
                raise ValueError(f"{row_id}: folds 与 train/test 分配不一致")


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    """一条规则的判定；`criterion` 必须是可执行判据的文字化，不接受“人工判断”。"""

    rule_id: str
    status: RuleStatus
    code: str
    criterion: str
    message: str
    counts: Mapping[str, int] = MappingProxyType({})
    pairs: tuple[tuple[str, str, float], ...] = ()
    detail: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        if self.rule_id not in ("R1", "R2", "R3", "R4", "R5"):
            raise ValueError(f"未知规则：{self.rule_id!r}")
        if self.status is RuleStatus.NOT_APPLICABLE and not self.detail.get("reason"):
            raise ValueError("NOT_APPLICABLE 必须给出 reason")


@dataclass(frozen=True, slots=True)
class LeakageReport:
    findings: tuple[LeakageFinding, ...]

    def __post_init__(self) -> None:
        ids = [finding.rule_id for finding in self.findings]
        if ids != ["R1", "R2", "R3", "R4", "R5"]:
            raise ValueError("泄漏报告必须按 R1–R5 顺序恰好五条")

    def blocking_findings(self) -> tuple[LeakageFinding, ...]:
        """FAIL 与 NOT_EVALUABLE 都阻塞；NOT_APPLICABLE 不阻塞但必须展示。"""
        return tuple(
            finding for finding in self.findings
            if finding.status in (RuleStatus.FAIL, RuleStatus.NOT_EVALUABLE)
        )

    def status(self) -> RuleStatus:
        blocking = self.blocking_findings()
        if not blocking:
            return RuleStatus.PASS
        if any(finding.status is RuleStatus.FAIL for finding in blocking):
            return RuleStatus.FAIL
        return RuleStatus.NOT_EVALUABLE

    def assert_no_pass_with_not_evaluable(self) -> None:
        if self.status() is RuleStatus.PASS and any(
            finding.status is RuleStatus.NOT_EVALUABLE for finding in self.findings
        ):
            raise AssertionError("NOT_EVALUABLE 不得被当成 PASS")


# ---------------------------------------------------------------------------
# 1. 列与值的公共工具
# ---------------------------------------------------------------------------
def _column_names(context: LeakageContext) -> tuple[str, ...]:
    return tuple(column.name for column in context.dataset.columns)


def _feature_columns(context: LeakageContext) -> tuple[str, ...]:
    if context.feature_whitelist is not None:
        return tuple(context.feature_whitelist)
    return tuple(column.name for column in context.dataset.columns if column.role == "feature")


def _value_token(value: object) -> str:
    """稳定值 token；bool 先于 int 判断，float 用 repr，避免 1 与 1.0 混同。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "b:1" if value else "b:0"
    if isinstance(value, (int, float)):
        return f"n:{float(value)!r}"
    if isinstance(value, str):
        return f"s:{value}"
    raise ValueError(f"不支持的值类型：{type(value).__name__}")


def _row_token(row: Mapping[str, object], columns: Sequence[str]) -> str:
    return "|".join(f"{name}={_value_token(row[name])}" for name in columns)


def _row_hash(row: Mapping[str, object], columns: Sequence[str]) -> str:
    return hashlib.sha256(_row_token(row, columns).encode("utf-8")).hexdigest()


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _to_float(value: object) -> float | None:
    return float(value) if _is_number(value) else None


def _shingles(text: str, size: int) -> frozenset[str]:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if len(normalized) <= size:
        return frozenset({normalized}) if normalized else frozenset()
    return frozenset(normalized[i:i + size] for i in range(len(normalized) - size + 1))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _time_value(value: object, *, field: str) -> float:
    """把时间值解析成可比较的 epoch 秒；无时区/混合类型一律拒绝。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field}: 无法解析时间 {value!r}") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field}: 时间必须带时区（UTC）")
        return parsed.astimezone(timezone.utc).timestamp()
    raise ValueError(f"{field}: 时间必须是 number 或 ISO 8601 字符串")


def _numeric_matrix(
    context: LeakageContext,
    columns: Sequence[str],
) -> tuple[tuple[float, ...], ...] | None:
    """取全数值特征矩阵；任一列非数值 → None（交给文本/精确判据）。"""
    matrix: list[tuple[float, ...]] = []
    for row in context.dataset.rows:
        values: list[float] = []
        for name in columns:
            number = _to_float(row[name])
            if number is None:
                return None
            values.append(number)
        matrix.append(tuple(values))
    return tuple(matrix)


# ---------------------------------------------------------------------------
# 2. R1 重复样本
# ---------------------------------------------------------------------------
def r1_duplicate_samples(context: LeakageContext) -> LeakageFinding:
    """R1：规范化行哈希 / 数值 L∞ / 文本 Jaccard。"""
    columns = _feature_columns(context)
    if not columns:
        return LeakageFinding(
            "R1", RuleStatus.NOT_EVALUABLE, "R1_NO_FEATURES",
            "feature_columns != []",
            "没有特征列，无法做重复样本检测", detail={"reason": "NO_FEATURE_COLUMNS"},
        )
    by_id = context.dataset.by_id()
    train = [by_id[row_id] for row_id in context.split.train_row_ids]
    test = [by_id[row_id] for row_id in context.split.test_row_ids]

    exact_pairs: list[tuple[str, str, float]] = []
    train_hashes: dict[str, str] = {}
    for row in train:
        train_hashes.setdefault(_row_hash(row, columns), str(row[context.dataset.row_id_column]))
    for row in test:
        digest = _row_hash(row, columns)
        if digest in train_hashes:
            exact_pairs.append((train_hashes[digest], str(row[context.dataset.row_id_column]), 1.0))
            if len(exact_pairs) >= context.near_duplicate.max_pairs:
                break

    near_pairs: list[tuple[str, str, float]] = []
    near_checked = False
    if context.near_duplicate.enabled:
        matrix = _numeric_matrix(context, columns)
        if matrix is not None:
            near_checked = True
            train_ids = context.split.train_row_ids
            train_index = {row_id: i for i, row_id in enumerate(context.dataset.row_ids())}
            train_rows = [matrix[train_index[row_id]] for row_id in train_ids]
            test_rows = [matrix[train_index[row_id]] for row_id in context.split.test_row_ids]
            for test_id, test_row in zip(context.split.test_row_ids, test_rows):
                for train_id, train_row in zip(train_ids, train_rows):
                    distance = max(abs(a - b) for a, b in zip(test_row, train_row))
                    if distance <= context.near_duplicate.l_inf_threshold:
                        near_pairs.append((train_id, test_id, distance))
                        if len(near_pairs) >= context.near_duplicate.max_pairs:
                            break
                if len(near_pairs) >= context.near_duplicate.max_pairs:
                    break
        else:
            # 文本近重复：对每个字符串特征列做 3-gram Jaccard；任一列过阈值即配对。
            string_columns = [
                name for name in columns if context.dataset.column(name).dtype == "string"
            ]
            if string_columns:
                near_checked = True
                for test_id in context.split.test_row_ids:
                    test_row = by_id[test_id]
                    for train_id in context.split.train_row_ids:
                        train_row = by_id[train_id]
                        best = 0.0
                        for name in string_columns:
                            left = _shingles(str(train_row[name]), context.near_duplicate.shingle_size)
                            right = _shingles(str(test_row[name]), context.near_duplicate.shingle_size)
                            best = max(best, _jaccard(left, right))
                        if best >= context.near_duplicate.jaccard_threshold:
                            near_pairs.append((train_id, test_id, best))
                            if len(near_pairs) >= context.near_duplicate.max_pairs:
                                break
                    if len(near_pairs) >= context.near_duplicate.max_pairs:
                        break

    pairs = tuple(exact_pairs + near_pairs)
    if pairs:
        return LeakageFinding(
            "R1", RuleStatus.FAIL, "R1_DUPLICATE_SAMPLE",
            "sha256(feature_token(train)) == sha256(feature_token(test)) OR "
            "L_inf(train,test) <= threshold OR jaccard_3gram >= threshold",
            "train/test 存在重复或近重复样本", counts={"pairs": len(pairs)},
            pairs=pairs, detail={"near_checked": near_checked},
        )
    if context.near_duplicate.enabled and not near_checked:
        return LeakageFinding(
            "R1", RuleStatus.NOT_EVALUABLE, "R1_NEAR_NOT_EVALUABLE",
            "numeric_or_string_features_available",
            "启用了近重复检测，但既无数值特征也无字符串特征，无法排除近重复",
            detail={"reason": "NO_NUMERIC_OR_STRING_FEATURES"},
        )
    return LeakageFinding(
        "R1", RuleStatus.PASS, "R1_OK",
        "no_duplicate_pair_found",
        "未发现重复/近重复样本", counts={"pairs": 0},
        detail={"near_checked": near_checked},
    )


# ---------------------------------------------------------------------------
# 3. R2 分组泄漏
# ---------------------------------------------------------------------------
def r2_group_leakage(context: LeakageContext) -> LeakageFinding:
    """R2：group_key 求交集；声明 none 时若存在 group 列则失败。"""
    group_key = context.manifest.group_key
    group_columns = [c.name for c in context.dataset.columns if c.role == "group"]
    if group_key is None:
        if group_columns:
            return LeakageFinding(
                "R2", RuleStatus.FAIL, "R2_GROUP_COLUMN_UNDECLARED",
                "manifest.group_key is None => no column with role=group",
                f"数据含 group 语义列 {group_columns}，但 manifest 声明无分组",
                detail={"group_columns": group_columns},
            )
        return LeakageFinding(
            "R2", RuleStatus.NOT_APPLICABLE, "R2_NO_GROUP",
            "manifest.group_key is None AND no role=group column",
            "未声明分组语义，R2 不适用",
            detail={"reason": "NO_GROUP_SEMANTICS"},
        )
    if group_key not in _column_names(context):
        return LeakageFinding(
            "R2", RuleStatus.NOT_EVALUABLE, "R2_GROUP_COLUMN_MISSING",
            f"column({group_key!r}) exists",
            f"manifest 声明 group_key={group_key!r}，但数据没有该列",
            detail={"reason": "GROUP_COLUMN_MISSING"},
        )
    by_id = context.dataset.by_id()
    train_groups = {str(by_id[row_id][group_key]) for row_id in context.split.train_row_ids}
    test_groups = {str(by_id[row_id][group_key]) for row_id in context.split.test_row_ids}
    if any(by_id[row_id][group_key] is None for row_id in context.dataset.row_ids()):
        return LeakageFinding(
            "R2", RuleStatus.NOT_EVALUABLE, "R2_GROUP_NULL",
            f"{group_key} IS NOT NULL",
            "group_key 存在空值，无法可靠求交集",
            detail={"reason": "GROUP_VALUE_NULL"},
        )
    overlap = train_groups & test_groups
    if overlap:
        return LeakageFinding(
            "R2", RuleStatus.FAIL, "R2_GROUP_OVERLAP",
            "set(group(train)) & set(group(test)) == empty",
            "同一 group 同时出现在 train/test",
            counts={"overlap": len(overlap)},
            detail={"overlap_sample": sorted(overlap)[:10]},
        )
    if group_key in _feature_columns(context):
        return LeakageFinding(
            "R2", RuleStatus.FAIL, "R2_GROUP_KEY_AS_FEATURE",
            f"{group_key} not in feature_columns",
            "group_key 被当作特征使用，等于把分组身份泄漏给模型",
            detail={"group_key": group_key},
        )
    return LeakageFinding(
        "R2", RuleStatus.PASS, "R2_OK",
        "set(group(train)) & set(group(test)) == empty",
        "train/test 分组不重叠", counts={"overlap": 0},
        detail={"group_key": group_key, "n_groups_train": len(train_groups), "n_groups_test": len(test_groups)},
    )


# ---------------------------------------------------------------------------
# 4. R3 时序泄漏
# ---------------------------------------------------------------------------
def r3_temporal_leakage(context: LeakageContext) -> LeakageFinding:
    """R3：时间边界 + 特征时间窗口。"""
    time_key = context.manifest.time_key
    time_columns = [c.name for c in context.dataset.columns if c.role == "time"]
    if time_key is None:
        if time_columns:
            return LeakageFinding(
                "R3", RuleStatus.FAIL, "R3_TIME_COLUMN_UNDECLARED",
                "manifest.time_key is None => no role=time column",
                f"数据含时间列 {time_columns}，但 manifest 声明无语义/非时序",
                detail={"time_columns": time_columns},
            )
        if context.feature_time_columns:
            return LeakageFinding(
                "R3", RuleStatus.FAIL, "R3_FEATURE_TIME_WITHOUT_SEMANTICS",
                "manifest.time_key is not None when feature_time_columns != []",
                "声明了特征时间列但 manifest 没有 time_key，无法判断未来信息",
                detail={"feature_time_columns": list(context.feature_time_columns)},
            )
        return LeakageFinding(
            "R3", RuleStatus.NOT_APPLICABLE, "R3_NO_TIME",
            "manifest.time_key is None AND no role=time column",
            "未声明时序语义，R3 不适用",
            detail={"reason": "NO_TIME_SEMANTICS"},
        )
    if time_key not in _column_names(context):
        return LeakageFinding(
            "R3", RuleStatus.NOT_EVALUABLE, "R3_TIME_COLUMN_MISSING",
            f"column({time_key!r}) exists",
            f"manifest 声明 time_key={time_key!r}，但数据没有该列",
            detail={"reason": "TIME_COLUMN_MISSING"},
        )
    if context.manifest.ordering != "time_ascending":
        return LeakageFinding(
            "R3", RuleStatus.FAIL, "R3_TIME_ORDERING",
            "manifest.ordering == 'time_ascending'",
            "时序划分必须按 time_ascending 切尾，不能 shuffle",
            detail={"ordering": context.manifest.ordering},
        )
    by_id = context.dataset.by_id()
    try:
        train_times = [_time_value(by_id[row_id][time_key], field=time_key)
                       for row_id in context.split.train_row_ids]
        test_times = [_time_value(by_id[row_id][time_key], field=time_key)
                      for row_id in context.split.test_row_ids]
    except ValueError as exc:
        return LeakageFinding(
            "R3", RuleStatus.NOT_EVALUABLE, "R3_TIME_UNPARSABLE",
            "all time values are numeric or ISO-8601 with timezone",
            f"时间列无法解析：{exc}", detail={"reason": "TIME_UNPARSABLE"},
        )
    max_train = max(train_times)
    min_test = min(test_times)
    if not (max_train <= min_test):
        return LeakageFinding(
            "R3", RuleStatus.FAIL, "R3_TIME_ORDER_VIOLATION",
            "max(time(train)) <= min(time(test))",
            "训练集时间晚于测试集，存在未来信息",
            detail={"max_train": max_train, "min_test": min_test},
        )
    violations: list[str] = []
    for name in context.feature_time_columns:
        if name not in _column_names(context):
            return LeakageFinding(
                "R3", RuleStatus.NOT_EVALUABLE, "R3_FEATURE_TIME_COLUMN_MISSING",
                f"column({name!r}) exists",
                f"feature_time_columns 引用不存在的列 {name!r}",
                detail={"reason": "FEATURE_TIME_COLUMN_MISSING"},
            )
        for row_id in context.dataset.row_ids():
            row = by_id[row_id]
            try:
                feature_time = _time_value(row[name], field=name)
                label_time = _time_value(row[time_key], field=time_key)
            except ValueError as exc:
                return LeakageFinding(
                    "R3", RuleStatus.NOT_EVALUABLE, "R3_FEATURE_TIME_UNPARSABLE",
                    "feature_time <= label_time for every row",
                    f"特征时间无法解析：{exc}", detail={"reason": "FEATURE_TIME_UNPARSABLE"},
                )
            if feature_time > label_time:
                violations.append(row_id)
    if violations:
        return LeakageFinding(
            "R3", RuleStatus.FAIL, "R3_FUTURE_FEATURE",
            "feature_time(row) <= label_time(row) for every row",
            "特征使用了标签时点之后的信息",
            counts={"violations": len(violations)},
            detail={"sample": violations[:10]},
        )
    return LeakageFinding(
        "R3", RuleStatus.PASS, "R3_OK",
        "max(time(train)) <= min(time(test)) AND feature_time <= label_time",
        "时间边界与特征窗口均成立",
        detail={"max_train": max_train, "min_test": min_test},
    )


# ---------------------------------------------------------------------------
# 5. R4 标签/后验字段
# ---------------------------------------------------------------------------
def _column_hash(context: LeakageContext, name: str) -> str:
    tokens = "|".join(_value_token(row[name]) for row in context.dataset.rows)
    return hashlib.sha256(tokens.encode("utf-8")).hexdigest()


def _is_forbidden_feature_name(name: str) -> bool:
    """标签/后验命名判据：精确名，或 `_` 分隔的完整 token。

    不能做裸子串匹配：`"y" in "year"` 会把正常特征全部误杀。短名（≤2 字符）
    只允许精确相等；长名允许作为 `_` 分隔 token 出现（如 `feature_score`）。
    """
    lowered = name.lower()
    if lowered in DEFAULT_FORBIDDEN_FEATURE_NAMES:
        return True
    for pattern in DEFAULT_FORBIDDEN_FEATURE_NAMES:
        if len(pattern) <= 2:
            continue
        if re.search(rf"(^|_){re.escape(pattern)}($|_)", lowered):
            return True
    return False


def _pearson(values: Sequence[float], targets: Sequence[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean_x = sum(values) / n
    mean_y = sum(targets) / n
    var_x = sum((x - mean_x) ** 2 for x in values)
    var_y = sum((y - mean_y) ** 2 for y in targets)
    if var_x == 0.0 or var_y == 0.0:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(values, targets))
    return covariance / math.sqrt(var_x * var_y)


def r4_label_or_posterior_fields(context: LeakageContext) -> LeakageFinding:
    """R4：白名单 + 角色 + target 混入 + 高基数 ID + 完全相关/确定性映射。"""
    if context.feature_whitelist is None:
        return LeakageFinding(
            "R4", RuleStatus.NOT_EVALUABLE, "R4_WHITELIST_MISSING",
            "feature_whitelist is not None",
            "没有特征白名单，无法判断标签/后验字段是否混入",
            detail={"reason": "FEATURE_WHITELIST_MISSING"},
        )
    features = tuple(context.feature_whitelist)
    targets = [c.name for c in context.dataset.columns if c.role == "target"]
    if len(targets) != 1:
        return LeakageFinding(
            "R4", RuleStatus.NOT_EVALUABLE, "R4_TARGET_AMBIGUOUS",
            "exactly one column with role=target",
            f"target 列必须恰好一个，实际 {targets}",
            detail={"reason": "TARGET_AMBIGUOUS"},
        )
    target = targets[0]
    # target 混入必须先于“集合相等”判定：否则白名单含 target 时会先命中
    # R4_FEATURE_SET_MISMATCH，R4_TARGET_IN_FEATURES 永远不可达。
    if target in features:
        return LeakageFinding(
            "R4", RuleStatus.FAIL, "R4_TARGET_IN_FEATURES",
            f"{target} not in feature_whitelist",
            "target 列被当作特征", detail={"target": target},
        )
    actual_features = tuple(c.name for c in context.dataset.columns if c.role == "feature")
    if set(features) != set(actual_features):
        return LeakageFinding(
            "R4", RuleStatus.FAIL, "R4_FEATURE_SET_MISMATCH",
            "set(feature_whitelist) == set(role=feature columns)",
            "实际特征列与白名单不一致",
            detail={
                "missing_in_data": sorted(set(features) - set(actual_features)),
                "not_whitelisted": sorted(set(actual_features) - set(features)),
            },
        )
    for name in features:
        if name not in _column_names(context):
            return LeakageFinding(
                "R4", RuleStatus.NOT_EVALUABLE, "R4_FEATURE_MISSING",
                f"column({name!r}) exists",
                f"白名单引用了不存在的列 {name!r}",
                detail={"reason": "FEATURE_COLUMN_MISSING"},
            )
        column = context.dataset.column(name)
        if column.role != "feature":
            return LeakageFinding(
                "R4", RuleStatus.FAIL, "R4_NON_FEATURE_ROLE_AS_FEATURE",
                f"role({name}) == 'feature'",
                f"列 {name!r} 的角色是 {column.role!r}，不得作为特征",
                detail={"column": name, "role": column.role},
            )
        if _is_forbidden_feature_name(name):
            return LeakageFinding(
                "R4", RuleStatus.FAIL, "R4_FORBIDDEN_NAME",
                "feature name not in DEFAULT_FORBIDDEN_FEATURE_NAMES",
                f"特征名 {name!r} 命中标签/后验命名模式",
                detail={"column": name},
            )
    target_hash = _column_hash(context, target)
    for name in features:
        if _column_hash(context, name) == target_hash:
            return LeakageFinding(
                "R4", RuleStatus.FAIL, "R4_TARGET_DUPLICATE_COLUMN",
                f"sha256({name}) != sha256({target})",
                f"特征列 {name!r} 与 target 列逐值相同",
                detail={"column": name, "target": target},
            )

    # 高基数 ID：字符串/类别列唯一值 == 行数且列名像 ID。
    n_rows = len(context.dataset.rows)
    for name in features:
        column = context.dataset.column(name)
        if column.dtype not in ("string", "category"):
            continue
        values = {str(row[name]) for row in context.dataset.rows}
        if len(values) == n_rows and ID_NAME_PATTERN.search(name):
            return LeakageFinding(
                "R4", RuleStatus.FAIL, "R4_HIGH_CARDINALITY_ID",
                "cardinality(feature) < n_rows OR not ID_name",
                f"特征列 {name!r} 是逐行唯一 ID（{n_rows} 行/{n_rows} 值）",
                detail={"column": name, "cardinality": len(values)},
            )

    # 数值特征与 target 完全相关 / 确定性映射。
    target_values = [row[target] for row in context.dataset.rows]
    target_numeric = [_to_float(value) for value in target_values]
    target_label = {value: index for index, value in enumerate(sorted({str(v) for v in target_values}))}
    target_encoded = [float(target_label[str(value)]) for value in target_values]
    for name in features:
        column = context.dataset.column(name)
        if column.dtype != "number":
            continue
        values = [_to_float(row[name]) for row in context.dataset.rows]
        if any(value is None for value in values):
            continue
        numeric = [float(value) for value in values if value is not None]
        y_values = [float(value) for value in target_numeric if value is not None] \
            if all(value is not None for value in target_numeric) else target_encoded
        correlation = _pearson(numeric, y_values)
        if correlation is not None and abs(correlation) >= context.correlation_threshold:
            return LeakageFinding(
                "R4", RuleStatus.FAIL, "R4_PERFECT_CORRELATION",
                f"abs(pearson({name}, {target})) < {context.correlation_threshold}",
                f"特征 {name!r} 与 target 相关系数 {correlation:.6f}，疑似后验字段",
                detail={"column": name, "correlation": correlation},
            )
        mapping: dict[float, set[str]] = {}
        for value, label in zip(numeric, [str(v) for v in target_values]):
            mapping.setdefault(value, set()).add(label)
        # 只对低基数、非逐行唯一的列判“确定性映射”。连续特征天然逐行唯一，
        # 那不是后验字段；把 len(mapping) == n_rows 也判失败会制造大面积误报。
        if 2 <= len(mapping) <= 20 and len(mapping) < n_rows and all(
            len(labels) == 1 for labels in mapping.values()
        ):
            return LeakageFinding(
                "R4", RuleStatus.FAIL, "R4_DETERMINISTIC_TARGET_MAPPING",
                "not every feature value maps to exactly one target label",
                f"特征 {name!r} 的每个取值都唯一决定 target，疑似标签副本/后验",
                detail={"column": name, "distinct_values": len(mapping)},
            )
    return LeakageFinding(
        "R4", RuleStatus.PASS, "R4_OK",
        "whitelist == features AND no forbidden role/name/correlation/mapping",
        "未发现标签或后验字段混入", detail={"target": target, "n_features": len(features)},
    )


# ---------------------------------------------------------------------------
# 6. R5 指标来源
# ---------------------------------------------------------------------------
def r5_metric_source(context: LeakageContext) -> LeakageFinding:
    """R5：指标必须来自 test split，且能由 predictions 重算。"""
    if context.metrics is None or context.predictions is None:
        return LeakageFinding(
            "R5", RuleStatus.NOT_EVALUABLE, "R5_ARTIFACTS_MISSING",
            "metrics is not None AND predictions is not None",
            "缺 metrics.json 或 predictions.csv，无法验证指标来源",
            detail={"reason": "METRICS_OR_PREDICTIONS_MISSING"},
        )
    metrics = context.metrics
    predictions = context.predictions
    if metrics.split != "test":
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_METRICS_NOT_TEST",
            'metrics.split == "test"',
            f"metrics 的 split={metrics.split!r}，不是 test",
            detail={"split": metrics.split},
        )
    if metrics.split_manifest_hash != context.manifest.manifest_hash:
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_MANIFEST_HASH_MISMATCH",
            "metrics.split_manifest_hash == manifest.manifest_hash",
            "metrics 绑定的 Split Manifest 与本次不一致",
            detail={
                "expected": context.manifest.manifest_hash,
                "actual": metrics.split_manifest_hash,
            },
        )
    if any(fold != 1 for fold in metrics.per_fold_values):
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_TRAIN_METRICS_PRESENT",
            "set(metrics.per_fold_values) <= {1}",
            "metrics 包含非 test fold 的指标，存在训练集调参风险",
            detail={"folds": sorted(metrics.per_fold_values)},
        )
    prediction_ids = tuple(row.row_id for row in predictions.rows)
    if len(set(prediction_ids)) != len(prediction_ids):
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_PREDICTIONS_DUPLICATED",
            "len(set(prediction_ids)) == len(prediction_ids)",
            "predictions 有重复 row_id", detail={"rows": len(prediction_ids)},
        )
    if set(prediction_ids) != set(context.split.test_row_ids):
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_PREDICTIONS_NOT_TEST_ROWS",
            "set(predictions.row_id) == set(test_row_ids)",
            "predictions 行集与 test 行集不一致",
            detail={
                "missing": sorted(set(context.split.test_row_ids) - set(prediction_ids))[:10],
                "extra": sorted(set(prediction_ids) - set(context.split.test_row_ids))[:10],
            },
        )
    if any(row.fold != 1 for row in predictions.rows):
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_NON_TEST_PREDICTION_ROW",
            "all(prediction.fold == 1)",
            "predictions 含非 test fold 行",
            detail={"bad_rows": [row.row_id for row in predictions.rows if row.fold != 1][:10]},
        )
    if metrics.n_test != len(context.split.test_row_ids):
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_N_TEST_MISMATCH",
            "metrics.n_test == len(test_row_ids)",
            "metrics.n_test 与 test 行数不一致",
            detail={"expected": len(context.split.test_row_ids), "actual": metrics.n_test},
        )
    try:
        recomputed = recompute_all(predictions.rows)
    except Exception as exc:
        return LeakageFinding(
            "R5", RuleStatus.NOT_EVALUABLE, "R5_RECOMPUTE_FAILED",
            "recompute_all(predictions) succeeds",
            f"指标无法重算：{exc}", detail={"reason": "RECOMPUTE_FAILED"},
        )
    mismatches: tuple[MetricMismatch, ...] = compare_metrics(metrics.values, recomputed)
    if mismatches:
        return LeakageFinding(
            "R5", RuleStatus.FAIL, "R5_METRICS_NOT_RECOMPUTABLE",
            "compare_metrics(metrics, recompute_all(predictions)) == []",
            "metrics 不能由 predictions 重算一致",
            counts={"mismatches": len(mismatches)},
            detail={"mismatches": [m.reason + ":" + m.metric for m in mismatches]},
        )
    return LeakageFinding(
        "R5", RuleStatus.PASS, "R5_OK",
        "split==test AND manifest_hash matches AND predictions==test_rows AND metrics recomputable",
        "指标来源为 test 且可由 predictions 重算", detail={"n_test": len(prediction_ids)},
    )


# ---------------------------------------------------------------------------
# 7. 汇总
# ---------------------------------------------------------------------------
def evaluate_all(context: LeakageContext) -> LeakageReport:
    """按 R1→R5 顺序执行；任一 FAIL/NOT_EVALUABLE 都会让 L2 不能 PASS。"""
    return LeakageReport(findings=(
        r1_duplicate_samples(context),
        r2_group_leakage(context),
        r3_temporal_leakage(context),
        r4_label_or_posterior_fields(context),
        r5_metric_source(context),
    ))


def assert_leakage_boundary() -> list[str]:
    """静态检查：五规则不修改数据、不重抽样、不读原运行产物。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("open", "Path", "requests", "socket", "subprocess", "Gate", "Verifier"):
        if hasattr(module, attr):
            problems.append(f"leakage_rules 暴露禁用名 {attr!r}")
    if tuple(f.__name__ for f in (r1_duplicate_samples, r2_group_leakage,
                                  r3_temporal_leakage, r4_label_or_posterior_fields,
                                  r5_metric_source)) != (
        "r1_duplicate_samples", "r2_group_leakage", "r3_temporal_leakage",
        "r4_label_or_posterior_fields", "r5_metric_source",
    ):
        problems.append("五规则顺序/名称被改动")
    return problems