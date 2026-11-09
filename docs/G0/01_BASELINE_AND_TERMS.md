# 01 基线版本与术语（G0 文档 ① v1.0）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v1.1（候选期编号）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ① v1.0（G0 冻结）**；v1.1 是候选期临时编号，冻结后归并入 v1.0（内容含 v1.1 的索引与已决项同步）；**不是 G0 门禁 PASS，不是 T0 开发批准**。
> 日期：2026-11-10（Asia/Shanghai）；候选期内容更新于 2026-11-09。
> 确认：用户 2026-11-09 确认 v1.0 口径；2026-11-10 指令将 ①–⑧/⑨ 统一标为 v1.0 并加冻结标记，**术语口径未改**。
> 变更：v0.1（2026-11-08 草案）→ v1.0（2026-11-09 确认）→ v1.1（2026-11-09 索引与已决项同步）→ v1.0（2026-11-10 冻结定版，归并 v1.1）。
> 适用范围：G0 文档包 01–08；后续文档术语以此为准，事实以策划书原文和用户书面决议为准。
> 基线：策划书**内部 v4.3.0**（文件名标签 v4.3.1；`BLK-002` 已关闭）。
> 锚点：`P####` → [`02_docx_body.txt`](../verification/stage7/02_docx_body.txt)；`TABLE ##` → [`05_docx_tables.txt`](../verification/stage7/05_docx_tables.txt)。DOCX 无可信页码，不用估算页码。
> 标注：`【策划书】` 原文明确；`【用户决议】` 2026-11-08 书面裁决；`【工程建议】` 未冻结；`【OPEN QUESTION】` 原文未定义、不得凭空补。

## 1. 目的、范围与优先级

本文固定两件事：**项目基线**（权威原件、版本、冲突、当前状态）和**规范性术语**（优先级/阶段、E0–E3、验证级 L1–L3、“能力下限”、`INVALIDATED`/`stale evidence`）。本文不定义 Schema 字段、API、DB 表、迁移守卫或错误码；这些由 05–08 冻结。

优先级：用户当前指令 > `AGENTS.md` > 本文（仅术语/基线） > 其他 G0 文档 > 阶段 7 知识文档。冲突时停止报告，不自行取舍。

本批先冻结本文 v1.0，再写 ②；不写 ③–⑧，不创建 `docs/G0/` 以外目录。该批当时未 commit、未建 `.venv`、未写业务代码。A–D 已裁决，不再作为开放问题。

## 2. 项目基线

### 2.1 权威原件

