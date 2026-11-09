# 阶段 4 验收证据 — ResearchFlow 持久记忆与动态状态系统

> 验收时间：2026-11-08 11:32–11:37（Asia/Shanghai）
> 执行解释器：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`（3.11.16, 64-bit）
> 结论：本阶段交付物已建立并通过真实运行验证；**未 commit**，等待用户批准阶段 5。
> 本文件是验收摘要，不替代原始日志。所有声明均可回溯到 `docs/verification/stage4/` 下的日志。

## 1. 验收清单

| 验收项 | 结果 | 证据 |
|---|---|---|
| 项目 AGENTS 是否实际加载 | 是 | 会话启动系统提示含 `Instructions from: AGENTS.md`；重写后收到 `Updated instructions from: AGENTS.md`；`00_environment.log` 与 `SESSION_HANDOFF.md` |
| Memory 索引是否完整 | 是 | `docs/memory/Memory.md` 索引 6 个记忆文件；5 个子文件均存在 |
| `project_state.json` 是否通过 validate | 是，exit 0 | `01_validate.log` |
| `state_sync.py` 三个子命令是否真实跑通 | 是，validate/render/check 均 exit 0 | `01_validate.log`、`03_render.log`、`04_check.log` |
| 生成文件与 JSON 是否一致 | 是，2 个文件逐字节一致 | `04_check.log`、`07_check_after_restore.log` |
| 手工篡改是否能被发现 | 是，exit 1，含 SHA256 与 diff | `05_check_after_tamper.log` |
| 测试是否全部通过 | 是，23 tests OK，exit 0 | `02_unittest.log` |
| 测试日志路径 | `docs/verification/stage4/` | `00`–`07` 日志 |
| 是否使用项目 Python 3.11.16 | 是，绝对路径，64-bit | 所有日志头部与 `00_environment.log` |
| 是否提前标记 G0–G7 PASS | 否，全部 `NOT_STARTED` | `PROJECT_STATE.md`、`project_state.json` |
| 是否编造研发任务 | 否，`tasks: []` | `project_state.json`、`PROJECT_STATE.md` |
| 是否自动 commit | 否，0 commits，`last_verified_commit=null` | `00_environment.log`、`SESSION_HANDOFF.md` |

## 2. 真实命令与退出码

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

# 1) 校验
& $py scripts\state_sync.py validate
# exit 0
# 日志：docs/verification/stage4/01_validate.log

# 2) 23 项测试
& $py -m unittest discover -s tests -v
# Ran 23 tests in 3.392s
# OK
# exit 0
# 日志：docs/verification/stage4/02_unittest.log

# 3) 渲染
& $py scripts\state_sync.py render
# 生成 docs/PROJECT_STATE.md、docs/IMPLEMENTATION_STATUS.md
# exit 0
# 日志：docs/verification/stage4/03_render.log

# 4) 一致性检查
& $py scripts\state_sync.py check
# 2 个生成文件与 project_state.json 逐字节一致
# exit 0
# 日志：docs/verification/stage4/04_check.log

# 5) 负例：手工篡改后检查
# 向 docs/PROJECT_STATE.md 追加 TAMPER-EVIDENCE-STAGE4
& $py scripts\state_sync.py check
# exit 1
# 日志：docs/verification/stage4/05_check_after_tamper.log

# 6) 恢复
& $py scripts\state_sync.py render
# exit 0
# 日志：docs/verification/stage4/06_render_restore.log

# 7) 恢复后检查
& $py scripts\state_sync.py check
# exit 0
# 日志：docs/verification/stage4/07_check_after_restore.log
```

## 3. 测试覆盖（23 项）

`tests/test_state_sync.py` 通过真实子进程调用 CLI，覆盖：

- 解释器基线为 Python 3.11.16 / 64-bit；
- 合法状态通过；
- 真实仓库状态通过；
- 缺失必填字段失败；
- 非法研发任务状态失败；
- 非法阶段失败；
- 重复 `task_id` 失败；
- 无效 `depends_on` 失败；
- 自依赖失败；
- 循环依赖失败；
- 未知顶层字段失败；
- `PASS` 门禁无证据失败；
- `BLOCKED` 任务无 `blocker` 失败；
- `DONE` 任务缺测试命令 / 证据失败；
- `render` 后 `check` 通过；
- 非空任务明细渲染后 `check` 通过；
- 手工修改生成文件后 `check` 失败；
- 生成文件缺失时 `check` 失败；
- 生成文件 CRLF 时 `check` 失败；
- 原子写入无残留 `.tmp`；
- JSON 损坏返回非零；
- 状态文件缺失返回非零；
- 真实状态 JSON 复制后 render/check 通过。

## 4. 关键文件 SHA256（核验时点）

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| `docs/state/project_state.json` | 3531 | `814093B8C2950E8FA131918ED9F7092B4DBB5737AB6043F3F364F63E48F8E002` |
| `docs/PROJECT_STATE.md` | 2196 | `457C0967EC242746AF9BF04F12C0CEDAD1152C1A6F20B434C677A32F33D9B389` |
| `docs/IMPLEMENTATION_STATUS.md` | 3566 | `F4415B10FADBBF198F6DA5A0C79043B42EAC6CF58E108EBE36587F57FAA4FE07` |
| `scripts/state_sync.py` | 47197 | `7DCA2B98036C93AB7A9831F96CE0EF87916647F51C5EB60B1617B8106942CCB8` |
| `tests/test_state_sync.py` | 15608 | `C6E1E82E5327C3ACDCB7575F856E4545C0D0069DC0E379C80B56156D4617E601` |
| `AGENTS.md` | 10265 | `4EF11BE084795C4447560F744F45C8EE91B3D076A196CA04466E22A0D9FB836A` |
| `docs/memory/Memory.md` | 3085 | `88E59DAB1F96FFA383F580ABD51260B770073C093582B7E8FC38424D2A31212C` |
| `docs/verification/stage4/02_unittest.log` | 3027 | `D8536C9730AAF0444D15C7156082AD5234D758ACFCD7B8BFCE740695C9B5E777` |

> 注意：上述哈希是 2026-11-08 本阶段验收时记录的快照；后续若修改文件，哈希会变化，`check` 只保证生成文件与 JSON 一致，不保证与本文哈希永久一致。

## 5. 状态基线

| 字段 | 值 |
|---|---|
| `schema_version` | `1.0` |
| `project_name` | `ResearchFlow` |
| `current_phase` | `G0_PREPARATION` |
| `current_milestone` | `M0_GOVERNANCE_BASELINE` |
| `tasks` | `[]`（未编造研发任务） |
| `stage_gates.G0`–`G7` | 全部 `NOT_STARTED` |
| `blockers` | `BLK-001` Git 身份未配置；`BLK-002` 策划书基线版本待确认 |
| `last_verified_commit` | `null` |

## 6. 未完成 / 未声明

- 未开发 ResearchFlow 业务代码；`researchflow/` 仍为空。
- 未创建 `.venv`；未安装任何第三方依赖。
- 未建立 `contracts/`、PRD、ADR；G0 规格尚未冻结。
- 未接入 LLM、六个 Agent 或 DeepSeek Harness Adapter。
- 未 commit；Git 身份未配置。
- 未创建全局 `C:\Users\Administrator\.dsh\AGENTS.md`；提案见 `docs/reference/GLOBAL_AGENTS_PROPOSAL.md`。
- 策划书 v4.3.1 是否唯一冻结基线仍待用户确认；未据此宣布 G0 通过。

## 7. 下一步

等待用户批准阶段 5。批准前不进入 T0 开发、不 commit、不扩大范围。
