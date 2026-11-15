from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from researchflow.api.app import create_app
from researchflow.persistence.db import connect
from wp03_support import TASK_PAYLOAD, TASK_ID


def _payload() -> dict:
    payload = {key: value for key, value in TASK_PAYLOAD.items() if key != "task_id"}
    return payload


@pytest.fixture()
def client(tmp_path: Path):
    db = tmp_path / "api.db"
    with TestClient(create_app(db_path=db)) as test_client:
        yield test_client, db


def test_create_returns_201_and_public_receipt(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v1/tasks", json=_payload())
    assert response.status_code == 201
    assert set(response.json()) == {"task_id", "state", "graph_version"}
    assert response.json()["state"] == "CREATED"
    assert response.json()["graph_version"] == 1


def test_same_key_same_body_replays_201(client) -> None:
    test_client, _ = client
    headers = {"Idempotency-Key": "api-idem-1"}
    first = test_client.post("/api/v1/tasks", json=_payload(), headers=headers)
    second = test_client.post("/api/v1/tasks", json=_payload(), headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.content == second.content


def test_same_key_different_body_conflicts_409(client) -> None:
    test_client, _ = client
    headers = {"Idempotency-Key": "api-idem-2"}
    assert test_client.post("/api/v1/tasks", json=_payload(), headers=headers).status_code == 201
    changed = _payload()
    changed["goal"] = "different goal"
    response = test_client.post("/api/v1/tasks", json=changed, headers=headers)
    assert response.status_code == 409
    assert response.json()["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_schema_error_is_422(client) -> None:
    test_client, _ = client
    payload = _payload()
    payload["dataset_ref"] = "dataset://x@sha256:" + "0" * 64
    response = test_client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 422
    assert response.json()["error_code"] == "SCHEMA_INVALID"
    assert response.json()["field_path"] == "dataset_ref"


def test_invalid_idempotency_key_is_422_with_field_path(client) -> None:
    test_client, _ = client
    response = test_client.post(
        "/api/v1/tasks", json=_payload(), headers={"Idempotency-Key": "bad key"}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "SCHEMA_INVALID"
    assert response.json()["field_path"] == "Idempotency-Key"


def test_get_existing_and_unknown_task(client) -> None:
    test_client, _ = client
    created = test_client.post("/api/v1/tasks", json=_payload()).json()
    existing = test_client.get(f"/api/v1/tasks/{created['task_id']}")
    assert existing.status_code == 200
    assert existing.json()["task_id"] == created["task_id"]
    assert existing.json()["state"] == "CREATED"
    assert "spec" in existing.json()
    missing = test_client.get(
        "/api/v1/tasks/task_00000000-0000-0000-0000-000000000000"
    )
    assert missing.status_code == 404


def test_recover_route_is_not_registered(client) -> None:
    test_client, _ = client
    created = test_client.post("/api/v1/tasks", json=_payload()).json()
    assert test_client.post(f"/api/v1/tasks/{created['task_id']}/recover").status_code == 404


def test_missing_key_creates_two_tasks(client) -> None:
    test_client, _ = client
    first = test_client.post("/api/v1/tasks", json=_payload())
    second = test_client.post("/api/v1/tasks", json=_payload())
    assert first.status_code == second.status_code == 201
    assert first.json()["task_id"] != second.json()["task_id"]


def test_restart_reads_the_same_sqlite_file(tmp_path: Path) -> None:
    db = tmp_path / "restart.db"
    with TestClient(create_app(db_path=db)) as first_client:
        created = first_client.post("/api/v1/tasks", json=_payload()).json()
    with TestClient(create_app(db_path=db)) as second_client:
        response = second_client.get(f"/api/v1/tasks/{created['task_id']}")
        assert response.status_code == 200
        assert response.json()["task_id"] == created["task_id"]


def test_readyz_and_audit_row(client) -> None:
    test_client, db = client
    assert test_client.get("/healthz").status_code == 200
    assert test_client.get("/readyz").status_code == 200
    created = test_client.post("/api/v1/tasks", json=_payload()).json()
    connection = connect(db)
    try:
        task = connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (created["task_id"],)
        ).fetchone()
        assert task is not None
        assert task["state"] == "CREATED"
        audit = connection.execute(
            "SELECT * FROM audit_log WHERE task_id = ? AND action = 'TASK_CREATED'",
            (created["task_id"],),
        ).fetchone()
        assert audit is not None
        assert audit["result"] == "OK"
    finally:
        connection.close()