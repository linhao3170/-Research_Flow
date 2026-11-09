# ResearchFlow Skill 目录

> 更新时间：2026-11-08（阶段 8 复核；原阶段 5 建立时间为 12:00）
> DSH：DeepSeek Harness 桌面版 0.2.2-rc.1（`D:\deepseek_harness1`）
> 项目根：`D:\ResearchFlow-project`
> 项目级 Skill 根：`.agents/skills/`
> 本文件只登记事实与验证状态，不复制 Skill 正文。

## 1. 三态定义

| 状态 | 含义 | 本阶段验证方式 |
|---|---|---|
| **已发现** | Skill 出现在当前会话的 model-facing catalog 中，Harness 已解析 frontmatter 并接受 name/description | 观察会话内 `available skill catalog changed` 替换消息；确认九个名称出现 |
| **已加载** | 通过 Harness `skill` 工具按名称加载，返回 `<skill_content name="...">`、resource base 与完整正文 | 逐个调用 `skill(name=...)`，检查返回名称与 resource base |
| **已执行验证** | 在受控、无业务副作用场景中按 Skill 主流程执行，并观察其要求的输出/检查 | 仅对 onboarding、spec-driven、memory-handoff 做只读/干跑测试 |

> “已发现”“已加载”“已执行验证”是三个不同状态，不得合并表述。加载成功不等于流程已执行。

## 2. 发现机制证据

| 项 | 事实 | 证据 |
|---|---|---|
| 实际运行版本 | 桌面版 `0.2.2-rc.1`；内置 runtime 依赖同为 `0.2.2-rc.1` | `D:\deepseek_harness1\resources\app.asar` 内 `package.json`、`dsh/package.json` |
| Provider | `@deepseek-ai/dsh-skill-filesystem@0.2.2-rc.1` | app.asar 内 `dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/package.json` |
| 扫描根 | `<projectRoot>/.dsh/skills`（rank 100）、`<projectRoot>/.agents/skills`（rank 200）、custom、`~/.dsh/skills`、`~/.agents/skills` | 同包 `lib/index.js` 第 160–190 行；`README.md` 第 48–54 行 |
| 项目根判定 | 最近的含 `.git` 的祖先目录；本项目为 `D:\ResearchFlow-project` | 同包 `README.md` 第 56 行；本项目 `.git` 存在 |
| Registry | `@deepseek-ai/dsh-skill@0.2.2-rc.1`，`ctx.skills.registerProvider/list/get` | app.asar 内同包 `README.md` 第 12、28 行 |
| Consumer | `@deepseek-ai/dsh-tool-skill@0.2.2-rc.1`，提供 catalog 与 `skill` 加载工具 | app.asar 内同包 `README.md` 第 12、28–30 行 |
| 当前会话结果 | 目录创建后 catalog 发生三次替换；最终包含全部九个 `researchflow-*` | 会话内 catalog replacement 消息（2026-11-08 11:49–11:52） |

结论：当前版本支持项目级 `.agents/skills`，无需改配置，也无需改用 `.dsh/skills` 或全局目录。

未使用的位置：

