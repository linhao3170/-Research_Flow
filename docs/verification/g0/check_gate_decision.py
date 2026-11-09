#!/usr/bin/env python3
"""G0 门禁裁决字段的正/负例校验（只读，不写项目文件）。

运行（项目 Python 3.11.16 64 位）：

    & $py -X utf8 docs/verification/g0/check_gate_decision.py

判定：只有字段路径与拒绝原因同时匹配才算 PASS；仅“被拒绝”不算。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import state_sync  # noqa: E402


def issues_for(state: dict) -> list[str]:
    return [issue.render() for issue in state_sync.validate_state(copy.deepcopy(state))]


def expect(issues: list[str], path: str, reason: str, label: str) -> None:
    matched = [issue for issue in issues if issue.startswith(path) and reason in issue]
    if not matched:
        raise AssertionError(f"{label}: 未命中 {path} / {reason}；实际：{issues}")


def main() -> int:
    state = json.loads(
        (ROOT / "docs" / "state" / "project_state.json").read_text(encoding="utf-8")
    )

    positive = issues_for(state)
    if positive:
        raise AssertionError(f"真实 project_state.json 应通过，实际：{positive}")

    missing_by = copy.deepcopy(state)
    missing_by["stage_gates"]["G0"].pop("decided_by")
    issues = issues_for(missing_by)
    expect(issues, "stage_gates.G0.decided_by", "必须提供裁决人", "missing_decided_by")

    missing_at = copy.deepcopy(state)
    missing_at["stage_gates"]["G0"].pop("decided_at")
    issues = issues_for(missing_at)
    expect(issues, "stage_gates.G0.decided_at", "必须提供裁决日期", "missing_decided_at")

    bad_date = copy.deepcopy(state)
    bad_date["stage_gates"]["G0"]["decided_at"] = "2026-13-01"
    issues = issues_for(bad_date)
    expect(issues, "stage_gates.G0.decided_at", "必须是 YYYY-MM-DD", "invalid_decided_at")

    empty_by = copy.deepcopy(state)
    empty_by["stage_gates"]["G0"]["decided_by"] = ""
    issues = issues_for(empty_by)
    expect(issues, "stage_gates.G0.decided_by", "不能为空字符串", "empty_decided_by")

    print("GATE_DECISION_SCHEMA_TEST=PASS checks=1 positive + 4 negative")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())