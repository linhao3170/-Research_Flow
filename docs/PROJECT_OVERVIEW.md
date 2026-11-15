# PROJECT_OVERVIEW — ResearchFlow 项目总览

> 状态：阶段 7 资料接手成果，等待用户验收
> 基线：策划书**内部 v4.3.0**（文件名标签 v4.3.1；`BLK-002` 已关闭，2026-11-08 用户决议）
> 证据锚点：`P####` 对应 [`docs/verification/stage7/02_docx_body.txt`](verification/stage7/02_docx_body.txt)；`TABLE ##` 对应 [`05_docx_tables.txt`](verification/stage7/05_docx_tables.txt)
> 页码说明：DOCX 无可信页码（无 TOC/缓存分页；Word COM 不可用）；引用使用章节号 + `P####` + `TABLE ##`，可在上述文件中逐行核验。
> 标注约定：`[策划书]` = 策划书明确要求；`[飞书]` = 飞书资料（当前未落地）；`[Harness]` = Harness 官方能力；`[建议]` = 工程建议；`[待确认]` = 需用户裁决；`[现状]` = 本机/仓库已核实事实
> 本文件不是需求合同，不替代 G0 冻结后的 PRD/契约/ADR。

## 1. 一句话定位

`[策划书]` ResearchFlow 3.1 是面向 AI 实验任务的**可信多智能体编排、动态调度与独立验证平台**。它不是通用聊天助手，也不是单纯的实验追踪器，而是把任务规划、执行控制、证据采集、故障恢复、结果验证和凭证签发整合成一条可审计工程链。

来源：§1.1 / P0026–P0027。

## 2. 要解决的问题

`[策划书]` 执行链越长，系统状态越复杂：某一步可能未执行、执行一半、复用旧产物、输出格式正确但语义错误，或多个 Agent 互相引用彼此声明形成“回音室”。聊天轨迹有价值，但轨迹本身不足以证明任务完成。

来源：§2.1 / P0045；§3.2 / TABLE 14。

平台的核心判定立场：

> Agent 的自然语言声明只提供“待核查主张”，不构成成功证据。任务是否完成由 StateMachine 根据 Gate 与独立 Verifier 的结构化结果决定，不由 Agent 自述决定。

来源：§1.1 / P0027；§3.1 / P0058；§5.1 / TABLE 20。

## 3. 三条核心技术主线

| 主线 | 机制组合 | 回答的问题 | 验证方式 |
|---|---|---|---|
| 可信完成判定 | EG + TLV + Completion Certificate | Agent 声称完成是否真实？ | 证据覆盖、独立重执行、签名凭证与第三方复核 |
| 确定性感知恢复 | DC + SPA + Recovery | 失败后哪些节点必须重跑，哪些可合法跳过？ | 限定条件 DC、PRR、SPA 审计链 |
| 风险/资源感知调度 | Scheduler + Governor + VAS | 任务如何运行、资源如何调节、有限预算先验证哪里？ | 调度日志、资源轨迹、同预算检出效率 |

来源：§1.4 / TABLE 08；摘要 / P0018。

## 4. 四类“面”与六层架构（摘要）

`[策划书]` 平台采用“**Agent 决策面 + 确定性控制面 + 受控执行面 + 独立证据/验证面**”的架构。

| 面 | 主要组件 | 关键边界 |
|---|---|---|
| Agent 决策面 | 六个逻辑角色：Planner / Data / Experiment / Analysis / Recovery / Verification | 只提交结构化请求；不写状态、证据、报告、凭证或私钥 |
| 确定性控制面 | API、DAG、Scheduler、StateMachine、Recovery、Governor、VAS、Gate | 状态单入口；不执行实验、不持私钥 |
| 受控执行面 | Tool Registry、内置模板 Executor、Workspace、SplitService、资源限制 | 只执行审核过的模板；不裁决成功 |
| 独立证据/验证面 | Collector、Evidence Store、Verifier、Certificate、KB、Bench | 按进程/权限分离写入；E2 由 Collector 观测，E3 由 Verifier 产生 |

六层架构（L1–L6）：

