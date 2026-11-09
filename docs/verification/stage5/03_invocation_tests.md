# Stage 5 — 无副作用调用验证

> 时间：2026-11-08 11:50–11:53（Asia/Shanghai）
> 方式：先通过 Harness `skill` 工具加载；再按 Skill 主流程做只读或干跑验证。
> 范围：onboarding、spec-driven-development、memory-handoff 三项做执行验证；其余六项只做按需加载。

## 1. 加载验证

九个 Skill 均通过 `skill` 工具按名称加载，返回：

```text
<skill_content name="<name>">
Base directory for this skill: D:\ResearchFlow-project\.agents\skills\<name>
...
</skill_content>
```

加载成功的九个名称：

```text
researchflow-onboarding
researchflow-spec-driven-development
researchflow-prompt-workflow
researchflow-contracts-api
researchflow-python-backend
researchflow-dag-state-machine
researchflow-evidence-security
researchflow-testing-benchmark
researchflow-memory-handoff
```

没有出现名称不匹配、frontmatter 解析错误或“Skill 不存在”。

## 2. T1 — onboarding（只读）

按 Skill 步骤执行：

- 确认会话系统提示含 `Instructions from: AGENTS.md`：是。
- 读取 `docs/memory/Memory.md`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/SESSION_HANDOFF.md`。
- 运行只读 Git 命令。
- 运行 `state_sync.py validate` 与 `check`。

实际结果（收尾更新前）：

| 项 | 值 |
|---|---|
| 当前阶段 | `G0_PREPARATION` |
| 当前里程碑 | `M0_GOVERNANCE_BASELINE` |
| 研发任务 | 0 |
| 门禁 | G0–G7 全部 `NOT_STARTED`，PASS 0/8 |
| 阻塞 | `BLK-001`、`BLK-002` 两个 OPEN |
| `last_verified_commit` | `null` |
| 分支 | `main` |
| commit 数 | 0 |
| 工作区 | 全部文件未跟踪（尚无首次 commit） |
| `validate` | exit 0 |
| `check` | 2 个生成文件逐字节一致，exit 0 |

结论：能指出事实来源；没有把未完成任务或门禁写成完成/通过；没有修改状态文件、记忆或业务文件。

## 3. T2 — spec-driven-development（干跑）

选一条已有书面来源的约束做干跑，不强行编造 FR 编号。

| 字段 | 值 |
|---|---|
| `req_id` | `CAND-001`（非正式 FR；FR-001–FR-020 内容尚未建立） |
| `source` | `AGENTS.md` §3.1–3.2；`docs/memory/environment.md` §2 |
| `requirement` | 项目 Python 脚本与测试必须使用 3.11.16（64 位）绝对路径，不得使用 PATH 的 3.12 或 `py -3.11` 的 32 位 3.11.0 |
| `priority` | P0 |
| `phase` | `WORKSTATION_SETUP` |
| `module` | 工程基线 / 测试环境 |
| `depends_on` | 无 |
| `risks` | PATH 解释器泄漏；CI 未固定路径；`.venv` 未来创建方式不一致 |
| `status` | `APPROVED`（用户已书面指定） |

验收条件：

- **AC-1 正例**：显式绝对路径运行 `-c "import sys, platform; print(sys.version); print(platform.architecture()[0])"`，输出含 `3.11.16` 与 `64bit`。
- **AC-2 负例**：裸 `python --version` 为 3.12.0；项目测试命令中不得使用裸 `python`。
- **AC-3 边界**：`py -3.11` 指向 32 位 3.11.0；必须被项目规则拒绝。

预期证据：`docs/memory/environment.md`、`docs/verification/stage4/00_environment.log`、Stage 5 结构校验日志。

结论：每条需求有来源和可验证条件；没有为了凑 FR 编号编造需求；没有写业务代码或改冻结文件。

## 4. T3 — memory-handoff（干跑）

按 Skill 分类信息，得到收尾时应更新的内容：

| 信息 | 目标文件 | 说明 |
|---|---|---|
| Skills 机制已核实、九个 Skill 已部署 | `docs/memory/environment.md`、`docs/memory/references.md` | 稳定事实，可长期复用 |
| 当前阶段调整为 `WORKSTATION_SETUP` | `docs/state/project_state.json` | 临时进度，只写状态文件 |
| Stage 5 变更与验证 | `docs/CHANGELOG_DEV.md` | 追加，不覆盖历史 |
| 交接摘要 | `docs/SESSION_HANDOFF.md` | 置顶 |
| 无运行时架构变化 | `docs/CHANGELOG_DEV.md` | 不需要 ADR；说明理由 |
| `last_verified_commit` | 保持 `null` | 无实际 commit，不得更新 |

干跑期间运行：

```powershell
& $py scripts/state_sync.py validate   # exit 0
& $py scripts/state_sync.py check      # exit 0，2 个生成文件一致
```

干跑期间没有执行 `render`，没有修改 `project_state.json`，没有改生成文件。实际收尾更新在 `docs/verification/stage5/04_state_sync.log` 记录。

## 5. 其余六个 Skill

`prompt-workflow`、`contracts-api`、`python-backend`、`dag-state-machine`、`evidence-security`、`testing-benchmark`：

- 已通过 `skill` 工具加载。
- 未执行真实业务流程，未修改业务文件。
- 留待对应任务触发时按需执行。

## 6. 总结

| Skill | 已发现 | 已加载 | 已执行验证 | 副作用 |
|---|---|---|---|---|
| onboarding | 是 | 是 | 是（只读） | 无业务文件修改 |
| spec-driven-development | 是 | 是 | 是（干跑） | 无文件修改 |
| memory-handoff | 是 | 是 | 是（干跑 + validate/check） | 无状态/生成文件修改 |
| prompt-workflow | 是 | 是 | 否 | 无 |
| contracts-api | 是 | 是 | 否 | 无 |
| python-backend | 是 | 是 | 否 | 无 |
| dag-state-machine | 是 | 是 | 否 | 无 |
| evidence-security | 是 | 是 | 否 | 无 |
| testing-benchmark | 是 | 是 | 否 | 无 |
