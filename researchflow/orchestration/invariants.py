"""Callable invariants used by WP-03 tests.

Only the invariants relevant to this work package are implemented.  Gate,
signature and evidence-chain calculations remain in later work packages.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "InvariantViolation",
    "NotApplicableInT0",
    "assert_i01_single_write_entrypoint",
    "assert_i02_e01_not_sufficient",
    "assert_i07_certificate_requires_verified_report",
    "assert_i14_denied_survives_rollback",
]


class InvariantViolation(RuntimeError):
    def __init__(self, invariant_id: str, code: str, message: str) -> None:
        self.invariant_id = invariant_id
        self.code = code
        self.message = message
        super().__init__(f"{invariant_id}/{code}: {message}")


class NotApplicableInT0(RuntimeError):
    pass


def assert_i01_single_write_entrypoint(problems: list[str]) -> None:
    if problems:
        raise InvariantViolation(
            "I-01", "MULTIPLE_STATE_WRITE_ENTRIES", "; ".join(problems)
        )


def assert_i02_e01_not_sufficient(
    *, check_id: str, check_class: str, levels: set[str]
) -> None:
    if check_class == "EXECUTION" and levels <= {"E0", "E1"}:
        raise InvariantViolation(
            "I-02",
            "REQUIRED_EVIDENCE_MISSING",
            f"execution check {check_id!r} cannot be satisfied by E0/E1 alone",
        )


def assert_i07_certificate_requires_verified_report(
    *, report_final_state: str, certificate_requested: bool
) -> None:
    if certificate_requested and report_final_state != "VERIFIED":
        raise InvariantViolation(
            "I-07",
            "CERTIFICATE_NOT_AVAILABLE",
            "a certificate requires a VERIFIED report",
        )


def assert_i14_denied_survives_rollback(
    *, denied_count: int, state_rolled_back: bool
) -> None:
    if state_rolled_back and denied_count < 1:
        raise InvariantViolation(
            "I-14",
            "DENIED_AUDIT_MISSING",
            "DENIED audit must survive a rolled-back state transaction",
        )