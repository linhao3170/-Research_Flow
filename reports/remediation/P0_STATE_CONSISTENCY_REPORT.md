# ResearchFlow 3.1 · 状态一致性检查报告（P0_STATE_CONSISTENCY_REPORT）

> 日期：2026-11-11（Asia/Shanghai）
> 事实源：`docs/state/project_state.json`
> 判定：**结构一致性 PASS；阶段验收未完成（P9/P10 BLOCKED，P2–P8 IN_REVIEW）**
> 说明：本报告只证明“状态源与文档/校验器一致”，不证明任何运行时能力已完成。

## 1. 唯一事实源与三套状态语义

| 维度 | 字段 | 状态枚举 | 当前值 |
|---|---|---|---|
| 研发任务 | `tasks` | `BACKLOG/READY/IN_PROGRESS/BLOCKED/IN_REVIEW/DONE/DEFERRED` | 8 个任务；7 DONE，1 IN_REVIEW |
| 伪代码阶段 | `pseudocode_stages` | `NOT_STARTED/IN_PROGRESS/IN_REVIEW/BLOCKED/ACCEPTED/DEFERRED` | 10 个阶段；1 ACCEPTED，7 IN_REVIEW，2 BLOCKED |
| 阶段门禁 | `stage_gates` | `NOT_STARTED/IN_PROGRESS/PASS/FAIL/BLOCKED` | G0 PASS；G1–G7 NOT_STARTED |

- P1–P10 的状态只从 `pseudocode_stages` 读取；没有把 P# 写成 WP-xx 任务或 G# 门禁。
- `ACCEPTED` 只用于 P1；P2–P10 没有任何 `ACCEPTED`。
- `DONE` 只用于研发任务，没有用于伪代码阶段。

## 2. 阶段注册表（P1–P10）

| 阶段 | 状态 | 依据摘要 |
|---|---|---|
| P1 | `ACCEPTED` | 用户 2026-11-11 验收；证据为现有设计件与 STAGE_LOG；OQ-P1-03/05 缺正文 |
| P2 | `IN_REVIEW` | M02 设计件存在；未验收；§12-2/6/7/8 未决 |
| P3 | `IN_REVIEW` | M04/M05 设计件存在；未验收 |
| P4 | `IN_REVIEW` | M06/M07 设计件存在；E3 路径未实现；未验收 |
| P5 | `IN_REVIEW` | M08–M10 设计件存在；L3 未真实重跑；未验收 |
| P6 | `IN_REVIEW` | M11/M12 设计件存在；未验收 |
| P7 | `IN_REVIEW` | M13/M14 设计件存在；STAGE_LOG 为补登；未验收 |
| P8 | `IN_REVIEW` | M17/M18 设计件存在；未验收 |
| P9 | `BLOCKED` | 6 个 `.py` 为并发重写，非原始恢复；未测试；来源待裁决 |
| P10 | `BLOCKED` | M19 仅 5 个 `.py`；无模块文档；未获开发授权 |

## 3. 自动校验结果

### 3.1 `state_sync.py`

命令与结果：

```text
& .venv/Scripts/python.exe scripts/state_sync.py validate
OK: project_state.json 校验通过。阶段=T0，任务=8，伪代码阶段=10（ACCEPTED 1，BLOCKED 2），门禁 PASS=1/8，阻塞=3。
VALIDATE_EXIT=0

& .venv/Scripts/python.exe scripts/state_sync.py render
已生成 docs/PROJECT_STATE.md  sha256=fb321d479d121747993b067ef68b7747e34fc4db6564eba643b019c07f12af98
已生成 docs/IMPLEMENTATION_STATUS.md  sha256=e0ba518f54af47aafc71191cb55b7d13daa2bd7d968d954f7ecda9f707e75fc3
RENDER_EXIT=0

& .venv/Scripts/python.exe scripts/state_sync.py check
[OK] docs/PROJECT_STATE.md  sha256=fb321d479d121747993b067ef68b7747e34fc4db6564eba643b019c07f12af98
[OK] docs/IMPLEMENTATION_STATUS.md  sha256=e0ba518f54af47aafc71191cb55b7d13daa2bd7d968d954f7ecda9f707e75fc3
OK: 2 个生成文件与 project_state.json 逐字节一致。
CHECK_EXIT=0
```

- 生成文件与 JSON 逐字节一致；未手工编辑生成文件。
- `state_sync.py` 校验内容：P1–P10 完整性、唯一性、状态枚举、模块目录存在、交付物/证据路径存在、ACCEPTED 证据、BLOCKED 原因、任务/门禁语义分离。

### 3.2 独立一致性断言

命令（stdout 见 `logs/84_state_consistency_assertions.log`）：

```powershell
# 内联 Python 断言（读取 JSON、INDEX、STAGE_LOG、OQ、handoff、生成文档与 git 状态）
```

结果：

```text
RESULT=PASS checks=52 failures=0
EXIT_CODE=0
```

