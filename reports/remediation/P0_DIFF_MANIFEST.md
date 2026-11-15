# P0 整改 Diff 清单（P0_DIFF_MANIFEST）

> 日期：2026-11-11（Asia/Shanghai）
> HEAD：`309083e715cb59a1f0c181d95df44e1946ffbaa5`（7 commits，未新增）
> 工作区：`D:\ResearchFlow-project`
> 状态：未 commit、未 `git add`、未清理临时文件。

## 1. 补丁文件

| 文件 | 内容 | SHA256 | 大小 |
|---|---|---|---:|
| `reports/remediation/P0_DIFF.patch` | 28 个已跟踪文件的完整 `git diff` + 新增 `tests/test_api_idempotency.py` 的新文件 diff | `fe523060ecc9bedbbda1d1daa24dfb1a705ef8dc0e4f1714937d9b1177f5f1bb` | 144,322 B |
| `reports/remediation/P0_UNTRACKED_CHANGES.patch` | 6 份未跟踪 `MODULE.md` 相对 22:53:44 备份的 diff；M15/M16 含并发重写，见警告 | `bda0b81366f850579b5228b3da3423039c6c574ba08940dc3b3777f1c0ccf97e` | 40,155 B |
| `reports/remediation/P0_DIFF_STAT.txt` | `git diff --stat` | `ea86549975516f4dd40e7397f35fe1149a65ed1262ca6a4f7ee60c070ad0b2ca` | 1,726 B |

## 2. 已跟踪文件 Diff 摘要

```text
28 files changed, 1370 insertions(+), 155 deletions(-)
```

涉及：

- `researchflow/api/app.py`
- `tests/test_state_sync.py`
- `scripts/state_sync.py`
- `docs/state/project_state.json`
- `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`
- `design/pseudocode/INDEX.md`、`STAGE_LOG.md`、`OPEN_QUESTIONS.md`
- `design/pseudocode/00_BASELINE/PHASE_RULES.md`
- `design/pseudocode/M01/M03/M04/M05/M06/M07/M08/M09/M10/M11 MODULE.md`
- `README.md`、`AGENTS.md`
- `docs/DEVELOPMENT_WORKFLOW.md`、`docs/SESSION_HANDOFF.md`
- `docs/PROJECT_OVERVIEW.md`、`docs/ARCHITECTURE.md`、`docs/state/G0_DECISION_LIST.md`
- `docs/CHANGELOG_DEV.md`

`P0_DIFF.patch` 末尾额外包含：

```text
diff --git a/tests/test_api_idempotency.py b/tests/test_api_idempotency.py
new file mode 100644
```

## 3. 未跟踪文件

### 3.1 本轮编辑的未跟踪模块文档

- `design/pseudocode/M13_scheduler/MODULE.md`
- `design/pseudocode/M14_recovery/MODULE.md`
- `design/pseudocode/M17_agents/MODULE.md`
- `design/pseudocode/M18_knowledge/MODULE.md`
- `design/pseudocode/M15_dcspa/MODULE.md`
- `design/pseudocode/M16_vas/MODULE.md`

这些文件没有 Git 基线；`P0_UNTRACKED_CHANGES.patch` 以 22:53:44 备份为旧侧。

**M15/M16 警告：** 22:53:54–55 有并发进程重写这两份文档及 6 个 `.py`；备份是重写前版本，因此该 patch 同时包含“并发重写”和“本轮复核横幅/状态修正”，不能当作纯整改 diff。当前文件哈希与逐文件时间见 `P0_OPEN_ISSUES.md` §3。

### 3.2 未由本轮修改的未跟踪目录

- `design/pseudocode/M19_api/`（5 个 `.py`；仅登记，未改）
- `design/pseudocode/M13_scheduler/`、`M14_recovery/`、`M15_dcspa/`、`M16_vas/`、`M17_agents/`、`M18_knowledge/` 中的 `.py`/`NEGATIVE_TESTS.md` 等（除上述 MODULE 外，本轮未逐文件改）

### 3.3 本轮新增报告/证据

- `reports/remediation/P0_CHANGELOG.md`
- `reports/remediation/P0_TEST_REPORT.md`
- `reports/remediation/P0_FINAL_ACCEPTANCE.md`
- `reports/remediation/P0_OPEN_ISSUES.md`
- `reports/remediation/P0_STATE_CONSISTENCY_REPORT.md`
- `reports/remediation/P0_DIFF.patch`、`P0_UNTRACKED_CHANGES.patch`、`P0_DIFF_STAT.txt`
- `reports/remediation/logs/` 下的测试、状态、P9/P10 清单日志
- `reports/remediation/backup_before/` 下的 6 份旧 MODULE 备份

这些是报告/证据，不进入 `git diff`；未 `git add`。

## 4. 未执行

- 未 `git add`、未 `git commit`、未 `git reset`、未 `git clean`。
- 未修改 `last_verified_commit`（仍 `1c9a104`）。
- 未删除/清理 `.pytest_cache`、`__pycache__`、`tmp/unittest-temp` 或其他临时目录。
- 未修改 `contracts/`、`docs/design/`、`docs/G0/`、`docs/PRD/`、`docs/ADR/`。

## 5. 复核方式

```powershell
git diff --stat
git diff -- researchflow/api/app.py tests/test_state_sync.py scripts/state_sync.py docs/state/project_state.json
# 或直接查看：
Get-Content reports/remediation/P0_DIFF.patch
Get-Content reports/remediation/P0_UNTRACKED_CHANGES.patch
```

> `P0_DIFF.patch` 是当前工作区相对 HEAD 的完整已跟踪 diff；未跟踪文件的 diff 见 `P0_UNTRACKED_CHANGES.patch` 与上述未跟踪清单。