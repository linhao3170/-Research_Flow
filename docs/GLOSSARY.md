# GLOSSARY — ResearchFlow 术语表

> 状态：阶段 7 资料接手成果
> 基线：策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）
> 证据锚点：`P####` → [`02_docx_body.txt`](verification/stage7/02_docx_body.txt)；`TABLE ##` → [`05_docx_tables.txt`](verification/stage7/05_docx_tables.txt)
> 页码说明：DOCX 无可信页码（无 TOC/缓存分页；Word COM 不可用）；引用使用章节号 + `P####` + `TABLE ##`，可在上述文件中逐行核验。
> 用法：术语定义只用于消除歧义，不替代 G0 冻结后的 Schema/契约；标注 `[建议]` 的是工程用法，不是策划书原文。

## 1. 项目与范围

| 术语 | 定义 | 来源 |
|---|---|---|
| **ResearchFlow 3.1** | 面向 AI 实验任务的可信多智能体编排、动态调度与独立验证平台 | §1.1 / P0026 |
| **T0 最小可信闭环** | 无模型、离线、单任务从提交到凭证全链跑通；不接 LLM、不开发六 Agent、不接 Harness Adapter | §15.2 / TABLE 56；`AGENTS.md` §5 |
| **T1 竞赛完整版** | 六角色、消息协议、Scheduler/Governor、故障注入、Recovery、KB/FOL、60 任务、四方案/消融、六页工作台 | §15.2 / TABLE 56 |
| **T2 差异化强化** | DC/SPA、VAS 四策略、盲测扩展、Harness 插件、第二 Domain Pack、第三方复核/试点 | §15.2 / TABLE 56 |
| **G0–G7** | 规格冻结、纵向闭环、证据可信、L3 独立重执行、动态调度/恢复、实验数据可信、外部复核、Harness 适配八道质量门禁 | §15.3 / TABLE 57 |
| **第一版边界** | Windows 11 单机、16GB、CPU-only、并发 2、内置表格 ML 模板；不执行任意用户代码、不默认开放网络、不强制 Docker、不部署本地大模型 | §4.1、§5.4、§17.1；`AGENTS.md` §5 |
| **明确不做** | 通用科研助手、GPU 集群/分布式/多机高可用、任意不可信代码、跨硬件普遍复现、绝对不可篡改、知识检索/Agent 自评作为完成证据 | §4.4 / P0085–P0090 |

## 2. 最容易混淆的三组命名

### 2.1 架构层 L1–L6 vs 验证级 L1–L3

| 记号 | 含义 | 来源 |
|---|---|---|
| **架构层 L1** | 交互层 | §5.2 / TABLE 21 |
| **架构层 L2** | 接入层 | 同上 |
| **架构层 L3** | 编排控制层（DAG、Scheduler、StateMachine、Recovery、Governor、VAS、Gate） | 同上 |
| **架构层 L4** | Agent 决策层（六逻辑角色） | 同上 |
| **架构层 L5** | 执行层（Tool Registry、Executor、Workspace、SplitService） | 同上 |
| **架构层 L6** | 证据/验证/知识层（Collector、Evidence Store、Verifier、Certificate、KB、Bench） | 同上 |
| **验证级 L1** | 过程完整性：代码、数据、配置、环境、日志、产物齐全且属于本次运行 | §9.1 / TABLE 38 |
| **验证级 L2** | 结果自洽：指标可从 predictions 重算，划分/口径合理 | 同上 |
| **验证级 L3 / IRC** | 新目录、独立进程、原始数据重读、真实重新训练/推理 | 同上 |

**规则**：写“L3”时必须加限定语。“架构层 L3”不是“验证级 L3”；“验证级 L3”不是“第三层架构”。

### 2.2 研发看板状态 vs 运行时状态