| 项 | 值 |
|---|---|
| 产品 | ResearchFlow 3.1（§1.1 / P0026） |
| 原件 | `D:\ResearchFlow-project\ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` |
| 大小 / SHA256 | 111,209 字节 / `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A` |
| 内容版本 | **v4.3.0**（封面 P0001/P0007、页眉、P0013、core 属性） |
| 文件名版本 | **v4.3.1**，仅标签 |
| 版本冲突 | `C-001` 已解决；`BLK-002` = `RESOLVED`（[CONFLICT_REPORT.md](../reference/CONFLICT_REPORT.md#L100-L114)） |
| 副本规则 | 禁止第二份 DOCX/PDF；根目录原件唯一（[SOURCE_REGISTER.md](../reference/SOURCE_REGISTER.md#L9-L16)） |

引用统一写“策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）”；不复制、不移动、不重命名、不覆盖原件。

### 2.2 资料冲突与缺口

| ID | 事项 | 状态 / G0 口径 |
|---|---|---|
| `C-001` | 文件名 v4.3.1 vs 内部 v4.3.0 | **RESOLVED**：内部 v4.3.0 为基线；v4.3.1 仅标签；不改 DOCX |
| `C-002` | 飞书 AI 开发说明未落地 | **OPEN**：不引用、不推测；使用须用户提供导出件 |
| `C-003` | 赛事通知/完整章程缺失 | **OPEN**：评分权重、页数、匿名、IP 等只引策划书转述并标“未独立核验” |
| `C-004` | DOCX 属性日期/页数异常 | LOW：不用 2013-12-23，不用 `Pages=1`；日期用文档控制表 2026-11-06 |
| `C-005` | 无可信页码 | LOW：只用章节 + `P####` / `TABLE ##` |
| `C-006` | 旧文档写 v4.3.1 | MEDIUM：新文档纠正；历史 CHANGELOG/交接不改写 |
| `C-007` | 策划书在根目录 | LOW：不复制、不移动；inbox 只留外部资料 |

`C-002`/`C-003` 不阻断 G0 一般准备，但不得把缺失资料写成“已核实”。

### 2.3 当前状态

| 项 | 当前值 |
|---|---|
| 研发看板阶段 | `WORKSTATION_SETUP`（[project_state.json](../state/project_state.json#L5)） |
| 阶段 8 | 25 PASS / 2 NOT VERIFIED / 0 FAIL，验收通过（[SESSION_HANDOFF.md](../SESSION_HANDOFF.md#L19-L28)） |
| G0–G7 | 全部 `NOT_STARTED` |
| T0 | 未开始；无业务代码、无契约实现、无运行时 DB |
| 契约 schema / `.venv` / 依赖 | 五份 schema 已建（⑨，v1.0 G0 冻结）/ 未创建 / 未安装 |
| Git | G0 规格基线提交见 `git log`；`last_verified_commit=null`（待用户确认后更新） |
| 阻塞 | `BLK-001` 已按仓库级身份配置关闭（全局身份仍为空）；`BLK-003` 沙箱子目录授权 `OPEN/MEDIUM`；13b、第 20 项 `NOT VERIFIED` |

**结论：阶段 8 已收尾，G0 未通过，T0 未开始。** 本文不是门禁通过证据。

### 2.4 第一版边界

| 维度 | 约束 |
|---|---|
| 环境 | Windows 11 单机；16GB；CPU-only；并发上限 2（须实测） |
| 模板 | 内置表格 ML；不执行任意用户/Agent 代码 |
| 网络/容器/模型 | 不默认开放网络；不强制 Docker；不部署本地大模型 |
| T0 排除 | 不接 LLM、不开发六角色、不接 Harness Adapter、不做动态调度/DC/SPA/VAS |
| 明确不做 | 通用科研助手、GPU 集群/分布式/多机、跨硬件普遍复现、绝对不可篡改、知识检索/Agent 自评作为完成证据（§4.4 / P0085–P0090） |

## 3. G0 已决事项（A–D）

| 裁决 | 用户决定 | 后续约束 |
|---|---|---|
| **A** | **A1**：§15.2 为阶段权威表、原文不改；“T0 必须完成”是**能力下限**；使能项清单见 §4.2；T1/T2 进 T0 仍须单独书面裁决；使能项若实质新增用户可见能力，停下来问，不得自行归类 | 01 解释能力下限；04/07 不得把 T1/T2 写成 T0 |
| **B** | **B1**：T0 只做“失效传播 + 执行前冻结恢复计划 + 受影响后代保守重跑”；不做 DC/SPA、动态调度、Recovery Agent、自动诊断；Node 新增 `INVALIDATED`，迁移 `VERIFIED → INVALIDATED → READY`，配 `ADR-001`；Gate 拒绝 stale 证据；Task 级 `COMPLETED` 后失效留 T1/revocation，写进原 12（现 ⑧）；其余 3 个 OQ 在 05/08 裁决；G4 仍 T1 | 05/08 实现 `INVALIDATED`；07 含 `WP-R`；04 标明信任边界 |
| **C** | **C1**：附录 J 为 T0 工作包基线；§15.5 为全项目能力叙事；不改表；T0 只做静态 DAG Builder，动态 Scheduler 属 T1；`WP-R` 在 `WP-13` 后、`WP-14` 前 | 07 按 `WP-01`–`WP-14` 排序；不得把 Scheduler 写成 T0 |
| **D** | **D1**：优先级 ≠ 阶段；`FR-011` 归 T1、不进 T0；`FR-015/016/017` 归 T2、不因 P1 提前；02 追踪矩阵必须双列“优先级/阶段”，禁止互相推导 | 02–08 所有 FR 表双列 |

### 3.1 B1 最小恢复边界

**做**：① 上游输入/参数/代码/环境/规则变化时，计算受影响后代并记录失效；② 重跑前生成并冻结恢复计划（受影响节点、原因、计划哈希）；③ 受影响后代全部保守重跑，不签 DC、不做 SPA；仍走 StateMachine → Executor → Collector → Gate。

**不做**：DC、SPA、动态 Scheduler、Governor、Recovery Agent、自动诊断、自动升级/重试、Task 级 `COMPLETED` 后撤销。

**`INVALIDATED`（已决）**：Node 状态 9→10；只允许 `VERIFIED → INVALIDATED`、`INVALIDATED → READY`；含义是“曾 VERIFIED，但输入/前驱/图版本/规则版本变化，原证据 stale”；Gate 必须拒绝 stale 证据；证据不删除，追加失效记录；其他边未授权；Task 级留 T1；配 `ADR-001`（见附录 A）。

### 3.2 C1 的 T0 工作包

| 编号 | 工作包 | 编号 | 工作包 |
|---|---|---|---|
| `WP-01` | 仓库/环境锁定 | `WP-09` | Verifier L1/L2 |
| `WP-02` | 核心 contracts | `WP-10` | Verifier L3 |
| `WP-03` | SQLite + StateMachine + audit_log | `WP-11` | Ed25519/JCS/Merkle |
| `WP-04` | DAG Builder（静态） | `WP-12` | Evidence Bundle + verify_bundle |
| `WP-05` | 内置数据与 ML 模板 | `WP-13` | 最小工作台 |
| `WP-06` | Executor | `WP-R` | FR-010 最小切片（B1，条件） |
| `WP-07` | Collector | `WP-14` | 端到端验收 |
| `WP-08` | Gate | | |

顺序：`WP-01 → … → WP-13 → WP-R → WP-14`；`WP-R` 不得早于 `WP-09`，不得替代 `WP-10`–`WP-13`；详细依赖图见 07。

## 4. 规范性术语

### 4.1 `P0/P1/P2` 与 `T0/T1/T2`：两条正交轴

**【用户决议 D1】`P0/P1/P2` = 业务重要度/必须程度，不是阶段。** `P0` 不表示“必须在 T0”；`P1` 不表示 T1；`P2` 不表示 T2。优先级不能推导阶段，阶段也不能推导优先级；每份 FR 表必须同时写两列。

**【策划书】`T0/T1/T2` = 交付阶段**（§15.2 / TABLE 56）：

| 阶段 | 定义 | 出口 |
|---|---|---|
| **T0** | 最小可信闭环；断网、无模型、单机完成一条内置表格 ML 任务 | 完成一条实验；导出证据包；第三方离线验签通过 |
| **T1** | 竞赛完整版：六角色、消息协议、Scheduler/Governor、故障注入、完整 Recovery、KB/FOL、60 任务、四方案/消融、六页工作台 | 六项能力有运行演示与原始证据 |
| **T2** | 差异化：DC/SPA、VAS 四策略、盲测扩展、Harness 插件、第二 Domain Pack、第三方复核/试点 | 创新点有对照数据；至少一个 Harness 适配可复核 |

**FR 交叉表**（用户决议 + 原文模块映射；逐条字段由 02 维护）：

| FR | 优先级 | 阶段 | 说明 |
|---|---|---|---|
| `FR-001`–`FR-009` | P0 | T0 | 任务、DAG、状态机、模板/Executor、Collector、Gate、L1–L3、签名、Bundle |
| `FR-010` | P0 | **T0 最小 + T1 完整** | T0 只做 B1 失效传播/冻结计划/保守重跑；完整 Recovery 与 Task 级 revocation 在 T1 |
| `FR-011`–`FR-014` | P1 | T1 | Scheduler/Governor、六角色、KB、FOL |
| `FR-015`–`FR-017` | P1 | **T2** | DC/SPA、VAS、Harness Adapter |
| `FR-018` | P1 | T1 | RF-Bench 60 任务与统计 |
| `FR-019`–`FR-020` | P2 | T2 | G-hold-72、第二 Domain Pack |

规则：`FR-010` 是唯一跨 T0/T1 的 P0；`FR-011` 是 P1 但属 T1，不因 §15.5 提到 Scheduler 进 T0；`FR-015/016/017` 是 P1 但属 T2，不因 P1 提前。

### 4.2 “T0 必须完成”的能力下限

**【用户决议 A1】§15.2 的 T0 清单是 T0 出口要求的“最小能力集合”，是下限（floor），不是上限（ceiling），也不是 WBS。** 它回答“T0 至少要能演示什么”，不回答“T0 只允许写哪些文件/模块”。

T0 工作分两类：

1. **能力项**：§15.2 原文列出的能力，一字不删、不改、不重排。
2. **使能项**：为使能力项可执行/可验证/可导出而必需、且经 A1 批准的工作包。

**A1 使能项清单（穷举）**：

| 使能项 | 对应能力/出口 |
|---|---|
| SQLite + `audit_log` | StateMachine 持久化/审计 |
| DAG Builder（静态） | “DAG”；FR-002；附录 J 04 |
| JCS + Merkle | Ed25519 规范化；证据链/包含证明 |
| Evidence Bundle + `verify_bundle.py` + 信任锚 | “导出证据包；第三方验签” |
| `VerificationReport` + `CompletionCertificate` | FR-008 签发/验签 |
| E3 | L1/L2/L3；FR-007（T0 表“E0–E2”是 Collector 范围） |

使能项必须同时满足：① 指向某个 T0 能力项或出口；② 不新增用户可见能力/FR/对外接口语义；③ 不引入 T1/T2 机制。

**用户可见能力测试**：若某项会新增/改变用户可调用的 API、页面、报告字段、任务类型、角色、算法或对外输出，它就不是使能项；**停下问用户**，不得自行归类。

边界：A1 不授权 T1/T2 进 T0；B1 的 `WP-R` 是单独裁决，不是 A1 使能项；使能项新增须书面批准；§15.2 原文不改。

### 4.3 证据等级 `E0–E3`

| 等级 | 来源 / 写入者 | 能证明 | 不能证明 | 状态作用 |
|---|---|---|---|---|
| **E0** | Agent 声明；Collector 标记 `agent_claim` | 曾提出主张 | 执行/结果 | **永不单独推动状态** |
| **E1** | 工具调用、Harness 轨迹、知识检索；Collector | 请求/轨迹存在 | 不等于真实执行 | 辅助；不得单独满足执行类必检项 |
| **E2** | 受控 Executor 进程/产物；Collector 监听 | 本次受控执行发生、产物存在 | 结果语义正确 | 可覆盖执行类必检项；依赖信任边界 |
| **E3** | Verifier 新目录重算/重执行 | 在声明环境下可独立复算/重跑 | 不等于跨环境普遍复现 | 最高；关键指标节点须满足 L3 |

规则：证据等级是来源类别，不是“信任分”；E0/E1 不单独满足执行类必检项；E2 必须来自真实受控执行，Collector 不得补造；Harness 轨迹默认 E1；外部数据/模型输出默认不是证据；证据只追加，纠错用新事件引用旧事件。**【工程解释】** T0 表里的“E0–E2”是 Collector 的采集范围，不是全部证据等级；E3 由 Verifier 产生，且 T0 的 L1/L2/L3 与 FR-007 必需。

### 4.4 验证级 `L1/L2/L3` 与架构层 `L1–L6`

| 记号 | 含义 |
|---|---|
| **架构层 L1–L6** | 交互 / 接入 / 编排控制 / Agent 决策 / 执行 / 证据验证知识（§5.2 / TABLE 21） |
| **验证级 L1** | 过程完整性：代码、数据、配置、环境、日志、产物齐全且属于本次运行 |
| **验证级 L2** | 结果自洽：指标可从 predictions 重算，划分/口径合理 |
| **验证级 L3 / IRC** | 新目录、独立进程、原始数据重读、真实重新训练/推理 |

写 `L3` 必须加限定语。“架构层 L3”不是“验证级 L3”；T0 需要验证级 L1/L2/L3，不开发架构层 L4 六角色，也不做架构层 L3 的动态 Scheduler/Governor/VAS。L3 只重算指标/重读 predictions 不算 L3。

### 4.5 运行时状态与研发看板

| 对象 | 允许值 | 存储/入口 |
|---|---|---|
| 研发看板 | `BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED` | `project_state.json` |
| 运行时 Task | `CREATED`、`PLANNING`、`READY`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED` | StateMachine / DB |
| 运行时 Node | `PLANNED`、`READY`、`RUNNING`、`VERIFYING`、`VERIFIED`、`FAILED`、`BLOCKED`、`DIAGNOSING`、`RECOVERING`、**`INVALIDATED`** | 同上 |
| Report / Certificate | `VERIFIED/PARTIAL/FAILED/BLOCKED`；证书仅 `VERIFIED` | Verifier |

`DONE` ≠ `COMPLETED`；研发看板 `BLOCKED` ≠ 运行时 `BLOCKED`；`INVALIDATED` 是运行时状态，不是看板状态。

### 4.6 `INVALIDATED`、`stale evidence`、`Recovery`

| 术语 | 定义 | 边界 |
|---|---|---|
| `INVALIDATED` | 曾 `VERIFIED`，因上游/前驱/图版本/规则变化，原结论失效 | 只允许 `VERIFIED → INVALIDATED → READY`；其他边未授权 |
| `stale evidence` | 与当前输入/前驱/图版本/规则不一致、不能继续满足必检项的旧证据 | 不删除；追加失效记录；Gate 拒绝 |
| `WP-R` | FR-010 T0 切片：失效传播 + 冻结计划 + 保守重跑 | 不是完整 Recovery |
| revocation event | 签发后发现撤销条件时追加的事件 | T1 / Task 级，不在 T0 |

`INVALIDATED` ≠ `FAILED`（执行/验证失败）≠ `BLOCKED`（缺口/权限/资源/冲突）。`Recovery` 必须加限定：**完整 Recovery（T1）**、**FR-010 T0 切片 `WP-R`（T0）**、**Recovery 角色（T1）**。T0 不得只写“Recovery”；G4 仍 T1。

### 4.7 `DAG Builder` vs `DAG Scheduler`

| 组件 | 阶段 | 职责 | 不做什么 |
|---|---|---|---|
| DAG Builder | T0 | 静态建图/校验：节点边、拓扑、环、孤立节点、重复边、缺失依赖、图版本、白名单 | 不做运行时优先级/资源调度 |
| DAG Scheduler / Ready Scheduler | T1 | 在已校验 DAG 的 READY 节点中按依赖、资源、优先级选下一执行对象 | 不建图；图变更须审批 |
| Governor / VAS | T1 / T2 | 资源水位/并发/回收；验证预算 | 不决定重跑子图 / 不剪枝执行节点 |

T0 只做静态 Builder；执行顺序用确定性拓扑序/固定顺序，不做 `SchedScore`；§15.5 提到 Scheduler/Governor 不等于 T0 要做。

### 4.8 核心组件与契约

| 组件 | 职责 / 单写者边界 |
|---|---|
| StateMachine | 运行时状态迁移唯一入口；成功/失败都写 `audit_log` |
| Executor | 只执行审核过的内置模板；不裁决成功、不写证据、不持私钥 |
| Collector | E0/E1/E2 单写者；`event_seq` 单调；追加写；不补造 |
| Gate | 按 `RequiredChecks` 评估覆盖/链/版本/等级/L3；不签凭证；输出 `GAP` |
| Verifier | 独立 L1/L2/L3，产生 E3，签发报告/凭证；与 Executor 目录/进程分离 |
| Tool Gateway | Agent 访问工具唯一入口；白名单/权限/审计 |

| 契约 | 来源状态 | G0 处理 |
|---|---|---|
| `TaskSpec` / `NodeSpec` / `EvidenceRecord` | 附录 D.1–D.3 有示例字段 | 05 冻结 |
| `VerificationReport` / `CompletionCertificate` | 附录 D.4 有示例字段 | 05 冻结 |
| `HarnessEvent` | §15.5 列入 contracts，附录 D 无 Schema | **OPEN QUESTION**；05 不得凭空补 |
| `DomainPack` | §5.7 有钩子，无完整 Schema | **OPEN QUESTION**；05 冻结钩子字段 |
| `RecoveryPlan` | 不在七个核心契约中；B1 需要内部产物 | **已决**（决议 3 / `ADR-004`）：T0 内部不可变产物，内容寻址文件，不签名、不进七契约、不对外 |

### 4.9 `G0–G7`

| 门禁 | 通过条件（摘要） | 阶段 |
|---|---|---|
| **G0 规格冻结** | 数据模型、状态机、API、错误码、证据等级、规则版本确定 | T0 前；需用户批准 |
| **G1 纵向闭环** | 无模型、离线、单任务从提交到凭证全链路跑通 | T0 |
| **G2 证据可信** | E0 不推动状态；E2 由 Collector 观察；权限拒绝通过 | T0 |
| **G3 L3 独立重执行** | 新目录、独立进程、真实重跑；假复现负例拒绝 | T0 |
| **G4 动态调度/恢复** | 资源变化改变调度；失败能执行完整恢复计划 | **T1** |
| **G5 实验数据可信** | 预注册、冻结哈希、四方案、原始 JSON、统计脚本齐全 | 实验阶段【工程映射：不早于 T1】 |
| **G6 外部复核** | **G6-T0**：独立环境（另一目录/另一设备/另一 Windows 用户）用 `verify_bundle.py` 与外部可信指纹验签真包通过；**G6 完整版（T1）**：真包通过 + 五类负例矩阵拒绝 | T0（G6-T0）/ T1（完整版） |
| **G7 Harness 适配** | 固定版本插件、工具、事件映射、状态回传契约通过 | T2 |

**G6-T0（T0 出口，必须落到 ⑦ 测试矩阵）**：在独立环境（另一目录 / 另一设备 / 另一 Windows 用户）使用 `verify_bundle.py` 与**外部可信指纹/信任锚**验签真包通过；**五类负例矩阵属 G6 完整版（T1）**，不得用“证据包可用后”把 G6-T0 整体推后。⑦ 的测试矩阵必须单列 `G6-T0`，并包含环境隔离、外部指纹、真包通过三项。

G0–G7 当前全部 `NOT_STARTED`；`G0` 不是 `T0`；文档写完 ≠ G0 通过；G4 不因 B1 提前。

## 5. 术语使用规则与禁止写法

| 不要写 | 应写 |
|---|---|
| “P1 所以进 T1” | “P1 是重要度；阶段见 §15.2 与 02 阶段列” |
| “P0 就是 T0” | “P0 是最高重要度；FR-010 T0 切片由 B1 单独决定” |
| “T0 只允许表内词” | “T0 是能力下限；A1 使能项已列，新增须批准” |
| “T0 做 Recovery” | “T0 做 FR-010 最小切片 `WP-R`；完整 Recovery 属 T1” |
| “`INVALIDATED` = `BLOCKED`” | “`INVALIDATED` 是曾 VERIFIED 的证据失效；`BLOCKED` 是缺口/权限/资源/冲突” |
| “删掉 stale 证据” | “保留证据，追加失效记录，Gate 拒绝其满足必检项” |
| “E1 替代 E2” / “E2 等于 E3” | “E2 必须真实受控执行；E3 由独立 Verifier 产生” |
| “L3 层” / “DONE=COMPLETED” | “架构层 L3”或“验证级 L3”；研发看板 DONE ≠ 运行时 COMPLETED |
| “T0 做六 Agent/Scheduler/Harness” | “六 Agent、Scheduler/Governor、Harness Adapter 分属 T1/T2” |

## 6. G0 文档包

| 编号 | 路径 | 内容 | 状态 |
|---|---|---|---|
| ① | `docs/G0/01_BASELINE_AND_TERMS.md` | 基线 + 术语（本文） | **v1.0（G0 冻结，2026-11-10；取代 v1.1 候选期编号）** |
| ② | `docs/PRD/02_REQUIREMENT_TRACEABILITY.md` | FR-001–020 追踪矩阵 | **v1.0（G0 冻结；取代 v0.2 候选）** |
| ③ | `docs/PRD/03_PRD_T0.md` | T0 PRD/用户故事（6–8 页，表格化） | **v1.0（G0 冻结；取代 v0.2 候选）** |
| ④ | `docs/design/04_ARCHITECTURE.md` | 六层架构与信任边界 | **v1.0（G0 冻结；取代 v0.2 候选）** |
| ⑤ | `docs/design/05_CONTRACTS_AND_STATES.md` | 契约 + 状态枚举/迁移 | **v1.0（G0 冻结；取代 v0.3 候选）** |
| ⑥ | `docs/design/06_DATA_AND_API.md` | SQLite + API/错误码/幂等 | **v1.0（G0 冻结；取代 v0.2 候选）** |
| ⑦ | `docs/design/07_T0_PLAN_AND_GATES.md` | T0 依赖图 + 测试/G0–G7（含 G6-T0）；WP-01 锁定基线 | **v1.0（G0 冻结；取代 v0.2 候选）** |
| ⑧ | `docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` | 未决问题 + 冻结决议 | **v1.0（G0 冻结；取代 v0.3 候选）** |
| ⑨ | `contracts/` | 五份 JSON Schema + 正反例 + 校验器 | **v1.0（G0 冻结）** |
| ADR | `docs/ADR/` | 架构决策记录 | **6 ACCEPTED + 1 PROPOSED（ADR-007 保持 PROPOSED，WP-13 前裁决）** |

②–⑧ 与 ⑨ 均已按用户 2026-11-10 指令统一为 v1.0；**G0 门禁仍 `NOT_STARTED`**，是否 PASS 由用户宣布。未建 `.venv`、未写业务代码。

## 7. 变更控制与已确认口径

- 本文已冻结为 v1.0；后续改动须版本递增、写原因、用户确认；影响状态机/Schema/DB/安全边界的改动另配 ADR。
- 术语变更若影响 02–08，须同步更新并复查，不得只改一处。
- DOCX 永不修改；不得生成第二份副本。

**已确认口径（2026-11-09，按现文执行，不改）**：① P0/P1/P2 = 重要度，非阶段；② T0 = 能力下限，A1 使能项穷举，用户可见能力测试；③ E0–E3 定义与 T0 表“E0–E2”为 Collector 范围；④ `INVALIDATED` 的 10 状态、两条迁移、Gate 拒绝 stale 证据，Task 级留 T1；⑤ `WP-R` 定位，G4 仍 T1。

**移交后续的 OPEN QUESTION（不是重新讨论 A–D）**：

| 编号 | 问题 | 状态 | 去向 |
|---|---|---|---|
| `OQ-B1-1` | `RecoveryPlan` 是内部产物还是公开契约？字段如何从 §8.4 推导？ | **已关闭**（决议 3 / `ADR-004`）：内部不可变产物 | 05/08 |
| `OQ-B1-2` | 失效/恢复控制事件属什么证据等级？只写 audit 还是 E1/E2？ | **已关闭**（决议 4 / `ADR-004`）：只写 `audit_log` + `evidence_invalidations`，不占 E0–E3 | 05/08 |
| `OQ-B1-3` | 已签发 `CompletionCertificate` 之后的撤销路径（T1 / ⑧）；节点级 `INVALIDATED` 已关闭，不再是开放问题 | 开放 | T1 / ⑧ |
| `OQ-C-1` | `HarnessEvent`、`DomainPack` 完整 Schema 缺失 | 开放（T2 前补齐；G0 不出 schema） | 05 |
| `OQ-D-1` | `FR-010` 的 T0/T1 双阶段证据已由 02 覆盖（§2.1） | 已覆盖 | 02（已覆盖） |
| `OQ-BASE-1` | `C-002` 飞书、`C-003` 赛事章程是否补入 | **已关闭**（决议 10）：不补入、不引用；赛事结论标“未独立核验” | 08 |
| `OQ-BASE-2` | `BLK-003`/13b/2C-2D/Git 无基线的风险排序 | 已登记（⑧ §3） | 08 |

**已移交 ⑧（不是开放 A–D 问题）**：Task 级 `COMPLETED` 之后的失效 → T1 + revocation；具体机制在 ⑧ 登记，不在 T0 实现。`INVALIDATED → READY` 的守卫、reason_code、计划关联字段在 05/08 定义，不在此处补字段。

**⑦ 待办（G6-T0）**：G6-T0 必须进入 ⑦ 的测试矩阵，单列“独立环境（另一目录/另一设备/另一 Windows 用户）+ `verify_bundle.py` + 外部可信指纹 + 真包通过”三项；五类负例矩阵归 G6 完整版（T1），不得混写。

**下一步**：①–⑧ 与 ⑨ 已按用户 2026-11-10 指令统一为 v1.0 并加冻结标记；三组枚举（`kind` 7 / `l1-l3_status` 4 / `side_effect_class` 3）按现值冻结；依赖矩阵锁定为 `WP-01` 基线并写入 ⑦；`ADR-007` 保持 `PROPOSED`，WP-13 前裁决。G0 门禁仍 `NOT_STARTED`，PASS 由用户宣布。`T-G0-001` 保持 `IN_PROGRESS`，不进入 T0。

## 附录 A：`ADR-001` 决策记录（内嵌）

> 本轮受“只写 ①”限制，未创建 `docs/ADR/` 文件；以下为决策原文，正式 ADR 在 05/08 批次落地，内容不得改变。

| 字段 | 内容 |
|---|---|
| 编号 | `ADR-001` |
| 标题 | Node `INVALIDATED` state for FR-010 T0 minimal slice |
| 状态 | **ACCEPTED**（用户 2026-11-08）；正式文件待落地 |
| 背景 | FR-010 为 P0；B1 要求 T0 失效传播/冻结计划/保守重跑；原 Node 迁移表无 `VERIFIED` 出边，已 VERIFIED 节点无法表达“证据失效”，存在复用 stale 证据风险 |
| 决策 | Node 新增 `INVALIDATED`；只允许 `VERIFIED → INVALIDATED → READY`；Gate 拒绝 stale 证据；证据不删除，追加失效记录；Task 级 `COMPLETED` 后失效留 T1/revocation |
| 后果 | Node 状态 9→10；StateMachine/DB/API/测试/文档同步；05/08 定义守卫、reason_code、计划关联字段；其他边未授权，需单独裁决 |
| 备选（未选） | ① `VERIFIED` + `stale` 字段：改动小但语义不显式；② 用 `BLOCKED`：与缺口/权限/资源/冲突混淆；③ 只靠 revocation：无法表达节点级重跑生命周期 |
| 验证 | `VERIFIED` 节点上游变化 → `INVALIDATED`；stale 证据不能过 Gate；`INVALIDATED → READY` 后重跑产生新证据；非法迁移拒绝；Task 级撤销不在 T0 |

## 附录 B：来源锚点

| 主题 | 锚点 |
|---|---|
| 定位 / 第一版范围 | §1.1 / P0026–P0027；§4.4 / P0085–P0090 |
| 六层架构 / 状态机 | §5.2 / TABLE 21；§6.2 / TABLE 26；附录 F / TABLE 70–71 |
| E0–E3 / Gate / 凭证 | §7.1–7.6 / TABLE 31–33 |
| 定向恢复 / 调度 | §8.4–8.8 / P0201–P0230 |
| L1–L3 | §9.1–9.4 / TABLE 38–39 |
| T0–T2 / G0–G7 | §15.2 / TABLE 56；§15.3 / TABLE 57 |
| 开发顺序 / T0 清单 / 需求 | §15.5 / P0386–P0395；附录 J / TABLE 78；附录 C / TABLE 67 |
| 版本冲突 / 当前状态 | `C-001`；[CONFLICT_REPORT.md](../reference/CONFLICT_REPORT.md)；[project_state.json](../state/project_state.json) |

## 附录 C：版本记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| v0.1 | 2026-11-08 | 基线 + 术语草案；记录 A–D；列出 OQ 与 G0 文档包 | 候选，已被 v1.0 取代 |
| v1.0 | 2026-11-09 | 用户确认 ①–⑤；`OQ-B1-3` 改为“已签发证书后的撤销路径（T1/⑧）”；G6 拆为 `G6-T0` 与 `G6 完整版（T1）`；增加 ⑦ 的 G6-T0 待办；后续仅更新文档包状态索引与 `OQ-D-1` 标记，**术语口径未改** | 已由 v1.1 候选期增补；2026-11-10 以 v1.0 定版冻结 |
| v1.1 | 2026-11-09 | 仅两处：§6 索引增加 ⑨ 并更新 ②–⑧ 状态；§4.8、§7 中与已关闭 OQ 同源的旧表述同步为决议结论（`OQ-B1-1/2`、`OQ-BASE-1`），§2.3 契约状态改为“五份 schema 已建（⑨，未冻结）”。**术语、边界、门禁口径均未改** | 候选期临时编号，已归并入 v1.0（2026-11-10 冻结） |
| v1.0 | 2026-11-10 | **G0 冻结定版**：沿用 v1.0 编号（v1.1 为候选期编号，冻结后归并），补冻结日期、G0 冻结状态与被取代版本；索引同步 ①–⑨ 全部 v1.0；记录枚举冻结与依赖矩阵锁定。**术语口径未改** | **G0 冻结** |

---

**标记：本文是 G0 文档 ① v1.0（G0 冻结），不是 G0 门禁 PASS。** 文档已按用户 2026-11-10 指令冻结；G0 是否 PASS 由用户宣布，T0 业务代码开发须另行批准。
