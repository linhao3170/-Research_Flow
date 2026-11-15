"""state_sync.py 的端到端测试（仅标准库）。

运行方式（必须使用项目 Python 3.11.16 64 位）：

    "C:\\Users\\Administrator\\AppData\\Roaming\\uv\\python\\cpython-3.11.16-windows-x86_64-none\\python.exe" \
        -m unittest discover -s tests -v

测试通过真实子进程调用 CLI，因此同时覆盖退出码、stdout/stderr 与文件行为。
"""

from __future__ import annotations

import copy
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "state_sync.py"
PYTHON = sys.executable
NOW = "2026-11-08T11:27:46+08:00"

GATE_IDS = tuple(f"G{index}" for index in range(8))
GATE_TITLES = {
    "G0": "规格冻结",
    "G1": "纵向闭环",
    "G2": "证据可信",
    "G3": "L3 独立重执行",
    "G4": "动态调度/恢复",
    "G5": "实验数据可信",
    "G6": "外部复核",
    "G7": "Harness 适配",
}


def make_gate(gate_id: str, status: str = "NOT_STARTED", **overrides: Any) -> dict[str, Any]:
    gate: dict[str, Any] = {
        "gate_id": gate_id,
        "title": GATE_TITLES[gate_id],
        "status": status,
        "criteria": [f"{GATE_TITLES[gate_id]}的验收条件"],
        "evidence_paths": [],
        "updated_at": NOW,
    }
    gate.update(overrides)
    return gate


def make_task(
    task_id: str = "RF-T0-001",
    status: str = "BACKLOG",
    **overrides: Any,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "task_id": task_id,
        "title": "示例研发任务",
        "phase": "T0",
        "status": status,
        "depends_on": [],
        "acceptance_criteria": ["示例验收标准"],
        "test_commands": [],
        "evidence_paths": [],
        "updated_at": NOW,
        "blocker": None,
    }
    if status in ("IN_REVIEW", "DONE"):
        task["test_commands"] = ["& $py -m unittest discover -s tests -v"]
    if status == "DONE":
        task["evidence_paths"] = ["docs/verification/example.md"]
    if status == "BLOCKED":
        task["blocker"] = "示例阻塞原因"
    task.update(overrides)
    return task


def make_state(
    *,
    tasks: list[dict[str, Any]] | None = None,
    gates: dict[str, dict[str, Any]] | None = None,
    blockers: list[dict[str, Any]] | None = None,
    stages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if gates is None:
        gates = {gate_id: make_gate(gate_id) for gate_id in GATE_IDS}
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "project_name": "ResearchFlow",
        "updated_at": NOW,
        "current_phase": "G0_PREPARATION",
        "current_milestone": "M0_GOVERNANCE_BASELINE",
        "tasks": tasks if tasks is not None else [],
        "stage_gates": gates,
        "blockers": blockers if blockers is not None else [],
        "last_verified_commit": None,
    }
    if stages is not None:
        state["pseudocode_stages"] = stages
    return state


def make_stage(
    stage_id: str,
    status: str = "IN_REVIEW",
    **overrides: Any,
) -> dict[str, Any]:
    stage: dict[str, Any] = {
        "stage_id": stage_id,
        "title": f"伪代码阶段 {stage_id}",
        "status": status,
        "modules": ["M01_contracts"],
        "deliverables": ["design/pseudocode/M01_contracts"],
        "acceptance_criteria": ["示例阶段验收标准"],
        "acceptance_basis": "示例阶段依据",
        "evidence_paths": ["design/pseudocode/STAGE_LOG.md"],
        "blocker": None,
        "updated_at": NOW,
    }
    if status == "BLOCKED":
        stage["blocker"] = "示例阶段阻塞原因"
    stage.update(overrides)
    return stage


def make_all_stages() -> list[dict[str, Any]]:
    return [make_stage(f"P{index}") for index in range(1, 11)]


def prepare_stage_paths(root: Path) -> None:
    (root / "design" / "pseudocode" / "M01_contracts").mkdir(parents=True, exist_ok=True)
    log_path = root / "design" / "pseudocode" / "STAGE_LOG.md"
    log_path.write_text("# stage log\n", encoding="utf-8", newline="\n")