| 记号 | 含义 | 允许值 | 存储 |
|---|---|---|---|
| **研发看板状态** | 研发任务/交付物进度 | `BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED` | `docs/state/project_state.json` |
| **运行时 Task 状态** | ResearchFlow 运行中的任务状态 | `CREATED`、`PLANNING`、`READY`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED` | 运行时 StateMachine / DB（未实现） |
| **运行时 Node 状态** | 运行中的节点状态 | `PLANNED`、`READY`、`RUNNING`、`VERIFYING`、`VERIFIED`、`FAILED`、`BLOCKED`、`DIAGNOSING`、`RECOVERING` | 同上 |

**规则**：两套词汇不得合并、改名或互相替代。`DONE` ≠ `COMPLETED`；研发看板的 `BLOCKED` ≠ 运行时 `BLOCKED`。详见 [`state/runtime_states.md`](state/runtime_states.md)。

### 2.3 G-hold vs G0–G7

| 记号 | 含义 | 来源 |
|---|---|---|
| **G0–G7** | 八道研发质量门禁 | §15.3 / TABLE 57 |
| **G-dev** | 开发可见对抗用例（8 个） | §12.2 / TABLE 45 |
| **G-hold** | 非规则开发者构造的核心留出变体（16 个） | 同上 |
| **G-hold-72** | T2 研究级独立盲测扩展（至少 72 个独立任务实例） | §12.4 / P0305 |

**规则**：`G-hold` 不是门禁 `G0`；`G-hold-72` 不是 `G7`。

## 3. 证据与验证

| 术语 | 定义 | 来源 |
|---|---|---|
| **E0** | Agent 声明；Collector 捕获并标记 `agent_claim`；永不单独推动状态 | §7.1 / TABLE 31 |
| **E1** | 工具调用、Harness 轨迹、知识检索；辅助证明请求/轨迹，不等于真实执行 | 同上 |
| **E2** | 受控 Executor 进程和产物观测；可覆盖执行类必检项，依赖信任边界 | 同上 |
| **E3** | Verifier 新目录重算或重执行；最高等级；关键指标节点必须满足 L3 | 同上 |
| **EG（Evidence Gate）** | 证据门控：把完成声明转换为可复核判定 | §1.4 / TABLE 08；§7 |
| **TLV（Three-Level Verification）** | 三级验证：L1 过程完整性、L2 结果自洽、L3 独立重执行 | §9.1 / TABLE 38 |
| **Gate** | 按 `RequiredChecks` 生成覆盖矩阵、校验链/哈希/版本/冲突/证据等级/ L3 的规则评估器 | §7.2 / P0159–P0168 |
| **GAP** | Gate 未通过时输出的结构化缺口清单；不是自由文本解释 | §7.2 / P0168 |
| **RequiredChecks** | Domain Pack 声明的领域必检项与规则版本 | §7.2 / P0159 |
| **coverage row** | 每个必检项的覆盖行：`required_check_id`、`evidence_ids`、`level`、`producer`、`hash_status`、`l3_status`、`result` | 同上 |
| **VerificationReport** | Verifier 签发的报告；四态 `VERIFIED/PARTIAL/FAILED/BLOCKED` | §7.4 / TABLE 32 |
| **CompletionCertificate** | 仅由 `VERIFIED` 报告生成的完成凭证 | 同上；附录 D.4 |
| **Evidence Bundle** | 可离线复核的证据包（manifest、task、graph、evidence、artifact、split、report、certificate、proofs、verify_bundle 等） | §9.5 / P0249 |
| **IRC（Independent Re-execution Check）** | 独立重执行检查；与验证级 L3 同义使用 | §9.1 / TABLE 38 |
| **PRR（Pruning Risk Rate）** | 被剪枝节点中重跑会改变结果的比例；观察值目标 0 | §4.2 / TABLE 18；§8 |
| **Split Manifest** | 数据划分清单：`dataset_hash`、`split_algorithm/version`、`seed`、`row_id_hash`、`fold_assignment_hash`、`group/time semantics` | §9.3 / P0243 |
| **bit-exact** | 逐位一致；DC 的 k 次重复要求 | §8.2 / P0192；§9.4 / P0247 |
| **TOST** | 等价性检验；随机性模式用预注册种子集合与等价边界 | §9.4 / P0247 |
| **tamper-evident** | 可发现篡改；不是“绝对不可篡改” | §7.3 / P0170；§7.7 / P0185 |

## 4. DC / SPA / 调度

| 术语 | 定义 | 来源 |
|---|---|---|
| **DC（Determinism Certificate）** | 对某节点类型、固定输入/代码/依赖/环境/规则，在受控条件下观察到 k 次跨进程、跨目录 bit-exact 一致的经验性资格；不是普遍确定性证明 | §8.2 / P0192 |
| **SPA（Skip Provenance Attestation）** | 省略溯源凭证；记录合法跳过的条件、证据与签名 | §8.3 / P0195–P0200 |
| **Ready Scheduler** | 只在依赖满足且资源允许的 READY 节点中选择下一执行对象 | §8.5 / P0216 |
| **Governor** | 资源感知：决定并发与资源水位 | §8.6 / TABLE 36 |
| **Recovery** | 失败后决定受影响子图、必须重跑节点与可合法省略节点 | §8.4 / P0201 |
| **VAS（Verification-Aware Scheduling）** | 把验证预算作为显式资源，按风险×覆盖收益/成本排序 | §8.7 / P0222 |
| **PRR** | 剪枝风险率 | §4.2 / TABLE 18 |
| **Role-off** | 逐一关闭六个角色，比较指标变化，避免“为凑数保留角色” | §10.4 / P0262–P0264 |
| **CPG（Collaboration Provenance Graph）** | 以“角色引用了谁产生的证据”为边，计算跨角色引用率/协作密度/贡献熵等 | §10.3 / P0260 |
| **FOL** | 三层反馈环：L-A 执行环、L-B 知识环、L-C 策略环 | §11.5 / TABLE 44 |

## 5. 密码学与数据契约

| 术语 | 定义 | 来源 |
|---|---|---|
| **JCS** | RFC 8785 JSON Canonicalization Scheme；递归排序对象键，保持数组顺序 | §7.5 / P0174–P0175 |
| **Ed25519** | RFC 8032 EdDSA 签名算法 | §7.5 / P0174 |
| **Merkle Tree** | RFC 9162；叶节点 `0x00` 前缀、内部节点 `0x01` 前缀；按 `event_seq` 固定顺序 | §7.3 / P0170 |
| **域分离前缀** | Report、Certificate、DC、SPA 各自的签名载荷前缀，防止跨类型重放 | §7.5 / P0178 |
| **trust anchor / 信任锚** | 验签工具预置的可信公钥指纹/信任根；不信任证书自带公钥 | §7.6 / TABLE 33；附录 F.2 / I-08 |
| **AnchorProof** | 独立 sidecar，记录证书哈希、Merkle 根、树大小、锚定类型/时间/收据/签名 | §7.4 / TABLE 32 |
| **TaskSpec** | 任务输入契约：`schema_version`、`task_id`、`domain_pack`、`goal`、`dataset_ref`、`template_id`、`parameters`、`ruleset_hash`、`limits` | 附录 D.1 / P0474–P0497 |
| **NodeSpec** | 节点契约：`node_id`、`node_type`、`template_id`、`depends_on`、`input_refs`、`parameters_hash`、`side_effect_class`、`retry_policy`、`required_checks` | 附录 D.2 / P0499–P0509 |
| **EvidenceRecord** | 证据记录：`evidence_id`、task/node/attempt、`event_seq`、`level`、`kind`、`producer`、`timestamp`、`payload_hash`、`artifact_refs`、`prev_hash`、`chain_hash` | 附录 D.3 / P0511–P0526 |
| **Domain Pack** | 领域包：`profile_data`、`required_checks`、`tool_contracts`、`knowledge_seeds`、`render_report` 钩子 | §5.7 / TABLE 24 |
| **KnowledgeUnit** | 知识单元：`kid`、`ktype`、`scope`、`version`、`source_url`、`license`、`effective_at`、`expires_at`、`content_hash`、`supersedes`、`status`、`created_by`、`reviewed_by` | §11.2 / P0272–P0277 |
| **RF-Bench** | ResearchFlow 基准：核心 60 任务、18 类攻击族、四方案、消融、盲测扩展 | §12 / P0293–P0317 |
| **iso-budget** | 同预算对照：相同模型/数据/并发/token/wall-clock/重试规则 | §12.7 / P0313–P0317 |

## 6. 角色与运行组件

| 术语 | 定义 | 来源 |
|---|---|---|
| **Agent Gateway** | 组织六角色调用、模型与工具权限；角色共享模型服务，不是六个常驻大模型进程 | §10.1 / P0255；§5.4 / TABLE 22 |
| **Planner** | 理解目标、选模板、提出 DAG；不写图/状态/证据 | §10.1 / TABLE 40 |
| **Data** | 检查数据结构与质量；不改原始数据、不写 E2 | 同上 |
| **Experiment** | 把配置映射为白名单模板请求；不生成/执行任意代码 | 同上 |
| **Analysis** | 解释指标、提出重算请求；不自签指标证据、不决定 VERIFIED | 同上 |
| **Recovery（角色）** | 诊断错误、提出恢复计划；不直接改图、不签 SPA | 同上 |
| **Verification（角色）** | 提出验证计划、解释差异与缺口；不写 E3、不签报告/凭证 | 同上 |
| **StateMachine** | 运行时状态迁移唯一入口；每次迁移写 `audit_log` | §5.1 / TABLE 20；§6.2 |
| **Executor** | 只执行审核过的内置模板；不裁决成功、不写证据、不持私钥 | §5.1；§17.1 |
| **Collector** | 受控记录者、单写者；追加 E0/E1/E2；分配 `event_seq` | §5.1；§7.1；附录 F.1 |
| **Verifier** | 独立验证、产生 E3、签发报告/凭证；与 Executor 工作目录分离 | §5.1；§9 |
| **Gate** | 规则评估器；不执行实验、不签凭证 | §7.2 |
| **Tool Gateway** | Agent 访问工具的唯一入口；白名单/权限/审计 | §5.1 / TABLE 20；§10.2 / TABLE 41 |

## 7. 常用动词与纪律

| 术语 | 含义 |
|---|---|
| **VERIFIED** | 报告状态：必检证据完整、链/签名/信任锚有效、L3 覆盖满足、无未解释冲突 |
| **PARTIAL** | 报告状态：部分通过但有缺口；映射为节点 `BLOCKED`，不能签发凭证 |
| **FAILED** | 报告状态：验证失败 |
| **BLOCKED** | 报告/节点状态：因缺口、权限、资源或冲突无法继续 |
| **保守重跑** | 无有效 DC 或任一剪枝条件不满足时，必须重新执行，不得剪枝 |
| **可发现篡改** | 哈希链/Merkle 的能力边界；不是“不可篡改” |
| **未测** | 没有真实运行/原始数据支撑的结论；不得写成“已实现/已验证” |
| **计划/设计中** | 尚未实现或尚未验证的功能；不得写成“已完成” |

## 8. 易错表述清单

| 不要写 | 应写 |
|---|---|
| “哈希链不可篡改” | “哈希链可发现篡改（tamper-evident），不抵御同时控制主机/密钥/锚定位置的攻击者” |
| “k 次 bit-exact 证明确定性” | “k 次 bit-exact 是限定条件下的经验性资格，不是数学确定性证明” |
| “v4.3.1 策划书” | “策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）” |
| “L3 层” | “架构层 L3”或“验证级 L3”，必须限定 |
| “T0 已完成六 Agent” | “六 Agent 属于 T1；T0 不开发六 Agent” |
| “E1 可以替代 E2” | “E2 必须来自真实受控执行观测；E1 不等于 E2” |
| “Gate 通过 = 任务完成” | “Gate PASS + Verifier VERIFIED + 有效凭证，才可能 `COMPLETED`” |
| “DONE（研发看板）= COMPLETED（运行时）” | 两套状态严格分离，不得互写 |

## 9. 来源与待确认

- 主要来源：策划书内部 v4.3.0 §3–§12、§15、附录 D/F；`AGENTS.md` §4、§6。
- 待确认：G0 冻结后的正式术语表（本文件不替代契约）；G0 剩余 3 项裁决见 [`state/G0_DECISION_LIST.md`](state/G0_DECISION_LIST.md)。
- 本文件不引入策划书之外的项目目标；`[建议]` 用法已在文中标注。
