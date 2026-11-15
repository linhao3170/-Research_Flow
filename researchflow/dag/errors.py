"""DAG validation errors (T0 WP-04)."""

from __future__ import annotations

__all__ = ["DagError"]


class DagError(RuntimeError):
    """A structural graph error with a stable machine code."""

    api_error_code = "SCHEMA_INVALID"

    def __init__(self, code: str, detail: str, *, field_path: str | None = None) -> None:
        self.code = code
        self.detail = detail
        self.field_path = field_path
        super().__init__(f"{code}: {detail}")