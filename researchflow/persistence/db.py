"""SQLite connection and transaction helpers for WP-03."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

__all__ = [
    "connect",
    "ensure_parent",
    "format_utc",
    "parse_utc",
    "transaction",
    "utc_now",
]


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with the WP-03 pragmas.

    Callers own the connection and must close it.  The helper never shares a
    connection globally: tests use a temporary file and the API opens a fresh
    connection per transaction.
    """

    connection = sqlite3.connect(
        str(path),
        isolation_level=None,
        timeout=5.0,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def ensure_parent(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@contextmanager
def transaction(
    connection: sqlite3.Connection, *, immediate: bool = True
) -> Iterator[sqlite3.Connection]:
    """Run a short explicit transaction.

    ``BEGIN IMMEDIATE`` is the default so writers serialise before doing any
    read-check-write work.  The context manager rolls back on any exception.
    """

    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        try:
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_utc(value: datetime) -> str:
    """Format a timezone-aware datetime as 27-character UTC text."""

    if value.tzinfo is None:
        raise ValueError("UTC formatting requires a timezone-aware datetime")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(value: str) -> datetime:
    """Parse the 27-character UTC text used by the database."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"not a UTC timestamp: {value!r}")
    return parsed.astimezone(timezone.utc)