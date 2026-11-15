"""Server startup guard (T0 decision 8).

T0 binds only to loopback.  A non-loopback bind is refused unless an access
token is configured; the refusal writes a startup audit row (without the token)
and exits non-zero without listening on the port.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "LOOPBACK_HOSTS",
    "NonLoopbackBindRequiresToken",
    "is_loopback",
    "serve",
    "write_startup_audit",
]

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class NonLoopbackBindRequiresToken(RuntimeError):
    code = "NON_LOOPBACK_BIND_REQUIRES_TOKEN"


def is_loopback(host: str) -> bool:
    return str(host).strip().lower() in LOOPBACK_HOSTS


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def write_startup_audit(
    db_path: str | Path, *, allowed: bool, reason: str
) -> None:
    """Append one STARTUP_GUARD audit row.  Never stores the token."""

    from researchflow.persistence.db import connect, transaction
    from researchflow.persistence.migrations import MigrationRunner
    from researchflow.persistence.repositories import (
        STATE_MACHINE_WRITE,
        AuditRepository,
    )

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        MigrationRunner().upgrade(connection)
        with transaction(connection):
            AuditRepository().append(
                connection,
                audit_id=uuid.uuid4().hex,
                task_id=None,
                node_id=None,
                actor="system:startup",
                action="STARTUP_GUARD",
                previous_state=None,
                next_state=None,
                reason_code=reason,
                rule_version="1.0",
                correlation_id=f"startup-{uuid.uuid4().hex}",
                plan_id=None,
                plan_hash=None,
                result="OK" if allowed else "DENIED",
                error_code=None if allowed else "NON_LOOPBACK_BIND_REQUIRES_TOKEN",
                created_at=_now(),
                capability=STATE_MACHINE_WRITE,
            )
    finally:
        connection.close()


def serve(
    db_path: str | Path,
    host: str,
    port: int,
    *,
    token: str | None = None,
    log_level: str = "info",
) -> int:
    token = token if token is not None else os.environ.get("RESEARCHFLOW_API_TOKEN")
    if not is_loopback(host) and not token:
        write_startup_audit(
            db_path, allowed=False, reason="non-loopback bind without token"
        )
        print(
            json.dumps(
                {
                    "error_code": "STARTUP_GUARD",
                    "message": "non-loopback bind requires token",
                    "host": host,
                    "allowed": False,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    write_startup_audit(
        db_path,
        allowed=True,
        reason="loopback bind" if is_loopback(host) else "non-loopback bind with token",
    )
    from researchflow.api.app import create_app

    import uvicorn

    uvicorn.run(create_app(db_path), host=host, port=port, log_level=log_level)
    return 0