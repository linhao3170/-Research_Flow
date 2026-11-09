---
name: researchflow-memory-handoff
description: Use when finishing a substantial task or session, updating project memory, synchronizing development status, recording decisions, or preparing a session handoff.
---

# ResearchFlow Memory and Handoff

## 1. 适用条件 / When to use

在以下情况使用：

- 完成一个较为完整的任务或会话，需要固化事实。
- 需要更新 `docs/memory/`、`project_state.json`、`CHANGELOG_DEV.md`、`SESSION_HANDOFF.md`。
- 需要记录新技术决策（ADR）或说明“无架构变化”。
- 需要为新会话准备可核对的交接。
- 需要判断某信息应写入长期记忆、状态文件还是临时交接。

不用于：自动 commit、删除历史记录、把未完成工作标为 DONE。

## 2. 输入与前置检查

1. 本任务实际完成了什么、未完成什么、改动了哪些文件，已有命令/日志证据。
2. 已确认哪些信息稳定且具有长期复用价值，哪些只是临时状态。
3. 已确认当前分支、commit 数、工作区变更；`last_verified_commit` 是否有真实 commit 支撑。
4. 已确认 Python 基线绝对路径，用于运行 `state_sync.py`。
5. 已确认是否需要 ADR；若只是治理/文档变更，也要在 CHANGELOG 写“无架构变化”及理由。
6. 已确认不读取或写入密钥、凭据、Session 标识。

若测试未真实运行或没有实际 commit，不得更新 `last_verified_commit`。

## 3. 执行步骤

1. **分类信息**：
   - 稳定项目事实 → 对应 `docs/memory/` 子文件。
   - 临时进度/门禁/阻塞 → `docs/state/project_state.json`。
   - 技术决策 → `docs/ADR/`（若已建立）或先提案。
   - 本次变更与验证 → `docs/CHANGELOG_DEV.md`。
   - 会话交接 → `docs/SESSION_HANDOFF.md`。
2. **更新记忆**：只写已确认事实；未知标“待核实”；同步“最近更新”日期。
3. **更新状态 JSON**：修改 `current_phase`、任务、门禁、阻塞、`last_verified_commit` 等字段；不编造任务，不提前 PASS。
4. **运行状态同步**（使用项目 Python 绝对路径）：

   ```powershell
   $py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'
   & $py scripts/state_sync.py validate
   & $py scripts/state_sync.py render
   & $py scripts/state_sync.py check
   ```

   三步都必须 exit 0；`render` 成功后才能说 Markdown 状态报告已同步。
5. **追加 CHANGELOG**：在文件末尾追加，不覆盖历史；写日期、阶段、变更、原因、验证、影响、相关文件。
6. **更新交接**：最新记录置顶；写完成内容、文件变更、真实测试、分支/commit、问题、下一步、待确认事项。
7. **核对一致性**：JSON 与生成 Markdown 一致；交接中的 commit/测试与命令输出一致；未完成项没有标 DONE。
8. **报告并停止**：不自动 commit；不删除旧记录；等待用户决定是否提交。

交接模板见 `references/handoff-template.md`。

## 4. 不可违反的约束

- 稳定事实才写长期记忆；临时状态不污染记忆文件。
- 新技术决策必须建立 ADR，不能只留在聊天里。
- 更新 `project_state.json` 后必须运行 `validate`、`render`、`check`。
- 只有 `render` 成功后才可称 Markdown 状态报告同步完成。
- `CHANGELOG_DEV.md` 只追加，不覆盖历史。
- 只有真实测试通过且存在实际 commit 时，才能更新 `last_verified_commit`。
- 不自动 commit；不自动删除旧记录；不把未完成工作标为 DONE。
- 不把研发看板状态与运行时状态混写。
- 不把推测、模型输出、未核验外部资料写成项目事实。
- 不记录密钥、令牌、凭据或 Session 标识。

## 5. 输出要求

至少交付：

1. **记忆更新清单**：更新了哪些文件、为什么、哪些标“待核实”。
2. **状态同步结果**：三条命令的退出码、生成文件、`check` 结果。
3. **CHANGELOG 记录**：本次追加的条目摘要。
4. **交接记录**：完成/未完成、文件变更、测试、分支/commit、问题、下一步、待确认。
5. **未解决问题**：阻塞、风险、需要用户决定的事项。
6. **commit 状态**：明确“未 commit”或真实 commit hash；不得含糊。

## 6. 验收标准

- `project_state.json` 通过 `validate`，生成文件通过 `check`。
- JSON 与 `PROJECT_STATE.md`、`IMPLEMENTATION_STATUS.md` 一致。
- 交接内容可由文件和命令证据核对。
- `last_verified_commit` 只在真实测试 + 实际 commit 后更新。
- 未完成任务没有被标为 DONE；门禁没有被提前标 PASS。
- CHANGELOG 历史未被覆盖。
- 没有秘密、凭据或 Session 标识写入文档。

## 7. 相关文件 / 参考资料

- `AGENTS.md`
- `docs/memory/Memory.md`
- `docs/state/project_state.json`
- `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`
- `docs/CHANGELOG_DEV.md`
- `docs/SESSION_HANDOFF.md`
- `scripts/state_sync.py`
- `references/handoff-template.md`

## 8. 失败与暂停条件

- `validate`/`render`/`check` 任一失败。
- JSON 与生成文件不一致，且原因未定位。
- 测试未真实运行，或没有实际 commit 却要求更新 `last_verified_commit`。
- 需要删除/覆盖历史记录。
- 需要提交但 Git 身份未配置或用户未批准。
- 发现秘密/凭据/敏感信息将被写入文档。
- 交接内容与 Git 状态、测试日志冲突。

暂停时报告：失败命令与退出码、冲突文件、需要用户确认的最小问题；不自行“修一下状态”掩盖失败。