| 层 | 名称 | 职责 | 边界 |
|---|---|---|---|
| L1 | 交互层 | 任务输入、DAG、证据中心、报告、基准看板 | 不直接修改状态/证据 |
| L2 | 接入层 | REST、Harness Adapter、认证、幂等、事件标准化 | Harness 轨迹默认 E1，不自动等于 E2 |
| L3 | 编排控制层 | Planner Router、DAG、Scheduler、StateMachine、Recovery、Governor、VAS、Gate | 不执行实验、不持私钥 |
| L4 | Agent 决策层 | 六个逻辑角色 | 只提交结构化请求，不自由聊天 |
| L5 | 执行层 | Tool Registry、Executor、Workspace、SplitService、资源限制 | 不裁决成功 |
| L6 | 证据/验证/知识层 | Collector、Evidence Store、Verifier、Certificate、KB、Bench | 按进程/权限分离写入 |

来源：§5.2 / TABLE 21；摘要 / P0017。

> **命名警告**：架构层 `L1–L6` 与验证等级 `L1/L2/L3` 使用了相同的字母前缀，但含义完全不同。写文档时必须写明“架构层 L3”或“验证级 L3”。详见 [`GLOSSARY.md`](GLOSSARY.md) §2。

## 5. 角色与职责

`[策划书]` 六个角色是**逻辑角色**，不是六个拥有独立 OS 权限的常驻进程；它们由 Agent Gateway 调度，可共用一个模型服务。

| 角色 | 职责 | 禁止权限 |
|---|---|---|
| Planner | 理解目标、选模板、提出 DAG | 写图、改状态、写证据 |
| Data | 检查数据结构与质量 | 改原始数据、写 E2 |
| Experiment | 把配置映射为白名单模板请求 | 生成/执行任意代码 |
| Analysis | 解释指标并提出重算请求 | 自签指标证据或决定 VERIFIED |
| Recovery | 诊断错误并提出恢复计划 | 直接改图、签 SPA |
| Verification | 提出验证计划、解释差异与缺口 | 写 E3、签报告/凭证 |

来源：§10.1 / TABLE 40；§10.2 / TABLE 41。

## 6. 第一版范围（已确认）

| 维度 | 约束 | 来源 |
|---|---|---|
| 运行环境 | Windows 11 单机；16GB 内存；CPU-only | §4.1 / P0074；§15.1 / P0378 |
| 并发 | 目标上限 2；**必须实测后才能宣称达成** | §5.4 / TABLE 22；`AGENTS.md` §5 |
| 模板 | 内置表格 ML 模板 | §4.4 / P0085；§15.2 / TABLE 56 |
| 代码执行 | 不执行 Agent 或用户生成的任意不可信代码；只运行审核过的内置模板 | §4.4 / P0087；§17.1 / P0427 |
| 网络 | 不默认开放网络 | §17.1 / P0427 |
| 容器 | 不强制 Docker；受控子进程不等于安全沙箱 | §5.6 / P0122 |
| 本地模型 | 不部署本地大模型 | §5.4 / TABLE 22；`AGENTS.md` §5 |
| 交付顺序 | 先 T0 最小可信闭环，再 T1，再 T2 | §15.2 / TABLE 56 |
| T0 边界 | 不接入 LLM；不开发六个 Agent；不接入 DeepSeek Harness Adapter | `AGENTS.md` §5；§15.2 / TABLE 56 |

## 7. T0 / T1 / T2 与 G0–G7

### 7.1 交付阶段

| 阶段 | 建设目标 | 必须完成 | 阶段出口 |
|---|---|---|---|
| **T0 最小可信闭环** | 证明不是 PPT | Task/Node Schema、DAG、StateMachine、内置模板、Executor、Collector、E0–E2、Gate、L1/L2/L3 单模板重跑、Ed25519、离线验签、最小工作台 | 断网/无模型完成一条实验；导出证据包；第三方验签通过 |
| **T1 竞赛完整版** | 覆盖赛道主要能力 | 六角色、消息协议、Scheduler/Governor、故障注入、Recovery、KB/FOL、60 任务、四方案/消融、六页工作台 | 六项能力均有运行演示与原始证据 |
| **T2 差异化强化** | 证明机制贡献和外部适配 | DC/SPA、VAS 四策略、盲测扩展、DeepSeek Harness 插件、第二 Domain Pack、第三方复核/试点 | 创新点有对照数据，至少一个 Harness 适配可复核 |

