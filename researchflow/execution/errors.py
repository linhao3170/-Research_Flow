"""Executor errors (T0 WP-06)."""

from __future__ import annotations

__all__ = [
    "AttemptDirReused",
    "ExecutionError",
    "PathEscape",
    "ToolNotAllowlisted",
]


class ExecutionError(RuntimeError):
    code = "EXECUTION_ERROR"
    api_error_code = "STATE_TRANSITION_DENIED"

    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        self.field_path = field_path
        super().__init__(f"{self.code}: {message}")


class ToolNotAllowlisted(ExecutionError):
    code = "TOOL_NOT_ALLOWLISTED"
    api_error_code = "TOOL_NOT_ALLOWLISTED"


class AttemptDirReused(ExecutionError):
    code = "ATTEMPT_DIR_REUSED"


class PathEscape(ExecutionError):
    code = "PATH_ESCAPE"