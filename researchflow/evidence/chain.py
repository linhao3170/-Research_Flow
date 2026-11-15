"""Evidence hash chain (T0 WP-07).

The chain is defined over the whitelisted ``EvidenceRecord`` fields, so adding
an unrelated column cannot silently change what was hashed.  ``prev_hash`` of
the first record is 64 zeros (adopted from the ⑧ §2 recommendation; ``OQ-CT-10``
remains formally open).  Tampering is *detectable*, not impossible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from researchflow.contracts.encoding import hash_payload
from researchflow.persistence.repositories import EvidenceRow

__all__ = [
    "CHAIN_FIELDS",
    "GENESIS_PREV_HASH",
    "ChainIssue",
    "ChainReport",
    "chain_hash_for",
    "record_payload",
    "verify_chain",
]

GENESIS_PREV_HASH = "0" * 64

CHAIN_FIELDS = (
    "schema_version",
    "evidence_id",
    "task_id",
    "node_id",
    "attempt_id",
    "event_seq",
    "level",
    "kind",
    "producer",
    "timestamp",
    "payload_hash",
    "artifact_refs",
    "prev_hash",
)


@dataclass(frozen=True, slots=True)
class ChainIssue:
    code: str
    evidence_id: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "evidence_id": self.evidence_id, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ChainReport:
    ok: bool
    count: int
    last_seq: int
    last_hash: str
    issues: tuple[ChainIssue, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "count": self.count,
            "last_seq": self.last_seq,
            "last_hash": self.last_hash,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _artifact_refs(row: EvidenceRow) -> list[str] | None:
    if row.artifact_refs is None:
        return None
    return list(json.loads(row.artifact_refs))


def record_payload(row: EvidenceRow) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "evidence_id": row.evidence_id,
        "task_id": row.task_id,
        "node_id": row.node_id,
        "attempt_id": row.attempt_id,
        "event_seq": row.event_seq,
        "level": row.level,
        "kind": row.kind,
        "producer": row.producer,
        "timestamp": row.timestamp,
        "payload_hash": row.payload_hash,
        "artifact_refs": _artifact_refs(row),
        "prev_hash": row.prev_hash,
    }


def chain_hash_for(row: EvidenceRow) -> str:
    return hash_payload(record_payload(row))


def verify_chain(
    rows: Sequence[EvidenceRow],
    payload_reader: Callable[[str], bytes | None],
) -> ChainReport:
    issues: list[ChainIssue] = []
    previous_hash = GENESIS_PREV_HASH
    previous_timestamp: str | None = None
    expected_seq = 1
    for row in rows:
        if row.event_seq != expected_seq:
            issues.append(
                ChainIssue(
                    "CHAIN_SEQ_GAP",
                    row.evidence_id,
                    f"expected event_seq {expected_seq}, found {row.event_seq}",
                )
            )
            expected_seq = row.event_seq
        if row.prev_hash != previous_hash:
            issues.append(
                ChainIssue(
                    "CHAIN_PREV_MISMATCH",
                    row.evidence_id,
                    f"prev_hash {row.prev_hash} != previous chain_hash {previous_hash}",
                )
            )
        if chain_hash_for(row) != row.chain_hash:
            issues.append(
                ChainIssue(
                    "CHAIN_HASH_MISMATCH",
                    row.evidence_id,
                    "recomputed chain_hash does not match the stored chain_hash",
                )
            )
        payload = payload_reader(row.payload_hash)
        if payload is None:
            issues.append(
                ChainIssue(
                    "CHAIN_PAYLOAD_MISSING",
                    row.evidence_id,
                    f"payload {row.payload_hash} is not in the evidence payload store",
                )
            )
        else:
            import hashlib

            if hashlib.sha256(payload).hexdigest() != row.payload_hash:
                issues.append(
                    ChainIssue(
                        "CHAIN_PAYLOAD_HASH_MISMATCH",
                        row.evidence_id,
                        "payload bytes do not hash to payload_hash",
                    )
                )
        expected_producer, expected_kinds = {
            "E0": ("collector", {"agent_claim"}),
            "E1": ("collector", {"tool_invocation", "harness_trace"}),
            "E2": (
                "collector",
                {"executor_launch", "executor_process_exit", "artifact_observed"},
            ),
            "E3": ("verifier", {"verifier_recheck"}),
        }.get(row.level, ("", set()))
        if row.producer != expected_producer or row.kind not in expected_kinds:
            issues.append(
                ChainIssue(
                    "CHAIN_LEVEL_MAPPING",
                    row.evidence_id,
                    f"level={row.level} cannot come from producer={row.producer} kind={row.kind}",
                )
            )
        if previous_timestamp is not None and row.timestamp < previous_timestamp:
            issues.append(
                ChainIssue(
                    "CHAIN_TIMESTAMP_ORDER",
                    row.evidence_id,
                    f"timestamp {row.timestamp} is before the previous record",
                )
            )
        previous_timestamp = row.timestamp
        previous_hash = row.chain_hash
        expected_seq = row.event_seq + 1
    return ChainReport(
        ok=not issues,
        count=len(rows),
        last_seq=rows[-1].event_seq if rows else 0,
        last_hash=rows[-1].chain_hash if rows else GENESIS_PREV_HASH,
        issues=tuple(issues),
    )