覆盖：

- P1–P10 恰好各一次；仅 P1 `ACCEPTED`；P9/P10 `BLOCKED`；P2–P8 `IN_REVIEW`。
- `last_verified_commit` 未变；任务 8；门禁键 G0–G7；无 P# 任务 ID。
- P9 11 文件 / 7,122 行（含复核横幅 +4 行；六个 `.py` 行数未变）；P10 5 文件 / 2,138 行。
- INDEX P9 7,122 / P10 2,138；STAGE_LOG P1 NEEDS_CONFIRMATION、P9 复核修正、P10 条目；OQ-P1-03/05 为 NEEDS_CONFIRMATION，未保留 DECIDED。
- SESSION_HANDOFF、PROJECT_STATE、IMPLEMENTATION_STATUS 均含 P9/P10 `BLOCKED` 或阶段段。
- README/DEVELOPMENT_WORKFLOW/ARCHITECTURE/PROJECT_OVERVIEW/G0_DECISION_LIST 的现状说明已更新。
- 所有 `M*/MODULE.md` 的 `> 前置` 行不含“已验收”。
- 未修改 `contracts/`、`docs/design/`、`docs/G0/`、`docs/PRD/`、`docs/ADR/`；无已跟踪文件删除；commit 数仍为 7。

### 3.3 文档漂移检查

```text
docs/state/project_state.json:848: WARNING: last_verified_commit 与当前 HEAD 不一致
STATE-FREE enforced=5/9；ERROR=0；WARNING=1
EXIT_CODE=0
```

WARNING 为预期：HEAD `309083e` 是未提交整改前的状态提交，`last_verified_commit` 仍为 `1c9a104`。未擅自推进。

日志：`logs/81_final_docs_drift.log`

### 3.4 Git 完整性

```text
git diff --check        exit 0（无空白错误；CRLF 警告已通过规范化为 LF 消除）
git diff --diff-filter=D --name-only   空（无删除）
git rev-list --count --all             7（无新 commit）
```

## 4. 关键文件哈希

| 文件 | SHA256 |
|---|---|
| `docs/state/project_state.json` | `8151c92bc38e0551978923678a3c19f9b00898b90af06d458e0e05f06e78a629` |
| `docs/PROJECT_STATE.md` | `fb321d479d121747993b067ef68b7747e34fc4db6564eba643b019c07f12af98` |
| `docs/IMPLEMENTATION_STATUS.md` | `e0ba518f54af47aafc71191cb55b7d13daa2bd7d968d954f7ecda9f707e75fc3` |
| `logs/84_state_consistency_assertions.log` | `9b0f447d516078a1ab9d006c9d441d564f9218a774408212d284befb7ad07731` |

## 5. 仍未一致/未完成的事项

1. **P9**：状态源 `BLOCKED` 与 INDEX/STAGE_LOG 的“待验收/存在（并发重写，未测试）”口径一致，但 P9 没有 `ACCEPTED` 证据；六个 `.py` 不是原始正文。
2. **P10**：状态源 `BLOCKED`，M19 仅 5 个 `.py`，无模块文档；未获开发授权。
3. **P2–P8**：全部 `IN_REVIEW`；状态源没有把它们写成 `ACCEPTED`/`DONE`。
4. **BLK-003**：仍 `OPEN`；`state_sync` 的阻塞统计为 OPEN 1。
5. **`last_verified_commit`**：仍 `1c9a104`；与 HEAD 不一致，属未提交整改的预期 WARNING。
6. **P9/P10 行数**：7,122 与 2,138 是当前文件行数；不是验收阈值，也不证明完成。

## 6. 结论

- **状态结构一致性：PASS**（52/52 断言；validate/render/check exit 0）。
- **阶段验收：未完成**（P2–P8 IN_REVIEW，P9/P10 BLOCKED；P1 仅设计件验收）。
- **门禁：未改变**（G0 PASS；G1–G7 NOT_STARTED）。
- **不得**把本报告解读为 P9/P10 已恢复、WP-03 可启动或 P0 整体完成。

## 7. 2026-11-12 停后复核

在会话恢复后（2026-11-12 09:37）重新检查，未发现 2026-11-11 23:15 之后由其他进程产生的新项目写入（本轮复核报告编辑除外）；P9 六个并发重写文件的 SHA256 与登记值全部一致。

```text
state_sync validate  exit 0
state_sync check     exit 0（2 文件逐字节一致）
check_docs_drift     ERROR=0；WARNING=1（last_verified_commit 与 HEAD 不一致，预期）
git diff --check     exit 0
commits              7；HEAD 309083e；last_verified_commit 1c9a104（未变）
缓存/临时目录        文件数与字节数未变；未删除
```

日志：`reports/remediation/logs/100_20261112_recheck.log`

复核结论不变：**结构一致性 PASS；项目最终验收仍为 BLOCKED（等待 D/P9/P10 决策）**。