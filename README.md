# ResearchFlow

ResearchFlow 3.1 是面向 AI 实验任务的可信多智能体编排、动态调度与独立验证平台。目标是把任务规划、执行控制、证据采集、故障恢复、结果验证和凭证签发整合为一条可审计工程链。

> 当前处于 **T0**：G0 已于 2026-11-10 由用户宣布 `PASS`；`T-WP-01-001`、`T-WP-02-001` 为 `DONE`；P1–P8 伪代码设计件 `ACCEPTED`（P1 2026-11-11；P2–P8 2026-11-12），P9 `BLOCKED`（并发重写来源待裁决），P10 `BLOCKED`（未获开发授权）；G1–G7 仍 `NOT_STARTED`。
> 策划书基线已确认（2026-11-08 用户决议）：内容基线为文档内部 `v4.3.0`，文件名标签 `v4.3.1` 仅作标签；`BLK-002` 已关闭。G0 冻结时的 3 项待裁决已由 G0 文档包关闭，历史记录见 [`docs/state/G0_DECISION_LIST.md`](docs/state/G0_DECISION_LIST.md)。
> 项目定位与边界以 [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) 与 [`docs/memory/project-context.md`](docs/memory/project-context.md) 为准；研发进度以 [`docs/state/project_state.json`](docs/state/project_state.json) 为唯一机器可读事实源。

## 目录结构

| 目录 | 说明 |
|---|---|
| `contracts/` | 5 份冻结 JSON Schema v1.0 + 72 个正反例 |
| `researchflow/` | Pydantic v2 契约模型 + 现有 `POST/GET /api/v1/tasks` 绑定；StateMachine/SQLite 未实现 |
| `tests/` | 测试代码 |
| `scripts/` | 工程辅助脚本 |
| `docs/reference/inbox/` | 后续外部资料入口（当前仅 `.gitkeep`；不存放策划书副本） |
| `docs/reference/` | 来源登记与冲突报告；策划书原件在仓库根目录，禁止复制 |
| `docs/memory/` | 项目记忆索引与子文件 |
| `docs/state/` | 研发状态 JSON 与运行时状态对照 |
| `docs/ADR/` | 架构决策记录：ADR-001–006 `ACCEPTED`，ADR-007 `PROPOSED` |
| `docs/PRD/` | G0 PRD、需求追踪矩阵与 T0 PRD |
| `docs/design/` | G0 冻结的架构、契约/状态、数据/API、T0 计划/门禁设计 |
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

PATH 上的 `python`（3.12）与 `py -3.11`（32 位 3.11.0）均不得用于本项目。项目 `.venv` 已按 3.11.16（64 位）创建，`requirements.lock` 锁定 58 个包；运行测试必须使用 `.venv/Scripts/python.exe` 或上述 uv 绝对路径。`BLK-003`（workspace-write 下的测试临时目录 ACL）仍 `OPEN`；2026-11-11 的 full-access 全量测试通过不能用于关闭该阻塞。

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

当前处于 T0 契约与治理基线，尚未进入运行时实现阶段：

- 已完成：G0 规格冻结（2026-11-10 `PASS`）；WP-01 环境锁定；WP-02 五份契约模型与创建/查询 API；P1–P8 伪代码设计件验收（P2–P8 于 2026-11-12 按 C 指令）。
- 部分完成：P1–P8 设计件已验收，但运行时实现尚未开始；P9 的 6 个 `.py` 为 2026-11-11 并发重写产物，不是原始正文恢复，状态 `BLOCKED`；P10/M19 仅登记现状，状态 `BLOCKED`，未获开发授权。
- 测试：2026-11-11 按用户 E 项授权执行一次受控 full-access 全量 pytest，`140 passed`、exit 0；该结果不关闭 `BLK-003`，也不构成 G1 或运行时能力通过。
- Git：`last_verified_commit` 仍为 `1c9a104`；HEAD 已前移到状态提交，整改未 commit。

当前不能宣称：G1–G7 `PASS`；StateMachine/SQLite/审计已实现；Collector/Gate/Verifier/签名/离线验签已实现；P9/P10 已验收；P2–P8 设计件已验收不等于运行时实现；六份 P9 并发重写文件等同于原始设计。

WP-03 的进入条件尚未满足：P2 未验收、§12-2/§12-6/§12-7/§12-8 未裁决、P9 缺口未获用户处置、`BLK-003` 仍 OPEN。后续阶段需用户明确批准；本仓库不自动 commit，提交前必须确认 Git 身份。根目录 DOCX 未复制、未移动、未改名、未修改。
