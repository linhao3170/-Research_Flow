"""Whitelisted T0 templates and parameter validation (WP-05).

Templates are data + code that ship with the product.  Nothing here accepts
arbitrary user code: a template id must be registered, every parameter is
type/range checked, and the model name must be in the frozen whitelist.

Task template ``classification_benchmark@1.0.0`` expands into one split node
plus one training node per requested model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from researchflow.rules import required_checks_for
from researchflow.templates.errors import ParameterInvalid, TemplateNotRegistered

__all__ = [
    "NODE_TEMPLATES",
    "NODE_TYPE_SPLIT",
    "NODE_TYPE_TRAIN",
    "SPLIT_TEMPLATE_ID",
    "TASK_TEMPLATES",
    "TASK_TEMPLATE_ID",
    "TRAIN_TEMPLATE_ID",
    "WHITELIST_MODELS",
    "TemplateSpec",
    "lookup_node_template",
    "lookup_task_template",
    "validate_split_parameters",
    "validate_task_parameters",
    "validate_train_parameters",
]

NODE_TYPE_SPLIT = "ml.split"
NODE_TYPE_TRAIN = "ml.train.classifier"

TASK_TEMPLATE_ID = "classification_benchmark@1.0.0"
SPLIT_TEMPLATE_ID = "split_dataset@1.0.0"
TRAIN_TEMPLATE_ID = "train_classifier@1.0.0"

WHITELIST_MODELS: tuple[str, ...] = (
    "logistic_regression",
    "random_forest",
    "decision_tree",
)

TASK_PARAMETER_KEYS: tuple[str, ...] = ("target", "seed", "test_size", "models")
SPLIT_PARAMETER_KEYS: tuple[str, ...] = ("target", "seed", "test_size")
TRAIN_PARAMETER_KEYS: tuple[str, ...] = ("model", "seed")

GROUP_COLUMN = "patient_id"
TIME_COLUMN = "event_time"
RESERVED_COLUMNS: tuple[str, ...] = (GROUP_COLUMN, TIME_COLUMN)


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    template_id: str
    kind: str
    node_type: str | None
    side_effect_class: str
    outputs: tuple[str, ...]
    description: str
    retry_policy: tuple[int, float] = (2, 0.0)

    @property
    def required_checks(self) -> tuple[str, ...]:
        if self.node_type is None:
            return ()
        return required_checks_for(self.node_type)


NODE_TEMPLATES: dict[str, TemplateSpec] = {
    SPLIT_TEMPLATE_ID: TemplateSpec(
        template_id=SPLIT_TEMPLATE_ID,
        kind="node",
        node_type=NODE_TYPE_SPLIT,
        side_effect_class="PURE_ARTIFACT",
        outputs=("split_manifest.json",),
        description="Deterministic temporal/group split; writes a split manifest.",
    ),
    TRAIN_TEMPLATE_ID: TemplateSpec(
        template_id=TRAIN_TEMPLATE_ID,
        kind="node",
        node_type=NODE_TYPE_TRAIN,
        side_effect_class="PURE_ARTIFACT",
        outputs=("metrics.json", "predictions.csv"),
        description="Fit one whitelisted classifier and score its test split.",
    ),
}

TASK_TEMPLATES: dict[str, TemplateSpec] = {
    TASK_TEMPLATE_ID: TemplateSpec(
        template_id=TASK_TEMPLATE_ID,
        kind="task",
        node_type=None,
        side_effect_class="PURE_ARTIFACT",
        outputs=(),
        description="Split + one classifier node per whitelisted model.",
    ),
}


def lookup_task_template(template_id: str) -> TemplateSpec:
    spec = TASK_TEMPLATES.get(template_id)
    if spec is None:
        raise TemplateNotRegistered(
            f"task template is not registered: {template_id!r}",
            field_path="template_id",
        )
    return spec


def lookup_node_template(template_id: str) -> TemplateSpec:
    spec = NODE_TEMPLATES.get(template_id)
    if spec is None:
        raise TemplateNotRegistered(
            f"node template is not registered: {template_id!r}",
            field_path="template_id",
        )
    return spec


def _require_mapping(parameters: Any) -> Mapping[str, Any]:
    if not isinstance(parameters, Mapping):
        raise ParameterInvalid("parameters must be a JSON object", field_path="parameters")
    return parameters


def _reject_unknown(parameters: Mapping[str, Any], allowed: Iterable[str]) -> None:
    allowed_set = set(allowed)
    for key in parameters:
        if key not in allowed_set:
            raise ParameterInvalid(
                f"unknown parameter {key!r}; allowed keys are {sorted(allowed_set)}",
                field_path=f"parameters.{key}",
            )


def _require_int(value: Any, field_path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParameterInvalid(
            f"{field_path} must be an integer", field_path=field_path
        )
    if value < minimum:
        raise ParameterInvalid(
            f"{field_path} must be >= {minimum}", field_path=field_path
        )
    return value


def _require_test_size(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParameterInvalid(
            "parameters.test_size must be a number", field_path="parameters.test_size"
        )
    number = float(value)
    if not 0.0 < number < 1.0:
        raise ParameterInvalid(
            "parameters.test_size must satisfy 0 < test_size < 1",
            field_path="parameters.test_size",
        )
    return number


def _require_target(value: Any, columns: Sequence[str]) -> str:
    if not isinstance(value, str) or not value:
        raise ParameterInvalid(
            "parameters.target must be a non-empty column name",
            field_path="parameters.target",
        )
    if value not in columns:
        raise ParameterInvalid(
            f"parameters.target {value!r} is not a dataset column",
            field_path="parameters.target",
        )
    if value in RESERVED_COLUMNS:
        raise ParameterInvalid(
            "parameters.target must not be the group or time column",
            field_path="parameters.target",
        )
    return value


def validate_task_parameters(
    parameters: Mapping[str, Any], columns: Sequence[str]
) -> dict[str, Any]:
    mapping = _require_mapping(parameters)
    _reject_unknown(mapping, TASK_PARAMETER_KEYS)
    target = _require_target(mapping.get("target"), columns)
    seed = _require_int(mapping.get("seed"), "parameters.seed")
    test_size = _require_test_size(mapping.get("test_size"))
    models = mapping.get("models")
    if not isinstance(models, list) or not models:
        raise ParameterInvalid(
            "parameters.models must be a non-empty array",
            field_path="parameters.models",
        )
    seen: list[str] = []
    for index, model in enumerate(models):
        if not isinstance(model, str):
            raise ParameterInvalid(
                "parameters.models entries must be strings",
                field_path=f"parameters.models[{index}]",
            )
        if model not in WHITELIST_MODELS:
            raise ParameterInvalid(
                f"model {model!r} is not in the frozen whitelist {list(WHITELIST_MODELS)}",
                field_path=f"parameters.models[{index}]",
            )
        if model in seen:
            raise ParameterInvalid(
                f"duplicate model {model!r}", field_path=f"parameters.models[{index}]"
            )
        seen.append(model)
    return {
        "target": target,
        "seed": seed,
        "test_size": test_size,
        "models": tuple(seen),
    }


def validate_split_parameters(
    parameters: Mapping[str, Any], columns: Sequence[str]
) -> dict[str, Any]:
    mapping = _require_mapping(parameters)
    _reject_unknown(mapping, SPLIT_PARAMETER_KEYS)
    return {
        "target": _require_target(mapping.get("target"), columns),
        "seed": _require_int(mapping.get("seed"), "parameters.seed"),
        "test_size": _require_test_size(mapping.get("test_size")),
    }


def validate_train_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    mapping = _require_mapping(parameters)
    _reject_unknown(mapping, TRAIN_PARAMETER_KEYS)
    model = mapping.get("model")
    if not isinstance(model, str) or model not in WHITELIST_MODELS:
        raise ParameterInvalid(
            f"model {model!r} is not in the frozen whitelist {list(WHITELIST_MODELS)}",
            field_path="parameters.model",
        )
    return {
        "model": model,
        "seed": _require_int(mapping.get("seed"), "parameters.seed"),
    }