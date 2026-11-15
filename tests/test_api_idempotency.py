"""WP-02 幂等创建回执测试（P0 整改 A–E）。

边界：只验证单进程 TestClient 内的重复提交；不证明多进程/多 worker 安全。
"""

from __future__ import annotations

import json
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

PUBLIC_FIELDS = {"task_id", "state", "graph_version"}


@pytest.fixture()
def client(tmp_path: Path):
    with TestClient(create_app(db_path=tmp_path / "api_idem.db")) as test_client:
        yield test_client


def test_a_first_and_replay_are_identical(client: TestClient) -> None:
    """A：同键同体的首次 201 与重放 201 必须完全一致。"""

    headers = {"Idempotency-Key": "p0-idem-a"}
    first = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)
    second = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.content == second.content
    assert first.json() == second.json()
    assert first.json()["task_id"] == second.json()["task_id"]
    assert first.json()["graph_version"] == second.json()["graph_version"]
    assert first.json()["state"] == second.json()["state"]


def test_b_same_key_different_body_conflicts_without_new_task(client: TestClient) -> None:
    """B：同键异体 409，且不创建新任务；原体仍按首次任务重放。"""

    headers = {"Idempotency-Key": "p0-idem-b"}
    first = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)
    assert first.status_code == 201

    changed = {**PAYLOAD, "goal": "A different goal for the same idempotency key."}
    conflict = client.post("/api/v1/tasks", json=changed, headers=headers)

    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"
    assert "spec" not in conflict.json()
    assert set(conflict.json()) == {"error_code", "message", "correlation_id"}

    replay = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)
    assert replay.status_code == 201
    assert replay.json() == first.json()

    first_task = client.get(f"/api/v1/tasks/{first.json()['task_id']}")
    assert first_task.status_code == 200
    assert first_task.json()["task_id"] == first.json()["task_id"]


def test_c_different_keys_same_body_create_distinct_tasks(client: TestClient) -> None:
    """C：不同幂等键、同一请求体应创建两个不同任务。"""

    first = client.post(
        "/api/v1/tasks", json=PAYLOAD, headers={"Idempotency-Key": "p0-idem-c-1"}
    )
    second = client.post(
        "/api/v1/tasks", json=PAYLOAD, headers={"Idempotency-Key": "p0-idem-c-2"}
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["task_id"] != second.json()["task_id"]
    assert client.get(f"/api/v1/tasks/{first.json()['task_id']}").status_code == 200
    assert client.get(f"/api/v1/tasks/{second.json()['task_id']}").status_code == 200


def test_d_create_response_exposes_only_public_fields(client: TestClient) -> None:
    """D：首次与重放响应键集合严格等于 06 §4.2 的三个公共字段。"""

    headers = {"Idempotency-Key": "p0-idem-d"}
    first = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)
    second = client.post("/api/v1/tasks", json=PAYLOAD, headers=headers)

    assert first.status_code == second.status_code == 201
    assert set(first.json()) == PUBLIC_FIELDS
    assert set(second.json()) == PUBLIC_FIELDS
    assert "spec" not in first.json()
    assert "spec" not in second.json()
    assert first.content == second.content


def test_e_repeated_submissions_do_not_create_new_tasks(client: TestClient) -> None:
    """E：同键同体连续 10 次均 201 且响应完全一致。

    只验证单进程重复提交，不证明多进程/多 worker 安全。
    """

    headers = {"Idempotency-Key": "p0-idem-e"}
    responses = [client.post("/api/v1/tasks", json=PAYLOAD, headers=headers) for _ in range(10)]

    assert all(response.status_code == 201 for response in responses)
    first = responses[0]
    assert all(response.content == first.content for response in responses[1:])
    assert all(response.json() == first.json() for response in responses[1:])
    assert len({response.json()["task_id"] for response in responses}) == 1
    assert set(first.json()) == PUBLIC_FIELDS