def materialize_stage_paths(root: Path, state: dict[str, Any]) -> None:
    """为真实状态 JSON 的阶段路径创建临时占位文件/目录。

    仅用于 render/check 测试；不复制真实内容，也不放宽 state_sync 的路径存在性校验。
    """

    for stage in state.get("pseudocode_stages", []):
        for module in stage.get("modules", []):
            (root / "design" / "pseudocode" / module).mkdir(parents=True, exist_ok=True)
        for key in ("deliverables", "evidence_paths"):
            for relative in stage.get(key, []):
                path = root / relative
                if path.suffix:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("placeholder\n", encoding="utf-8", newline="\n")
                else:
                    path.mkdir(parents=True, exist_ok=True)


def write_state(root: Path, state: dict[str, Any] | str) -> None:
    path = root / "docs" / "state" / "project_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(state, str):
        path.write_text(state, encoding="utf-8", newline="\n")
        return
    text = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def run_cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    command = [PYTHON, str(SCRIPT), *arguments, "--root", str(root)]
    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )


def combined(result: subprocess.CompletedProcess[str]) -> str:
    return f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"


class StateSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="rf_state_sync_")
        self.root = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    # ------------------------------------------------------------------
    # 解释器基线
    # ------------------------------------------------------------------

    def test_python_baseline_is_31116_64bit(self) -> None:
        self.assertEqual(
            sys.version_info[:3],
            (3, 11, 16),
            f"测试必须使用项目 Python 3.11.16，当前为 {sys.version.split()[0]}：{sys.executable}",
        )
        self.assertEqual(
            platform.architecture()[0],
            "64bit",
            f"测试必须使用 64 位解释器，当前为 {platform.architecture()[0]}：{sys.executable}",
        )

    # ------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------

    def test_valid_state_passes(self) -> None:
        write_state(self.root, make_state(tasks=[make_task()]))
        result = run_cli(self.root, "validate")
        self.assertEqual(result.returncode, 0, combined(result))
        self.assertIn("校验通过", result.stdout)

    def test_repository_state_passes(self) -> None:
        result = run_cli(ROOT, "validate")
        self.assertEqual(result.returncode, 0, combined(result))
        self.assertIn("校验通过", result.stdout)

    def test_missing_required_field_fails(self) -> None:
        state = make_state()
        del state["current_phase"]
        write_state(self.root, state)
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("缺失必填字段", result.stderr)
        self.assertIn("current_phase", result.stderr)

    def test_invalid_task_status_fails(self) -> None:
        write_state(self.root, make_state(tasks=[make_task(status="FINISHED")]))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("tasks[0].status", result.stderr)
        self.assertIn("非法研发任务状态", result.stderr)

    def test_invalid_phase_fails(self) -> None:
        write_state(self.root, make_state(tasks=[make_task(phase="T9")]))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("tasks[0].phase", result.stderr)
        self.assertIn("非法阶段", result.stderr)

    def test_duplicate_task_id_fails(self) -> None:
        tasks = [make_task(task_id="RF-T0-001"), make_task(task_id="RF-T0-001")]
        write_state(self.root, make_state(tasks=tasks))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("tasks[1].task_id", result.stderr)
        self.assertIn("重复的 task_id", result.stderr)

    def test_invalid_depends_on_fails(self) -> None:
        write_state(
            self.root,
            make_state(tasks=[make_task(depends_on=["RF-T0-999"])]),
        )
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("tasks[0].depends_on[0]", result.stderr)
        self.assertIn("不存在的 task_id", result.stderr)

    def test_self_dependency_fails(self) -> None:
        write_state(
            self.root,
            make_state(tasks=[make_task(task_id="RF-T0-001", depends_on=["RF-T0-001"])]),
        )
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("不能依赖自身", result.stderr)

    def test_cycle_dependency_fails(self) -> None:
        tasks = [
            make_task(task_id="RF-T0-001", depends_on=["RF-T0-002"]),
            make_task(task_id="RF-T0-002", depends_on=["RF-T0-001"]),
        ]
        write_state(self.root, make_state(tasks=tasks))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("循环依赖", result.stderr)

    def test_unknown_top_level_field_fails(self) -> None:
        state = make_state()
        state["owner"] = "someone"
        write_state(self.root, state)
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("$.owner", result.stderr)
        self.assertIn("未知字段", result.stderr)

    def test_pass_gate_without_evidence_fails(self) -> None:
        gates = {gate_id: make_gate(gate_id) for gate_id in GATE_IDS}
        gates["G0"] = make_gate("G0", status="PASS")
        write_state(self.root, make_state(gates=gates))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("stage_gates.G0.evidence_paths", result.stderr)
        self.assertIn("PASS", result.stderr)

    def test_blocked_task_requires_blocker(self) -> None:
        task = make_task(status="BLOCKED", blocker=None)
        write_state(self.root, make_state(tasks=[task]))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("tasks[0].blocker", result.stderr)
        self.assertIn("BLOCKED", result.stderr)

    def test_done_task_requires_test_commands_and_evidence(self) -> None:
        task = make_task(status="DONE", test_commands=[], evidence_paths=[])
        write_state(self.root, make_state(tasks=[task]))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("tasks[0].test_commands", result.stderr)
        self.assertIn("tasks[0].evidence_paths", result.stderr)

    # ------------------------------------------------------------------
    # pseudocode_stages：P1–P10 独立状态注册表
    # ------------------------------------------------------------------

    def test_valid_pseudocode_stages_pass(self) -> None:
        prepare_stage_paths(self.root)
        write_state(self.root, make_state(stages=make_all_stages()))
        result = run_cli(self.root, "validate")
        self.assertEqual(result.returncode, 0, combined(result))
        self.assertIn("伪代码阶段=10", result.stdout)

    def test_pseudocode_stage_status_cannot_reuse_task_status(self) -> None:
        prepare_stage_paths(self.root)
        stages = make_all_stages()
        stages[0]["status"] = "DONE"
        write_state(self.root, make_state(stages=stages))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("pseudocode_stages[0].status", result.stderr)
        self.assertIn("非法伪代码阶段状态", result.stderr)

    def test_accepted_stage_requires_evidence(self) -> None:
        prepare_stage_paths(self.root)
        stages = make_all_stages()
        stages[0].update(status="ACCEPTED", evidence_paths=[])
        write_state(self.root, make_state(stages=stages))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("pseudocode_stages[0].evidence_paths", result.stderr)
        self.assertIn("ACCEPTED", result.stderr)

    def test_blocked_stage_requires_blocker(self) -> None:
        prepare_stage_paths(self.root)
        stages = make_all_stages()
        stages[0].update(status="BLOCKED", blocker=None)
        write_state(self.root, make_state(stages=stages))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("pseudocode_stages[0].blocker", result.stderr)
        self.assertIn("BLOCKED", result.stderr)

    def test_duplicate_pseudocode_stage_id_fails(self) -> None:
        prepare_stage_paths(self.root)
        stages = make_all_stages()
        stages[1]["stage_id"] = "P1"
        write_state(self.root, make_state(stages=stages))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("重复的 stage_id", result.stderr)
        self.assertIn("P1", result.stderr)

    def test_missing_pseudocode_stage_fails(self) -> None:
        prepare_stage_paths(self.root)
        stages = make_all_stages()[:9]
        write_state(self.root, make_state(stages=stages))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("缺少伪代码阶段 P10", result.stderr)

    def test_missing_stage_module_directory_fails(self) -> None:
        prepare_stage_paths(self.root)
        stages = make_all_stages()
        stages[0]["modules"] = ["M99_missing"]
        write_state(self.root, make_state(stages=stages))
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("pseudocode_stages[0].modules[0]", result.stderr)
        self.assertIn("模块目录不存在", result.stderr)

    def test_render_includes_pseudocode_stages(self) -> None:
        prepare_stage_paths(self.root)
        stages = make_all_stages()
        stages[0].update(status="ACCEPTED")
        write_state(self.root, make_state(stages=stages))
        render = run_cli(self.root, "render")
        self.assertEqual(render.returncode, 0, combined(render))
        check = run_cli(self.root, "check")
        self.assertEqual(check.returncode, 0, combined(check))
        project_state = (self.root / "docs" / "PROJECT_STATE.md").read_text(encoding="utf-8")
        implementation_status = (self.root / "docs" / "IMPLEMENTATION_STATUS.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## 伪代码阶段", project_state)
        self.assertIn("`P1`", project_state)
        self.assertIn("## 4. 伪代码阶段明细", implementation_status)
        self.assertIn("`P10`", implementation_status)

    # ------------------------------------------------------------------
    # render / check
    # ------------------------------------------------------------------

    def test_render_then_check_passes(self) -> None:
        write_state(self.root, make_state())
        render = run_cli(self.root, "render")
        self.assertEqual(render.returncode, 0, combined(render))

        project_state = self.root / "docs" / "PROJECT_STATE.md"
        implementation_status = self.root / "docs" / "IMPLEMENTATION_STATUS.md"
        self.assertTrue(project_state.is_file())
        self.assertTrue(implementation_status.is_file())
        for path in (project_state, implementation_status):
            content = path.read_text(encoding="utf-8")
            self.assertIn("由 project_state.json 自动生成，请勿手工编辑", content)

        check = run_cli(self.root, "check")
        self.assertEqual(check.returncode, 0, combined(check))
        self.assertIn("逐字节一致", check.stdout)

    def test_render_with_task_detail_passes(self) -> None:
        task = make_task(task_id="RF-T0-001", status="DONE", title="示例完成任务")
        write_state(self.root, make_state(tasks=[task]))

        render = run_cli(self.root, "render")
        self.assertEqual(render.returncode, 0, combined(render))
        check = run_cli(self.root, "check")
        self.assertEqual(check.returncode, 0, combined(check))

        project_state = (self.root / "docs" / "PROJECT_STATE.md").read_text(
            encoding="utf-8"
        )
        implementation_status = (
            self.root / "docs" / "IMPLEMENTATION_STATUS.md"
        ).read_text(encoding="utf-8")
        self.assertIn("RF-T0-001", project_state)
        self.assertIn("示例完成任务", project_state)
        self.assertIn("RF-T0-001", implementation_status)
        self.assertIn("示例验收标准", implementation_status)
        self.assertIn("& $py -m unittest discover -s tests -v", implementation_status)
        self.assertIn("docs/verification/example.md", implementation_status)

    def test_manual_edit_fails_check(self) -> None:
        write_state(self.root, make_state())
        self.assertEqual(run_cli(self.root, "render").returncode, 0)
        project_state = self.root / "docs" / "PROJECT_STATE.md"
        with project_state.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n手工修改，不应保留。\n")

        check = run_cli(self.root, "check")
        self.assertNotEqual(check.returncode, 0, combined(check))
        self.assertIn("PROJECT_STATE.md", check.stderr)
        self.assertIn("内容与 JSON 渲染结果不一致", check.stderr)
        self.assertIn("手工修改", check.stderr)

    def test_missing_generated_file_fails_check(self) -> None:
        write_state(self.root, make_state())
        self.assertEqual(run_cli(self.root, "render").returncode, 0)
        (self.root / "docs" / "PROJECT_STATE.md").unlink()

        check = run_cli(self.root, "check")
        self.assertNotEqual(check.returncode, 0, combined(check))
        self.assertIn("文件不存在", check.stderr)
        self.assertIn("检查失败", check.stderr)

    def test_crlf_in_generated_file_fails_check(self) -> None:
        write_state(self.root, make_state())
        self.assertEqual(run_cli(self.root, "render").returncode, 0)
        project_state = self.root / "docs" / "PROJECT_STATE.md"
        content = project_state.read_bytes()
        project_state.write_bytes(content.replace(b"\n", b"\r\n"))

        check = run_cli(self.root, "check")
        self.assertNotEqual(check.returncode, 0, combined(check))
        self.assertIn("CRLF", check.stderr)

    def test_atomic_write_leaves_no_temporary_files(self) -> None:
        write_state(self.root, make_state())
        render = run_cli(self.root, "render")
        self.assertEqual(render.returncode, 0, combined(render))
        temporary_files = list(self.root.rglob("*.tmp"))
        self.assertEqual(temporary_files, [], f"发现残留临时文件：{temporary_files}")

    # ------------------------------------------------------------------
    # 损坏输入
    # ------------------------------------------------------------------

    def test_corrupt_json_returns_nonzero(self) -> None:
        write_state(self.root, '{"schema_version": "1.0",')
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("JSON 解析失败", result.stderr)

    def test_missing_state_file_returns_nonzero(self) -> None:
        result = run_cli(self.root, "validate")
        self.assertNotEqual(result.returncode, 0, combined(result))
        self.assertIn("状态文件不存在", result.stderr)

    # ------------------------------------------------------------------
    # 真实状态文件的生成结果可复现
    # ------------------------------------------------------------------

    def test_repository_render_then_check_passes(self) -> None:
        # 不写真实仓库：在临时目录复制真实 JSON，验证同一渲染结果。
        real_state = (ROOT / "docs" / "state" / "project_state.json").read_text(
            encoding="utf-8"
        )
        copied = copy.deepcopy(json.loads(real_state))
        write_state(self.root, copied)
        materialize_stage_paths(self.root, copied)
        render = run_cli(self.root, "render")
        self.assertEqual(render.returncode, 0, combined(render))
        check = run_cli(self.root, "check")
        self.assertEqual(check.returncode, 0, combined(check))


if __name__ == "__main__":
    unittest.main(verbosity=2)
