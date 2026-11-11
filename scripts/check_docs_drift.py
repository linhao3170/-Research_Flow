#!/usr/bin/env python3
"""检查背景文档是否混入 ``docs/state/project_state.json`` 的状态值。

只读脚本，不修改任何文件。退出码：

* ``0``：没有 ERROR（可以有 WARNING）。
* ``1``：至少一个 ERROR。
* ``2``：工具或解析失败（含 ``project_state.json`` 无效）。

分类与规则写死在代码里，不做全目录扫描。历史类文档永不判冲突。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_sync import validate_state  # noqa: E402


STATE_REL_PATH = "docs/state/project_state.json"
POINTER_SENTENCE = "当前状态以 docs/state/project_state.json 为准。"
READ_ORDER_SENTENCE = "读取顺序见 AGENTS.md §0。"
WRITE_ORDER_SENTENCE = "写入顺序见 AGENTS.md §7。"

RULES_FILES = ("AGENTS.md",)
INDEX_FILES = ("docs/memory/Memory.md",)

# 全量 STATE-FREE 分类；A 轮只激活 A 轮清单内的 5 份，B 轮再扩展到全部。
STATE_FREE_FILES = (
    "docs/memory/project-context.md",
    "docs/memory/architecture-decisions.md",
    "docs/memory/environment.md",
    "docs/memory/references.md",
    "docs/MEMORY_GUIDE.md",
    "README.md",
    "docs/PROJECT_OVERVIEW.md",
    "docs/DEVELOPMENT_WORKFLOW.md",
    "docs/ARCHITECTURE.md",
)
STATE_FREE_ENFORCED = STATE_FREE_FILES[:5]

HISTORICAL_BASENAMES = {
    "CHANGELOG_DEV.md",
    "SESSION_HANDOFF.md",
    "GLOSSARY.md",
    "G0_DECISION_LIST.md",
    "runtime_states.md",
    "MCP_CATALOG.md",
    "SECURITY_POLICY.md",
    "SKILL_CATALOG.md",
    "feedback-and-lessons.md",
}
HISTORICAL_PREFIXES = (
    "docs/verification/",
    "docs/G0/",
    "docs/design/",
    "docs/PRD/",
    "docs/ADR/",
)

STATUS_DECL_RE = re.compile(
    r"(?P<ident>T-[A-Z0-9]+(?:-[A-Z0-9]+)*|G[0-7])"
    r"\s*[:：=]?\s*"
    r"(?P<status>BACKLOG|READY|IN_PROGRESS|BLOCKED|IN_REVIEW|DONE|"
    r"DEFERRED|NOT_STARTED|PASS|FAIL)"
)
LAST_COMMIT_RE = re.compile(
    r"last_verified_commit\s*[:：=]?\s*`?([0-9a-f]{7,40}|null)"
)
PHASE_RE = re.compile(r"(current_phase|当前阶段)\s*[:：=]\s*`?([A-Z_]+)")
OUTDATED_RE = re.compile(
    r"尚未通过|尚未建立|尚未开发|未创建|未安装|0 commit|尚无 commit"
)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
INDEX_STATUS_RE = re.compile(
    r"\b(BACKLOG|READY|IN_PROGRESS|BLOCKED|IN_REVIEW|DONE|"
    r"DEFERRED|NOT_STARTED|PASS|FAIL)\b"
)
PROJECT_CONTEXT_MENTION = "project-context.md"
CURRENT_BASELINE_RE = re.compile(r"当前(?:阶段)?基线")
INDEX_METADATA_RE = re.compile(r"最近更新|是否已核验|当前(?:阶段)?基线")


class DriftToolError(RuntimeError):
    """工具或输入无法解析，CLI 应以退出码 2 结束。"""


@dataclass(frozen=True)
class Issue:
    path: str
    line: int
    severity: str
    message: str
    expected: str
    actual: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.severity}: {self.message} "
            f"(expected={self.expected}, actual={self.actual})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
        }


def normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def classify(path: str) -> str:
    normalized = normalize_path(path)
    if normalized in RULES_FILES:
        return "rules"
    if normalized in INDEX_FILES:
        return "index"
    if normalized in STATE_FREE_FILES:
        return "state_free" if normalized in STATE_FREE_ENFORCED else "pending"
    return "historical"


def _one_line(value: Any) -> str:
    text = " ".join(str(value).splitlines()).strip()
    return text or "缺失"


def _add(
    issues: list[Issue],
    path: str,
    line: int,
    severity: str,
    message: str,
    expected: Any,
    actual: Any,
) -> None:
    issues.append(
        Issue(
            path=path,
            line=max(1, int(line)),
            severity=severity,
            message=message,
            expected=_one_line(expected),
            actual=_one_line(actual),
        )
    )


def _iter_content_lines(text: str) -> Iterable[tuple[int, str]]:
    """跳过 ``` 代码块与以 ``>`` 开头的行。"""

    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped.startswith(">"):
            continue
        yield lineno, line


def _status_maps(state: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    tasks: dict[str, str] = {}
    for task in state.get("tasks", []):
        if isinstance(task, dict) and isinstance(task.get("task_id"), str):
            tasks[task["task_id"]] = str(task.get("status", ""))

    gates: dict[str, str] = {}
    raw_gates = state.get("stage_gates", {})
    if isinstance(raw_gates, dict):
        for gate in raw_gates.values():
            if isinstance(gate, dict) and isinstance(gate.get("gate_id"), str):
                gates[gate["gate_id"]] = str(gate.get("status", ""))
    return tasks, gates


def _check_state_declarations(
    path: str, text: str, state: dict[str, Any]
) -> list[Issue]:
    issues: list[Issue] = []
    tasks, gates = _status_maps(state)

    for lineno, line in _iter_content_lines(text):
        for match in STATUS_DECL_RE.finditer(line):
            identifier = match.group("ident")
            actual = match.group("status")
            expected = tasks.get(identifier, gates.get(identifier, "未定义"))
            _add(
                issues,
                path,
                lineno,
                "ERROR",
                "背景文档不得包含研发状态声明；状态只允许出现在 project_state.json",
                expected,
                actual,
            )

        commit_match = LAST_COMMIT_RE.search(line)
        if commit_match:
            expected_commit = state.get("last_verified_commit")
            _add(
                issues,
                path,
                lineno,
                "ERROR",
                "背景文档不得包含 last_verified_commit 值",
                "null" if expected_commit is None else expected_commit,
                commit_match.group(1),
            )

        phase_match = PHASE_RE.search(line)
        if phase_match:
            _add(
                issues,
                path,
                lineno,
                "ERROR",
                "背景文档不得包含当前阶段值",
                str(state.get("current_phase", "")),
                phase_match.group(2),
            )

    return issues


def _check_outdated(path: str, text: str) -> list[Issue]:
    issues: list[Issue] = []
    for lineno, line in _iter_content_lines(text):
        match = OUTDATED_RE.search(line)
        if match:
            _add(
                issues,
                path,
                lineno,
                "WARNING",
                "含可能过期的“未…”措辞；请确认是否应改为状态指针或历史表述",
                "无过期状态措辞",
                match.group(0),
            )
    return issues


def _check_pointer(path: str, text: str) -> list[Issue]:
    if POINTER_SENTENCE in text:
        return []
    for lineno, line in enumerate(text.splitlines(), 1):
        if "当前状态以" in line:
            return [
                Issue(
                    path,
                    lineno,
                    "ERROR",
                    "规范指针句不正确",
                    POINTER_SENTENCE,
                    _one_line(line),
                )
            ]
    return [
        Issue(
            path,
            1,
            "ERROR",
            "缺少规范指针句",
            POINTER_SENTENCE,
            "缺失",
        )
    ]


def _check_project_context_baseline(path: str, text: str) -> list[Issue]:
    """R8：提到 project-context.md 的行不得同时声称“当前基线”。"""

    issues: list[Issue] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if PROJECT_CONTEXT_MENTION not in line:
            continue
        match = CURRENT_BASELINE_RE.search(line)
        if not match:
            continue
        _add(
            issues,
            path,
            lineno,
            "ERROR",
            "提到 project-context.md 的行不得同时出现“当前基线”措辞；"
            "背景文档不维护当前状态",
            "无“当前基线”措辞",
            match.group(0),
        )
    return issues


def _find_section(
    lines: list[str], heading_pattern: str
) -> tuple[int, int] | None:
    start = None
    for index, line in enumerate(lines):
        if re.match(heading_pattern, line):
            start = index
            break
    if start is None:
        return None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^##\s+", lines[index]):
            end = index
            break
    return start, end


def _check_agents_read_order(path: str, text: str) -> list[Issue]:
    lines = text.splitlines()
    section = _find_section(lines, r"^##\s+0\.")
    if section is None:
        return [
            Issue(path, 1, "ERROR", "AGENTS 缺少 §0 读取顺序定义", "包含 §0", "缺失")
        ]

    start, end = section
    state_index: int | None = None
    memory_index: int | None = None
    memory_line = 1
    for index in range(start, end):
        if state_index is None and "project_state.json" in lines[index]:
            state_index = index
        if memory_index is None and "docs/memory/" in lines[index]:
            memory_index = index
            memory_line = index + 1

    if state_index is None or memory_index is None:
        return [
            Issue(
                path,
                start + 1,
                "ERROR",
                "AGENTS §0 读取顺序不完整",
                "project_state.json 与 docs/memory/ 均出现且前者在前",
                f"project_state.json={state_index is not None}, "
                f"docs/memory/={memory_index is not None}",
            )
        ]

    if state_index > memory_index:
        return [
            Issue(
                path,
                memory_line,
                "ERROR",
                "AGENTS §0 读取顺序错误：project_state.json 必须先于 docs/memory/",
                "project_state.json 先于 docs/memory/",
                "docs/memory/ 先于 project_state.json",
            )
        ]
    return []


def _check_required_sentence(
    path: str, text: str, sentence: str, label: str
) -> list[Issue]:
    if sentence in text:
        return []
    return [
        Issue(
            path,
            1,
            "ERROR",
            f"缺少{label}指针句",
            sentence,
            "缺失",
        )
    ]


def check_text(path: str, text: str, state: dict[str, Any]) -> list[Issue]:
    """纯文本检查：不访问文件系统，不读取 JSON，不调用 git。"""

    normalized = normalize_path(path)
    issues: list[Issue] = []

    if normalized == "AGENTS.md":
        issues.extend(_check_agents_read_order(normalized, text))
    if normalized in (
        "docs/memory/Memory.md",
        "docs/MEMORY_GUIDE.md",
        ".agents/skills/researchflow-onboarding/SKILL.md",
    ):
        issues.extend(
            _check_required_sentence(
                normalized, text, READ_ORDER_SENTENCE, "读取顺序"
            )
        )
    if normalized == ".agents/skills/researchflow-memory-handoff/SKILL.md":
        issues.extend(
            _check_required_sentence(
                normalized, text, WRITE_ORDER_SENTENCE, "写入顺序"
            )
        )

    category = classify(normalized)
    if category != "historical":
        issues.extend(_check_project_context_baseline(normalized, text))
    if category in ("historical", "pending"):
        return issues

    if category == "state_free":
        issues.extend(_check_pointer(normalized, text))
        issues.extend(_check_state_declarations(normalized, text, state))
        issues.extend(_check_outdated(normalized, text))
    elif category == "rules":
        issues.extend(_check_state_declarations(normalized, text, state))
        issues.extend(_check_outdated(normalized, text))
    elif category == "index":
        issues.extend(_check_outdated(normalized, text))

    return issues


def _read_text(root: Path, rel_path: str) -> str:
    path = root / rel_path
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DriftToolError(f"文件不存在：{rel_path}") from exc
    except UnicodeDecodeError as exc:
        raise DriftToolError(f"不是有效的 UTF-8：{rel_path}：{exc}") from exc
    except OSError as exc:
        raise DriftToolError(f"无法读取 {rel_path}：{exc}") from exc


def load_state(root: Path) -> tuple[dict[str, Any], str]:
    text = _read_text(root, STATE_REL_PATH)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DriftToolError(
            "project_state.json JSON 解析失败："
            f"第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}"
        ) from exc

    issues = validate_state(data)
    if issues:
        detail = "；".join(f"{issue.path}: {issue.message}" for issue in issues[:5])
        raise DriftToolError(f"project_state.json 校验失败：{detail}")
    assert isinstance(data, dict)
    return data, text


def _git_head(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except OSError as exc:
        raise DriftToolError(f"无法运行 git：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DriftToolError("git rev-parse HEAD 超时") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DriftToolError(f"git rev-parse HEAD 失败：{detail}")
    head = completed.stdout.strip()
    if not head:
        raise DriftToolError("git rev-parse HEAD 返回空值")
    return head


def _field_line(text: str, field: str) -> int:
    for lineno, line in enumerate(text.splitlines(), 1):
        if field in line:
            return lineno
    return 1


def check_last_verified_commit(
    root: Path, state: dict[str, Any], state_text: str
) -> list[Issue]:
    commit = state.get("last_verified_commit")
    actual = "null" if commit is None else str(commit)
    head = _git_head(root)
    if actual == head:
        return []

    return [
        Issue(
            STATE_REL_PATH,
            _field_line(state_text, "last_verified_commit"),
            "WARNING",
            "last_verified_commit 与当前 HEAD 不一致",
            head,
            actual,
        )
    ]


def check_memory_index(root: Path) -> list[Issue]:
    rel_path = "docs/memory/Memory.md"
    text = _read_text(root, rel_path)
    memory_dir = (root / rel_path).parent
    lines = text.splitlines()
    issues: list[Issue] = []
    resolved_targets: set[Path] = set()

    for lineno, line in enumerate(lines, 1):
        for match in LINK_RE.finditer(line):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            resolved = (memory_dir / target).resolve()
            resolved_targets.add(resolved)
            if not resolved.exists():
                _add(
                    issues,
                    rel_path,
                    lineno,
                    "ERROR",
                    "记忆索引列出的文件不存在",
                    "文件存在",
                    target,
                )

        status_match = INDEX_STATUS_RE.search(line)
        if status_match:
            _add(
                issues,
                rel_path,
                lineno,
                "ERROR",
                "记忆索引行不得包含研发状态词",
                "无状态词",
                status_match.group(0),
            )

        metadata_match = INDEX_METADATA_RE.search(line)
        if metadata_match:
            _add(
                issues,
                rel_path,
                lineno,
                "ERROR",
                "记忆索引不得含“最近更新”“是否已核验”列或“当前基线”措辞",
                "无时效/核验列，无“当前基线”措辞",
                metadata_match.group(0),
            )

    for memory_file in sorted(memory_dir.glob("*.md")):
        if memory_file.name == "Memory.md":
            continue
        if memory_file.resolve() not in resolved_targets:
            _add(
                issues,
                rel_path,
                1,
                "ERROR",
                "记忆文件未被 Memory.md 索引",
                "被 Memory.md 索引",
                memory_file.name,
            )

    return issues


def scanned_paths() -> list[str]:
    paths: list[str] = []
    for rel_path in RULES_FILES + INDEX_FILES + tuple(
        path for path in STATE_FREE_FILES if path in STATE_FREE_ENFORCED
    ):
        if rel_path not in paths:
            paths.append(rel_path)

    # R7 的读序/写序指针也检查这两个 Skill。
    for rel_path in (
        ".agents/skills/researchflow-onboarding/SKILL.md",
        ".agents/skills/researchflow-memory-handoff/SKILL.md",
    ):
        if rel_path not in paths:
            paths.append(rel_path)
    return paths


def collect_issues(root: Path) -> list[Issue]:
    state, state_text = load_state(root)
    issues: list[Issue] = []

    for rel_path in scanned_paths():
        text = _read_text(root, rel_path)
        issues.extend(check_text(rel_path, text, state))

    issues.extend(check_memory_index(root))
    issues.extend(check_last_verified_commit(root, state, state_text))
    issues.sort(
        key=lambda issue: (
            issue.path,
            issue.line,
            0 if issue.severity == "ERROR" else 1,
            issue.message,
            issue.expected,
            issue.actual,
        )
    )
    return issues


def run(root: Path, as_json: bool = False) -> int:
    root = Path(root)
    if not root.is_dir():
        print(f"ERROR: 根目录不存在：{root}", file=sys.stderr)
        return 2

    try:
        issues = collect_issues(root)
    except DriftToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    error_count = sum(1 for issue in issues if issue.severity == "ERROR")
    warning_count = sum(1 for issue in issues if issue.severity == "WARNING")

    if as_json:
        payload = {
            "errors": error_count,
            "warnings": warning_count,
            "issues": [issue.as_dict() for issue in issues],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for issue in issues:
            print(issue.render())
        print(
            f"STATE-FREE enforced={len(STATE_FREE_ENFORCED)}/{len(STATE_FREE_FILES)}；"
            f"ERROR={error_count}；WARNING={warning_count}"
        )

    return 1 if error_count else 0


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
        description=(
            "检查背景文档是否混入 project_state.json 的状态值；"
            "只读，不修改文件。"
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=SCRIPT_DIR.parent,
        help="仓库根目录（默认：脚本上级目录）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出问题列表",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    return run(args.root, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())