"""Registrated template and parameter errors (T0 WP-05).

Error codes are internal domain codes; they are surfaced through the API only
as the frozen ``06 §4.4`` codes (``TOOL_NOT_ALLOWLISTED`` / ``SCHEMA_INVALID``).
"""

from __future__ import annotations

__all__ = [
    "DatasetError",
    "DatasetHashMismatch",
    "DatasetPathEscape",
    "DatasetUriInvalid",
    "ParameterInvalid",
    "SplitError",
    "TemplateError",
    "TemplateNotRegistered",
]


class TemplateError(RuntimeError):
    code = "TEMPLATE_ERROR"
    api_error_code = "SCHEMA_INVALID"

    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        self.field_path = field_path
        super().__init__(f"{self.code}: {message}")


class TemplateNotRegistered(TemplateError):
    code = "TEMPLATE_NOT_REGISTERED"
    api_error_code = "TOOL_NOT_ALLOWLISTED"


class ParameterInvalid(TemplateError):
    code = "PARAM_INVALID"
    api_error_code = "SCHEMA_INVALID"


class DatasetError(TemplateError):
    code = "DATASET_ERROR"
    api_error_code = "SCHEMA_INVALID"


class DatasetUriInvalid(DatasetError):
    code = "DATASET_URI_INVALID"


class DatasetPathEscape(DatasetError):
    code = "DATASET_PATH_ESCAPE"


class DatasetHashMismatch(DatasetError):
    code = "DATASET_HASH_MISMATCH"


class SplitError(TemplateError):
    code = "SPLIT_INVALID"
    api_error_code = "SCHEMA_INVALID"