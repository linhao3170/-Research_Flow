"""Task creation service: idempotency key + task row in one transaction."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from researchflow.contracts.models import TaskSpec, TaskSpecCreate
from researchflow.persistence.db import connect, format_utc, transaction, utc_now
from researchflow.persistence.migrations import current_version
from researchflow.persistence.repositories import (
    IDEMPOTENCY_WRITE,
    IdempotencyRepository,
    TaskRepository,
)
from researchflow.orchestration.state_machine import Actor, InitializationDenied, StateMachine
from researchflow.orchestration.transitions import ActorRole

__all__ = ["CreationOutcome", "TaskCreationService"]


@dataclass(frozen=True, slots=True)
class CreationOutcome:
    kind: str
    request_hash: str
    task_id: str | None = None
    state: str | None = None
    graph_version: int | None = None

    def public_body(self) -> dict[str, object] | None:
        if self.task_id is None:
            return None
        return {
            "task_id": self.task_id,
            "state": self.state,
            "graph_version": self.graph_version,
        }


class TaskCreationService:
    def __init__(
        self,
        db_path: str | Path,
        state_machine: StateMachine,
        *,
        task_repository: TaskRepository | None = None,
        idempotency_repository: IdempotencyRepository | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._state_machine = state_machine
        self._tasks = task_repository or TaskRepository()
        self._idempotency = idempotency_repository or IdempotencyRepository()

    def ready(self) -> bool:
        connection = connect(self._db_path)
        try:
            return current_version(connection) is not None
        finally:
            connection.close()

    def create_task(
        self,
        *,
        create_spec: TaskSpecCreate,
        request_hash: str,
        idempotency_key: str | None,
    ) -> CreationOutcome:
        task_id = f"task_{uuid.uuid4()}"
        spec = TaskSpec(task_id=task_id, **create_spec.model_dump())
        connection = connect(self._db_path)
        try:
            try:
                with transaction(connection):
                    if idempotency_key is not None:
                        existing = self._idempotency.lookup(connection, idempotency_key)
                        if existing is not None:
                            if existing.request_hash == request_hash:
                                task = self._tasks.get(connection, existing.task_id)
                                if task is None:
                                    raise RuntimeError(
                                        "idempotency key references a missing task"
                                    )
                                return CreationOutcome(
                                    kind="REPLAY",
                                    request_hash=request_hash,
                                    task_id=task.task_id,
                                    state="CREATED",
                                    graph_version=1,
                                )
                            return CreationOutcome(
                                kind="CONFLICT",
                                request_hash=request_hash,
                            )
                    self._state_machine.create_initial(
                        obj_type="task",
                        task_id=task_id,
                        actor=Actor(ActorRole.API, "create"),
                        correlation_id=f"req-{uuid.uuid4().hex}",
                        rule_version="1.0",
                        task_spec=spec,
                        connection=connection,
                    )
                    if idempotency_key is not None:
                        self._idempotency.insert(
                            connection,
                            idem_key=idempotency_key,
                            request_hash=request_hash,
                            task_id=task_id,
                            created_at=format_utc(utc_now()),
                            capability=IDEMPOTENCY_WRITE,
                        )
                    return CreationOutcome(
                        kind="CREATED",
                        request_hash=request_hash,
                        task_id=task_id,
                        state="CREATED",
                        graph_version=1,
                    )
            except sqlite3.IntegrityError:
                # The transaction context rolled back.  A concurrent writer may
                # have inserted the same key; re-read and resolve.
                if idempotency_key is not None:
                    return self._resolve_race(
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                    )
                raise
        finally:
            connection.close()

    def _resolve_race(
        self, *, idempotency_key: str, request_hash: str
    ) -> CreationOutcome:
        connection = connect(self._db_path)
        try:
            existing = self._idempotency.lookup(connection, idempotency_key)
            if existing is None:
                raise RuntimeError("idempotency conflict without a persisted key")
            if existing.request_hash != request_hash:
                return CreationOutcome(kind="CONFLICT", request_hash=request_hash)
            task = self._tasks.get(connection, existing.task_id)
            if task is None:
                raise RuntimeError("idempotency key references a missing task")
            return CreationOutcome(
                kind="REPLAY",
                request_hash=request_hash,
                task_id=task.task_id,
                state="CREATED",
                graph_version=1,
            )
        finally:
            connection.close()

    def get_task(self, task_id: str) -> dict[str, object] | None:
        connection = connect(self._db_path)
        try:
            task = self._tasks.get(connection, task_id)
        finally:
            connection.close()
        if task is None:
            return None
        return {
            "task_id": task.task_id,
            "state": task.state,
            "graph_version": task.graph_version,
            "spec": json.loads(task.task_spec_json),
        }