- 未在 `.dsh/skills/` 创建任何 ResearchFlow Skill。
- 未在 `C:\Users\Administrator\.dsh\skills\` 或 `C:\Users\Administrator\.agents\skills\` 创建同名 Skill。
- 未修改 DSH Profile、preset 或全局配置。

## 3. Skill 清单

| Skill 名称 | 用途 | 触发条件 | 依赖资料 | 已发现 | 已加载 | 已执行验证 | 最后验证 |
|---|---|---|---|---|---|---|---|
| `researchflow-onboarding` | 新会话/恢复时重建项目事实基线 | 新会话、恢复工作、需确认阶段/门禁/阻塞 | `AGENTS.md`、`Memory.md`、`project_state.json`、`SESSION_HANDOFF.md`、`references/project-file-map.md` | 是 | 是 | 是（只读上下文摘要） | 2026-11-08 12:00 |
| `researchflow-spec-driven-development` | 需求→PRD/用户故事/验收/实施计划 | 写 PRD、映射 FR、变更冻结规格 | `project-context.md`、`architecture-decisions.md`、策划书、`references/requirement-traceability.md` | 是 | 是 | 是（CAND-001 干跑） | 2026-11-08 12:00 |
| `researchflow-prompt-workflow` | 结构化提示词与阶段编排 | 给 DSH/子 Agent 写实施、审查、调试、调研提示词 | `references/prompt-templates.md` | 是 | 是 | 否（仅按需加载） | 2026-11-08 12:00 |
| `researchflow-contracts-api` | 契约、Schema、API、错误码、幂等 | 设计/评审/版本化契约与 API | `architecture-decisions.md`、`runtime_states.md`、策划书附录 D/E/F、`references/contract-index.md` | 是 | 是 | 否（仅按需加载） | 2026-11-08 12:00 |
| `researchflow-python-backend` | Python/FastAPI/Pydantic/SQLite 后端 | 实现或评审后端模块 | `environment.md`、`architecture-decisions.md`、`references/python-quality-rules.md` | 是 | 是 | 否（仅按需加载） | 2026-11-08 12:00 |
| `researchflow-dag-state-machine` | DAG、状态机、调度、恢复 | 改状态迁移、DAG 校验、失效/恢复 | `runtime_states.md`、策划书第 5/6 章、附录 F、`references/state-transition-reference.md` | 是 | 是 | 否（仅按需加载） | 2026-11-08 12:00 |
| `researchflow-evidence-security` | E0–E3、Collector、Gate、Verifier、签名 | 证据、信任边界、L3、凭证、权限 | `architecture-decisions.md`、策划书第 3/5/17 章、附录 D/F、`references/evidence-trust-boundaries.md` | 是 | 是 | 否（仅按需加载） | 2026-11-08 12:00 |
| `researchflow-testing-benchmark` | 测试分层、G0–G7 验收、RF-Bench 统计 | 写测试、跑验收、分析基准 | `project_state.json`、`docs/verification/`、策划书第 4/15 章、附录 G/J、`references/acceptance-matrix.md` | 是 | 是 | 否（仅按需加载） | 2026-11-08 12:00 |
| `researchflow-memory-handoff` | 记忆、状态同步、CHANGELOG、交接 | 任务/会话结束、记录决策、更新状态 | `Memory.md`、`project_state.json`、`state_sync.py`、`references/handoff-template.md` | 是 | 是 | 是（干跑 + validate/check） | 2026-11-08 12:00 |

## 4. 验证结果

### 4.1 已发现

- 创建 `researchflow-onboarding` 后，catalog replacement 出现该名称。
- 再创建四个后，catalog replacement 包含 5 个 `researchflow-*`。
- 创建最后四个后，catalog replacement 包含全部 9 个 `researchflow-*`。
- 目录变更触发 catalog 刷新，无需重启 Harness；与 Consumer 文档“entry changes append a replacement catalog”一致。

### 4.2 已加载

逐个调用 `skill` 工具，九个均返回：

- `<skill_content name="<name>">`，名称与目录名一致。
- `Base directory for this skill: D:\ResearchFlow-project\.agents\skills\<name>`。
- 完整正文，无 frontmatter 解析错误、无“未找到 Skill”。

### 4.3 已执行验证

| Skill | 场景 | 结果 | 副作用 |
|---|---|---|---|
| `researchflow-onboarding` | 只读读取 `Memory.md`、`project_state.json`、生成状态、交接、Git 事实 | 测试时正确报告阶段 `G0_PREPARATION`、0 任务、G0–G7 全 `NOT_STARTED`、2 个 OPEN 阻塞、0 commit | 无业务文件修改 |
| `researchflow-spec-driven-development` | 对真实约束 CAND-001（Python 3.11.16 基线）做干跑追踪 | 生成来源、优先级、依赖、正/负/边界验收条件；未强行编造 FR 编号 | 仅输出，无文件修改 |
| `researchflow-memory-handoff` | 干跑状态同步与交接清单；运行只读 `validate` / `check` | `validate` exit 0；`check` 2 个生成文件一致；识别需更新的状态/日志/交接 | 测试时未改状态文件；实际收尾更新另记 |

其余六个 Skill：加载通过；未执行真实业务流程，未修改任何业务文件。后续按任务触发时再执行。

### 4.4 结构与负例验证

| 检查 | 命令 / 场景 | 结果 | 日志 |
|---|---|---|---|
| 九个 Skill 结构 | `& $py scripts/validate_skills.py` | 9 PASS，exit 0 | `docs/verification/stage5/01_structure.log` |
| 缺失 SKILL.md 负例 | 临时副本删除 `researchflow-onboarding/SKILL.md` 后运行 validator | exit 1，指出缺失文件 | `docs/verification/stage5/06_structure_negative.log` |
| 23 项回归测试 | `& $py -m unittest discover -s tests -v` | 23 tests，OK，exit 0，3.342s | `docs/verification/stage5/05_validation.log` |
| 状态同步 | `validate` / `render` / `check` | 均 exit 0；2 个生成文件一致 | `docs/verification/stage5/04_state_sync.log` |
| 秘密扫描 | 7 类模式扫描 20 个 Stage 5 文件 | 0 命中 | `docs/verification/stage5/02_secret_scan.log` |
| 全仓库秘密扫描 | 7 类模式扫描仓库文本文件 | 0 命中 | `docs/verification/stage5/07_repo_secret_scan.log` |

## 5. 计划中的 Skill

| Skill 名称 | 状态 | 说明 |
|---|---|---|
| `researchflow-harness-adapter` | **计划在 T2 创建** | 当前未创建目录、未注册、未启用、未出现在 catalog。G7 前不得提前实现或宣称可用。 |

## 6. 目录与文件

```text
.agents/skills/
├── researchflow-onboarding/
│   ├── SKILL.md
│   └── references/project-file-map.md
├── researchflow-spec-driven-development/
│   ├── SKILL.md
│   └── references/requirement-traceability.md
├── researchflow-prompt-workflow/
│   ├── SKILL.md
│   └── references/prompt-templates.md
├── researchflow-contracts-api/
│   ├── SKILL.md
│   └── references/contract-index.md
├── researchflow-python-backend/
│   ├── SKILL.md
│   └── references/python-quality-rules.md
├── researchflow-dag-state-machine/
│   ├── SKILL.md
│   └── references/state-transition-reference.md
├── researchflow-evidence-security/
│   ├── SKILL.md
│   └── references/evidence-trust-boundaries.md
├── researchflow-testing-benchmark/
│   ├── SKILL.md
│   └── references/acceptance-matrix.md
└── researchflow-memory-handoff/
    ├── SKILL.md
    └── references/handoff-template.md
