# project-context.md — 项目目标、边界与当前基线

> 更新时间：2026-11-08（阶段 7；阶段 8 复核）
> 核验状态：部分核验。项目定位、第一版范围与 T0 出口已与策划书**内部 v4.3.0**（文件名标签 v4.3.1；`BLK-002` 已关闭）的 §1.1、§4.4、§15.2 对照；用户已于 2026-11-08 确认内部 v4.3.0 为内容基线，v4.3.1 仅为文件名标签。
> 本文件不是需求合同；需求以后续评审通过的 PRD / 契约 / ADR 为准。

## 1. 项目定位

ResearchFlow 3.1 是面向 AI 实验任务的可信多智能体编排、动态调度与独立验证平台。它不是通用聊天助手，也不是单纯的实验追踪器，而是把以下环节整合成一条可审计工程链：

1. 任务规划；
2. 执行控制；
3. 证据采集；
4. 故障恢复；
5. 结果验证；
6. 完成凭证签发。

来源：策划书内部 v4.3.0（文件名标签 v4.3.1，`BLK-002`）§1.1（一句话定位）。

核心判定立场：Agent 的自然语言声明只提供“待核查主张”，不构成成功证据。任务是否完成由 StateMachine 根据 Gate 与独立 Verifier 的结构化结果决定，不由 Agent 自述决定。

## 2. 要解决的核心问题

- 执行链越长，状态越复杂：未执行、执行一半、复用旧产物、格式正确但语义错误、多个 Agent 互相引用声明形成回音室。
- 聊天轨迹有价值，但轨迹本身不足以证明任务完成。
- 因此需要：证据分级（E0–E3）、单写者证据记录、独立验证、可发现篡改的哈希链、离线可复核的证据包。

## 3. 第一版范围（已确认）

| 维度 | 约束 |
|---|---|
| 运行环境 | Windows 11 单机；16GB 内存；CPU-only |
| 并发 | 上限 2；必须实测后才能宣称达成 |
| 模板 | 内置表格 ML 模板 |
| 代码执行 | 不执行任意用户代码 |
| 网络 | 不默认开放网络 |
| 容器 | 不强制 Docker |
| 本地模型 | 不部署本地大模型 |
| 交付顺序 | 先 T0 最小可信闭环，再 T1，再 T2 |
| T0 边界 | 不接入 LLM；不开发六个 Agent；不接入 DeepSeek Harness Adapter |

来源：用户阶段 4 指令；策划书内部 v4.3.0（文件名标签 v4.3.1，`BLK-002`）§4.4、§15.2。

“不得擅自扩大范围。”任何范围变更必须先获得用户明确批准并记录 ADR。

## 4. 阶段与门禁基线（当前）

- 当前阶段：`WORKSTATION_SETUP`（阶段 7 完成资料接手与知识整理；阶段 8 验收通过：25 PASS / 2 NOT VERIFIED / 0 FAIL；G0 规格冻结尚未通过）。
- 当前里程碑：`M0_GOVERNANCE_BASELINE`（项目记忆、状态同步、协作规则、Skills、资料基线、工作站验收）。
- 阶段 4 建立可审计的治理与状态系统；阶段 5 建立九个项目级 Skills；阶段 6 接入 Context7 MCP；阶段 7 完成策划书全文抽取、来源登记、冲突报告与知识文档；阶段 8 完成工作站 26 项验收、策略恢复补验与验收，未开发 ResearchFlow 业务代码。
- 研发看板任务：`T-SKILLS-001` 已 `DONE`（阶段 5 验收通过）；`T-MCP-001` 已 `DONE`；`T-DOCS-001` 已 `DONE`（阶段 8 按用户决议关闭版本冲突）；`T-STAGE8-001`（阶段 8 综合验收）已 `DONE`（用户 2026-11-08 验收通过）。这不表示 T0 已开始或已完成。
- G0–G7：全部 `NOT_STARTED`；不得提前标记 `PASS`。
- `last_verified_commit`：`null`；在真实 commit 经测试验证前保持为空。
- `BLK-002`：**已关闭**（`RESOLVED`）；内容基线为文档内部 v4.3.0，文件名 v4.3.1 仅为标签。
- `BLK-003`：**OPEN / MEDIUM**；DSH 权限诊断结论 `NOT_THIS_CLASS`（`FIXED=0`，未改任何 ACL），机制为“沙箱未向运行期新建子目录传播授权”，非仓库 ACL 损坏、非项目缺陷。workspace-write 下 23 项测试仍 43 errors，13b 维持 NOT VERIFIED；代码正确性测试可在单独批准的 full-access 会话运行，但结果不得用于第 5/6/23 项或安全项。`tmpavet2qv9` 为空目录，阶段 9 开始时只删除该目录。
- 阶段 6 备份 `cordis.patch.yml.bak-20261108-stage6`：保留，至少到阶段 8 验收结束。

G0–G7 的名称与通过条件（摘自策划书内部 v4.3.0 §15.3 质量门禁表，作为门禁索引）：

