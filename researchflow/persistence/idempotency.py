"""Idempotency key validation and request hashing for WP-03."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from researchflow.contracts.encoding import hash_payload
from researchflow.persistence.repositories import (
    IDEMPOTENCY_WRITE,
    IdempotencyRepository,
    IdempotencyRow,
)

__all__ = [
    "IdempotencyStore",
    "InvalidIdempotencyKey",
    "compute_request_hash",
    "validate_idempotency_key",
]


class InvalidIdempotencyKey(ValueError):
    field_path = "Idempotency-Key"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def validate_idempotency_key(key: str | None) -> str | None:
    """Validate an optional Idempotency-Key header.

    ``None`` means the header was absent and is allowed.  An empty string is a
    present but invalid key.  Valid keys are 1–255 visible ASCII characters
    (0x21–0x7E) with no whitespace.
    """

    if key is None:
        return None
    if not isinstance(key, str):
        raise InvalidIdempotencyKey("Idempotency-Key must be a string")
    if not 1 <= len(key) <= 255:
        raise InvalidIdempotencyKey("Idempotency-Key must be 1–255 characters")
    if any(not (0x21 <= ord(character) <= 0x7E) for character in key):
        raise InvalidIdempotencyKey(
            "Idempotency-Key must contain only visible ASCII characters"
        )
    return key


def compute_request_hash(payload: object) -> str:
    return hash_payload(payload)


@dataclass(frozen=True, slots=True)
class IdempotencyStore:
    repository: IdempotencyRepository

    def lookup(self, connection: sqlite3.Connection, key: str) -> IdempotencyRow | None:
        return self.repository.lookup(connection, key)

    def insert(
        self,
        connection: sqlite3.Connection,
        *,
        key: str,
        request_hash: str,
        task_id: str,
        created_at: str,
    ) -> None:
        self.repository.insert(
            connection,
            idem_key=key,
            request_hash=request_hash,
            task_id=task_id,
            created_at=created_at,
            capability=IDEMPOTENCY_WRITE,
        )