```

## 7. 维护规则

1. 新增/改名/删除 Skill 后，观察下一次 catalog replacement；不假设“文件已写=模型已发现”。
2. 只改正文或 references 时，catalog 摘要不必变化；下次 `skill` 加载会重读正文。
3. 不在 `.dsh/skills`、全局目录或第二个项目目录复制同名 Skill。
4. 九个 Skill 的全文不写入 `AGENTS.md`，也不在每轮注入；只依赖 Harness 按需加载。
5. 更新本目录时同步“最后验证”时间；未实际加载/执行的，不得标“是”。

## 8. 阶段 7 复核记录

> 阶段 7 的用户指令：`T-SKILLS-001` 在状态同步中由 `IN_REVIEW` 转 `DONE`（阶段 5 已验收通过）；`T-MCP-001` 保持 `DONE`；不顺手改 G0–G7。

| 项 | 结果 | 证据 |
|---|---|---|
| `T-SKILLS-001` | **DONE**（阶段 5 验收通过；阶段 7 状态同步） | `docs/state/project_state.json` |
| 九个项目级 Skill | 文件未改动；catalog 仍为九个 `researchflow-*` | `.agents/skills/`；当前会话 catalog |
| 阶段 7 实际加载 | `researchflow-onboarding`、`researchflow-memory-handoff`、`office-docx` | 当前会话 `skill` 工具返回 |
| `office-docx` 归属 | Harness 全局 Skill，**不是**本项目 Skill；未复制到 `.agents/skills/` | 其 base directory 为 runtime office-skills |
| 新增项目 Skill | 无 | 目录未新增 |
| `researchflow-harness-adapter` | 仍为**计划在 T2 创建**；未创建、未注册、未启用 | §5；G7 仍 `NOT_STARTED` |
| 未使用位置 | 未在 `.dsh/skills`、`~/.dsh/skills`、`~/.agents/skills` 创建同名 Skill | 目录检查 |

阶段 7 的使用方式：

- `researchflow-onboarding`：建立阶段 7 的事实基线（阶段、任务、门禁、阻塞、Git 状态）。
- `researchflow-memory-handoff`：收尾时更新状态、CHANGELOG、交接与记忆。
- `office-docx`：只读读取 DOCX 的指引；实际抽取使用项目 Python 3.11.16 + 标准库脚本，未用 `python-docx` 写文件、未修改原件。

> 说明：加载成功不等于流程已完整执行；阶段 7 只对上述三个 Skill 做了实际使用，其余六个未在阶段 7 执行真实业务流程。

## 9. 阶段 8 复核记录

| 项 | 结果 | 证据 |
|---|---|---|
| catalog 中的项目级 Skill | 9 个 `researchflow-*`；与目录、SKILL.md 数量一致 | `docs/verification/stage8/14_skills_catalog.log`、`17_skill_catalog_check.log` |
| 阶段 8 实际加载 | 6/9：onboarding、memory-handoff、testing-benchmark、evidence-security、contracts-api、dag-state-machine | 当前会话 `skill` 工具返回 |
| 阶段 8 未加载 | 3/9：prompt-workflow、python-backend、spec-driven-development | 当前会话 catalog；未调用 |
| 新增无副作用调用测试 | evidence-security、contracts-api、dag-state-machine：加载前后项目 167 个文件内容聚合 SHA256 一致 | `docs/verification/stage8/16_skill_no_side_effect.log` |
| 新增项目 Skill | 无 | `.agents/skills/` 未新增目录 |
| 每轮注入全文 | 未发生；catalog 只有名称/description，正文仅在 `skill` 调用时返回 | 当前会话系统提示与 `skill` 返回 |
| `researchflow-harness-adapter` | 仍为计划在 T2 创建；未创建、未注册、未启用 | 本文件 §5 |

> 阶段 8 的“无副作用调用测试”只证明加载 Skill 不会写业务文件，不等于执行业务流程；表中“已执行验证”列仍按阶段 5 的实际执行记录保留。

## 10. 阶段 7 后的维护提示

1. 阶段 7 的文档整理不改变九个 Skill 的职责；新增知识文档不自动变成 Skill。
2. 若后续把 `ARCHITECTURE.md`、`SECURITY_POLICY.md` 等纳入某个 Skill 的 references，需单独评审，避免重复维护。
3. G0 冻结后如新增契约/测试 Skill，先提交方案，不直接创建。
4. 任何“已加载/已执行”标记必须有当前会话或日志证据；不得凭历史记忆补写。

