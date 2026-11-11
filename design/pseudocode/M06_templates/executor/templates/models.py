"""M06 · executor/templates/models.py — 三模型工厂、超参白名单与拒绝点（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-004（内置表格 ML 模板）、FR-005（E2 只来自真实执行）
依赖：M05 registry.ParamSchema（参数先校验一次）、M06 splits（划分先于拟合）、tools/requirements.lock
不变量：模型只来自三值白名单；超参只来自本文件白名单；不做类型强转；用户不得设置 random_state/n_jobs；
        预处理只在训练折上 fit；模型工厂不联网、不读任意代码、不做反序列化
错误码：SCHEMA_INVALID（422，参数/模型名非法）；RESOURCE_BUDGET_EXCEEDED（429，仅由执行器限额层给出）
写入者：**无**（本文件只构造内存对象；不写 artifacts/、不写证据、不写状态）
状态：伪代码；模型拟合属 WP-05，本文件只定义契约、白名单与拒绝点

## 三条边界

  1. **白名单外没有模型**：只有 logistic_regression / random_forest / svm 三个键。
     不接受 `xgboost`、`lightgbm`、任意 dotted path、`module:Class`、pickle/joblib 文件。
  2. **白名单外没有超参**：每个模型只认本文件 `MODEL_SPECS` 列出的键；
     未知键、保留键（`random_state`/`n_jobs`/`warm_start`）、别的模型的键一律拒绝。
     不做 `"42" -> 42`、`true -> 1` 之类强转；不做“猜你想传”。
  3. **随机性与并行由工厂钉死**：`random_state=seed`、`n_jobs=1` 由工厂写入，
     用户无权覆盖。并行度属于 Governor/Executor，不属于模板；模板里再开线程/进程会
     让资源峰值与 E2 观测失真。

## 为什么没有模型二进制产物

  T0 的验证路径是 L3 从原始数据**重新训练**，不是加载 Executor 的模型文件。
  保存 `.pkl/.joblib` 会把反序列化风险带进证据包（pickle 可执行任意代码），
  而它又不构成独立验证所需的事实。因此本模板只产出指标、预测、划分清单、
  运行摘要与泄漏诊断；模型对象只在本次进程内存在。
  【OQ-P4-10】若 WP-05 坚持要模型产物，必须同时给出“永不反序列化”的验证规则。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

__all__ = [
    "MODEL_KEYS",
    "MODEL_SPECS",
    "RESERVED_PARAM_NAMES",
    "ModelParamError",
    "ModelSpec",
    "HyperParam",
    "HyperKind",
    "assert_model_boundary",
    "assert_no_foreign_model_params",
    "assert_no_reserved_params",
    "build_estimator",
    "param_field_specs",
    "parse_model_list",
    "resolve_params",
]

MODEL_KEYS: Final[tuple[str, ...]] = (
    "logistic_regression",
    "random_forest",
    "svm",
)

# 这些名字由工厂写入，不接受用户传值。`n_jobs` 固定 1；`random_state` 固定 seed。
RESERVED_PARAM_NAMES: Final[tuple[str, ...]] = (
    "random_state",
    "n_jobs",
    "warm_start",
    "verbose",
    "n_threads",
    "thread_count",
)

# 静态扫描禁名：模型模块不得联网、起进程、动态导入或反序列化。
FORBIDDEN_MODEL_ATTRS: Final[tuple[str, ...]] = (
    "socket", "requests", "urllib", "http", "subprocess", "multiprocessing",
    "eval", "exec", "compile", "__import__", "importlib",
    "pickle", "joblib", "dill", "cloudpickle",
)

FIXED_N_JOBS: Final[int] = 1


class HyperKind(StrEnum):
    NUMBER = "number"
    INTEGER = "integer"
    ENUM = "enum"


@dataclass(frozen=True, slots=True)
class HyperParam:
    """一个超参的白名单项。

    `name` 是模型内的短名；对外键名是 `f"{model_key}.{name}"`。
    `default` 是模板默认值，**不是** schema 默认值；运行摘要必须记录解析后的完整取值。
    """

    name: str
    kind: HyperKind
    default: object
    minimum: float | None = None
    maximum: float | None = None
    enum: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if not self.name or "." in self.name:
            raise ValueError("超参短名不得为空或含点")
        if self.kind is HyperKind.ENUM and not self.enum:
            raise ValueError(f"枚举超参 {self.name!r} 必须给出 enum")
        if self.kind is not HyperKind.ENUM and self.enum:
            raise ValueError(f"非枚举超参 {self.name!r} 不得带 enum")

    @property
    def public_name(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """一个白名单模型的完整契约。"""

    model_key: str
    display_name: str
    estimator_symbol: str
    params: tuple[HyperParam, ...]
    requires_scaling: bool
    supports_decision_function: bool = False
    note: str = ""

    def param(self, short_name: str) -> HyperParam | None:
        for spec in self.params:
            if spec.name == short_name:
                return spec
        return None

    @property
    def full_param_names(self) -> tuple[str, ...]:
        return tuple(f"{self.model_key}.{p.name}" for p in self.params)


def _p(name: str, kind: HyperKind, default: object, **kwargs: object) -> HyperParam:
    return HyperParam(name=name, kind=kind, default=default, **kwargs)  # type: ignore[arg-type]


# 默认值不是“最优参数”，只是 T0 可复现的保守起点。所有默认值都必须能在
# Wine（178 行）与 Breast Cancer（569 行）上于预算内完成。
MODEL_SPECS: Final[Mapping[str, ModelSpec]] = MappingProxyType({
    "logistic_regression": ModelSpec(
        model_key="logistic_regression",
        display_name="Logistic Regression",
        estimator_symbol="sklearn.linear_model.LogisticRegression",
        params=(
            _p("C", HyperKind.NUMBER, 1.0, minimum=1e-6, maximum=1e6,
               note="正则强度倒数；越大越弱正则"),
            _p("max_iter", HyperKind.INTEGER, 1000, minimum=100, maximum=10000),
            _p("class_weight", HyperKind.ENUM, "none", enum=("none", "balanced")),
        ),
        requires_scaling=True,
        supports_decision_function=True,
        note="lbfgs + l2；多分类使用 multinomial（由 sklearn 版本决定，版本须进 run_summary）",
    ),
    "random_forest": ModelSpec(
        model_key="random_forest",
        display_name="Random Forest",
        estimator_symbol="sklearn.ensemble.RandomForestClassifier",
        params=(
            _p("n_estimators", HyperKind.INTEGER, 200, minimum=10, maximum=500),
            _p("max_depth", HyperKind.INTEGER, 16, minimum=1, maximum=64),
            _p("min_samples_leaf", HyperKind.INTEGER, 1, minimum=1, maximum=50),
            _p("max_features", HyperKind.ENUM, "sqrt", enum=("sqrt", "log2")),
            _p("class_weight", HyperKind.ENUM, "none", enum=("none", "balanced")),
        ),
        requires_scaling=False,
        supports_decision_function=True,
        note="n_jobs 固定 1；不启用 warm_start；不写模型文件",
    ),
    "svm": ModelSpec(
        model_key="svm",
        display_name="Support Vector Machine",
        estimator_symbol="sklearn.svm.SVC",
        params=(
            _p("C", HyperKind.NUMBER, 1.0, minimum=1e-6, maximum=1e6),
            _p("kernel", HyperKind.ENUM, "rbf", enum=("linear", "rbf")),
            _p("gamma", HyperKind.ENUM, "scale", enum=("scale", "auto")),
            _p("class_weight", HyperKind.ENUM, "none", enum=("none", "balanced")),
        ),
        requires_scaling=True,
        supports_decision_function=True,
        note="probability=False；roc_auc 用 decision_function，避免内部 CV 引入第二层随机性",
    ),
})


# ---------------------------------------------------------------------------
# 1. 拒绝原因
# ---------------------------------------------------------------------------
class ModelParamError(ValueError):
    """模型/超参拒绝。对外统一 `SCHEMA_INVALID`(422)，但内部 reason 必须可断言。

    为什么不用 500：这是调用方输入问题（模型名、超参键、类型、范围），
    不是服务端故障；按 field_path 修正后可重发。
    """

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str,
        keyword: str = "invalid",
    ) -> None:
        self.reason = reason
        self.field_path = field_path
        self.keyword = keyword
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


# ---------------------------------------------------------------------------
# 2. 模型列表
# ---------------------------------------------------------------------------
def parse_model_list(value: object) -> tuple[str, ...]:
    """解析 `parameters.models`：非空、无重复、每个都在三值白名单内。

    错误顺序固定：先判形态（list），再逐项判字符串，再判白名单，最后判重复。
    这样负例可以精确断言 `field_path=parameters.models[i]` 与 reason。
    """
    if not isinstance(value, list):
        raise ModelParamError(
            "MODELS_NOT_ARRAY",
            f"models 必须是数组，实际 {type(value).__name__}",
            field_path="parameters.models",
            keyword="type",
        )
    if not value:
        raise ModelParamError(
            "MODELS_EMPTY",
            "models 至少选一个模型",
            field_path="parameters.models",
            keyword="minItems",
        )
    out: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        path = f"parameters.models[{index}]"
        if not isinstance(item, str):
            raise ModelParamError(
                "MODEL_NOT_STRING",
                f"模型名必须是字符串，实际 {type(item).__name__}",
                field_path=path,
                keyword="type",
            )
        if item not in MODEL_SPECS:
            raise ModelParamError(
                "MODEL_NOT_ALLOWED",
                f"{item!r} 不在白名单 {list(MODEL_KEYS)}",
                field_path=path,
                keyword="enum",
            )
        if item in seen:
            raise ModelParamError(
                "MODEL_DUPLICATED",
                f"模型 {item!r} 重复出现",
                field_path=path,
                keyword="uniqueItems",
            )
        seen.add(item)
        out.append(item)
    return tuple(out)


def assert_no_reserved_params(params: Mapping[str, object]) -> None:
    """拒绝用户直接设置 `random_state`/`n_jobs` 等保留键。

    允许两种写法都拒绝：裸键 `n_jobs`，以及带模型前缀的 `random_forest.n_jobs`。
    后者在 `resolve_params` 里还会按“不在白名单”再拒一次（纵深防御）。
    """
    for key in params:
        short = key.rsplit(".", 1)[-1]
        if key in RESERVED_PARAM_NAMES or short in RESERVED_PARAM_NAMES:
            raise ModelParamError(
                "RESERVED_MODEL_PARAM",
                f"{key!r} 由工厂固定写入，不接受用户传值",
                field_path=f"parameters.{key}",
                keyword="reserved",
            )


def assert_no_foreign_model_params(
    selected: Sequence[str],
    params: Mapping[str, object],
) -> None:
    """拒绝给“未选中的模型”传超参，避免静默忽略或误用。

    例：`models=["svm"]` 但传了 `random_forest.n_estimators` → 拒绝。
    键必须以 `model_key + "."` 开头且 model_key 是三值之一；否则不在此函数处理
    （未知顶层键由 M05 ParamSchema 拒绝）。
    """
    selected_set = set(selected)
    for key in params:
        for model_key in MODEL_KEYS:
            prefix = model_key + "."
            if key.startswith(prefix) and model_key not in selected_set:
                raise ModelParamError(
                    "MODEL_PARAM_FOR_UNSELECTED_MODEL",
                    f"{key!r} 属于未选中的模型 {model_key!r}",
                    field_path=f"parameters.{key}",
                    keyword="unknown-key",
                )


# ---------------------------------------------------------------------------
# 3. 超参解析
# ---------------------------------------------------------------------------
def resolve_params(
    model_key: str,
    params: Mapping[str, object],
    *,
    selected: Sequence[str],
) -> Mapping[str, object]:
    """解析一个模型的最终超参：默认值 + 用户覆盖，并逐项校验。

    返回只读映射，键为**短名**（`C`、`n_estimators`），值不做类型强转。
    未知键、保留键、未选中模型的键、类型/范围/枚举不符都在这里拒绝。
    """
    if model_key not in MODEL_SPECS:
        raise ModelParamError(
            "MODEL_NOT_ALLOWED",
            f"{model_key!r} 不在白名单",
            field_path="parameters.models",
            keyword="enum",
        )
    if model_key not in selected:
        raise ModelParamError(
            "MODEL_PARAM_FOR_UNSELECTED_MODEL",
            f"模型 {model_key!r} 未被 models 选中",
            field_path="parameters.models",
            keyword="unknown-key",
        )
    spec = MODEL_SPECS[model_key]
    resolved: dict[str, object] = {p.name: p.default for p in spec.params}
    prefix = model_key + "."

    for key, value in params.items():
        if not key.startswith(prefix):
            continue
        short = key[len(prefix):]
        param = spec.param(short)
        if param is None:
            raise ModelParamError(
                "UNKNOWN_MODEL_PARAM",
                f"{model_key!r} 没有白名单超参 {short!r}",
                field_path=f"parameters.{key}",
                keyword="unknown-key",
            )
        _validate_value(model_key, param, value, path=f"parameters.{key}")
        resolved[short] = value
    return MappingProxyType(resolved)


def _validate_value(model_key: str, param: HyperParam, value: object, *, path: str) -> None:
    """单项校验。bool 永远不是 integer/number；不做任何强转。"""
    if param.kind is HyperKind.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ModelParamError(
                "MODEL_PARAM_TYPE",
                f"{param.name} 期望 integer，实际 {type(value).__name__}",
                field_path=path,
                keyword="type",
            )
        numeric = float(value)
    elif param.kind is HyperKind.NUMBER:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ModelParamError(
                "MODEL_PARAM_TYPE",
                f"{param.name} 期望 number，实际 {type(value).__name__}",
                field_path=path,
                keyword="type",
            )
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ModelParamError(
                "MODEL_PARAM_NON_FINITE",
                f"{param.name} 不得为 NaN/Infinity",
                field_path=path,
                keyword="type",
            )
    elif param.kind is HyperKind.ENUM:
        if not isinstance(value, str):
            raise ModelParamError(
                "MODEL_PARAM_TYPE",
                f"{param.name} 期望字符串枚举，实际 {type(value).__name__}",
                field_path=path,
                keyword="type",
            )
        if value not in param.enum:
            raise ModelParamError(
                "MODEL_PARAM_ENUM",
                f"{param.name}={value!r} 不在 {list(param.enum)}",
                field_path=path,
                keyword="enum",
            )
        return
    else:  # pragma: no cover - 枚举已封闭
        raise AssertionError(f"未处理的 HyperKind: {param.kind}")

    if param.minimum is not None and numeric < param.minimum:
        raise ModelParamError(
            "MODEL_PARAM_RANGE",
            f"{param.name}={numeric} < {param.minimum}",
            field_path=path,
            keyword="minimum",
        )
    if param.maximum is not None and numeric > param.maximum:
        raise ModelParamError(
            "MODEL_PARAM_RANGE",
            f"{param.name}={numeric} > {param.maximum}",
            field_path=path,
            keyword="maximum",
        )


# ---------------------------------------------------------------------------
# 4. 参数 Schema 导出（供 WP-05 登记到 M05 ParamSchema）
# ---------------------------------------------------------------------------
def param_field_specs() -> tuple[Mapping[str, object], ...]:
    """把白名单导出为 M05 `ParamField` 的构造参数（只读、稳定顺序）。

    导出的字段名是**完整键** `model.param`；M05 `ParamSchema.validate` 会把
    `field_path` 拼成 `parameters.model.param`，负例因此可以精确断言。
    `required=False`：未传时用模板默认值；默认值不写进 schema（M05 的既有口径）。
    """
    out: list[Mapping[str, object]] = []
    for model_key in MODEL_KEYS:
        spec = MODEL_SPECS[model_key]
        for param in spec.params:
            kind = {
                HyperKind.INTEGER: "integer",
                HyperKind.NUMBER: "number",
                HyperKind.ENUM: "string",
            }[param.kind]
            out.append(MappingProxyType({
                "name": f"{model_key}.{param.name}",
                "type": kind,
                "required": False,
                "minimum": param.minimum,
                "maximum": param.maximum,
                "enum": param.enum,
                "note": param.note,
            }))
    return tuple(out)


# ---------------------------------------------------------------------------
# 5. 模型工厂（构造属 WP-05；本文件钉死形状与随机性）
# ---------------------------------------------------------------------------
def build_estimator(
    model_key: str,
    resolved: Mapping[str, object],
    *,
    seed: int,
    scale_features: bool,
) -> object:
    """按白名单构造一个**未拟合**的 estimator/pipeline。

    形状（落地时必须逐条一致）：
      - LR/SVM：`Pipeline([("scaler", StandardScaler()), ("model", <estimator>)])`；
        scaler 只在训练折 `fit`，测试折只 `transform`（防泄漏；训练折索引只能从
        `splits.SplitBundle.train_indices` 取，拟合前必须已通过 `splits.SplitService.assert_valid`）。
      - RF：裸 `RandomForestClassifier`，不加 scaler。
      - 三个模型都写 `random_state=seed`；RF 写 `n_jobs=1`。
      - `class_weight="none"` 映射为 `None`，不把字符串传给 sklearn。
      - 不做 `eval`/`getattr(sklearn, user_string)`；映射是静态的。

    本函数在 P4 不实现拟合/构造细节（属 WP-05），只保留可检查的契约与 `# LIB:` 意图。
    """
    if model_key not in MODEL_SPECS:
        raise ModelParamError(
            "MODEL_NOT_ALLOWED",
            f"{model_key!r} 不在白名单",
            field_path="parameters.models",
            keyword="enum",
        )
    spec = MODEL_SPECS[model_key]
    allowed = {p.name for p in spec.params}
    unexpected = set(resolved) - allowed
    if unexpected:
        raise ModelParamError(
            "UNKNOWN_MODEL_PARAM",
            f"解析结果含白名单外键 {sorted(unexpected)}",
            field_path=f"parameters.{model_key}",
            keyword="unknown-key",
        )
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ModelParamError(
            "SEED_INVALID",
            "seed 必须是 ≥0 的 integer",
            field_path="parameters.seed",
            keyword="type",
        )
    if spec.requires_scaling and not scale_features:
        raise ModelParamError(
            "FEATURE_SCALING_REQUIRED",
            f"{model_key} 需要训练折内 scaler；scale_features 不得为 false",
            field_path="parameters.scale_features",
            keyword="const",
        )

    # LIB: from sklearn.pipeline import Pipeline
    # LIB: from sklearn.preprocessing import StandardScaler
    # LIB: from sklearn.linear_model import LogisticRegression
    # LIB: from sklearn.ensemble import RandomForestClassifier
    # LIB: from sklearn.svm import SVC
    #
    # LR:  LogisticRegression(C=..., max_iter=..., class_weight=..., random_state=seed)
    # RF:  RandomForestClassifier(n_estimators=..., max_depth=..., min_samples_leaf=...,
    #                              max_features=..., class_weight=..., random_state=seed,
    #                              n_jobs=1)
    # SVM: SVC(C=..., kernel=..., gamma=..., class_weight=..., probability=False,
    #          random_state=seed)
    #
    # 返回未拟合对象；任何 fit 都只能发生在 `splits.SplitBundle.train_indices` 上，
    # 且拟合前必须已通过 `splits.SplitService.assert_valid`。
    raise NotImplementedError("P4 伪代码：模型构造属 WP-05；白名单与拒绝点已在本文件定义")


# ---------------------------------------------------------------------------
# 6. 静态边界自检
# ---------------------------------------------------------------------------
def assert_model_boundary() -> list[str]:
    """检查本模块没有把“模型”变成任意代码入口。

    返回违反项（空 = 通过）。检查的是**代码结构**，不是运行结果：
      1. 模块级不得暴露 FORBIDDEN_MODEL_ATTRS；
      2. `MODEL_SPECS` 的键必须恰为三值白名单；
      3. 每个模型的 estimator_symbol 必须以 `sklearn.` 开头（不是任意 dotted path）；
      4. 用户可传键里不得出现 `random_state`/`n_jobs`。
    """
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in FORBIDDEN_MODEL_ATTRS:
        if hasattr(module, attr):
            problems.append(f"模块暴露禁用名 {attr!r}（任意代码/网络/反序列化）")
    if set(MODEL_SPECS) != set(MODEL_KEYS):
        problems.append("MODEL_SPECS 键集合与 MODEL_KEYS 不一致")
    for key, spec in MODEL_SPECS.items():
        if not spec.estimator_symbol.startswith("sklearn."):
            problems.append(f"{key}: estimator_symbol 必须指向 sklearn.*，实际 {spec.estimator_symbol!r}")
        for param in spec.params:
            if param.name in RESERVED_PARAM_NAMES:
                problems.append(f"{key}: 超参 {param.name!r} 与保留名冲突")
    return problems