"""M06 · executor/templates/classification_benchmark.py — 三模型分类基准模板（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-004（内置模板）、FR-005（E2 来自真实受控执行）、FR-006（Gate 可判定）
依赖：M05 template_protocol（三方法形状）、M06 models（三模型白名单）、M06 splits（六字段）、M06 datasets_registry（绑定）
不变量：只训练白名单模型；只在训练折 fit；只在测试折算指标；不返回 PASS/FAIL；不写证据/状态/审计；
        不自报产物哈希；不联网、不起子进程、不读凭据、不做反序列化
错误码：SCHEMA_INVALID（422，参数/绑定/产物声明非法）；TOOL_NOT_ALLOWLISTED（403，未登记模板）；
        REQUIRED_EVIDENCE_MISSING（409，留给 Gate：E0/E1 不能顶替执行类必检）
写入者：模板写 `artifacts/`（5 个文件）；Worker 计算产物哈希并写事件；Collector 写 E2 证据
状态：伪代码；拟合/写文件属 WP-05；本文件只定义契约、流程、产物与 required_checks

## 这个模板做什么

  在一个已绑定、已登记的数据集上：
    1. 校验 `inputs/dataset_binding.json` 与 `inputs/dataset.csv` 的哈希；
    2. 用 `SplitService` 生成/校验 Split Manifest（六字段）；
    3. 对 `models` 选中的 1–3 个模型：训练折 fit → 测试折 predict/score；
    4. 计算指标、写预测、写运行摘要与泄漏诊断；
    5. 返回“算出了什么”的事实，**不返回结论**。

## 为什么指标只在测试折算

  训练折指标不能作为泛化证据；在训练折上算指标再写进 metrics.json 会把“记住训练集”
  伪装成“模型有效”。L2 重算时只接受测试折预测 + 测试折标签。

## 为什么没有 `status`/`passed`

  模板不裁决（AGENTS §4.4）。它只报告 metrics、rows、hashes、warnings；
  是否满足必检、是否 VERIFIED 由 Gate/Verifier 在拿到 E2/E3 后判定。
  结构上本文件的 `RunReport` 没有 verdict 槽位；出现即契约破坏。

## required_checks 的口径

  `REQUIRED_CHECKS` 是**声明**，不是自检结果。Gate 为每项生成 coverage row；
  执行类必检（dataset_hash_match / split_manifest_valid / predictions_cover_test_rows /
  metrics_recomputable / no_train_test_overlap / leakage_report_present）至少需要 E2；
  E0/E1 只能辅助，不能顶替。P4 不实现 Gate（P5），但把等级要求写进 `RequiredCheckSpec.min_level`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Mapping, Protocol

from .models import (
    MODEL_KEYS,
    MODEL_SPECS,
    ModelParamError,
    assert_no_foreign_model_params,
    assert_no_reserved_params,
    param_field_specs,
    parse_model_list,
    resolve_params,
)

__all__ = [
    "ARTIFACT_SPECS",
    "DEFAULT_PARAMS",
    "METRIC_NAMES",
    "PARAM_SPECS",
    "REQUIRED_CHECKS",
    "TEMPLATE_ID",
    "ArtifactSpec",
    "BenchmarkParams",
    "ClassificationBenchmarkTemplate",
    "DatasetBindingView",
    "ParamSpec",
    "RequiredCheckSpec",
    "assert_template_boundary",
    "template_registration_metadata",
]

TEMPLATE_ID: Final[str] = "classification_benchmark@1.0.0"
TEMPLATE_VERSION: Final[str] = "1.0.0"
NODE_TYPE: Final[str] = "ml.classification.benchmark"
SIDE_EFFECT_CLASS: Final[str] = "PURE_ARTIFACT"
ALLOWED_DATASET_IDS: Final[tuple[str, ...]] = ("wine", "breast_cancer")

METRIC_NAMES: Final[tuple[str, ...]] = (
    "accuracy",
    "precision_macro",
    "recall_macro",
    "f1_macro",
    "roc_auc_ovr",
)
# roc_auc_ovr 口径：二分类把 1D decision_function 转成 [-s, s] 两列；
# 多分类直接使用 (n_samples, n_classes)。不调用 predict_proba，避免 SVM 内部 CV。

DEFAULT_PARAMS: Final[Mapping[str, object]] = MappingProxyType({
    "scale_features": True,
})

# 产物只放“验证需要的事实”，不放模型二进制（理由见 models.py 头）。
ARTIFACT_NAMES: Final[tuple[str, ...]] = (
    "split_manifest.json",
    "metrics.json",
    "predictions.csv",
    "run_summary.json",
    "leakage_report.json",
)

# 参数契约：顶层 5 项 + 三个模型的扁平超参（`model.param`）。
@dataclass(frozen=True, slots=True)
class ParamSpec:
    """模板参数声明；字段名与 M05 `ParamField` 对齐，供 WP-05 转换。

    `item_enum` 是 M05 当前 `ParamField` 不支持的数组元素枚举；
    本模板在 `parse_params()` 里补做，拒绝点仍是 `parameters.models[i]`。
    """

    name: str
    type: str
    required: bool
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    enum: tuple[str, ...] = ()
    item_enum: tuple[str, ...] = ()
    note: str = ""


_PARAM_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("target", "string", required=True, min_length=1, max_length=64,
              note="目标列名；必须存在于绑定 CSV 表头"),
    ParamSpec("seed", "integer", required=True, minimum=0, maximum=2**31 - 1),
    ParamSpec("test_size", "number", required=True, minimum=0.1, maximum=0.5,
              note="模板收紧到 [0.1,0.5]；TaskSpec 仍为 (0,1)"),
    ParamSpec("models", "array", required=True, min_items=1, max_items=3,
              item_enum=MODEL_KEYS, note="1–3 个白名单模型；不重复"),
    ParamSpec("scale_features", "boolean", required=False,
              note="默认 true；LR/SVM 选中时必须 true"),
)
PARAM_SPECS: Final[tuple[ParamSpec, ...]] = _PARAM_SPECS + tuple(
    ParamSpec(
        name=str(item["name"]),
        type=str(item["type"]),
        required=False,
        minimum=item.get("minimum"),          # type: ignore[arg-type]
        maximum=item.get("maximum"),          # type: ignore[arg-type]
        enum=tuple(item.get("enum") or ()),   # type: ignore[arg-type]
        note=str(item.get("note", "")),
    )
    for item in param_field_specs()
)


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """产物声明（无哈希槽位；哈希由 Worker 计算）。"""

    name: str
    relative_path: str
    media_type: str
    description: str


ARTIFACT_SPECS: Final[tuple[ArtifactSpec, ...]] = (
    ArtifactSpec("split_manifest", "artifacts/split_manifest.json", "application/json",
                 "Split Manifest 六字段 + manifest_hash"),
    ArtifactSpec("metrics", "artifacts/metrics.json", "application/json",
                 "每个模型在测试折上的指标；无 PASS/FAIL"),
    ArtifactSpec("predictions", "artifacts/predictions.csv", "text/csv",
                 "测试折逐行预测/分数；供 L2 重算，行序按数据行顺序"),
    ArtifactSpec("run_summary", "artifacts/run_summary.json", "application/json",
                 "解析后的参数、库版本、行数、耗时；不含裁决"),
    ArtifactSpec("leakage_report", "artifacts/leakage_report.json", "application/json",
                 "泄漏诊断的观测值；判定留给 L2/Gate"),
)


@dataclass(frozen=True, slots=True)
class RequiredCheckSpec:
    """一个必检项声明。`min_level` 是**最低证据等级**，不是“有了就通过”。

    `execution_critical=True` 的项必须由 E2/E3 覆盖；E0/E1 不满足。
    Gate 还必须检查：producer 正确、payload_hash 一致、artifact_refs 存在、
    规则版本一致、没有未解释冲突（P5 实现）。
    """

    check_id: str
    description: str
    execution_critical: bool
    min_level: str


REQUIRED_CHECKS: Final[tuple[RequiredCheckSpec, ...]] = (
    RequiredCheckSpec("dataset_hash_match", "绑定数据字节哈希 = 登记哈希", True, "E2"),
    RequiredCheckSpec("split_manifest_valid", "六字段齐全且 manifest_hash 重算一致", True, "E2"),
    RequiredCheckSpec("predictions_cover_test_rows", "predictions 覆盖全部测试行且无多余行", True, "E2"),
    RequiredCheckSpec("metrics_recomputable", "由 predictions + 标签可重算全部指标", True, "E2"),
    RequiredCheckSpec("no_train_test_overlap", "train/test 行无交集", True, "E2"),
    RequiredCheckSpec("leakage_report_present", "泄漏诊断产物存在且字段完整", True, "E2"),
    RequiredCheckSpec("model_params_whitelisted", "模型与超参均来自白名单", False, "E1"),
    RequiredCheckSpec("seed_recorded", "seed 进入 split manifest 与 run_summary", False, "E1"),
)

_REQUIRED_CHECK_ID = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# 1. 参数解析
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BenchmarkParams:
    """模板的解析后参数（只读）。"""

    target: str
    seed: int
    test_size: float
    models: tuple[str, ...]
    scale_features: bool
    model_params: Mapping[str, Mapping[str, object]]

    @property
    def requires_scaling(self) -> bool:
        return any(MODEL_SPECS[m].requires_scaling for m in self.models)


def parse_params(raw: Mapping[str, object]) -> BenchmarkParams:
    """解析并校验参数；错误按“先形态、后跨字段”的顺序抛出。

    顺序：
      1. 必需键存在；
      2. 未知顶层键拒绝（白名单 = 顶层 5 + `model.param`）；
      3. 保留键拒绝；
      4. target/seed/test_size/scale_features 类型与范围；
      5. models 白名单/重复；
      6. 未选中模型的超参拒绝；
      7. 逐模型解析超参；
      8. 跨字段：LR/SVM 必须 scale_features=true。
    """
    allowed_top = {spec.name for spec in PARAM_SPECS}
    for name in ("target", "seed", "test_size", "models"):
        if name not in raw:
            raise ModelParamError(
                "PARAM_REQUIRED", f"缺少必填参数 {name!r}", field_path=f"parameters.{name}", keyword="required"
            )
    for key in raw:
        if key in allowed_top:
            continue
        if any(key.startswith(model + ".") for model in MODEL_KEYS):
            continue
        raise ModelParamError(
            "PARAM_UNKNOWN", f"未声明的参数 {key!r}", field_path=f"parameters.{key}", keyword="unknown-key"
        )
    assert_no_reserved_params(raw)

    target = raw["target"]
    if not isinstance(target, str) or not target or len(target) > 64:
        raise ModelParamError(
            "TARGET_INVALID", "target 必须是 1–64 字符的字符串", field_path="parameters.target", keyword="type"
        )
    seed = raw["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool) or not (0 <= seed <= 2**31 - 1):
        raise ModelParamError(
            "SEED_INVALID", "seed 必须是 [0, 2^31-1] 的 integer", field_path="parameters.seed", keyword="type"
        )
    test_size = raw["test_size"]
    if isinstance(test_size, bool) or not isinstance(test_size, (int, float)) or not (0.1 <= float(test_size) <= 0.5):
        raise ModelParamError(
            "TEST_SIZE_INVALID", "test_size 必须是 [0.1,0.5] 的 number",
            field_path="parameters.test_size", keyword="range",
        )
    models = parse_model_list(raw["models"])
    scale_features = raw.get("scale_features", DEFAULT_PARAMS["scale_features"])
    if not isinstance(scale_features, bool):
        raise ModelParamError(
            "SCALE_FLAG_INVALID", "scale_features 必须是 boolean",
            field_path="parameters.scale_features", keyword="type",
        )
    assert_no_foreign_model_params(models, raw)
    resolved: dict[str, Mapping[str, object]] = {}
    for model_key in models:
        resolved[model_key] = resolve_params(model_key, raw, selected=models)
    if not scale_features and any(MODEL_SPECS[m].requires_scaling for m in models):
        raise ModelParamError(
            "FEATURE_SCALING_REQUIRED",
            "选中 LR/SVM 时 scale_features 必须为 true（scalers 只在训练折 fit）",
            field_path="parameters.scale_features",
            keyword="const",
        )
    return BenchmarkParams(
        target=target,
        seed=seed,
        test_size=float(test_size),
        models=models,
        scale_features=scale_features,
        model_params=MappingProxyType(resolved),
    )


# ---------------------------------------------------------------------------
# 2. 绑定输入
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DatasetBindingView:
    """模板看到的绑定事实；路径是 attempt 内相对路径，不是绝对路径。"""

    dataset_id: str
    dataset_hash: str
    size_bytes: int
    license_id: str
    relative_path: str
    rows: int

    def __post_init__(self) -> None:
        if self.dataset_id not in ALLOWED_DATASET_IDS:
            raise ModelParamError(
                "DATASET_NOT_ALLOWED",
                f"{self.dataset_id!r} 不在模板允许的数据集 {list(ALLOWED_DATASET_IDS)}",
                field_path="inputs.dataset_binding.dataset_id",
                keyword="enum",
            )
        if not isinstance(self.dataset_hash, str) or len(self.dataset_hash) != 64 or any(
            c not in "0123456789abcdef" for c in self.dataset_hash
        ):
            raise ModelParamError(
                "DATASET_BINDING_HASH_INVALID",
                "dataset_hash 必须是 64 位小写十六进制",
                field_path="inputs.dataset_binding.dataset_hash",
                keyword="pattern",
            )
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes < 1:
            raise ModelParamError(
                "DATASET_BINDING_SIZE_INVALID",
                "size_bytes 必须是正整数",
                field_path="inputs.dataset_binding.size_bytes",
                keyword="type",
            )
        if self.relative_path != "inputs/dataset.csv":
            raise ModelParamError(
                "DATASET_BINDING_PATH_INVALID",
                "绑定路径必须是 inputs/dataset.csv（模板不读外部路径）",
                field_path="inputs.dataset_binding.relative_path",
                keyword="const",
            )
        if self.rows < 2:
            raise ModelParamError(
                "DATASET_ROWS_INVALID", "数据行数必须 ≥2", field_path="inputs.dataset_binding.rows"
            )


class BindingReaderPort(Protocol):
    """读取并校验 `inputs/dataset_binding.json` + `inputs/dataset.csv`。"""

    def read(self, *, relative_inputs: str) -> DatasetBindingView:
        ...


# ---------------------------------------------------------------------------
# 3. 运行报告与模板
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RunReport:
    """`run()` 的返回值：只有事实，没有裁决。"""

    metrics_summary: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    warnings: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        for key, value in self.metrics_summary.items():
            if not isinstance(key, str) or not key:
                raise ValueError("指标名必须非空")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"指标 {key!r} 必须是数值")
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"指标 {key!r} 不得为 NaN/Infinity")


@dataclass(frozen=True, slots=True)
class PreparedPlan:
    """`prepare()` 的返回值：只描述计划，不落地、不拟合。"""

    inputs: Mapping[str, str]
    planned_artifacts: tuple[str, ...]
    params: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    notes: str = ""


class LoggerPort(Protocol):
    def info(self, event: str, **fields: object) -> None: ...
    def warning(self, event: str, **fields: object) -> None: ...


class ClassificationBenchmarkTemplate:
    """三模型分类基准模板；实现 M05 三方法形状。

    这里只写流程与契约。真正的 sklearn 调用、CSV 写出属 WP-05；
    P4 不执行、不导入 sklearn、不产生任何文件。
    """

    template_id = TEMPLATE_ID
    node_type = NODE_TYPE
    side_effect_class = SIDE_EFFECT_CLASS

    def __init__(self, binding_reader: BindingReaderPort, logger: LoggerPort | None = None) -> None:
        self._binding_reader = binding_reader
        self._logger = logger

    # -- 3.1 prepare ------------------------------------------------------
    def prepare(self, *, params: Mapping[str, object], relative_inputs: str = "inputs") -> PreparedPlan:
        """校验参数与绑定；**无副作用**。

        步骤：
          1. `parse_params()`；任何非法模型/超参在此拒绝（尚未拟合）；
          2. 读绑定清单与 CSV，重算 SHA-256，确认 `dataset_id` 在允许集；
          3. 确认 `target` 列存在、类别数 ≥2、每类样本数够分层；
          4. 返回计划：输入两个绑定文件，产物 5 个；不写文件、不 fit。
        """
        parsed = parse_params(params)
        binding = self._binding_reader.read(relative_inputs=relative_inputs)
        # LIB: pandas.read_csv(relative_inputs/dataset.csv) 后检查 target 列、类别数、每类计数。
        # 这里不执行；负例在 WP-05 用真实 CSV 断言列缺失/单类/样本不足的拒绝原因。
        if parsed.requires_scaling and not parsed.scale_features:
            raise ModelParamError(
                "FEATURE_SCALING_REQUIRED", "选中模型需要训练折内 scaler",
                field_path="parameters.scale_features", keyword="const",
            )
        return PreparedPlan(
            inputs={
                "dataset": f"{relative_inputs}/dataset.csv",
                "dataset_binding": f"{relative_inputs}/dataset_binding.json",
            },
            planned_artifacts=tuple(spec.relative_path for spec in ARTIFACT_SPECS),
            params={
                "target": parsed.target,
                "seed": parsed.seed,
                "test_size": parsed.test_size,
                "models": list(parsed.models),
                "scale_features": parsed.scale_features,
                "model_params": {k: dict(v) for k, v in parsed.model_params.items()},
            },
            notes=f"dataset={binding.dataset_id}; models={list(parsed.models)}; seed={parsed.seed}",
        )

    # -- 3.2 run ----------------------------------------------------------
    def run(self, plan: PreparedPlan) -> RunReport:
        """执行训练/评估；只写 artifacts/、logs/、tmp/；不写证据/状态。

        落地步骤（WP-05）：
          1. 从 `plan.params` 取解析结果；读绑定 CSV；校验哈希（prepare 与 run 之间文件不得变）；
          2. 构造 `DatasetView`；`SplitService.build()` 得到六字段 manifest 与 train/test 索引；
          3. 对每个选中模型：
             a. `build_estimator()` 得到未拟合 pipeline；
             b. **只在 train_indices 上 fit**；测试折只 transform/predict；
             c. 测试折 predict / decision_function；
             d. 计算 METRIC_NAMES；记录 n_test；
          4. 生成 predictions.csv（按数据行顺序、仅 test 行）；
          5. 计算泄漏诊断（行重叠、重复行、target 列混入特征、ID 类特征、scaler 作用域）；
          6. 原子写 5 个产物；每个文件先写 tmp 再 replace；
          7. 返回 RunReport（metrics_summary 只放聚合均值，明细在 metrics.json）。
        """
        # 关键断言（落地必须保留）：
        #   - fit 的索引集合 == split.train_indices；predict 的索引集合 == split.test_indices；
        #   - 任何 scaler/encoder 只在 train 上 fit；
        #   - 不读原运行的 metrics/predictions/模型文件；
        #   - 不返回 status/passed/success/verdict。
        raise NotImplementedError("P4 伪代码：模板执行属 WP-05；契约与拒绝点已定义")

    # -- 3.3 emit_artifacts ----------------------------------------------
    def emit_artifacts(self, report: RunReport | None = None) -> tuple[ArtifactSpec, ...]:
        """声明写出的产物；**不提供哈希/大小**（Worker 计算）。"""
        return ARTIFACT_SPECS


# ---------------------------------------------------------------------------
# 4. 登记元数据与自检
# ---------------------------------------------------------------------------
def template_registration_metadata() -> Mapping[str, object]:
    """供 WP-05 构造 M05 `TemplateRegistration` 的静态元数据。

    `module`/`symbol` 是唯一入口形态；`outputs` 与 `ARTIFACT_SPECS` 必须一致；
    `required_checks` 由 M04 Builder 写入 NodeSpec（M05 登记项当前没有该字段，
    见 OQ-P4-08）；`caps.network_allowed` 恒 False。
    """
    return MappingProxyType({
        "template_id": TEMPLATE_ID,
        "node_type": NODE_TYPE,
        "side_effect_class": SIDE_EFFECT_CLASS,
        "module": "researchflow.templates.classification_benchmark",
        "symbol": "ClassificationBenchmarkTemplate",
        "outputs": ARTIFACT_NAMES,
        "required_checks": tuple(spec.check_id for spec in REQUIRED_CHECKS),
        "caps": MappingProxyType({
            "wall_time_sec": 600,
            "memory_mb": 2048,
            "disk_mb": 512,
            "max_attempts": 2,
            "max_artifacts": 8,
            "max_artifact_bytes": 64 * 1024 * 1024,
            "network_allowed": False,
        }),
    })


def assert_template_boundary() -> list[str]:
    """静态边界：无任意代码入口、无网络、无裁决、无自报哈希。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("eval", "exec", "compile", "__import__", "subprocess", "socket",
                 "requests", "urllib", "http", "pickle", "joblib"):
        if hasattr(module, attr):
            problems.append(f"模块暴露禁用名 {attr!r}（任意代码/网络/反序列化）")
    for spec in ARTIFACT_SPECS:
        if hasattr(spec, "sha256") or hasattr(spec, "size_bytes"):
            problems.append(f"产物声明 {spec.name} 含哈希/大小槽位（必须由 Worker 计算）")
    for check in REQUIRED_CHECKS:
        if not _REQUIRED_CHECK_ID.match(check.check_id):
            problems.append(f"required_check {check.check_id!r} 不符合 ^[a-z][a-z0-9_]*$")
        if check.execution_critical and check.min_level not in ("E2", "E3"):
            problems.append(f"{check.check_id}: 执行类必检最低等级必须是 E2/E3")
    if len({c.check_id for c in REQUIRED_CHECKS}) != len(REQUIRED_CHECKS):
        problems.append("required_checks 有重复")
    if set(ARTIFACT_NAMES) != {spec.name for spec in ARTIFACT_SPECS}:
        problems.append("ARTIFACT_NAMES 与 ARTIFACT_SPECS 不一致")
    return problems