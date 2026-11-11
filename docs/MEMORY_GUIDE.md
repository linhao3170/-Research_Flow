# MEMORY_GUIDE — ResearchFlow 记忆与交接指南

> 状态：阶段 7 资料接手成果
> 适用：所有新会话、任务恢复、阶段收尾、状态同步、交接
> 依据：`AGENTS.md` §1、§2、§6、§7；[`memory/Memory.md`](memory/Memory.md)；`researchflow-memory-handoff` Skill
> 原则：只记录可核对事实；未知标“待核实”；不把聊天记录、推测或计划当成项目事实。

当前状态以 docs/state/project_state.json 为准。

## 1. 记忆系统的分层

| 层 | 文件/目录 | 回答什么问题 | 谁维护 |
|---|---|---|---|
| 规则层 | [`AGENTS.md`](../AGENTS.md) | 项目规则、架构约束、环境限制、范围 | 用户批准后更新 |
| 记忆索引 | [`memory/Memory.md`](memory/Memory.md) | 有哪些记忆文件、何时读 | 任务收尾时更新 |
| 长期记忆 | [`memory/project-context.md`](memory/project-context.md)、[`architecture-decisions.md`](memory/architecture-decisions.md)、[`environment.md`](memory/environment.md)、[`references.md`](memory/references.md)、[`feedback-and-lessons.md`](memory/feedback-and-lessons.md) | 稳定项目事实、架构约束、环境、来源、教训 | 只在事实确认后更新 |
| 研发状态 | [`state/project_state.json`](state/project_state.json) | 当前阶段、任务、门禁、阻塞、最近验证提交 | 唯一机器可读事实源 |
| 生成视图 | [`PROJECT_STATE.md`](PROJECT_STATE.md)、[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) | 状态的可读视图 | 只由 `state_sync.py render` 生成，禁止手改 |
| 运行时状态 | [`state/runtime_states.md`](state/runtime_states.md) | Task/Node/Report/Certificate 状态与迁移 | 与研发看板严格分离 |
| 开发日志 | [`CHANGELOG_DEV.md`](CHANGELOG_DEV.md) | 本次变更、原因、验证、影响 | 追加式，不覆盖历史 |
| 会话交接 | [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md) | 上次完成/未完成、风险、下一步、待确认 | 最新置顶 |
| 阶段证据 | [`verification/stage4-7/`](verification/) | 真实命令、日志、测试结果 | 只追加，保留原始日志 |
| 知识文档 | [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md)、[`ARCHITECTURE.md`](ARCHITECTURE.md)、[`GLOSSARY.md`](GLOSSARY.md)、[`DEVELOPMENT_WORKFLOW.md`](DEVELOPMENT_WORKFLOW.md)、[`SECURITY_POLICY.md`](SECURITY_POLICY.md)、[`SKILL_CATALOG.md`](SKILL_CATALOG.md)、[`MCP_CATALOG.md`](MCP_CATALOG.md) | 结构化知识、来源、建议/决策区分 | 阶段 7 建立；按需更新 |

## 2. 新会话读取顺序

读取顺序见 AGENTS.md §0。

## 3. 什么信息放哪里

| 信息 | 放哪里 | 不放哪里 |
|---|---|---|
| 项目目标、范围、设计原因、历史阶段 | `memory/project-context.md` | `CHANGELOG` 之外的临时笔记 |
| 稳定架构约束、ADR 索引 | `memory/architecture-decisions.md`、`docs/ADR/` | 聊天记录、`PROJECT_STATE.md` |
| 本机环境、版本、配置摘要 | `memory/environment.md` | 密钥、令牌、凭据、Session 标识 |
| 资料来源、引用、版本冲突 | `memory/references.md`、`reference/SOURCE_REGISTER.md`、`reference/CONFLICT_REPORT.md` | 正文摘要冒充原文 |
| 用户反馈、失败教训 | `memory/feedback-and-lessons.md` | 未确认的推测 |
| 当前任务/门禁/阻塞 | `state/project_state.json` | 记忆文件（长期事实） |
| 本次变更、真实测试 | `CHANGELOG_DEV.md`、`verification/stageN/` | 只写在聊天里 |
| 会话交接 | `SESSION_HANDOFF.md` | 长期记忆（临时状态） |
| 运行时 Task/Node 状态 | `state/runtime_states.md` + 未来运行时 DB | `project_state.json` |

## 4. 写入顺序（收尾时）

```text
1. 确认已完成/未完成/改动文件/真实测试
2. 更新 docs/state/project_state.json
3. & $py scripts/state_sync.py validate
4. & $py scripts/state_sync.py render
5. & $py scripts/state_sync.py check
6. 追加 docs/CHANGELOG_DEV.md
7. 更新 docs/SESSION_HANDOFF.md（最新置顶）
8. 只将稳定事实写入 docs/memory/*
9. 输出交接摘要，停止；不自动 commit
```

来源：`AGENTS.md` §7；`researchflow-memory-handoff` Skill §3。

