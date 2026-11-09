#!/usr/bin/env python3
"""ResearchFlow 研发状态同步工具（仅使用 Python 标准库）。

用途
----
以 ``docs/state/project_state.json`` 为唯一机器可读事实源，提供三个子命令：

* ``validate``：校验 JSON 格式、必填字段、状态枚举、task_id 唯一性与依赖引用。
* ``render``：生成 ``docs/PROJECT_STATE.md`` 与 ``docs/IMPLEMENTATION_STATUS.md``。
* ``check``：重新渲染并与现有生成文件逐字节比较，不一致返回非零退出码。

设计约束
--------
* 不访问网络，不自动安装依赖。
* 不使用当前时间参与渲染；所有时间均来自 JSON，保证可复现。
* 写文件采用“临时文件 + 原子替换”，避免写到一半损坏。
* 错误信息包含字段路径，便于审计。

退出码
------
* 0：成功。
* 1：校验失败、检查不一致、文件读写失败。
* 2：命令行参数错误（由 argparse 返回）。
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SUPPORTED_SCHEMA_VERSION = "1.0"
PROJECT_NAME = "ResearchFlow"

STATE_REL_PATH = Path("docs/state/project_state.json")
PROJECT_STATE_REL_PATH = Path("docs/PROJECT_STATE.md")
IMPLEMENTATION_STATUS_REL_PATH = Path("docs/IMPLEMENTATION_STATUS.md")

TASK_STATUSES = (
    "BACKLOG",
    "READY",
    "IN_PROGRESS",
    "BLOCKED",
    "IN_REVIEW",
    "DONE",
    "DEFERRED",
)

GATE_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "PASS", "FAIL", "BLOCKED")
GATE_IDS = tuple(f"G{index}" for index in range(8))

BLOCKER_STATUSES = ("OPEN", "RESOLVED", "WAIVED")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

# 研发阶段，不是 ResearchFlow 运行时 Task/Node 状态。
PHASE_VALUES = (
    "WORKSTATION_SETUP",
    "G0_PREPARATION",
    "G0",
    "T0",
    "T1",
    "T2",
)

TASK_REQUIRED_FIELDS = (
    "task_id",
    "title",
    "phase",
    "status",
    "depends_on",
    "acceptance_criteria",
    "test_commands",
    "evidence_paths",
    "updated_at",
    "blocker",
)

TASK_ALLOWED_FIELDS = TASK_REQUIRED_FIELDS

GATE_REQUIRED_FIELDS = (
    "gate_id",
    "title",
    "status",
    "criteria",
    "evidence_paths",
    "updated_at",
)

GATE_ALLOWED_FIELDS = GATE_REQUIRED_FIELDS

BLOCKER_REQUIRED_FIELDS = (
    "blocker_id",
    "title",
    "description",
    "status",
    "severity",
    "affected_tasks",
    "opened_at",
    "resolution",
)

BLOCKER_ALLOWED_FIELDS = BLOCKER_REQUIRED_FIELDS

TOP_LEVEL_REQUIRED_FIELDS = (
    "schema_version",
    "project_name",
    "updated_at",
    "current_phase",
    "current_milestone",
    "tasks",
    "stage_gates",
    "blockers",
    "last_verified_commit",
)

TOP_LEVEL_ALLOWED_FIELDS = TOP_LEVEL_REQUIRED_FIELDS

TASK_STATUS_LABELS = {
    "BACKLOG": "待办",
    "READY": "就绪",
    "IN_PROGRESS": "进行中",
    "BLOCKED": "阻塞",
    "IN_REVIEW": "评审中",
    "DONE": "完成",
    "DEFERRED": "延期",
}

GATE_STATUS_LABELS = {
    "NOT_STARTED": "未开始",
    "IN_PROGRESS": "进行中",
    "PASS": "通过",
    "FAIL": "失败",
    "BLOCKED": "阻塞",
}

BLOCKER_STATUS_LABELS = {
    "OPEN": "未解决",
    "RESOLVED": "已解决",
    "WAIVED": "已豁免",
}

SEVERITY_LABELS = {
    "CRITICAL": "严重",
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
}

TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
BLOCKER_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
DRIVE_RE = re.compile(r"^[A-Za-z]:")

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """单个校验问题，``path`` 使用点号与数组下标定位字段。"""

    path: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.message}"


# ---------------------------------------------------------------------------
# 通用校验辅助
# ---------------------------------------------------------------------------


def _field_path(base: str, key: str) -> str:
    if base in ("", "$"):
        return f"$.{key}"
    return f"{base}.{key}"


def _add(issues: list[Issue], path: str, message: str) -> None:
    issues.append(Issue(path=path, message=message))


def _validate_object_fields(
    value: dict[str, Any],
    base: str,
    required: Iterable[str],
    allowed: Iterable[str],
    issues: list[Issue],
) -> None:
    allowed_set = set(allowed)
    for key in value:
        if key not in allowed_set:
            _add(
                issues,
                _field_path(base, key),
                f"未知字段；允许字段为：{', '.join(sorted(allowed_set))}",
            )
    for key in required:
        if key not in value:
            _add(issues, _field_path(base, key), "缺失必填字段")


def _non_empty_string(
    value: Any,
    path: str,
    issues: list[Issue],
    *,
    max_length: int | None = None,
) -> str | None:
    if not isinstance(value, str):
        _add(issues, path, f"必须是字符串，实际类型为 {type(value).__name__}")
        return None
    if not value.strip():
        _add(issues, path, "不能为空字符串")
        return None
    if value != value.strip():
        _add(issues, path, "首尾不能包含空白字符")
        return None
    if max_length is not None and len(value) > max_length:
        _add(issues, path, f"长度不能超过 {max_length} 个字符")
        return None
    return value


def _is_iso8601_with_timezone(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _validate_timestamp(value: Any, path: str, issues: list[Issue]) -> None:
    if not isinstance(value, str):
        _add(issues, path, f"必须是带时区的 ISO-8601 字符串，实际类型为 {type(value).__name__}")
        return
    if not _is_iso8601_with_timezone(value):
        _add(
            issues,
            path,
            "必须是带时区的 ISO-8601 时间，例如 2026-11-08T11:27:46+08:00",
        )


def _validate_repo_relative_path(value: str, path: str, issues: list[Issue]) -> None:
    if not value.strip():
        _add(issues, path, "路径不能为空")
        return
    if "\\" in value:
        _add(issues, path, "必须使用正斜杠 '/'，不能包含反斜杠")
        return
    if DRIVE_RE.match(value):
        _add(issues, path, "必须是仓库相对路径，不能包含 Windows 盘符")
        return
    pure = PurePosixPath(value)
    if pure.is_absolute():
        _add(issues, path, "必须是仓库相对路径，不能是绝对路径")
        return
    if not pure.parts:
        _add(issues, path, "必须是有效的仓库相对路径")
        return
    if ".." in pure.parts:
        _add(issues, path, "不能包含 '..'，不得逃逸项目目录")
        return


def _string_list(
    value: Any,
    path: str,
    issues: list[Issue],
    *,
    min_items: int = 0,
    unique: bool = False,
    repo_relative: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        _add(issues, path, f"必须是数组，实际类型为 {type(value).__name__}")
        return []
    if len(value) < min_items:
        _add(issues, path, f"至少需要 {min_items} 项，当前为 {len(value)} 项")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str):
            _add(issues, item_path, f"必须是字符串，实际类型为 {type(item).__name__}")
            continue
        if not item.strip():
            _add(issues, item_path, "不能为空字符串")
            continue
        if unique:
            if item in seen:
                _add(issues, item_path, f"重复项：{item!r}")
                continue
            seen.add(item)
        if repo_relative:
            _validate_repo_relative_path(item, item_path, issues)
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# 顶层与各对象校验
# ---------------------------------------------------------------------------


def validate_state(data: Any) -> list[Issue]:
    """校验完整状态对象，返回问题列表；空列表表示通过。"""

    issues: list[Issue] = []

    if not isinstance(data, dict):
        return [Issue("$", f"根节点必须是 JSON 对象，实际类型为 {type(data).__name__}")]

    _validate_object_fields(
        data,
        "$",
        TOP_LEVEL_REQUIRED_FIELDS,
        TOP_LEVEL_ALLOWED_FIELDS,
        issues,
    )

    if "schema_version" in data:
        schema_version = data["schema_version"]
        if not isinstance(schema_version, str):
            _add(issues, "$.schema_version", "必须是字符串")
        elif schema_version != SUPPORTED_SCHEMA_VERSION:
            _add(
                issues,
                "$.schema_version",
                f"不支持的值 {schema_version!r}；当前工具只支持 {SUPPORTED_SCHEMA_VERSION!r}",
            )

    if "project_name" in data:
        project_name = _non_empty_string(data["project_name"], "$.project_name", issues)
        if project_name is not None and project_name != PROJECT_NAME:
            _add(
                issues,
                "$.project_name",
                f"必须是 {PROJECT_NAME!r}，当前为 {project_name!r}",
            )

    if "updated_at" in data:
        _validate_timestamp(data["updated_at"], "$.updated_at", issues)

    if "current_phase" in data:
        current_phase = data["current_phase"]
        if not isinstance(current_phase, str):
            _add(issues, "$.current_phase", "必须是字符串")
        elif current_phase not in PHASE_VALUES:
            _add(
                issues,
                "$.current_phase",
                f"非法阶段 {current_phase!r}；允许值：{', '.join(PHASE_VALUES)}",
            )

    if "current_milestone" in data:
        _non_empty_string(
            data["current_milestone"],
            "$.current_milestone",
            issues,
            max_length=100,
        )

    task_ids: dict[str, int] = {}
    if "tasks" in data:
        task_ids = _validate_tasks(data["tasks"], issues)

    if "stage_gates" in data:
        _validate_stage_gates(data["stage_gates"], issues)

    if "blockers" in data:
        _validate_blockers(data["blockers"], task_ids, issues)

    if "last_verified_commit" in data:
        commit = data["last_verified_commit"]
        if commit is not None:
            if not isinstance(commit, str):
                _add(
                    issues,
                    "$.last_verified_commit",
                    "必须是 null 或 7–40 位小写十六进制 commit SHA",
                )
            elif not COMMIT_RE.fullmatch(commit):
                _add(
                    issues,
                    "$.last_verified_commit",
                    f"非法 commit SHA {commit!r}；必须是 7–40 位小写十六进制字符",
                )

    return issues


def _validate_tasks(value: Any, issues: list[Issue]) -> dict[str, int]:
    """校验任务数组，返回 {task_id: 首次出现的下标}。"""

    if not isinstance(value, list):
        _add(issues, "$.tasks", f"必须是数组，实际类型为 {type(value).__name__}")
        return {}

    task_ids: dict[str, int] = {}
    records: list[dict[str, Any]] = []

    for index, task in enumerate(value):
        base = f"tasks[{index}]"
        if not isinstance(task, dict):
            _add(issues, base, f"必须是对象，实际类型为 {type(task).__name__}")
            continue

        _validate_object_fields(
            task,
            base,
            TASK_REQUIRED_FIELDS,
            TASK_ALLOWED_FIELDS,
            issues,
        )

        task_id: str | None = None
        if "task_id" in task:
            task_id = _non_empty_string(task["task_id"], f"{base}.task_id", issues, max_length=64)
            if task_id is not None and not TASK_ID_RE.fullmatch(task_id):
                _add(
                    issues,
                    f"{base}.task_id",
                    "只能包含字母、数字、下划线和连字符，且必须以字母开头",
                )
                task_id = None
            if task_id is not None:
                if task_id in task_ids:
                    _add(
                        issues,
                        f"{base}.task_id",
                        f"重复的 task_id {task_id!r}；首次出现于 tasks[{task_ids[task_id]}]",
                    )
                else:
                    task_ids[task_id] = index

        if "title" in task:
            _non_empty_string(task["title"], f"{base}.title", issues, max_length=200)

        phase = task.get("phase")
        if "phase" in task:
            if not isinstance(phase, str):
                _add(issues, f"{base}.phase", "必须是字符串")
                phase = None
            elif phase not in PHASE_VALUES:
                _add(
                    issues,
                    f"{base}.phase",
                    f"非法阶段 {phase!r}；允许值：{', '.join(PHASE_VALUES)}",
                )
                phase = None

        status: str | None = None
        if "status" in task:
            status_value = task["status"]
            if not isinstance(status_value, str):
                _add(issues, f"{base}.status", "必须是字符串")
            elif status_value not in TASK_STATUSES:
                _add(
                    issues,
                    f"{base}.status",
                    f"非法研发任务状态 {status_value!r}；允许值：{', '.join(TASK_STATUSES)}",
                )
            else:
                status = status_value

        if "depends_on" in task:
            depends_on = _string_list(
                task["depends_on"],
                f"{base}.depends_on",
                issues,
                unique=True,
            )
        else:
            depends_on = []

        if "acceptance_criteria" in task:
            _string_list(
                task["acceptance_criteria"],
                f"{base}.acceptance_criteria",
                issues,
                min_items=1,
            )

        test_commands: list[str] = []
        if "test_commands" in task:
            test_commands = _string_list(
                task["test_commands"],
                f"{base}.test_commands",
                issues,
            )
            if status in ("IN_REVIEW", "DONE") and not test_commands:
                _add(
                    issues,
                    f"{base}.test_commands",
                    f"状态为 {status} 时必须至少记录 1 条真实测试命令",
                )

        evidence_paths: list[str] = []
        if "evidence_paths" in task:
            evidence_paths = _string_list(
                task["evidence_paths"],
                f"{base}.evidence_paths",
                issues,
                unique=True,
                repo_relative=True,
            )
            if status == "DONE" and not evidence_paths:
                _add(
                    issues,
                    f"{base}.evidence_paths",
                    "状态为 DONE 时必须至少提供 1 条证据路径",
                )

        if "updated_at" in task:
            _validate_timestamp(task["updated_at"], f"{base}.updated_at", issues)

        if "blocker" in task:
            blocker = task["blocker"]
            if status == "BLOCKED":
                if not isinstance(blocker, str) or not blocker.strip():
                    _add(
                        issues,
                        f"{base}.blocker",
                        "状态为 BLOCKED 时必须提供非空的阻塞原因",
                    )
            elif blocker is not None:
                _add(
                    issues,
                    f"{base}.blocker",
                    "非 BLOCKED 状态下 blocker 必须为 null",
                )

        records.append(
            {
                "index": index,
                "task_id": task_id,
                "depends_on": depends_on,
                "status": status,
            }
        )

    # 依赖引用校验（必须在收集完所有 task_id 之后进行）
    for record in records:
        task_id = record["task_id"]
        if task_id is None:
            continue
        for dep_index, dependency in enumerate(record["depends_on"]):
            dep_path = f"tasks[{record['index']}].depends_on[{dep_index}]"
            if dependency == task_id:
                _add(issues, dep_path, f"不能依赖自身（task_id={task_id!r}）")
            elif dependency not in task_ids:
                _add(
                    issues,
                    dep_path,
                    f"引用了不存在的 task_id {dependency!r}",
                )

    # 循环依赖检测
    graph: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    for record in records:
        task_id = record["task_id"]
        if task_id is None:
            continue
        for dependency in record["depends_on"]:
            if dependency in graph and dependency != task_id:
                graph[task_id].append(dependency)

    cycle = _find_cycle(graph)
    if cycle is not None:
        first = cycle[0]
        _add(
            issues,
            f"tasks[{task_ids[first]}].depends_on",
            f"存在循环依赖：{' -> '.join(cycle)}",
        )

    return task_ids


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """返回一个循环路径（首尾相同），无循环返回 None。"""

    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for dependency in graph.get(node, []):
            if state.get(dependency, 0) == 1:
                start = stack.index(dependency)
                return stack[start:] + [dependency]
            if state.get(dependency, 0) == 0:
                found = visit(dependency)
                if found is not None:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if state.get(node, 0) == 0:
            found = visit(node)
            if found is not None:
                return found
    return None


def _validate_stage_gates(value: Any, issues: list[Issue]) -> None:
    if not isinstance(value, dict):
        _add(issues, "$.stage_gates", f"必须是对象，实际类型为 {type(value).__name__}")
        return

    for key in value:
        if key not in GATE_IDS:
            _add(
                issues,
                f"stage_gates.{key}",
                f"未知门禁；只允许 {', '.join(GATE_IDS)}",
            )

    for gate_id in GATE_IDS:
        base = f"stage_gates.{gate_id}"
        if gate_id not in value:
            _add(issues, base, "缺失阶段门禁")
            continue

        gate = value[gate_id]
        if not isinstance(gate, dict):
            _add(issues, base, f"必须是对象，实际类型为 {type(gate).__name__}")
            continue

        _validate_object_fields(
            gate,
            base,
            GATE_REQUIRED_FIELDS,
            GATE_ALLOWED_FIELDS,
            issues,
        )

        if "gate_id" in gate:
            declared_id = gate["gate_id"]
            if not isinstance(declared_id, str):
                _add(issues, f"{base}.gate_id", "必须是字符串")
            elif declared_id != gate_id:
                _add(
                    issues,
                    f"{base}.gate_id",
                    f"必须与键名一致（期望 {gate_id!r}，实际 {declared_id!r}）",
                )

        if "title" in gate:
            _non_empty_string(gate["title"], f"{base}.title", issues, max_length=200)

        status: str | None = None
        if "status" in gate:
            status_value = gate["status"]
            if not isinstance(status_value, str):
                _add(issues, f"{base}.status", "必须是字符串")
            elif status_value not in GATE_STATUSES:
                _add(
                    issues,
                    f"{base}.status",
                    f"非法门禁状态 {status_value!r}；允许值：{', '.join(GATE_STATUSES)}",
                )
            else:
                status = status_value

        if "criteria" in gate:
            _string_list(
                gate["criteria"],
                f"{base}.criteria",
                issues,
                min_items=1,
            )

        evidence_paths: list[str] = []
        if "evidence_paths" in gate:
            evidence_paths = _string_list(
                gate["evidence_paths"],
                f"{base}.evidence_paths",
                issues,
                unique=True,
                repo_relative=True,
            )

        if "updated_at" in gate:
            _validate_timestamp(gate["updated_at"], f"{base}.updated_at", issues)

        if status == "PASS" and not evidence_paths:
            _add(
                issues,
                f"{base}.evidence_paths",
                "门禁状态为 PASS 时必须至少提供 1 条证据路径",
            )


def _validate_blockers(
    value: Any,
    task_ids: dict[str, int],
    issues: list[Issue],
) -> None:
    if not isinstance(value, list):
        _add(issues, "$.blockers", f"必须是数组，实际类型为 {type(value).__name__}")
        return

    seen: dict[str, int] = {}
    for index, blocker in enumerate(value):
        base = f"blockers[{index}]"
        if not isinstance(blocker, dict):
            _add(issues, base, f"必须是对象，实际类型为 {type(blocker).__name__}")
            continue

        _validate_object_fields(
            blocker,
            base,
            BLOCKER_REQUIRED_FIELDS,
            BLOCKER_ALLOWED_FIELDS,
            issues,
        )

        if "blocker_id" in blocker:
            blocker_id = _non_empty_string(
                blocker["blocker_id"],
                f"{base}.blocker_id",
                issues,
                max_length=64,
            )
            if blocker_id is not None and not BLOCKER_ID_RE.fullmatch(blocker_id):
                _add(
                    issues,
                    f"{base}.blocker_id",
                    "只能包含字母、数字、下划线和连字符，且必须以字母开头",
                )
            elif blocker_id is not None:
                if blocker_id in seen:
                    _add(
                        issues,
                        f"{base}.blocker_id",
                        f"重复的 blocker_id {blocker_id!r}；首次出现于 blockers[{seen[blocker_id]}]",
                    )
                else:
                    seen[blocker_id] = index

        if "title" in blocker:
            _non_empty_string(blocker["title"], f"{base}.title", issues, max_length=200)

        if "description" in blocker:
            _non_empty_string(
                blocker["description"],
                f"{base}.description",
                issues,
                max_length=2000,
            )

        status: str | None = None
        if "status" in blocker:
            status_value = blocker["status"]
            if not isinstance(status_value, str):
                _add(issues, f"{base}.status", "必须是字符串")
            elif status_value not in BLOCKER_STATUSES:
                _add(
                    issues,
                    f"{base}.status",
                    f"非法阻塞状态 {status_value!r}；允许值：{', '.join(BLOCKER_STATUSES)}",
                )
            else:
                status = status_value

        if "severity" in blocker:
            severity = blocker["severity"]
            if not isinstance(severity, str):
                _add(issues, f"{base}.severity", "必须是字符串")
            elif severity not in SEVERITIES:
                _add(
                    issues,
                    f"{base}.severity",
                    f"非法严重度 {severity!r}；允许值：{', '.join(SEVERITIES)}",
                )

        if "affected_tasks" in blocker:
            affected = _string_list(
                blocker["affected_tasks"],
                f"{base}.affected_tasks",
                issues,
                unique=True,
            )
            for affected_index, task_id in enumerate(affected):
                if task_id not in task_ids:
                    _add(
                        issues,
                        f"{base}.affected_tasks[{affected_index}]",
                        f"引用了不存在的 task_id {task_id!r}",
                    )

        if "opened_at" in blocker:
            _validate_timestamp(blocker["opened_at"], f"{base}.opened_at", issues)

        if "resolution" in blocker:
            resolution = blocker["resolution"]
            if status == "OPEN":
                if resolution is not None:
                    _add(issues, f"{base}.resolution", "OPEN 状态下 resolution 必须为 null")
            elif status in ("RESOLVED", "WAIVED"):
                if not isinstance(resolution, str) or not resolution.strip():
                    _add(
                        issues,
                        f"{base}.resolution",
                        f"{status} 状态下必须提供非空处理说明",
                    )
            elif resolution is not None and not isinstance(resolution, str):
                _add(issues, f"{base}.resolution", "必须是 null 或字符串")


# ---------------------------------------------------------------------------
# 渲染辅助
# ---------------------------------------------------------------------------


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("|", "\\|")
    text = text.replace("\n", "<br>")
    return text


def _code(value: Any) -> str:
    return f"`{_cell(value)}`"


def _code_list(values: Iterable[str]) -> str:
    items = [_code(value) for value in values]
    return "、".join(items) if items else "无"


def _status_text(code: str, labels: dict[str, str]) -> str:
    label = labels.get(code)
    return f"`{code}` {label}" if label else f"`{code}`"


def _counts(codes: Iterable[str], allowed: Iterable[str]) -> dict[str, int]:
    counts = {code: 0 for code in allowed}
    for code in codes:
        if code in counts:
            counts[code] += 1
    return counts


def _task_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    return _counts((task["status"] for task in tasks), TASK_STATUSES)


def _gate_counts(gates: list[dict[str, Any]]) -> dict[str, int]:
    return _counts((gate["status"] for gate in gates), GATE_STATUSES)


def _sorted_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(state["tasks"], key=lambda task: task["task_id"])


def _sorted_gates(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [state["stage_gates"][gate_id] for gate_id in GATE_IDS]


def _sorted_blockers(state: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(state["blockers"], key=lambda blocker: blocker["blocker_id"])


# ---------------------------------------------------------------------------
# 生成 PROJECT_STATE.md
# ---------------------------------------------------------------------------


def render_project_state(state: dict[str, Any]) -> str:
    tasks = _sorted_tasks(state)
    gates = _sorted_gates(state)
    blockers = _sorted_blockers(state)
    gate_counts = _gate_counts(gates)
    task_counts = _task_counts(tasks)
    open_blockers = sum(1 for blocker in blockers if blocker["status"] == "OPEN")

    commit = state["last_verified_commit"]
    commit_text = "无（`null`）" if commit is None else _code(commit)

    lines: list[str] = [
        "<!-- 由 project_state.json 自动生成，请勿手工编辑。 -->",
        "# ResearchFlow 项目状态",
        "",
        "> 由 project_state.json 自动生成，请勿手工编辑。",
        "> 数据源：`docs/state/project_state.json`；生成器：`scripts/state_sync.py`。",
        "",
        "## 概览",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 项目名称 | {_cell(state['project_name'])} |",
        f"| Schema 版本 | {_cell(state['schema_version'])} |",
        f"| 当前阶段 | {_code(state['current_phase'])} |",
        f"| 当前里程碑 | {_code(state['current_milestone'])} |",
        f"| 状态更新时间 | {_cell(state['updated_at'])} |",
        f"| 最近验证提交 | {commit_text} |",
        f"| 研发任务 | {len(tasks)}（{_format_task_summary(task_counts)}） |",
        f"| 阶段门禁 | {gate_counts['PASS']} / {len(gates)} PASS |",
        f"| 阻塞项 | {len(blockers)}（OPEN {open_blockers}） |",
        "",
        "## 阶段门禁",
        "",
        "| 门禁 | 名称 | 状态 | 验收条件 | 证据 | 更新时间 |",
        "|---|---|---|---|---|---|",
    ]

    for gate in gates:
        lines.append(
            "| {gate_id} | {title} | {status} | {criteria} 条 | {evidence} 条 | {updated} |".format(
                gate_id=_code(gate["gate_id"]),
                title=_cell(gate["title"]),
                status=_status_text(gate["status"], GATE_STATUS_LABELS),
                criteria=len(gate["criteria"]),
                evidence=len(gate["evidence_paths"]),
                updated=_cell(gate["updated_at"]),
            )
        )

    lines.extend(
        [
            "",
            f"**汇总**：PASS {gate_counts['PASS']} / {len(gates)}；"
            f"未开始 {gate_counts['NOT_STARTED']} / {len(gates)}；"
            f"进行中 {gate_counts['IN_PROGRESS']} / {len(gates)}。",
            "",
            "## 研发任务",
            "",
        ]
    )

    if not tasks:
        lines.extend(
            [
                "当前没有登记研发任务（`tasks` 为空数组）。这表示研发看板尚未登记任务；"
                "T0 是否开始以真实代码、测试和 commit 为准。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "| 任务 ID | 标题 | 阶段 | 状态 | 依赖 | 阻塞 | 更新时间 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for task in tasks:
            blocker = task["blocker"] if task["blocker"] else "无"
            lines.append(
                "| {task_id} | {title} | {phase} | {status} | {depends} | {blocker} | {updated} |".format(
                    task_id=_code(task["task_id"]),
                    title=_cell(task["title"]),
                    phase=_code(task["phase"]),
                    status=_status_text(task["status"], TASK_STATUS_LABELS),
                    depends=_code_list(task["depends_on"]),
                    blocker=_cell(blocker),
                    updated=_cell(task["updated_at"]),
                )
            )
        lines.append("")

    lines.extend(
        [
            "## 阻塞项",
            "",
            "| 阻塞 ID | 标题 | 状态 | 严重度 | 影响任务 | 打开时间 |",
            "|---|---|---|---|---|---|",
        ]
    )

    if not blockers:
        lines.append("| 无 | 当前无阻塞项 | — | — | — | — |")
    else:
        for blocker in blockers:
            lines.append(
                "| {blocker_id} | {title} | {status} | {severity} | {affected} | {opened} |".format(
                    blocker_id=_code(blocker["blocker_id"]),
                    title=_cell(blocker["title"]),
                    status=_status_text(blocker["status"], BLOCKER_STATUS_LABELS),
                    severity=_status_text(blocker["severity"], SEVERITY_LABELS),
                    affected=_code_list(blocker["affected_tasks"]),
                    opened=_cell(blocker["opened_at"]),
                )
            )

    lines.extend(
        [
            "",
            "---",
            "",
            "本文件只反映 `project_state.json` 的当前内容，不构成开发完成声明。",
            "",
        ]
    )
    return "\n".join(lines)


def _format_task_summary(counts: dict[str, int]) -> str:
    active = counts["IN_PROGRESS"] + counts["IN_REVIEW"]
    done = counts["DONE"]
    return f"进行中/评审 {active}，完成 {done}"


# ---------------------------------------------------------------------------
# 生成 IMPLEMENTATION_STATUS.md
# ---------------------------------------------------------------------------


def render_implementation_status(state: dict[str, Any]) -> str:
    tasks = _sorted_tasks(state)
    gates = _sorted_gates(state)
    blockers = _sorted_blockers(state)
    task_counts = _task_counts(tasks)

    lines: list[str] = [
        "<!-- 由 project_state.json 自动生成，请勿手工编辑。 -->",
        "# ResearchFlow 实现状态",
        "",
        "> 由 project_state.json 自动生成，请勿手工编辑。",
        "> 数据源：`docs/state/project_state.json`；生成器：`scripts/state_sync.py`。",
        "> 本文件只记录研发看板状态，不记录 ResearchFlow 运行时 Task/Node 状态。",
        "",
        "## 1. 任务状态统计",
        "",
        "| 状态 | 含义 | 数量 |",
        "|---|---|---|",
    ]

    for status in TASK_STATUSES:
        lines.append(
            f"| {_code(status)} | {TASK_STATUS_LABELS[status]} | {task_counts[status]} |"
        )
    lines.extend(
        [
            f"| **合计** | — | **{len(tasks)}** |",
            "",
            "## 2. 任务明细",
            "",
        ]
    )

    if not tasks:
        lines.extend(
            [
                "当前没有登记研发任务（`tasks` 为空数组）。",
                "",
                "阶段 4 的治理工作记录在 `docs/CHANGELOG_DEV.md` 与 `docs/verification/stage4/`，"
                "不作为 ResearchFlow 研发任务计入看板。",
                "",
            ]
        )
    else:
        for task in tasks:
            lines.extend(
                [
                    f"### {_code(task['task_id'])} {_cell(task['title'])}",
                    "",
                    f"- 阶段：{_code(task['phase'])}",
                    f"- 状态：{_status_text(task['status'], TASK_STATUS_LABELS)}",
                    f"- 依赖：{_code_list(task['depends_on'])}",
                    f"- 更新时间：{_cell(task['updated_at'])}",
                    f"- 阻塞：{_cell(task['blocker']) if task['blocker'] else '无'}",
                    "- 验收标准：",
                ]
            )
            for criterion in task["acceptance_criteria"]:
                lines.append(f"  - {_cell(criterion)}")
            lines.append("- 测试命令：")
            if task["test_commands"]:
                for command in task["test_commands"]:
                    lines.append(f"  - {_code(command)}")
            else:
                lines.append("  - 无")
            lines.append("- 证据路径：")
            if task["evidence_paths"]:
                for evidence_path in task["evidence_paths"]:
                    lines.append(f"  - {_code(evidence_path)}")
            else:
                lines.append("  - 无")
            lines.append("")

    lines.extend(
        [
            "## 3. 阶段门禁明细",
            "",
        ]
    )

    for gate in gates:
        lines.extend(
            [
                f"### {_code(gate['gate_id'])} · {_cell(gate['title'])}",
                "",
                f"- 状态：{_status_text(gate['status'], GATE_STATUS_LABELS)}",
                f"- 更新时间：{_cell(gate['updated_at'])}",
                "- 验收条件：",
            ]
        )
        for criterion in gate["criteria"]:
            lines.append(f"  - {_cell(criterion)}")
        lines.append("- 证据路径：")
        if gate["evidence_paths"]:
            for evidence_path in gate["evidence_paths"]:
                lines.append(f"  - {_code(evidence_path)}")
        else:
            lines.append("  - 无")
        lines.append("")

    lines.extend(
        [
            "## 4. 阻塞项",
            "",
        ]
    )

    if not blockers:
        lines.extend(["当前无阻塞项。", ""])
    else:
        for blocker in blockers:
            lines.extend(
                [
                    f"### {_code(blocker['blocker_id'])} {_cell(blocker['title'])}",
                    "",
                    f"- 状态：{_status_text(blocker['status'], BLOCKER_STATUS_LABELS)}",
                    f"- 严重度：{_status_text(blocker['severity'], SEVERITY_LABELS)}",
                    f"- 描述：{_cell(blocker['description'])}",
                    f"- 影响任务：{_code_list(blocker['affected_tasks'])}",
                    f"- 打开时间：{_cell(blocker['opened_at'])}",
                    f"- 处理记录：{_cell(blocker['resolution']) if blocker['resolution'] else '未解决'}",
                    "",
                ]
            )

    lines.extend(
        [
            "---",
            "",
            "本文件由 `scripts/state_sync.py` 从 `docs/state/project_state.json` 生成；"
            "请勿手工编辑。",
            "",
        ]
    )
    return "\n".join(lines)


def build_generated_documents(state: dict[str, Any]) -> dict[Path, str]:
    """返回 {相对路径: 完整文本}，顺序固定。"""

    return {
        PROJECT_STATE_REL_PATH: render_project_state(state),
        IMPLEMENTATION_STATUS_REL_PATH: render_implementation_status(state),
    }


# ---------------------------------------------------------------------------
# 文件读写
# ---------------------------------------------------------------------------


def atomic_write_text(path: Path, text: str) -> None:
    """以临时文件 + ``os.replace`` 原子写入 UTF-8 文本（LF）。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_state_file(
    path: Path,
    display_path: str | None = None,
) -> tuple[Any | None, list[Issue]]:
    """读取并校验状态文件，返回 (数据, 问题列表)。"""

    display = display_path or STATE_REL_PATH.as_posix()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, [Issue(display, "状态文件不存在")]
    except OSError as exc:
        return None, [Issue(display, f"无法读取状态文件：{exc}")]

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, [Issue(display, f"不是有效的 UTF-8 文本：{exc}")]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [
            Issue(
                display,
                f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
            )
        ]

    return data, validate_state(data)


