"""Forward-only migration runner for WP-03."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Sequence

from researchflow.persistence.db import format_utc, utc_now
from researchflow.persistence.schema_sql import (
    DDL_STATEMENTS,
    INITIAL_SCHEMA_VERSION,
    SCHEMA_MIGRATIONS_DDL,
)
from researchflow.persistence.schema_sql_v2 import (
    GRAPH_VERSION_TABLE_VERSION,
    MIGRATION_V2_STATEMENTS,
)
from researchflow.persistence.schema_sql_v3 import (
    AUDIT_ACTION_TABLE_VERSION,
    MIGRATION_V3_STATEMENTS,
)

__all__ = [
    "DEFAULT_MIGRATIONS",
    "Migration",
    "MigrationError",
    "MigrationRunner",
    "current_version",
]


class MigrationError(RuntimeError):
    """Raised when a migration cannot be applied safely."""


@dataclass(frozen=True)
class Migration:
    version: str
    statements: Sequence[str]

    def checksum(self) -> str:
        payload = "\n".join(self.statements).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


DEFAULT_MIGRATIONS: tuple[Migration, ...] = (
    Migration(INITIAL_SCHEMA_VERSION, DDL_STATEMENTS),
    Migration(GRAPH_VERSION_TABLE_VERSION, MIGRATION_V2_STATEMENTS),
    Migration(AUDIT_ACTION_TABLE_VERSION, MIGRATION_V3_STATEMENTS),
)


class MigrationRunner:
    """Apply pending migrations in one transaction.

    ``executescript`` is deliberately not used: sqlite3's implementation issues
    an implicit COMMIT before running the script, which would break the
    all-or-nothing guarantee.
    """

    def __init__(self, migrations: Iterable[Migration] = DEFAULT_MIGRATIONS) -> None:
        self._migrations = tuple(migrations)
        versions = [migration.version for migration in self._migrations]
        if len(versions) != len(set(versions)):
            raise ValueError("duplicate migration version")
        self._migrations = tuple(sorted(self._migrations, key=lambda item: item.version))

    @property
    def migrations(self) -> tuple[Migration, ...]:
        return self._migrations

    def upgrade(self, connection) -> str:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(SCHEMA_MIGRATIONS_DDL)
            applied = {
                row["version"]: row["checksum"]
                for row in connection.execute(
                    "SELECT version, checksum FROM schema_migrations"
                )
            }
            for migration in self._migrations:
                known = applied.get(migration.version)
                checksum = migration.checksum()
                if known is not None:
                    if known != checksum:
                        raise MigrationError(
                            f"migration checksum mismatch: {migration.version}"
                        )
                    continue
                for statement in migration.statements:
                    statement = statement.strip()
                    if statement:
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at, checksum) "
                    "VALUES (?, ?, ?)",
                    (migration.version, format_utc(utc_now()), checksum),
                )
            connection.execute("COMMIT")
            return current_version(connection)
        except BaseException:
            connection.execute("ROLLBACK")
            raise


def current_version(connection) -> str | None:
    row = connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return None if row is None else str(row["version"])