### 4.1 状态同步命令

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'
& $py scripts/state_sync.py validate
& $py scripts/state_sync.py render
& $py scripts/state_sync.py check
```

要求：三步均 exit 0；`check` 通过后才可说 Markdown 状态报告已同步。生成文件禁止手工编辑。

## 5. 状态词汇纪律

### 5.1 研发看板（只用于 `project_state.json`）

`BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED`。

### 5.2 运行时（按策划书附录 F）

- Task：`CREATED`、`PLANNING`、`READY`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED`。
- Node：`PLANNED`、`READY`、`RUNNING`、`VERIFYING`、`VERIFIED`、`FAILED`、`BLOCKED`、`DIAGNOSING`、`RECOVERING`。

禁止：把 `DONE` 当 `COMPLETED`；把运行时 `VERIFYING` 写进研发看板；用研发看板 `BLOCKED` 替代运行时 `BLOCKED`；为了“统一”合并/改名/删减任一状态集合。

来源：`AGENTS.md` §6；[`state/runtime_states.md`](state/runtime_states.md)。

## 6. 记忆卫生

### 6.1 必须做

- 只写已确认事实；每条关键结论能指向文件、字段、命令输出或证据路径。
- 更新时间戳；写明核验状态（已核验/部分核验/待核实）。
- 冲突时先报告，不自行选择一个“看起来合理”的版本。
- 外部资料默认不是可信证据；引用写 URL/访问日期/版本。
- 测试结果写命令、解释器、退出码、日志路径、运行时间。
- 交接写“完成/未完成/风险/下一步/待确认”，最新置顶。

### 6.2 禁止做

- 写入密钥、令牌、`.credentials.yaml`、私钥、Session 标识、个人信息。
- 写入原始聊天记录或模型思维过程。
- 把计划功能写成已完成；把 `NOT_STARTED` 门禁写成 PASS。
- 用记忆文件替代正式 ADR/契约/PRD。
- 为“让状态好看”编造任务或提前更新 `last_verified_commit`。
- 改写 `CHANGELOG_DEV.md` 历史；只追加。

来源：`AGENTS.md` §1、§6、§8；`researchflow-memory-handoff` Skill §4。

## 7. 交接模板

```markdown
### YYYY-MM-DD · 阶段 X · <主题>

- 本次完成：
- 未完成：
- 修改文件：
- 实际测试命令与结果：
  - 解释器：
  - 命令 / 退出码 / 日志：
- 当前分支与 commit：
- 未解决/风险：
- 下一步（最多 3 项）：
- 待用户确认：
- 相关证据目录：
```

要求：

- 不写“应该通过”“大概完成”；
- 未运行测试就写“未测”；
- 没有 commit 就写“提交数为零”；
- 不把下一步写成已批准。

参考：`researchflow-memory-handoff/references/handoff-template.md`。

## 8. 阶段 7 的记忆变更

阶段 7 新增/更新：

- 新增 `docs/PROJECT_OVERVIEW.md`、`ARCHITECTURE.md`、`GLOSSARY.md`、`DEVELOPMENT_WORKFLOW.md`、`MEMORY_GUIDE.md`、`MCP_CATALOG.md`、`SECURITY_POLICY.md`。
- 更新 `docs/SKILL_CATALOG.md`（阶段 7 复核；`T-SKILLS-001` 转 `DONE`）。
- 新增 `docs/reference/SOURCE_REGISTER.md`、`CONFLICT_REPORT.md`。
- 更新 `docs/memory/references.md`、`project-context.md`、`architecture-decisions.md`，修正版本引用。
- 更新 `docs/state/project_state.json`：`T-SKILLS-001` → `DONE`；`T-MCP-001` 保持 `DONE`；`BLK-002` 保持 `OPEN`；G0–G7 不变。
- 追加 `docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`。

来源：阶段 7 指令与真实执行；详见 [`verification/stage7/STAGE7_REPORT.md`](verification/stage7/STAGE7_REPORT.md)。

## 9. 恢复上下文的最小步骤

如果新会话只能读三个文件：

1. `AGENTS.md`（规则与边界）
2. `docs/state/project_state.json`（当前阶段/任务/门禁/阻塞）
3. `docs/SESSION_HANDOFF.md` 最新一条（上次做到哪、下一步）

然后按任务读 [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) → [`ARCHITECTURE.md`](ARCHITECTURE.md) → 对应领域文档。不要一上来读全部文档。

## 10. 相关文件

- [`AGENTS.md`](../AGENTS.md)
- [`memory/Memory.md`](memory/Memory.md)
- [`state/project_state.json`](state/project_state.json)
- [`state/runtime_states.md`](state/runtime_states.md)
- [`CHANGELOG_DEV.md`](CHANGELOG_DEV.md)
- [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md)
- [`reference/SOURCE_REGISTER.md`](reference/SOURCE_REGISTER.md)
- [`reference/CONFLICT_REPORT.md`](reference/CONFLICT_REPORT.md)
