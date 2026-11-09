# Memory.md — ResearchFlow 项目记忆索引

> 本文件只做索引，不复制聊天记录，不承载完整规则。
> 规则优先级：用户当前明确指令 > `AGENTS.md` > 已批准 ADR / 冻结契约 > 本索引指向的记忆文件。
> 读取顺序：`AGENTS.md` → 本文件 → `docs/state/project_state.json` → 与任务相关的记忆子文件 / PRD / ADR / 契约。

## 1. 记忆文件清单

| 文件 | 用途 | 何种任务需要读取 | 最近更新 | 是否已核验 |
|---|---|---|---|---|
| [`project-context.md`](project-context.md) | 项目定位、目标、第一版边界、当前阶段基线 | 任何任务开始前；判断范围与优先级时 | 2026-11-08 | 部分核验：用户指令与策划书 §1.1 / §4.4 / §15.2 已核对；策划书内部 v4.3.0 已由用户 2026-11-08 确认为内容基线 |
| [`architecture-decisions.md`](architecture-decisions.md) | 不可协商架构约束、证据等级、ADR 索引 | 设计 Schema、状态机、Executor、Collector、Verifier、签名或接口时 | 2026-11-08 | 部分核验：14 条约束与用户阶段 4 指令逐条核对；详细契约尚未冻结 |
| [`feedback-and-lessons.md`](feedback-and-lessons.md) | 用户反馈、失败经验、流程教训 | 制定计划、运行测试、写交接或复盘时 | 2026-11-08 | 已核验：来自用户明确指令与本阶段真实操作 |
| [`environment.md`](environment.md) | 已核实 OS、解释器、工具链、DSH 配置摘要 | 运行脚本、测试、安装依赖、排查环境问题时 | 2026-11-08 | 已核验：2026-11-08 本机命令实测；不含密钥 |
| [`references.md`](references.md) | 策划书、官方资料、DSH 文档与引用索引 | 引用来源、核对指标、写 PRD / ADR 时 | 2026-11-08 | 阶段 7 已全文抽取（754 段/80 表）；版本冲突已由用户 2026-11-08 决议关闭 |
| [`../state/runtime_states.md`](../state/runtime_states.md) | 运行时 Task/Node/Report/Certificate 状态与迁移对照 | 开发或评审 StateMachine、Gate、Verifier 前 | 2026-11-08 | 部分核验：名称与迁移表已从策划书附录 F 抽取；G0 契约冻结时需逐条确认 |

## 2. 不放进记忆文件的内容

- 密钥、令牌、凭据、`.credentials.yaml`、私钥、证书私钥。
- 原始聊天记录、Session 内容、模型思维过程。
- 未经确认的推测、计划中的功能、未实测的性能数字。
- 可变的逐任务流水账；这类信息写入 `docs/CHANGELOG_DEV.md` 与 `docs/state/project_state.json`。
- 运行时 Task/Node 状态；这类状态按 `docs/state/runtime_states.md` 与后续冻结契约定义，不写入研发看板。

## 3. 维护规则

1. 只在内容已被用户确认、文档确认或本机实测后更新；未知内容标记“待核实”。
2. 每次更新在表头“最近更新”列同步日期，并在 `docs/CHANGELOG_DEV.md` 追加变更记录。
3. 发现记忆文件与 `AGENTS.md`、ADR 或冻结契约冲突时，以更高优先级文件为准，并立即报告冲突。
4. 本索引本身不定义架构、不改变验收阈值、不构成开发批准。

## 4. 阶段 7 知识文档索引

以下文档是阶段 7 的结构化知识成果，不属于“长期记忆子文件”，但新会话恢复时应按任务读取：

| 文档 | 用途 |
|---|---|
| [`../PROJECT_OVERVIEW.md`](../PROJECT_OVERVIEW.md) | 项目定位、范围、T0/T1/T2、G0–G7、当前状态 |
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | 六层架构、组件边界、证据/验证、密码学、部署边界 |
| [`../GLOSSARY.md`](../GLOSSARY.md) | 术语与易混命名 |
| [`../DEVELOPMENT_WORKFLOW.md`](../DEVELOPMENT_WORKFLOW.md) | 开发顺序、门禁、测试/证据、状态同步 |
| [`../MEMORY_GUIDE.md`](../MEMORY_GUIDE.md) | 记忆/状态/交接的读写规则 |
| [`../SKILL_CATALOG.md`](../SKILL_CATALOG.md) | 九个项目级 Skill 与三态验证 |
| [`../MCP_CATALOG.md`](../MCP_CATALOG.md) | 当前 MCP server/tool、配置与信任边界 |
| [`../SECURITY_POLICY.md`](../SECURITY_POLICY.md) | 安全与信任边界 |
| [`../reference/SOURCE_REGISTER.md`](../reference/SOURCE_REGISTER.md) | 资料来源、版本证据、缺失资料 |
| [`../reference/CONFLICT_REPORT.md`](../reference/CONFLICT_REPORT.md) | 冲突、影响、方案与推荐 |
