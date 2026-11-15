"""API 422 字段路径映射与创建绑定测试（T0 · WP-02）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from researchflow.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD: dict[str, Any] = json.loads(
    (ROOT / "contracts" / "examples" / "taskspec.positive.json").read_text(encoding="utf-8")
)
PAYLOAD.pop("task_id")  # 服务端生成

TASK_ID_RE = re.compile(
    r"^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@pytest.fixture()
def client(tmp_path: Path):
    with TestClient(create_app(db_path=tmp_path / "api422.db")) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200


def test_create_task_returns_201_and_server_side_task_id(client: TestClient) -> None:
    response = client.post("/api/v1/tasks", json=PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert TASK_ID_RE.match(body["task_id"])
    assert body["state"] == "CREATED"
    assert body["graph_version"] == 1


def test_dataset_ref_string_maps_to_422_with_field_path(client: TestClient) -> None:
    payload = {**PAYLOAD, "dataset_ref": "dataset://breast_cancer@sha256:" + "0" * 64}
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "SCHEMA_INVALID"
    assert body["field_path"] == "dataset_ref"
    assert "object with fields uri, sha256, license" in body["message"]
    assert body["correlation_id"].startswith("req-")


def test_unknown_top_level_field_maps_to_its_name(client: TestClient) -> None:
    response = client.post("/api/v1/tasks", json={**PAYLOAD, "foo": 1})
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "SCHEMA_INVALID"
    assert body["field_path"] == "foo"


def test_missing_required_field_maps_to_its_name(client: TestClient) -> None:
    payload = dict(PAYLOAD)
    payload.pop("dataset_ref")
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["field_path"] == "dataset_ref"
    assert body["error_code"] == "SCHEMA_INVALID"


def test_nested_field_violation_maps_to_dotted_path(client: TestClient) -> None:
    payload = json.loads(json.dumps(PAYLOAD))
    payload["limits"]["max_workers"] = 3
    response = client.post("/api/v1/tasks", json=payload)
    assert response.status_code == 422
    assert response.json()["field_path"] == "limits.max_workers"


def test_duplicate_json_key_rejected_with_422(client: TestClient) -> None:
    text = json.dumps(PAYLOAD, ensure_ascii=False)
    duplicated = text[:-1] + ', "goal": "duplicated"}'
    response = client.post(
        "/api/v1/tasks", content=duplicated, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "SCHEMA_INVALID"
    assert body["field_path"] == "goal"


def test_nan_rejected_with_422(client: TestClient) -> None:
    payload = json.loads(json.dumps(PAYLOAD))
    payload["limits"]["wall_time_sec"] = float("nan")
    response = client.post(
        "/api/v1/tasks", content=json.dumps(payload), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "SCHEMA_INVALID"
    assert body["field_path"] == "$"


def test_idempotent_replay_returns_same_task(client: TestClient) -> None:
    headers = {"Idempotency-Key": "wp-02-idem-1"}
    first = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)
    second = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["task_id"] == second.json()["task_id"]


def test_idempotency_conflict_returns_409(client: TestClient) -> None:
    headers = {"Idempotency-Key": "wp-02-idem-2"}
    assert client.post("/api/v1/tasks", json=PAYLOAD, headers=headers).status_code == 201
    changed = {**PAYLOAD, "goal": "A different goal for the same idempotency key."}
    response = client.post("/api/v1/tasks", json=changed, headers=headers)
    assert response.status_code == 409
    assert response.json()["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_recover_route_is_not_registered(client: TestClient) -> None:
    created = client.post("/api/v1/tasks", json=PAYLOAD).json()
    response = client.post(f"/api/v1/tasks/{created['task_id']}/recover")
    assert response.status_code == 404


def test_get_unknown_task_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/tasks/task_00000000-0000-0000-0000-000000000000").status_code == 404