| 门禁 | 名称 | 通过条件摘要 |
|---|---|---|
| G0 | 规格冻结 | 数据模型、状态机、API、错误码、证据等级和规则版本确定 |
| G1 | 纵向闭环 | 无模型、离线、单任务从提交到凭证全链跑通 |
| G2 | 证据可信 | E0 不推动状态；E2 由 Collector 观察；权限拒绝通过 |
| G3 | L3 独立重执行 | 新目录、独立进程、真实重跑；假复现负例拒绝 |
| G4 | 动态调度/恢复 | 资源变化改变调度；失败能执行恢复计划 |
| G5 | 实验数据可信 | 预注册、冻结哈希、四方案、原始 JSON 和统计脚本齐全 |
| G6 | 外部复核 | 真包通过、五类负例拒绝；独立环境可验证 |
| G7 | Harness 适配 | 固定版本插件、工具、事件映射和状态回传契约通过 |

当前门禁状态是“未开始”，不是“通过”。任何 PASS 必须有真实证据路径，且由 `scripts/state_sync.py` 校验。

## 5. 交付主线（T0 视角）

T0 的验收出口：断网 / 无模型条件下完成一条实验；导出证据包；第三方离线验签通过。

T0 必须覆盖的能力（策划书内部 v4.3.0 §15.2 T0/T1/T2 交付阶段表摘要）：

- Task / Node Schema；
- DAG；
- StateMachine；
- 内置模板；
- Executor；
- Collector；
- E0–E2；
- Gate；
- L1/L2/L3 单模板重跑；
- Ed25519；
- 离线验签；
- 最小工作台。

以上是 T0 的目标范围，不是当前已完成内容。

## 6. 明确不做（第一版）

- 不做通用科研助手；首期只覆盖可机器验证的表格型 ML 实验。
- 不做 GPU 集群、分布式执行、多机高可用。
- 不执行 Agent 或用户生成的任意不可信代码，只运行审核过的内置模板。
- 不宣称跨硬件/跨版本普遍复现；首期目标是同软件环境下独立重执行。
- 不宣称哈希链绝对不可篡改；只称可发现篡改，并说明密钥与锚定边界。
- 不把知识检索、Agent 自评或多 Agent 投票当作实验完成证据。

来源：策划书内部 v4.3.0（文件名标签 v4.3.1，`BLK-002`）§4.4。

## 7. 当前仓库基线

- 分支：`main`。
- commit：尚无（`git rev-list --count --all` 为 0）。
- 已有内容：目录骨架、`.gitignore`、占位文档、策划书 DOCX。
- 尚无：ResearchFlow 业务代码、`contracts/` 契约、`.venv`、依赖锁文件。
- 阶段 4 新增：项目 `AGENTS.md`、记忆索引与子文件、研发状态 JSON、状态同步脚本、测试与真实日志。
- 阶段 5 新增：`.agents/skills/` 下九个 ResearchFlow Skill、`docs/SKILL_CATALOG.md`、`scripts/validate_skills.py` 与 `docs/verification/stage5/` 证据。
- 阶段 6 新增：`docs/verification/stage6/`（MCP 能力、Context7 接入、写入校验与真实调用）；`cordis.patch.yml` 已写入 context7（1,462 字节）。
- 阶段 7 新增：`docs/PROJECT_OVERVIEW.md`、`ARCHITECTURE.md`、`GLOSSARY.md`、`DEVELOPMENT_WORKFLOW.md`、`MEMORY_GUIDE.md`、`MCP_CATALOG.md`、`SECURITY_POLICY.md`；`docs/reference/SOURCE_REGISTER.md`、`CONFLICT_REPORT.md`；`docs/verification/stage7/` 只读抽取与版本证据。
- 尚未开发：ResearchFlow 业务代码、`contracts/` 契约、运行时数据库/StateMachine、`.venv`、依赖锁文件。

## 8. 待核实

- 策划书基线版本：**已确认**（2026-11-08）。内容基线 = 文档内部 v4.3.0；文件名 v4.3.1 仅为标签；`BLK-002` 已关闭。版本已定不等于 G0 已通过；G0 仍有 FR-010 边界、开发顺序、P1/T2 错位 3 项待裁决（见 `docs/state/G0_DECISION_LIST.md`）。
- 飞书 AI 开发说明：项目内未落地；如作为优先级 2 来源，需用户提供导出件。
- 赛事官方章程的完整要求；策划书 §1.3 记录“官方动态页本次读取未返回完整章程”，项目内无通知原图/章程文件；不得自行推断评分权重、页数、匿名要求等。
- 产品 PRD、详细 Schema、API 契约、错误码表尚未建立，属于 G0 范围。
- 16GB 内存与“并发 2”是设计约束；并发能力尚未实测，不得宣称已达成。
- DOCX 无可信页码；来源引用使用章节 + `P####`/`TABLE ##` 锚点。

## 9. 相关文件

- [`AGENTS.md`](../../AGENTS.md)
- [`docs/state/project_state.json`](../state/project_state.json)
- [`docs/state/runtime_states.md`](../state/runtime_states.md)
- [`docs/SKILL_CATALOG.md`](../SKILL_CATALOG.md)
- [`docs/PROJECT_OVERVIEW.md`](../PROJECT_OVERVIEW.md)
- [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)
- [`docs/DEVELOPMENT_WORKFLOW.md`](../DEVELOPMENT_WORKFLOW.md)
- [`docs/reference/SOURCE_REGISTER.md`](../reference/SOURCE_REGISTER.md)
- [`docs/reference/CONFLICT_REPORT.md`](../reference/CONFLICT_REPORT.md)
- [`docs/memory/architecture-decisions.md`](architecture-decisions.md)
- [`docs/memory/references.md`](references.md)