def _load_for_root(root: Path) -> tuple[Any | None, list[Issue]]:
    return load_state_file(root / STATE_REL_PATH)


def _print_issues(issues: list[Issue], title: str = "校验失败") -> None:
    print(f"{title}：发现 {len(issues)} 个问题。", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue.render()}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def command_validate(root: Path) -> int:
    state, issues = _load_for_root(root)
    if issues:
        _print_issues(issues)
        return 1

    assert isinstance(state, dict)  # 校验通过后必然成立
    task_count = len(state["tasks"])
    gate_counts = _gate_counts(_sorted_gates(state))
    blocker_count = len(state["blockers"])
    print(
        "OK: project_state.json 校验通过。"
        f"阶段={state['current_phase']}，任务={task_count}，"
        f"门禁 PASS={gate_counts['PASS']}/{len(GATE_IDS)}，阻塞={blocker_count}。"
    )
    return 0


def command_render(root: Path) -> int:
    state, issues = _load_for_root(root)
    if issues:
        _print_issues(issues)
        print("提示：校验失败，未写入任何生成文件。", file=sys.stderr)
        return 1

    assert isinstance(state, dict)
    documents = build_generated_documents(state)
    for relative_path, content in documents.items():
        path = root / relative_path
        atomic_write_text(path, content)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        print(f"已生成 {relative_path.as_posix()}  sha256={digest}")

    print(f"OK: 已生成 {len(documents)} 个文件。")
    return 0


