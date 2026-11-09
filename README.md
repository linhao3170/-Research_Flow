# ResearchFlow

ResearchFlow 3.1 是面向 AI 实验任务的可信多智能体编排、动态调度与独立验证平台。目标是把任务规划、执行控制、证据采集、故障恢复、结果验证和凭证签发整合为一条可审计工程链。

> 当前处于 **WORKSTATION_SETUP**：已建立项目规则、记忆、研发状态基线、九个项目级 Skills、Context7 MCP 接入（匿名额度），并在阶段 7 完成策划书全文抽取、来源登记、冲突报告与知识文档。尚未开发 ResearchFlow 业务代码，G0–G7 均为 `NOT_STARTED`。
> 策划书基线已确认（2026-11-08 用户决议）：内容基线为文档内部 `v4.3.0`，文件名标签 `v4.3.1` 仅作标签；`BLK-002` 已关闭。G0 仍有 3 项待裁决，见 [`docs/state/G0_DECISION_LIST.md`](docs/state/G0_DECISION_LIST.md)。
> 项目定位与边界以 [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) 与 [`docs/memory/project-context.md`](docs/memory/project-context.md) 为准；研发进度以 [`docs/state/project_state.json`](docs/state/project_state.json) 为唯一机器可读事实源。

## 目录结构

| 目录 | 说明 |
|---|---|
| `contracts/` | 对外数据契约 / JSON Schema（尚未建立） |
| `researchflow/` | 未来 Python 应用代码包（尚未开发） |
| `tests/` | 测试代码 |
| `scripts/` | 工程辅助脚本 |
| `docs/reference/inbox/` | 后续外部资料入口（当前仅 `.gitkeep`；不存放策划书副本） |
| `docs/reference/` | 来源登记与冲突报告；策划书原件在仓库根目录，禁止复制 |
| `docs/memory/` | 项目记忆索引与子文件 |
| `docs/state/` | 研发状态 JSON 与运行时状态对照 |
| `docs/ADR/` | 架构决策记录（当前为空） |
| `docs/PRD/` | 产品需求文档（尚未建立） |
| `docs/design/` | 设计文档（尚未建立） |
| `docs/verification/` | 真实验证日志与阶段证据 |
| `.agents/skills/` | 项目级 Agent Skills（9 个 ResearchFlow Skill Bundle） |

## 规则入口

- [项目规则 AGENTS.md](AGENTS.md)：行为规范、任务工作流、环境约束、架构约束与第一版范围。
- [记忆索引](docs/memory/Memory.md)：先读索引，再按任务加载子文件。
- [项目状态 JSON](docs/state/project_state.json)：研发看板状态唯一事实源。
- [生成的项目状态](docs/PROJECT_STATE.md)
- [生成的实现状态](docs/IMPLEMENTATION_STATUS.md)
- [运行时状态对照](docs/state/runtime_states.md)：Task/Node/Report/Certificate 状态，禁止与研发看板混用。
- [开发日志](docs/CHANGELOG_DEV.md)
- [会话交接](docs/SESSION_HANDOFF.md)
- [Skill 目录与三态验证](docs/SKILL_CATALOG.md)：九个项目级 Skill 的用途、发现、加载与执行状态。
- [项目总览](docs/PROJECT_OVERVIEW.md)：定位、范围、T0/T1/T2、G0–G7、当前状态。
- [架构基线](docs/ARCHITECTURE.md)：六层架构、组件边界、证据/验证、密码学、部署边界。
- [开发工作流](docs/DEVELOPMENT_WORKFLOW.md)：开发顺序、门禁、测试/证据、状态同步。
- [安全与信任边界](docs/SECURITY_POLICY.md)：威胁模型、权限、密钥、网络/数据边界。
- [术语表](docs/GLOSSARY.md)：EG/TLV/DC/SPA/VAS、L1–L6 与 L1–L3 等易混命名。
- [MCP 目录](docs/MCP_CATALOG.md)：当前 context7 server/tool、配置、限制与信任边界。
- [资料来源登记](docs/reference/SOURCE_REGISTER.md)：唯一权威原件、版本证据、缺失资料。
- [资料冲突报告](docs/reference/CONFLICT_REPORT.md)：v4.3.1/v4.3.0 冲突与待裁决项。
- [阶段 7 资料接手报告](docs/verification/stage7/STAGE7_REPORT.md)：抽取、阅读完整性、限制与验收清单。
- [阶段 6 MCP 能力与接入结果](docs/verification/stage6/08_apply_result.md)：MCP Client 能力、Context7 探测、已执行的配置变更、字节校验与真实工具调用。

## 环境

项目 Python 基线是 **3.11.16（64 位）**，绝对路径：

```text
C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe
```

PATH 上的 `python`（3.12）与 `py -3.11`（32 位 3.11.0）均不得用于本项目。当前未创建 `.venv`、未安装第三方依赖；状态同步脚本与测试只使用标准库。

详细环境核验见 [`docs/memory/environment.md`](docs/memory/environment.md)。

## 状态同步

```powershell
& 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe' scripts\state_sync.py validate
& 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe' scripts\state_sync.py render
& 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe' scripts\state_sync.py check
```

`docs/PROJECT_STATE.md` 与 `docs/IMPLEMENTATION_STATUS.md` 由 JSON 自动生成，禁止手工编辑。

Skill 结构校验：

```powershell
& 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe' scripts\validate_skills.py
```

## 当前阶段

阶段 7：ResearchFlow 项目资料接手。已完成策划书全文只读抽取（754 段落 / 80 表格 / 0 媒体）、版本证据核对、来源登记、冲突报告与知识文档；**未复制/移动/修改根目录 DOCX**。阶段 6 的 Context7 接入保持可用（匿名额度，未配置 API Key），备份保留。未 commit、未建 `.venv`、未装依赖、未开发业务代码。

当前关键未决项：G0 的 3 项裁决（FR-010 的 T0 边界、§15.5 与附录 J 的顺序、FR-015/016/017 的 P1 与 T2 错位）；版本项已决。`BLK-003`（workspace-write 下测试临时目录 ACL）仍 `OPEN`。

后续阶段需用户明确批准；本仓库不自动 commit，提交前必须确认 Git 身份。
