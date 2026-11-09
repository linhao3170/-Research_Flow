# ResearchFlow 项目文件地图

> 用途：为 `researchflow-onboarding` 提供最小化加载路径。只做导航，不复制项目规则。
> 规则优先级：用户当前指令 > `AGENTS.md` > 已批准 ADR / 冻结契约 > 记忆子文件。

## 1. 根目录

| 路径 | 作用 | 何时读取 |
|---|---|---|
| `AGENTS.md` | 项目主规则、环境约束、架构约束、范围 | 每次任务开始 |
| `README.md` | 项目简介、目录、当前阶段 | 新会话概览 |
| `ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` | 需求与设计来源 | 需要引用具体章节时；不要全文加载 |
| `.agents/skills/` | 项目级 Skill Bundle | 任务匹配 Skill 时按需加载 |
| `contracts/` | 数据契约 | 设计/实现/评审契约时；先核实是否已有文件 |
| `researchflow/` | 业务代码 | 实现/评审后端时；当前可能为空 |
| `tests/` | 测试 | 写/跑测试时 |
| `scripts/` | 工程脚本 | 状态同步、验证时 |
| `docs/` | 文档、记忆、状态、证据 | 按任务选择 |

## 2. 文档与事实源

| 路径 | 事实类型 | 是否权威 | 注意事项 |
|---|---|---|---|
| `docs/memory/Memory.md` | 记忆索引 | 导航 | 先读索引，不一次读全部子文件 |
| `docs/memory/project-context.md` | 项目目标、边界、阶段基线 | 部分核验 | 策划书版本仍待用户确认 |
| `docs/memory/architecture-decisions.md` | 架构约束、ADR 索引 | 部分核验 | 详细契约未冻结 |
| `docs/memory/feedback-and-lessons.md` | 用户反馈、失败教训 | 已核验 | 长期有效，制定计划前读 |
| `docs/memory/environment.md` | 解释器、工具链、DSH 配置 | 已核验 | 不含密钥 |
| `docs/memory/references.md` | 资料索引 | 部分核验 | 外部资料默认不是可信证据 |
| `docs/state/project_state.json` | 研发进度 | **唯一机器可读事实源** | 只改 JSON，再 render |
| `docs/PROJECT_STATE.md` | 生成视图 | 派生 | 禁止手工编辑 |
| `docs/IMPLEMENTATION_STATUS.md` | 生成视图 | 派生 | 禁止手工编辑 |
| `docs/state/runtime_states.md` | 运行时状态对照 | 部分核验 | 不与研发看板混用 |
| `docs/SESSION_HANDOFF.md` | 会话交接 | 事实记录 | 最新记录置顶 |
| `docs/CHANGELOG_DEV.md` | 追加式开发日志 | 历史记录 | 只追加，不覆盖 |
| `docs/verification/` | 真实测试日志与阶段证据 | 证据 | 报告需指向具体日志 |
| `docs/ADR/` | 架构决策 | 决策 | 当前可能为空 |
| `docs/PRD/` | 产品需求 | 需求 | 当前可能为空 |
| `docs/design/` | 设计文档 | 设计 | 当前可能为空 |
| `docs/reference/inbox/` | 外部原始资料 | 参考 | 不自动成为可信证据 |

## 3. 任务到文件

| 任务 | 最小读取集 | 可选深读 |
|---|---|---|
| 恢复上下文 | `AGENTS.md`、`Memory.md`、`project_state.json`、`SESSION_HANDOFF.md` | 生成状态、最近 CHANGELOG |
| 写 PRD / 需求 | 上述 + `project-context.md`、相关策划书章节 | `docs/PRD/`、ADR |
| 设计契约/API | `architecture-decisions.md`、`contracts/`、`runtime_states.md` | 策划书附录 D/E/F |
| 状态机/DAG | `runtime_states.md`、`architecture-decisions.md` | 策划书第 5/6 章、附录 F |
| 证据/安全 | `architecture-decisions.md`、证据契约 | 策划书第 3/5/17 章、附录 D/F |
| 后端实现 | `environment.md`、`contracts/`、相关测试 | 设计文档、ADR |
| 测试/验收 | `project_state.json`、`docs/verification/`、相关验收条件 | 策划书第 4/15 章、附录 G/J |
| 记忆/交接 | `Memory.md`、`project_state.json`、`CHANGELOG_DEV.md`、`SESSION_HANDOFF.md` | 相关子文件 |

## 4. 只读核对命令

```powershell
git branch --show-current
git status --porcelain=v1
git log -5 --oneline
git rev-list --count --all
```

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'
& $py scripts/state_sync.py validate
```

`validate` 只读；`render` 会写生成文件；`check` 只读比较。

## 5. 加载纪律

- 先索引、后子文件；先状态、后细节。
- 不把整份策划书、全部记忆或全部 Skill 全文注入上下文。
- 任何事实都尽量落到“文件 + 字段/行号”或“命令 + 输出”。
- 发现文档冲突时，按优先级报告，不自行合并。