来源：§15.2 / TABLE 56。

### 7.2 质量门禁

| 门禁 | 通过条件 | 未通过处理 |
|---|---|---|
| G0 规格冻结 | 数据模型、状态机、API、错误码、证据等级和规则版本确定 | 暂停并行开发，先统一契约 |
| G1 纵向闭环 | 无模型、离线、单任务从提交到凭证全链跑通 | 停止前端美化和新增 Agent，修复执行/证据/验证 |
| G2 证据可信 | E0 不推动状态；E2 由 Collector 观察；权限拒绝通过 | 不得对外展示 VERIFIED |
| G3 L3 独立重执行 | 新目录、独立进程、真实重跑；假复现负例拒绝 | 缩小可 VERIFIED 模板范围 |
| G4 动态调度/恢复 | 资源变化改变调度；失败能执行恢复计划 | 只交付固定调度基线，不宣称动态优化 |
| G5 实验数据可信 | 预注册、冻结哈希、四方案、原始 JSON 和统计脚本齐全 | 缺数据保持未测 |
| G6 外部复核 | 真包通过、五类负例拒绝；独立环境可验证 | 不得宣称第三方可复核 |
| G7 Harness 适配 | 固定版本插件、工具、事件映射和状态回传契约通过 | 标注实验性/计划，不写已接入 |

来源：§15.3 / TABLE 57。

`[现状]` `G0` 已于 2026-11-10 `PASS`；`G1`–`G7` 仍 `NOT_STARTED`。目标数字与门禁条件不是实测成绩，不得把本文件中的目标写成已达成。

## 8. 核心验收指标（目标，不是实测）

| 指标 | 定义/分母 | 建议目标 | 统计/证据口径 |
|---|---|---|---|
| 正常任务完成率 | 正常任务中通过验证并获得凭证的比例 | 核心 12 任务目标 ≥90% | 任务级精确区间；报告 pass@3/pass^3 |
| 一般故障检测率 | 24 个一般异常任务中正确检测或恢复的比例 | 目标 ≥90% | 按故障类别分层 |
| 错误放行数 | 无真实必检证据却判 VERIFIED 的对抗任务数 | 观察值目标 0 | 同时给 n 与置信区间 |
| 盲测错误率上界 | 独立盲测任务错误放行率的置信上界 | 研究级扩展：0/72 时双侧 95% 上界约 4.99% | 仅独立 Bernoulli 假设下成立；另报家族聚类 |
| 定向恢复成功率 | 可恢复任务恢复到 VERIFIED 的比例 | 目标 ≥80% | 可恢复/不可恢复预先标注 |
| 重执行节点占比 | 恢复实际重跑节点/全量重跑节点 | 中位数目标 ≤40% | 中位数、IQR、配对比较 |
| 剪枝风险率 PRR | 被剪枝节点中重跑会改变结果的比例 | 观察值目标 0 | 逐节点原始 JSON；无 DC 必须重跑 |
| L3 覆盖率 | 报告关键指标来源节点的 L3 覆盖 | 100% | 按 report_id 输出覆盖矩阵 |
| 证据完整率 | 必需证据齐全且哈希可复核的任务比例 | 目标 ≥95% | 缺失证据不得由模型补写 |
| VAS 单位预算检出率 | 固定预算下每单位成本发现的有效问题数 | 风险优先应优于随机基线 | 同预算、同任务、同验证器 |
| 适配器一致性 | Harness 事件映射、任务提交和状态同步通过率 | 关键契约测试全部通过 | 固定版本 Adapter Contract Test |
| 资源占用 | 应用进程树峰值 RSS | 无本地 LLM 目标 ≤7GB | 实测 CPU/RSS/持续时间 |

来源：§4.2 / TABLE 18。

> 这些是**拟验收目标**，不是实测成绩。只有能追溯到 `run_id`、原始 JSON、日志、版本和复核脚本的数字才可标记为实测（§4.2 表后“数据纪律”，TABLE 19）。

## 9. 明确不做（第一版）

