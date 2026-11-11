"""check_docs_drift.py 的单元测试与真实仓库冒烟（仅标准库）。

运行方式（必须使用项目 Python 3.11.16 64 位）：

    "C:\\Users\\Administrator\\AppData\\Roaming\\uv\\python\\cpython-3.11.16-windows-x86_64-none\\python.exe" \
        -m unittest tests.test_check_docs_drift -v
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_docs_drift as drift  # noqa: E402


STATE = {
    "current_phase": "T0",
    "last_verified_commit": "19c337f350fead30efd52c222356ad6248a3f937",
    "tasks": [
        {"task_id": "T-WP-01-001", "status": "DONE"},
    ],
    "stage_gates": {
        "G0": {"gate_id": "G0", "status": "PASS"},
        "G1": {"gate_id": "G1", "status": "NOT_STARTED"},
    },
}

PROJECT_CONTEXT = "docs/memory/project-context.md"
CLEAN_TEXT = (
    "背景说明。\n"
    "当前状态以 docs/state/project_state.json 为准。\n"
)


def errors(issues: list[drift.Issue]) -> list[drift.Issue]:
    return [issue for issue in issues if issue.severity == "ERROR"]


def warnings(issues: list[drift.Issue]) -> list[drift.Issue]:
    return [issue for issue in issues if issue.severity == "WARNING"]


class CheckTextTests(unittest.TestCase):
    def test_clean_text_has_no_error(self) -> None:
        issues = drift.check_text(PROJECT_CONTEXT, CLEAN_TEXT, STATE)
        self.assertEqual([], errors(issues))

    def test_wrong_pointer_path_reports_correct_line(self) -> None:
        text = (
            "第一行\n"
            "第二行\n"
            "当前状态以 docs/state/other.json 为准。\n"
        )
        issues = drift.check_text(PROJECT_CONTEXT, text, STATE)
        found = errors(issues)
        self.assertEqual(1, len(found))
        self.assertEqual(3, found[0].line)
        self.assertIn("规范指针句不正确", found[0].message)
        self.assertEqual(drift.POINTER_SENTENCE, found[0].expected)

    def test_task_status_declaration_reports_expected_done(self) -> None:
        text = CLEAN_TEXT + "T-WP-01-001 IN_REVIEW\n"
        issues = drift.check_text(PROJECT_CONTEXT, text, STATE)
        found = errors(issues)
        self.assertEqual(1, len(found))
        self.assertEqual(3, found[0].line)
        self.assertEqual("DONE", found[0].expected)
        self.assertEqual("IN_REVIEW", found[0].actual)

    def test_gate_status_declaration_reports_expected_pass(self) -> None:
        text = CLEAN_TEXT + "G0 NOT_STARTED\n"
        issues = drift.check_text(PROJECT_CONTEXT, text, STATE)
        found = errors(issues)
        self.assertEqual(1, len(found))
        self.assertEqual("PASS", found[0].expected)
        self.assertEqual("NOT_STARTED", found[0].actual)

    def test_historical_document_never_conflicts(self) -> None:
        text = (
            "T-WP-01-001 IN_REVIEW\n"
            "G0 NOT_STARTED\n"
            "last_verified_commit: deadbeef\n"
            "当前阶段：T0\n"
        )
        self.assertEqual(
            [],
            drift.check_text("docs/CHANGELOG_DEV.md", text, STATE),
        )

    def test_outdated_wording_is_warning_only(self) -> None:
        text = CLEAN_TEXT + "尚未建立\n"
        issues = drift.check_text(PROJECT_CONTEXT, text, STATE)
        self.assertEqual([], errors(issues))
        found = warnings(issues)
        self.assertEqual(1, len(found))
        self.assertEqual(3, found[0].line)
        self.assertEqual("尚未建立", found[0].actual)


class CliTests(unittest.TestCase):
    def test_invalid_json_exits_2(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(drift, "_read_text", return_value="{broken"):
            with redirect_stderr(stderr):
                code = drift.run(ROOT)
        self.assertEqual(2, code)
        self.assertIn("JSON 解析失败", stderr.getvalue())

    def test_two_runs_are_byte_identical(self) -> None:
        def capture() -> tuple[int, str]:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = drift.run(ROOT)
            return code, stdout.getvalue()

        first = capture()
        second = capture()
        self.assertEqual(0, first[0])
        self.assertEqual(first, second)

    def _run_with_text_override(
        self, rel_path: str, transform
    ) -> tuple[int, str]:
        """只替换目标文件的读取结果，其余文件仍按真实仓库读取。"""

        def fake_read_text(root: Path, path: str) -> str:
            text = (root / path).read_text(encoding="utf-8")
            if drift.normalize_path(path) == rel_path:
                return transform(text)
            return text

        stdout = io.StringIO()
        with mock.patch.object(drift, "_read_text", side_effect=fake_read_text):
            with redirect_stdout(stdout):
                code = drift.run(ROOT)
        return code, stdout.getvalue()

    def test_memory_index_with_verification_column_exits_1(self) -> None:
        code, output = self._run_with_text_override(
            "docs/memory/Memory.md",
            lambda text: text + "\n是否已核验\n",
        )
        self.assertEqual(1, code)
        self.assertIn("记忆索引不得含", output)
        self.assertIn("actual=是否已核验", output)

    def test_agents_project_context_line_with_baseline_exits_1(self) -> None:
        def reintroduce_baseline(text: str) -> str:
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if line.lstrip().startswith(
                    "- `docs/memory/project-context.md`"
                ):
                    lines[index] = (
                        "- `docs/memory/project-context.md`：项目目标、边界、当前基线。"
                    )
            return "\n".join(lines) + "\n"

        code, output = self._run_with_text_override(
            "AGENTS.md", reintroduce_baseline
        )
        self.assertEqual(1, code)
        self.assertIn("AGENTS.md:107: ERROR: 提到 project-context.md", output)
        self.assertIn("actual=当前基线", output)


if __name__ == "__main__":
    unittest.main()