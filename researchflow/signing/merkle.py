"""Merkle tree over evidence records (T0 WP-11).

Follows the certificate-transparency shape: leaf = SHA-256(0x00 || payload) and
internal node = SHA-256(0x01 || left || right).  An empty tree has the root
``SHA-256(b"")``.  Inclusion proofs are sibling lists; verification recomputes
the root.  A Merkle root proves the *set* was not changed — it does not make
anything immutable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Sequence

from researchflow.contracts.encoding import canonical_bytes
from researchflow.persistence.repositories import EvidenceRow

__all__ = [
    "EMPTY_ROOT",
    "InclusionProof",
    "evidence_record_bytes",
    "inclusion_proof",
    "leaf_hash",
    "merkle_root",
    "merkle_tree_hash",
    "verify_inclusion",
]


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


EMPTY_ROOT = _sha256(b"").hex()


def leaf_hash(payload: bytes) -> bytes:
    return _sha256(b"\x00" + payload)


def _node_hash(left: bytes, right: bytes) -> bytes:
    return _sha256(b"\x01" + left + right)


def evidence_record_bytes(row: EvidenceRow) -> bytes:
    """Canonical bytes of one evidence record (what the leaf commits to)."""

    return canonical_bytes(
        {
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
            "artifact_refs": (
                None
                if row.artifact_refs is None
                else list(json.loads(row.artifact_refs))
            ),
            "prev_hash": row.prev_hash,
            "chain_hash": row.chain_hash,
        }
    )


def _layers(leaves: Sequence[bytes]) -> list[list[bytes]]:
    if not leaves:
        return []
    layers = [list(leaves)]
    while len(layers[-1]) > 1:
        current = layers[-1]
        parents: list[bytes] = []
        for index in range(0, len(current), 2):
            left = current[index]
            right = current[index + 1] if index + 1 < len(current) else left
            parents.append(_node_hash(left, right))
        layers.append(parents)
    return layers


def merkle_tree_hash(leaves: Sequence[bytes]) -> str:
    if not leaves:
        return EMPTY_ROOT
    return _layers(leaves)[-1][0].hex()


def merkle_root(payloads: Sequence[bytes]) -> str:
    return merkle_tree_hash([leaf_hash(payload) for payload in payloads])


@dataclass(frozen=True, slots=True)
class InclusionProof:
    index: int
    size: int
    siblings: tuple[str, ...]
    root: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "size": self.size,
            "siblings": list(self.siblings),
            "root": self.root,
        }


def inclusion_proof(payloads: Sequence[bytes], index: int) -> InclusionProof:
    if not 0 <= index < len(payloads):
        raise IndexError("leaf index out of range")
    leaves = [leaf_hash(payload) for payload in payloads]
    layers = _layers(leaves)
    siblings: list[str] = []
    position = index
    for layer in layers[:-1]:
        sibling_index = position ^ 1
        sibling = layer[sibling_index] if sibling_index < len(layer) else layer[position]
        siblings.append(sibling.hex())
        position //= 2
    return InclusionProof(
        index=index,
        size=len(payloads),
        siblings=tuple(siblings),
        root=layers[-1][0].hex(),
    )


def verify_inclusion(payload: bytes, proof: InclusionProof) -> bool:
    node = leaf_hash(payload)
    position = proof.index
    for sibling_hex in proof.siblings:
        sibling = bytes.fromhex(sibling_hex)
        if position % 2 == 0:
            node = _node_hash(node, sibling)
        else:
            node = _node_hash(sibling, node)
        position //= 2
    return node.hex() == proof.root