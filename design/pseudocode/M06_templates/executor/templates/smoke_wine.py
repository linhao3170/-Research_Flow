"""M06 · executor/templates/smoke_wine.py — Wine 冒烟任务与 Breast Cancer 主干差异（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-004（模板可跑）、策划书 §14.1（Wine 冒烟 / BCW 主演示）
依赖：M06 classification_benchmark（同一模板实现）、M06 models（三模型）、M06 datasets_registry（wine 登记）
不变量：冒烟只用 wine；三模型全选但超参收紧；wall_time_sec=120；max_workers=1；不联网；
        冒烟结果不得被写成 VERIFIED/L3 证据；模板不自报耗时是否“通过”
错误码：SCHEMA_INVALID（422，超参超过冒烟上限/数据集不是 wine）；RESOURCE_BUDGET_EXCEEDED（429，执行器墙钟）
写入者：模板写 artifacts/；Worker 记录 elapsed/exit；Collector 写 E2；Gate 才能判定是否满足预算
状态：伪代码；不执行、不计时、不声称“2 分钟内已实测”

## 冒烟与主干：相同点与差异点

  相同：同一个 `classification_benchmark` 模板、同一组 5 个产物、同一组指标、
        同一个 Split Manifest 六字段、同一套 required_checks（冒烟另加墙钟项）。
  差异：
    | 维度 | Wine 冒烟 | Breast Cancer 主干 |
    |---|---|---|
    | dataset_id | `wine` | `breast_cancer` |
    | 行/特征/类别 | 178 / 13 / 3 | 569 / 30 / 2 |
    | models | 三模型全选 | 三模型全选 |
    | 超参 | 上限收紧（见 SMOKE_CAPS） | 模板默认值 |
    | wall_time_sec | 120 | 600 |
    | memory_mb | 1024 | 2048 |
    | test_size | 0.2 | 0.2 |
    | 额外必检 | `smoke_within_wall_time` | 无；主干按 L3 覆盖判定 |
    | 用途 | 30 秒级链路自检；不得作为论文/验收成绩 | 正式演示；L3 必须覆盖指标来源节点 |

## “2 分钟”怎么保证（不是靠嘴）

  1. 超参上限由 `assert_smoke_budget()` 在 `prepare()` 前拒绝（RF ≤100 棵树、LR/SVM C 收紧）；
  2. 任务级 `limits.wall_time_sec=120` 由执行器强制；超时走 P3 的整树回收，
     不会出现“模板还在跑但任务已结束”；
  3. 是否真的在 120s 内完成，由 E2 的 `executor_process_exit` + elapsed 观测，
     再由 Gate 的 `smoke_within_wall_time` 判定；P4 不预填“已通过”。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

from .classification_benchmark import (
    ALLOWED_DATASET_IDS,
    ARTIFACT_SPECS,
    REQUIRED_CHECKS,
    TEMPLATE_ID,
    RequiredCheckSpec,
    assert_template_boundary,
)
from .models import MODEL_KEYS, ModelParamError, resolve_params

__all__ = [
    "SMOKE_CAPS",
    "SMOKE_DATASET_ID",
    "SMOKE_REQUIRED_CHECKS",
    "SMOKE_TASK_DRAFT",
    "SMOKE_WALL_TIME_SEC",
    "SmokeTaskDraft",
    "assert_smoke_budget",
    "assert_smoke_profile",
    "build_smoke_params",
    "differences_vs_main",
]

SMOKE_DATASET_ID: Final[str] = "wine"
SMOKE_WALL_TIME_SEC: Final[int] = 120
SMOKE_MEMORY_MB: Final[int] = 1024
SMOKE_SEED: Final[int] = 20261111
SMOKE_TEST_SIZE: Final[float] = 0.2

# 每个模型在冒烟里的上限；超过即拒绝，不靠“应该很快”的假设。
SMOKE_CAPS: Final[Mapping[str, Mapping[str, float]]] = MappingProxyType({
    "logistic_regression": MappingProxyType({"max_iter": 1000, "C": 100.0}),
    "random_forest": MappingProxyType({"n_estimators": 100, "max_depth": 32}),
    "svm": MappingProxyType({"C": 10.0}),
})

SMOKE_REQUIRED_CHECKS: Final[tuple[RequiredCheckSpec, ...]] = REQUIRED_CHECKS + (
    RequiredCheckSpec(
        "smoke_within_wall_time",
        "E2 观测的 elapsed ≤ 120s；超时不算通过",
        True,
        "E2",
    ),
)

# 冒烟参数：三模型全选、收紧超参、固定 seed。默认值必须已在上限内。
_SMOKE_OVERRIDES: Final[Mapping[str, Mapping[str, object]]] = MappingProxyType({
    "logistic_regression": MappingProxyType({"C": 1.0, "max_iter": 500}),
    "random_forest": MappingProxyType({"n_estimators": 50, "max_depth": 12}),
    "svm": MappingProxyType({"C": 1.0, "kernel": "rbf"}),
})


def build_smoke_params() -> dict[str, object]:
    """构造冒烟任务的 `TaskSpec.parameters`（不是 TaskSpec 本体）。"""
    params: dict[str, object] = {
        "target": "target",
        "seed": SMOKE_SEED,
        "test_size": SMOKE_TEST_SIZE,
        "models": list(MODEL_KEYS),
        "scale_features": True,
    }
    for model_key, overrides in _SMOKE_OVERRIDES.items():
        for name, value in overrides.items():
            params[f"{model_key}.{name}"] = value
    return params


def assert_smoke_budget(params: Mapping[str, object]) -> None:
    """在 `prepare()` 前拒绝超预算的冒烟参数。

    检查：
      1. `models` 必须恰好是三模型全选（冒烟要覆盖三个工厂）；
      2. 每个模型解析后的超参不得超过 `SMOKE_CAPS`；
      3. `test_size` 必须等于 0.2（冒烟与主干的唯一允许差异是数据/预算，不是评估口径）。
    错误 reason 固定：`SMOKE_MODELS_INCOMPLETE` / `SMOKE_BUDGET_EXCEEDED` / `SMOKE_TEST_SIZE_DRIFT`。
    """
    models = params.get("models")
    if not isinstance(models, list) or set(models) != set(MODEL_KEYS) or len(models) != len(MODEL_KEYS):
        raise ModelParamError(
            "SMOKE_MODELS_INCOMPLETE",
            f"冒烟必须全选 {list(MODEL_KEYS)}",
            field_path="parameters.models",
            keyword="const",
        )
    if params.get("test_size") != SMOKE_TEST_SIZE:
        raise ModelParamError(
            "SMOKE_TEST_SIZE_DRIFT",
            f"冒烟 test_size 固定 {SMOKE_TEST_SIZE}",
            field_path="parameters.test_size",
            keyword="const",
        )
    for model_key, caps in SMOKE_CAPS.items():
        resolved = resolve_params(model_key, params, selected=list(MODEL_KEYS))
        for name, cap in caps.items():
            value = resolved.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > cap:
                raise ModelParamError(
                    "SMOKE_BUDGET_EXCEEDED",
                    f"{model_key}.{name}={value} > 冒烟上限 {cap}",
                    field_path=f"parameters.{model_key}.{name}",
                    keyword="maximum",
                )


@dataclass(frozen=True, slots=True)
class SmokeTaskDraft:
    """冒烟任务草案；`ruleset_hash` 由创建入口注入，不在本文件伪造。

    这不是合法 `TaskSpec` 的完整实例：`task_id`/`ruleset_hash`/`dataset_ref.sha256`
    都要由 API/登记层注入。它只固定“冒烟任务长什么样”的可评审形状。
    """

    template_id: str
    dataset_uri: str
    dataset_sha256_source: str
    parameters: Mapping[str, object]
    wall_time_sec: int
    max_workers: int
    max_memory_mb: int
    notes: str = ""

    def __post_init__(self) -> None:
        if self.template_id != TEMPLATE_ID:
            raise ValueError("冒烟必须复用 classification_benchmark 模板")
        if self.dataset_uri != f"local://datasets/{SMOKE_DATASET_ID}":
            raise ValueError("冒烟数据集必须是 wine")
        if self.wall_time_sec != SMOKE_WALL_TIME_SEC:
            raise ValueError("冒烟 wall_time_sec 必须是 120")
        if self.max_workers != 1:
            raise ValueError("冒烟 max_workers 必须是 1")
        if self.max_memory_mb < 512:
            raise ValueError("冒烟 max_memory_mb 不得低于 512")


def _smoke_draft() -> SmokeTaskDraft:
    params = build_smoke_params()
    assert_smoke_budget(params)
    return SmokeTaskDraft(
        template_id=TEMPLATE_ID,
        dataset_uri=f"local://datasets/{SMOKE_DATASET_ID}",
        dataset_sha256_source="datasets.lock.json#wine（WP-05 注入；本文件不写真实哈希）",
        parameters=MappingProxyType(params),
        wall_time_sec=SMOKE_WALL_TIME_SEC,
        max_workers=1,
        max_memory_mb=SMOKE_MEMORY_MB,
        notes="冒烟只证明链路可跑；不得写成 VERIFIED/L3 证据",
    )


SMOKE_TASK_DRAFT: Final[SmokeTaskDraft] = _smoke_draft()


def differences_vs_main() -> tuple[Mapping[str, str], ...]:
    """返回冒烟 vs 主干的差异表（供 MODULE.md 与评审逐行核对）。"""
    return (
        MappingProxyType({"dimension": "dataset", "smoke": "wine (178×13, 3 classes)",
                          "main": "breast_cancer (569×30, 2 classes)"}),
        MappingProxyType({"dimension": "models", "smoke": "三模型全选",
                          "main": "三模型全选"}),
        MappingProxyType({"dimension": "hyperparameters", "smoke": "SMOKE_CAPS 收紧",
                          "main": "模板默认值"}),
        MappingProxyType({"dimension": "wall_time_sec", "smoke": "120", "main": "600"}),
        MappingProxyType({"dimension": "memory_mb", "smoke": "1024", "main": "2048"}),
        MappingProxyType({"dimension": "extra_check", "smoke": "smoke_within_wall_time",
                          "main": "无；按 L3 覆盖判定"}),
        MappingProxyType({"dimension": "artifacts", "smoke": "5 个，与主干相同",
                          "main": "5 个，与冒烟相同"}),
        MappingProxyType({"dimension": "claim", "smoke": "只证明链路可跑",
                          "main": "可作为演示；L3 覆盖后才有 VERIFIED 资格"}),
    )


def assert_smoke_profile() -> list[str]:
    """静态检查冒烟档案：预算、数据集、产物、check 名。"""
    problems: list[str] = []
    if SMOKE_WALL_TIME_SEC > 120:
        problems.append("冒烟墙钟超过 120s")
    if SMOKE_DATASET_ID not in ALLOWED_DATASET_IDS:
        problems.append("冒烟数据集不在登记表")
    if SMOKE_TASK_DRAFT.max_workers != 1:
        problems.append("冒烟 max_workers 必须为 1")
    for check in SMOKE_REQUIRED_CHECKS:
        if not check.check_id.replace("_", "").isalnum() or not check.check_id[0].islower():
            problems.append(f"check_id 形态非法：{check.check_id}")
    if {spec.name for spec in ARTIFACT_SPECS} != {
        "split_manifest", "metrics", "predictions", "run_summary", "leakage_report"
    }:
        problems.append("冒烟产物集与主干不一致")
    problems.extend(assert_template_boundary())
    return problems