- 不做通用科研助手；首期只覆盖可机器验证的表格型 ML 实验。
- 不做 GPU 集群、分布式执行、多机高可用。
- 不执行 Agent 或用户生成的任意不可信代码，只运行审核过的内置模板。
- 不宣称跨硬件/跨版本普遍复现；首期目标是同软件环境下独立重执行。
- 不宣称哈希链绝对不可篡改；只称可发现篡改，并说明密钥与锚定边界。
- 不把知识检索、Agent 自评或多 Agent 投票当作实验完成证据。

来源：§4.4 / P0085–P0090；§17.4 / P0437–P0441。

## 10. 当前实际状态（`[现状]`）

| 项 | 状态 | 证据 |
|---|---|---|
| 业务代码 | **部分实现**：Pydantic v2 契约模型与 `POST/GET /api/v1/tasks` 绑定；StateMachine/SQLite/审计未实现 | `researchflow/contracts/`、`researchflow/api/app.py`、[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) |
| 契约/Schema | **5 份冻结 JSON Schema v1.0 + 72 个正反例** | `contracts/`、`docs/verification/g0/02_validate_contracts.log` |
| `.venv` / 依赖 | **已创建 / 已锁定**：3.11.16（64 位），58 包 | `requirements.lock`、`docs/verification/t0/wp-01/` |
| 运行时 StateMachine | **未实现**；设计见 P2，设计件已验收（2026-11-12），实现未开始 | `docs/state/runtime_states.md`、`pseudocode_stages.P2` |
| T0 | **进行中**：G0 `PASS`；G1–G7 `NOT_STARTED` | [`PROJECT_STATE.md`](PROJECT_STATE.md) |
| 伪代码阶段 | P1–P8 设计件 `ACCEPTED`（P2–P8 于 2026-11-12 验收）；P9/P10 `BLOCKED` | `docs/state/project_state.json` → `pseudocode_stages` |
| 策划书基线 | **已确认**（2026-11-08）；内部 v4.3.0 为内容基线，v4.3.1 仅为文件名标签 | `BLK-002` 已关闭；[`CONFLICT_REPORT.md`](reference/CONFLICT_REPORT.md) |
| P9 产物 | 6 个 `.py` 为 2026-11-11 并发重写，不是原始正文恢复；未测试、未验收 | `reports/remediation/P0_OPEN_ISSUES.md` |
| P10/M19 | 仅 5 个 API `.py`；无模块文档；未获开发授权 | `design/pseudocode/M19_api/` |

**不得把 T1/T2 的功能写成 T0 已完成，也不得把策划书目标写成当前能力。** 当前状态以 [`state/project_state.json`](state/project_state.json) 为唯一机器可读事实源；本表是阅读指路，不另建状态。

## 11. 文档地图

| 文档 | 用途 |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 六层架构、组件边界、证据/验证、密码学、调度、部署边界 |
| [`SECURITY_POLICY.md`](SECURITY_POLICY.md) | 威胁模型、权限、证据完整性、密钥、网络与数据边界 |
| [`DEVELOPMENT_WORKFLOW.md`](DEVELOPMENT_WORKFLOW.md) | 开发顺序、门禁、测试/证据规则、审批与交接 |
| [`GLOSSARY.md`](GLOSSARY.md) | 术语、缩写、易混淆命名 |
| [`MEMORY_GUIDE.md`](MEMORY_GUIDE.md) | 记忆/状态/交接的读写规则 |
| [`SKILL_CATALOG.md`](SKILL_CATALOG.md) | 九个项目级 Skill 与三态验证 |
| [`MCP_CATALOG.md`](MCP_CATALOG.md) | 当前 MCP server/tool、配置与信任边界 |
| [`reference/SOURCE_REGISTER.md`](reference/SOURCE_REGISTER.md) | 资料来源、版本证据、缺失资料 |
| [`reference/CONFLICT_REPORT.md`](reference/CONFLICT_REPORT.md) | 冲突、影响、方案与推荐 |
| [`state/project_state.json`](state/project_state.json) | 研发看板唯一机器可读事实源 |

## 12. 来源与待确认

- 主要来源：策划书内部 v4.3.0（文件名 v4.3.1，`BLK-002`）§1、§3、§4、§5、§10、§15、§17、§18。
- 飞书 AI 开发说明：**未落地**，本文件未引用其内容。
- 待确认：基线版本；飞书资料是否补入；赛事通知/章程是否补入；并发 2 与 16GB 的最终验收口径。
