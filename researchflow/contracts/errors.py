"""Frozen API error codes and HTTP mappings (T0 · WP-03).

Only the 13 codes from ``docs/design/06_DATA_AND_API.md`` §4.4 are exposed as
API error codes.  Internal domain codes such as ``PLAN_HASH_MISMATCH`` or
``AUDIT_WRITE_FAILED`` are deliberately not listed here; they may appear in
exceptions or structured stderr but must never become a 14th HTTP error code.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

__all__ = ["API_ERROR_CODES", "API_ERROR_STATUS", "api_status"]

API_ERROR_STATUS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "SCHEMA_INVALID": 422,
        "IDEMPOTENCY_CONFLICT": 409,
        "STATE_TRANSITION_DENIED": 409,
        "TOOL_NOT_ALLOWLISTED": 403,
        "EVIDENCE_REFERENCE_NOT_FOUND": 422,
        "REQUIRED_EVIDENCE_MISSING": 409,
        "RULESET_VERSION_MISMATCH": 409,
        "RESOURCE_BUDGET_EXCEEDED": 429,
        "RECOVERY_NOT_SAFE": 409,
        "SIGNATURE_INVALID": 422,
        "BUNDLE_TAMPERED": 422,
        "HARNESS_EVENT_DUPLICATE": 200,
        "HARNESS_EVENT_GAP": 202,
    }
)

API_ERROR_CODES: Final[tuple[str, ...]] = tuple(API_ERROR_STATUS)


def api_status(code: str, *, default: int = 409) -> int:
    """Return the frozen HTTP status for an API error code."""

    return API_ERROR_STATUS.get(code, default)