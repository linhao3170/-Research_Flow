"""RFC 8259 严格解析层（05 §1.3）。

JSON Schema 无法表达"重复键"与 `NaN`/`Infinity`，因此运行时在进入模型前先做
严格解析：重复键、非有限数、非法 UTF-8/JSON 一律拒绝，并带上字段路径。
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ContractJSONError(ValueError):
    """JSON 层拒绝；`pointer` 用于 API 的 `field_path`。"""

    def __init__(self, keyword: str, pointer: str, message: str) -> None:
        super().__init__(message)
        self.keyword = keyword
        self.pointer = pointer
        self.message = message


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractJSONError("duplicate-key", key, f"重复键 {key!r}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise ContractJSONError(
        "non-finite-number", "$", f"不允许非有限数 {token}（RFC 8259）"
    )


def loads_strict(text: str) -> Any:
    """解析 JSON 文本；拒绝重复键、NaN/Infinity 与语法错误。"""
    try:
        return json.loads(
            text,
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except ContractJSONError:
        raise
    except json.JSONDecodeError as exc:
        raise ContractJSONError(
            "invalid-json", "$", f"JSON 语法错误：{exc.msg}（第 {exc.lineno} 行第 {exc.colno} 列）"
        ) from exc


def parse_model(model: type[T], raw: str | bytes) -> T:
    """严格解析 + 严格模型校验；异常类型保持区分，便于 API 映射 422。"""
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractJSONError("invalid-encoding", "$", "请求体不是合法 UTF-8") from exc
    else:
        text = raw
    return model.model_validate(loads_strict(text))