def command_check(root: Path) -> int:
    state, issues = _load_for_root(root)
    if issues:
        _print_issues(issues, title="检查失败")
        return 1

    assert isinstance(state, dict)
    documents = build_generated_documents(state)
    failures = 0

    for relative_path, expected in documents.items():
        path = root / relative_path
        expected_bytes = expected.encode("utf-8")
        if not path.is_file():
            print(f"[FAIL] {relative_path.as_posix()}：文件不存在", file=sys.stderr)
            failures += 1
            continue

        actual = path.read_bytes()
        if actual == expected_bytes:
            digest = hashlib.sha256(actual).hexdigest()
            print(f"[OK] {relative_path.as_posix()}  sha256={digest}")
            continue

        failures += 1
        print(f"[FAIL] {relative_path.as_posix()}：内容与 JSON 渲染结果不一致", file=sys.stderr)
        print(
            f"  预期 SHA256：{hashlib.sha256(expected_bytes).hexdigest()}",
            file=sys.stderr,
        )
        print(
            f"  实际 SHA256：{hashlib.sha256(actual).hexdigest()}",
            file=sys.stderr,
        )
        if actual.startswith(b"\xef\xbb\xbf"):
            print("  注意：实际文件包含 UTF-8 BOM；生成文件不应有 BOM。", file=sys.stderr)
        if b"\r\n" in actual:
            print("  注意：实际文件包含 CRLF；生成文件应为 LF。", file=sys.stderr)

        actual_text = actual.decode("utf-8", errors="replace")
        diff = list(
            difflib.unified_diff(
                expected.splitlines(),
                actual_text.splitlines(),
                fromfile="预期（JSON 渲染）",
                tofile=f"实际（{relative_path.as_posix()}）",
                lineterm="",
            )
        )
        if len(diff) > 120:
            diff = diff[:120] + ["...（差异过长，已截断）"]
        print("\n".join(f"  {line}" for line in diff), file=sys.stderr)

    if failures:
        print(
            f"检查失败：{failures} 个生成文件与 project_state.json 不一致。",
            file=sys.stderr,
        )
        print(
            "修复方式：修改 docs/state/project_state.json 后运行 "
            "`state_sync.py render`；不要手工编辑生成文件。",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(documents)} 个生成文件与 project_state.json 逐字节一致。")
    return 0


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="state_sync.py",
        description="ResearchFlow 研发状态校验、渲染与一致性检查（仅标准库）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例（必须使用项目 Python 3.11.16 绝对路径）：\n"
            "  <Python-3.11.16-绝对路径> scripts/state_sync.py validate\n"
            "  <Python-3.11.16-绝对路径> scripts/state_sync.py render\n"
            "  <Python-3.11.16-绝对路径> scripts/state_sync.py check\n"
            "  <Python-3.11.16-绝对路径> scripts/state_sync.py check --root D:\\ResearchFlow-project\n"
        ),
    )
    parser.add_argument(
        "command",
        choices=("validate", "render", "check"),
        help="validate=校验；render=生成；check=逐字节一致性检查",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="项目根目录（默认：脚本所在仓库根目录）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"错误：项目根目录不存在或不是目录：{root}", file=sys.stderr)
        return 1

    try:
        if args.command == "validate":
            return command_validate(root)
        if args.command == "render":
            return command_render(root)
        if args.command == "check":
            return command_check(root)
    except OSError as exc:
        print(f"错误：文件操作失败：{exc}", file=sys.stderr)
        return 1

    parser.error(f"未知命令：{args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
