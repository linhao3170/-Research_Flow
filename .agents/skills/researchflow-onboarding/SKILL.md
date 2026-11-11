---
name: researchflow-onboarding
description: Use when starting a new ResearchFlow session, resuming work, or when project context, current phase, architecture constraints, or blockers must be reloaded.
---

# ResearchFlow Onboarding

## 1. 适用条件 / When to use

在以下任一情况使用本 Skill：

- 新会话开始，或用户要求“恢复项目上下文”“继续之前的工作”。
- 需要确认当前阶段、里程碑、门禁、阻塞项、最近验证提交。
- 需要判断某项工作是否已获批准、是否已完成、是否属于当前范围。
- 需要把任务交给新的 Agent 或新的会话，先建立共同事实基线。

不用于：修改状态、写业务代码、代替正式需求评审。需要改文件时使用对应开发或 `researchflow-memory-handoff` Skill。

## 2. 输入与前置检查

按顺序确认：

1. 当前工作目录是 `D:\ResearchFlow-project`，或能由当前目录向上找到项目根。
2. 会话系统提示已包含 `Instructions from: AGENTS.md`。若未包含，停止并报告，不得凭记忆执行。
3. 以下文件存在且可读：
   - `AGENTS.md`
   - `docs/memory/Memory.md`
   - `docs/state/project_state.json`
   - `docs/PROJECT_STATE.md`
   - `docs/IMPLEMENTATION_STATUS.md`
   - `docs/SESSION_HANDOFF.md`
4. 当前任务至少有一个明确问题；不要以“先了解项目”为由无差别读取全部文档。

若项目 AGENTS 未加载，先报告缺失事实；用户明确确认可以继续后，才可按文件内容做只读分析，并在输出中标注“AGENTS 未由 Harness 加载”。

## 3. 执行步骤

读取顺序见 AGENTS.md §0。

1. **确认规则来源**：记录 AGENTS 是否已加载；若加载，记录其版本或最近修改时间。
2. **读机器状态**：读取 `docs/state/project_state.json`，提取 `current_phase`、`current_milestone`、`tasks`、`stage_gates`、`blockers`、`last_verified_commit`、`updated_at`。
3. **读记忆索引**：只读 `docs/memory/Memory.md`，按任务选择子文件，不一次加载全部记忆。
4. **读生成视图**：读取 `docs/PROJECT_STATE.md` 与 `docs/IMPLEMENTATION_STATUS.md`，只用于快速概览；发现与 JSON 不一致时以 JSON 为准，并报告 `check` 可能失败。
5. **读交接记录**：读取 `docs/SESSION_HANDOFF.md` 最新一条记录，提取上次完成、未完成、已知风险和待确认事项。
6. **核对 Git 事实**：运行只读命令：
   - `git branch --show-current`
   - `git status --porcelain=v1`
   - `git log -5 --oneline`
   - `git rev-list --count --all`
   若无 commit，明确写“0 commit”，不要把空历史当成异常。
7. **按任务加载**：根据当前任务查 `references/project-file-map.md` 的“任务到文件”表，只读取必要文档；需要详细协议时再读 `docs/PRD/`、`docs/design/`、`docs/ADR/`、`contracts/` 中已存在的文件。
8. **做一致性检查**：确认阶段与任务状态不矛盾；门禁 `PASS` 是否有证据；`DONE` 任务是否有测试命令与证据；`last_verified_commit` 是否有真实 commit 支撑。
9. **输出上下文摘要**，不修改任何文件；若用户只要求“读一下”，到此停止。

## 4. 不可违反的约束

- 不得把聊天记录、模型推测、记忆中的旧摘要当成当前项目事实；事实必须能指向文件、字段或命令输出。
- 不得无差别读取全部大文件；按任务最小化加载。
- 不得修改 `project_state.json`、生成文件、记忆或任何业务文件。
- 不得把未完成任务标为 DONE，不得把 `NOT_STARTED` 门禁说成通过。
- 不得把研发看板状态与运行时 Task/Node 状态混用。
- 不得读取或输出 `.credentials.yaml`、私钥、令牌、Session 标识等敏感内容。
- 不得为了“让上下文完整”而自动 commit、安装依赖或创建 `.venv`。

## 5. 输出要求

输出一份中文上下文摘要，至少包含：

1. **事实来源**：本次实际读取的文件与命令。
2. **当前阶段与里程碑**：来自 `project_state.json` 的字段值。
3. **门禁与阻塞**：G0–G7 状态；OPEN 阻塞及其影响。
4. **最近验证**：`last_verified_commit`、最近测试证据路径；没有则写“无”。
5. **工作区**：分支、未提交变更、commit 数；是否与交接记录一致。
6. **本次任务相关约束**：从 AGENTS、ADR、冻结契约中摘出的适用条目。
7. **待确认事项**：明确标“待核实”，不得用推测补齐。
8. **下一步建议**：最多 3 项，每项说明依据和停止条件。

建议格式：

```text
## 项目上下文摘要
- 事实来源：
- 当前阶段 / 里程碑：
- 门禁：
- 阻塞：
- 最近验证：
- 工作区：
- 适用约束：
- 待确认：
- 下一步：
```

## 6. 验收标准

- 每个关键结论都能指出文件路径与字段/行号，或命令及输出。
- 没有把未完成任务或未通过门禁写成完成/通过。
- 没有修改任何文件；`git status --porcelain=v1` 在操作前后一致。
- 明确区分“已核实事实”“待核实”“未确认”。
- 输出不超过任务所需；没有用全文摘抄代替判断。
- 若发现状态不一致，明确指出冲突文件和字段，而不是自行选择一个“看起来合理”的版本。

## 7. 相关文件 / 参考资料

- `AGENTS.md`
- `docs/memory/Memory.md` 及其子文件
- `docs/state/project_state.json`
- `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`
- `docs/state/runtime_states.md`
- `docs/SESSION_HANDOFF.md`
- `references/project-file-map.md`

## 8. 失败与暂停条件

出现以下任一情况时停止，不继续推断：

- 项目 AGENTS 未被 Harness 加载，且用户未确认可按文件继续。
- `project_state.json` 缺失、无法解析，或 `validate` 失败。
- `project_state.json` 与生成 Markdown 明显不一致，且无法判断哪份是当前事实。
- 交接记录与 Git 状态冲突（例如声称有 commit 但 `git rev-list` 为 0）。
- 任务需要读取敏感凭据、私钥或未授权的项目外文件。
- 当前任务范围与 AGENTS 或已批准阶段冲突，需要用户先裁决。

暂停时报告：缺失/冲突的事实、已读取的文件、需要用户确认的具体问题。
