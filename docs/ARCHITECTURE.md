# ARCHITECTURE — ResearchFlow 架构基线（G0 已 PASS）

> 状态：G0 已于 2026-11-10 由用户宣布 `PASS`；本文件是架构基线，不是门禁证据，也不替代冻结契约。当前实现/阶段状态以 `docs/state/project_state.json` 为准。
> 基线：策划书**内部 v4.3.0**（文件名标签 v4.3.1；`BLK-002` 已关闭，2026-11-08 用户决议）
> 证据锚点：`P####` → [`02_docx_body.txt`](verification/stage7/02_docx_body.txt)；`TABLE ##` → [`05_docx_tables.txt`](verification/stage7/05_docx_tables.txt)
> 页码说明：DOCX 无可信页码（无 TOC/缓存分页；Word COM 不可用）；引用使用章节号 + `P####` + `TABLE ##`，可在上述文件中逐行核验。
> 标注：`[策划书]` 明确要求；`[建议]` 工程建议（未冻结）；`[待确认]` 需用户/G0 裁决；`[现状]` 已核实事实
> 关键边界：本文件保留架构基线，但**不替代** G0 的 Schema、API、错误码、数据库与规则版本冻结；不得据本文件宣布任何门禁通过。

## 0. 阅读前必读：两组 L1–L3 不是同一件事

| 记号 | 含义 | 来源 |
|---|---|---|
| **架构层 L1–L6** | 交互 / 接入 / 编排控制 / Agent 决策 / 执行 / 证据验证知识 | §5.2 / TABLE 21 |
| **验证级 L1/L2/L3** | 过程完整性 / 结果自洽 / 独立重执行 | §9.1 / TABLE 38 |

本文件写“架构层 L3”或“验证级 L3”时都会显式限定。不要把“验证级 L3”误读为“编排控制层”，也不要把“架构层 L6”误读为“验证级 L3 之上还有 L6”。

## 1. 架构立场

`[策划书]` 平台把 Agent 的自然语言声明视为低等级输入，不直接据此改变任务状态。任务是否完成由 StateMachine 根据 Gate 与独立 Verifier 的结构化结果决定。

来源：§1.1 / P0027；§3.1 / P0058；§5.1 / TABLE 20。

四条不可协商的分离：

1. **写入者隔离**：LLM Agent 无状态库、证据目录与私钥写权限；Agent 只经 Tool Gateway。
2. **状态单入口**：节点状态只能由 `StateMachine.transition()` 改变；无公开 setter；每次迁移写 `audit_log`。
3. **执行与判定分离**：Executor 只执行；Collector 只记录；Gate 只按规则评估；Verifier 才判定与签发。
4. **证据与声明分离**：E0 声明不能推动状态；Gate 只读取结构化证据和规则。

来源：§5.1 / TABLE 20；`AGENTS.md` §4。

四类“面”：

| 面 | 组件 | 不做什么 |
|---|---|---|
| Agent 决策面 | 六个逻辑角色、Agent Gateway | 不写状态/证据/报告/凭证/私钥；不直接执行任意代码 |
| 确定性控制面 | API、DAG、Scheduler、StateMachine、Recovery、Governor、VAS、Gate | 不执行实验；不持私钥；不根据自然语言裁决成功 |
| 受控执行面 | Tool Registry、内置模板 Executor、Workspace、SplitService、资源限制 | 不裁决成功；不写证据库 |
| 独立证据/验证面 | Collector、Evidence Store、Verifier、Certificate、KB、Bench | 不替 Agent 补造证据；不复用 Executor 进程内状态作为独立证据 |

来源：摘要 / P0017；§3.4 / TABLE 16；§10.2 / TABLE 41。

## 2. 六层架构（架构层 L1–L6）

| 层 | 名称 | 职责 | 边界 |
|---|---|---|---|
| **架构层 L1** | 交互层 | 任务输入、DAG、证据中心、报告、基准看板 | 不直接修改状态/证据 |
| **架构层 L2** | 接入层 | REST、Harness Adapter、认证、幂等、事件标准化 | Harness 轨迹默认 E1，不自动等于 E2 |
| **架构层 L3** | 编排控制层 | Planner Router、DAG、Scheduler、StateMachine、Recovery、Governor、VAS、Gate | 不执行实验、不持私钥 |
| **架构层 L4** | Agent 决策层 | 六个逻辑角色：Planner / Data / Experiment / Analysis / Recovery / Verification | 只提交结构化请求，不自由聊天 |
| **架构层 L5** | 执行层 | Tool Registry、内置模板 Executor、Workspace、SplitService、资源限制 | 不裁决成功 |
| **架构层 L6** | 证据/验证/知识层 | Collector、Evidence Store、Verifier、Certificate、KB、Bench | 按进程/权限分离写入 |

来源：§5.2 / TABLE 21。

`[建议]` 实现时把“架构层 L3 的 Gate”与“架构层 L6 的 Verifier”保持为两个独立组件：Gate 负责规则覆盖矩阵与 GAP 输出，Verifier 负责独立执行 L1/L2/L3 并签发报告。二者共享规则版本，但不共享进程内状态。该建议不改变策划书职责划分，只是实现边界建议。

## 3. 组件职责与分离

### 3.1 StateMachine（唯一状态入口）

- `[策划书]` Task/Node 状态只能由 StateMachine 迁移；Agent 不得直接写状态。
- 每次迁移写 `audit_log`；迁移事件包含 `previous_state`、`next_state`、`actor`、`reason_code`、`rule_version`、`correlation_id`。
- 非法迁移一律拒绝；迁移失败也写 `audit_log`。
- 系统重启后先校验数据库、证据链和未完成 attempt，再恢复调度；不得默认把 `RUNNING` 改成 `COMPLETED`。

来源：§5.1 / TABLE 20；§6.2 / TABLE 26；附录 F.1 / P0635–P0640；`AGENTS.md` §4.1–4.2。

`[建议]` 代码层不暴露 `set_state()` 之类的公共写入口；所有迁移通过带前置条件与审计的单一方法；数据库权限与进程边界共同保证“即使绕过应用层也难以直接改状态”。这是实现建议，待 G0 细化。

### 3.2 Executor（只执行）

- 只运行审核过的内置模板；不执行任意用户/Agent 生成的代码。
- 独立子进程/工作目录；记录 PID/attempt、退出码、stdout/stderr 摘要、耗时、资源峰值、产物 SHA-256、环境指纹。
- 不裁决成功；不写 Evidence Store；不持有私钥。
- 超时/资源超限时回收进程树并记录原因。

来源：§5.1 / TABLE 20；§7.1 / TABLE 31；§17.1 / P0427；`AGENTS.md` §4.4–4.5。

### 3.3 Collector（受控记录者，单写者）

- 采集 E0/E1/E2；E2 必须来自真实受控执行观测，不得由 Agent 自述补造。
- 追加写；`event_seq` 单调分配；并发事件先进入单写队列。
- 同一 `event_id` 重复投递只产生一次逻辑记录；原始投递次数可另记 `ingestion_log`。
- 记录 `evidence_id`、task/node/attempt、level、kind、producer、payload_hash、prev_hash、chain_hash、ruleset_version、timestamp。
- 不根据 Agent 声明补造证据；不裁决成功。

来源：§5.1 / TABLE 20；§7.1 / TABLE 31；§7.3 / P0170；附录 F.1 / P0635–P0638；`AGENTS.md` §4.5。

### 3.4 Gate（规则评估）

`[策划书]` 每个 Domain Pack 声明 `RequiredChecks`。Gate 为每项生成 coverage row，至少包含：

`required_check_id`、`evidence_ids`、`level`、`producer`、`hash_status`、`l3_status`、`result`。

Gate 顺序：

1. `validate_schema_and_versions()`
2. `verify_event_sequence_and_hash_chain()`
3. `verify_artifact_hashes_and_producers()`
4. `build_required_check_coverage_matrix()`
5. `reject_unresolved_evidence_conflicts()`
6. `require E2/E3 for execution-critical checks`
7. `require L3/IRC for report-metric source nodes`
8. 全部通过才 PASS；否则输出 `GAP(list)`

任何必检项缺失、哈希不一致、规则版本不匹配或冲突未解释，均不能 `VERIFIED`。

来源：§7.2 / P0159–P0168。

### 3.5 Verifier（独立验证与签发）

- 独立执行 L1/L2/L3；产生 E3；签发 `VerificationReport` 与 `CompletionCertificate`。
- 使用与 Executor 分离的工作目录；不得复用 Executor 的进程内状态作为独立证据。
- L3 必须在新目录、独立进程中，从原始数据真实重新训练/推理；只重算指标或重读 predictions 不算 L3。
- 只有报告 `VERIFIED`、必检证据完整、签名/信任锚有效且规定 L3 覆盖满足时，才签发凭证。

来源：§9.1–9.3 / TABLE 38、P0241–P0245；`AGENTS.md` §4.6、§4.9–4.10。

### 3.6 签名与凭证

- `VerificationReport` 四态：`VERIFIED`、`PARTIAL`、`FAILED`、`BLOCKED`。
- `CompletionCertificate` 只允许由 `VERIFIED` 报告生成；`PARTIAL` 映射为节点 `BLOCKED`，不能签发凭证。
- 签名载荷包含规则版本、证据根和状态；私钥不得进入 Git、日志、证据包或前端。
- 详见 §8。

来源：§7.4 / TABLE 32；附录 D.4 / P0527–P0560；附录 F.2 / I-06、I-07。

### 3.7 Agent Gateway（逻辑角色，不是六个 OS 进程）

- 六个角色由 Agent Gateway 调度，可共用一个模型服务；身份由 `contract_version`、system policy、tool allowlist 和上下文范围共同确定。
- 角色只提交结构化请求/提案；不得直接改图、写状态、写证据、签报告/凭证。
- 模型不可用时回退模板/规则；离线模式通过表单选择模板，仍完成执行、证据、验证与签发。

来源：§10.1 / TABLE 40；§10.4 / P0265–P0266；§5.6 / P0124。

## 4. 运行时状态

### 4.1 四类状态机

| 对象 | 状态迁移 | 约束 |
|---|---|---|
| Task | `CREATED → PLANNING → READY → RUNNING → VERIFYING → COMPLETED/FAILED/BLOCKED/CANCELLED` | 汇总状态由系统产生 |
| Node | `PLANNED → READY → RUNNING → VERIFYING → VERIFIED/FAILED/BLOCKED`；`FAILED → DIAGNOSING → RECOVERING → READY`；`VERIFIED → INVALIDATED → READY` | 10 个状态；`VERIFIED` 唯一入口是 Gate PASS + Verifier VERIFIED + 有效凭证；`INVALIDATED → READY` 需计划存在、`plan_hash` 一致、先冻结后重跑 |
| Evidence | `RECEIVED → VALIDATED → APPENDED`；`INVALID/CONFLICT` | 只追加；无效记录保留并标注 |
| Recovery | `PROPOSED → VALIDATED → APPROVED → EXECUTING → RECHECKED → CLOSED/ESCALATED` | Recovery Agent 只提案，调度器/人工批准 |

来源：§6.2 / TABLE 26；附录 F / TABLE 70；`docs/design/05` §9.2–§9.3；`ADR-001`。

完整迁移表与不变量见 [`docs/state/runtime_states.md`](state/runtime_states.md)。该文件是附录 F 与 `ADR-001` 的对照索引，规范性以 G0 冻结契约为准。

### 4.2 核心不变量

| 编号 | 不变量 |
|---|---|
| I-01 | Agent 不能直接写 Task/Node 状态 |
| I-02 | E0/E1 不能单独满足执行类必检项 |
| I-03 | Verifier 与 Executor 工作目录分离 |
| I-04 | 报告指标来源节点必须达到规定 L3 覆盖 |
| I-05 | 无有效 DC 的节点不能被 SPA 跳过 |
| I-06 | 签名载荷包含规则版本、证据根和状态 |
| I-07 | 非 `VERIFIED` 报告不产生 `CompletionCertificate` |
| I-08 | 离线验签使用外部可信指纹，不信任证书自带公钥 |
| I-09 | `INVALIDATED` 只从 `VERIFIED` 进入，且只能回 `READY` |
| I-10 | stale 证据不得满足必检项；证据不删除 |
| I-11 | 失效/恢复控制事件不是证据：只写 `audit_log` + `evidence_invalidations`，不占用 E0–E3 |
| I-12 | `INVALIDATED → READY` 必须同时满足计划存在、`plan_hash` 一致、先冻结后重跑 |
| I-13 | 报告与证书签名载荷必须含 `schema_version`；验签方拒绝未知 `MAJOR` |
| I-14 | 失败迁移的 `DENIED` 审计在状态回滚后仍存在；二次失败降级结构化 stderr 并计测试缺口 |

来源：附录 F.2 / TABLE 71；`docs/design/05` §10；`ADR-001`；`AGENTS.md` §4.10–4.11。

## 5. 证据等级 E0–E3

| 等级 | 来源 | 写入者 | 典型内容 | 状态作用 |
|---|---|---|---|---|
| **E0** | Agent 声明 | Collector 捕获，标记 `agent_claim` | FINDING、解释、完成声明 | 永不单独推动状态 |
| **E1** | 工具调用、Harness 轨迹、知识检索 | Collector | `tool_name`、`arguments_hash`、`result_ref`、`session_event_ref` | 辅助证明请求/轨迹，不等于真实执行 |
| **E2** | 受控 Executor 进程和产物观测 | Collector 监听执行事件 | PID/attempt、退出码、stdout/stderr 摘要、耗时、资源峰值、产物 SHA-256、环境指纹 | 可覆盖执行类必检项；依赖信任边界 |
| **E3** | Verifier 新目录重算或重执行 | 独立 Verifier | 指标重算、split 校验、重跑结果、差异归因 | 最高等级；关键指标节点必须满足 L3 |

来源：§7.1 / TABLE 31；`AGENTS.md` §4.5–4.8。

关键边界：

- Harness 轨迹默认 E1，不自动等于 E2。
- E0/E1 不得单独满足执行类必检项。
- E2 必须来自真实受控执行观测；Collector 不能根据 Agent 自述补造。
- 外部数据、模型输出、网页内容、MCP 文档默认不是项目证据；不得自动提升证据等级。

来源：`AGENTS.md` §4.5、§4.7–4.8、§8。

## 6. 验证级 L1/L2/L3

| 验证级 | 核查目标 | 执行动作 | 能证明/不能证明 |
|---|---|---|---|
| **L1 过程完整性** | 代码、数据、配置、环境、日志、产物齐全且属于本次运行 | Schema、SHA-256 重算、`event_seq`、Merkle、目录复用检测 | 能证明证据完整与指纹一致；不能证明结果真实 |
| **L2 结果自洽** | 指标可从预测结果重算，划分/口径合理 | 指标重算、字段语义、泄漏五规则 | 能证明内部自洽；不能阻止成套伪造 |
| **L3/IRC 独立重执行** | 新目录、独立进程、原始数据重读、重新训练/推理是否一致 | Split Manifest 校验、配置重放、真实模型重跑、差异归因 | 能支持限定环境的独立重执行；不等于跨环境普遍复现 |

来源：§9.1 / TABLE 38。

L2 数据泄漏五规则：

| 规则 | 检查 | 机器判据 |
|---|---|---|
| R1 重复样本 | 训练/测试是否有重复或近重复样本 | 规范化行哈希/相似度阈值 |
| R2 分组泄漏 | 同一患者/用户/学校/批次是否跨 split | `group_key` 求交集 |
| R3 时序泄漏 | 训练/调参是否使用测试期未来信息 | 时间边界与特征窗口检查 |
| R4 标签/后验字段 | 标签、ID、时间戳或后验字段是否误作特征 | 字段白名单与配置比对 |
| R5 指标来源 | 指标是否来自 test split，能否从 predictions 重算 | split 字段、manifest、metrics 重算、混淆矩阵交叉校验 |

来源：§9.2 / TABLE 39。

L3 独立重执行步骤：

1. Verifier 创建新临时目录、只读挂载原始数据，记录目录和进程标识。
2. 只读原始数据、代码快照、配置快照、依赖锁和系统 Split Manifest；禁止读取原运行 metrics、predictions、模型文件和结果目录。
3. Split Manifest 包含 `dataset_hash`、`split_algorithm/version`、`seed`、`row_id_hash`、`fold_assignment_hash`、`group/time semantics`。
4. 在独立进程真正重跑训练/推理；只重算指标或重读 predictions 不算 L3。
5. 比较预测、指标和产物，按环境、数据、代码、随机性、规则、未知六类归因。

来源：§9.3 / P0241–P0245。

等价性判定：

- 确定性模式要求 bit-exact；不一致即不授予 DC。
- 随机性模式使用预注册种子集合（建议至少 5 个），报告均值/标准差和任务级分布，并用 TOST 检验预先定义的等价边界。
- 等价边界必须在正式运行前根据独立预实验确定并哈希冻结。

来源：§9.4 / P0247。

## 7. Gate、报告与凭证的判定链

```text
执行事件 / 产物
  → Collector 追加 E0/E1/E2
  → Gate 校验 Schema、版本、事件顺序、哈希链、产物、必检覆盖、冲突、E2/E3、L3
  → 全部通过？ ── 否 → GAP(list) / PARTIAL / FAILED / BLOCKED
                └ 是 → Verifier 独立验证（L1/L2/L3）
                        → VerificationReport = VERIFIED
                        → 签名
                        → CompletionCertificate（仅 VERIFIED）
                        → Evidence Bundle
                        → 第三方离线验签
```

来源：§5.3 / P0099–P0108；§7.2 / P0159–P0168；§7.4 / TABLE 32；§9.5 / P0249–P0251。

签发条件（全部满足）：

1. 报告状态 `VERIFIED`；
2. 必检证据完整；
3. 签名与信任锚有效；
4. 规定 L3 覆盖满足；
5. 无未解释冲突；
6. 规则版本匹配。

来源：`AGENTS.md` §4.10；§7.2；§7.6 / TABLE 33；附录 F.2。

## 8. Ed25519 / JCS / Merkle 与离线验签

### 8.1 JCS

- 签名载荷用 RFC 8785 JCS 生成规范化 UTF-8 字节串，再添加对象类型域分离前缀，并用 Ed25519（RFC 8032）签名。
- JCS 递归排序 JSON 对象属性名；**数组元素顺序必须保持原样**，数组内对象属性仍递归规范化；不得把数组整体按字典序重排。
- 拒绝重复键、NaN、Infinity 和非法 Unicode；时间统一 RFC 3339 UTC；数值字段采用明确 Schema 类型与精度。
- 签名字段采用版本化白名单；未知字段不得静默纳入或忽略；Schema 升级必须提高版本号。
- 公钥不作为自证信任来源；验签工具预置可信指纹/信任根；域分离前缀分别用于 Report、Certificate、DC、SPA。

来源：§7.5 / P0173–P0178；附录 D.6 / P0574–P0579。

### 8.2 Merkle 与哈希链

- 证据按 `event_seq` 顺序追加；记录 `evidence_id`、task/node/attempt、level、kind、producer、payload_hash、prev_hash、chain_hash、ruleset_version、timestamp。
- Merkle 按 RFC 9162：叶节点使用 `0x00` 前缀，内部节点使用 `0x01` 前缀；输入顺序固定为 `event_seq`；必须实现 inclusion proof 并用标准测试向量/跨语言测试。
- 哈希链和 Merkle 提高篡改**可发现性**，不抵御同时控制主机、数据库、密钥和锚定位置的攻击者。
- 准确术语是 **tamper-evident**，不是“绝对不可篡改”。

来源：§7.3 / P0170；§7.7 / P0185；`AGENTS.md` §4.12。

### 8.3 密钥生命周期

| 环节 | 要求 | 验收 |
|---|---|---|
| 生成 | Verifier 初始化或受控密钥工具生成；开发密钥与交付信任锚分开 | 私钥不进入 Git、日志、证据包或前端 |
| 存储 | 受限目录/ACL/系统密钥存储；最小权限 | Agent/Executor 读取私钥失败 |
| 信任 | `verify_bundle.py` 预置公钥指纹；不信任证书自带公钥 | 换公钥和指纹的伪造包被拒绝 |
| 轮换 | `key_id`、有效期、撤销列表；明确历史证书策略 | 轮换/撤销演练通过 |
| 锚定 | 优先独立时间戳或第二存储；本地副本只称备份 | AnchorProof 独立验证；缺失标 `absent` |

来源：§7.6 / TABLE 33。

### 8.4 Evidence Bundle 与离线验签

证据包至少包含：

`bundle_manifest.json`、`task_spec.json`、`graph.json`、`evidence.jsonl`、`artifact_manifest.json`、`split_manifest.json`、`verification_report.json`、`completion_certificate.json`、`merkle_proofs`、`anchor_proof`（如有）、`trusted_key_fingerprint`、`verify_bundle.py`、`README` 和必要的轻量复核数据。

```text
python verify_bundle.py ./evidence_bundle --trust-store ./trusted_keys.json
```

离线工具必须覆盖五类负例：

1. 修改证据 payload；
2. 替换公钥；
3. 删除 `split_manifest`；
4. 修改报告状态；
5. 破坏签名。

真包通过；负例按预期拒绝。`verify_bundle.py` 必须独立于数据库和模型运行；离线验签必须使用外部可信指纹/信任锚。

来源：§9.5 / P0249–P0251；`AGENTS.md` §4.11、§4 补充边界。

## 9. 调度、恢复、DC/SPA/VAS（T1/T2 范围）

> `[策划书]` 这些机制主要属于 T1/T2；**T0 不要求完整动态调度、DC/SPA、VAS**。不得把本节的机制写成 T0 已完成。

### 9.1 四个决策组件

| 组件 | 决定什么 | 不决定什么 |
|---|---|---|
| Ready Scheduler | READY 节点执行顺序 | 不决定验证预算 |
| Governor | 并发与资源水位 | 不决定重跑子图 |
| Recovery | 失败后哪些节点失效、哪些必须重跑 | 不替代 Scheduler |
| VAS | 有限验证预算投向哪些验证项 | 不剪枝执行节点 |

DC/SPA 是 Recovery 的安全剪枝依据，不替代 Scheduler。

来源：§8.1 / P0190。

### 9.2 DC（确定性资格凭证）

`[策划书]` DC 不是数学意义上的普遍确定性证明，而是对某节点类型、固定输入结构、代码版本、依赖锁、环境指纹和规则版本，在受控条件下观察到 k 次跨进程、跨目录 bit-exact 一致的经验性资格。仅纯函数、无外部副作用、输入可完整枚举的节点可申请。

| 条件 | 要求 | 不满足时 |
|---|---|---|
| 节点纯度 | 无数据库写入、网络请求、全局状态修改、当前时间/随机外部源依赖 | 永不签 DC |
| 输入固定 | 数据、配置、代码、模板、依赖与上游哈希一致 | DC 失效 |
| 环境指纹 | OS/架构/CPU、Python、依赖锁、关键库、线程变量、locale/timezone、种子策略 | 环境变化即失效 |
| 重复执行 | 默认 k=3 独立进程/目录；敏感因素增加探针 | 任一产物/指标不 bit-exact，不签 DC |
| 随机性节点 | 预期具有随机波动的训练/采样节点不签 DC | 用多种子/TOST 评估，不允许 DC 剪枝 |
| 有效期 | DC 带 `expires_at`、`ruleset_hash`、`code_hash`、`input_schema_hash` | 到期/规则变更后重新评估 |

来源：§8.2 / P0192、TABLE 34。

### 9.3 SPA（省略溯源凭证）

只有同时满足以下条件才允许 SPA：

1. 节点类型存在有效 DC，且输入结构、代码、环境和规则版本与当前一致。
2. 所有直接前驱输出哈希与恢复前历史一致；上游变化沿 DAG 传播失效。
3. 磁盘产物现场重算 SHA-256，与历史证据一致；解析软链接后不得越界或指向旧目录。
4. 节点旧证据在当前规则集下仍通过 Gate，未过期、未撤销、无新冲突。
5. 节点无副作用，且任务规则未要求本次必须实际执行。

来源：§8.3 / P0195–P0200。

### 9.4 定向恢复

```text
affected = descendants(failed_node) ∪ {failed_node}
for node in topological_order(affected):
    if node == failed_node or not retryable(node): retry_or_escalate()
    elif has_side_effect(node): reexecute()
    elif not evidence_valid(node): reexecute()
    elif not predecessor_hashes_unchanged(node): reexecute()
    elif not valid_DC(node, current_env): reexecute()
    elif not disk_rehash_matches(node): reexecute()
    elif not gate_passes_under_current_rules(node): reexecute()
    else: sign_SPA(node, all_checks)
return immutable_plan
```

恢复计划在执行前冻结；先算受影响子图再执行，避免运行中上游变化造成剪枝判据前后不一致。未持有 DC 的节点一律保守重跑。

来源：§8.4 / P0201–P0214。

### 9.5 Ready Scheduler / Governor / VAS

Ready Scheduler 初始评分：

```text
SchedScore(n) = 0.30·CriticalPath + 0.25·Risk + 0.20·Age
              + 0.15·ResourceFit + 0.10·UserPriority
```

各特征归一化到 `[0,1]`；Age 防止饥饿；权重为配置初值，须通过历史回放和敏感性分析校准，不声称理论最优。

来源：§8.5 / P0216–P0218。

Governor 初始策略（**待校准**，不是硬阈值）：

| 监控项 | 初始策略 | 触发动作 |
|---|---|---|
| 内存 | 软/硬阈值按应用预算配置；70%/85% 仅作初始待校准值 | 软阈值减并发/暂停非关键新任务；硬阈值停止派发并回收超限子进程 |
| CPU | 持续高负载阈值可配置，例如 85% 持续 30 秒 | 降低并发或调整低优先级任务 |
| 磁盘 | 工作区剩余空间、产物大小、日志增长 | 停止新任务；只清理临时缓存，不删证据 |
| 预算 | token、wall-clock、验证预算、重试次数 | 切换模板/模型、减少非关键验证，保留强制 L3 |
| 进程 | 超时、僵尸进程、子进程树未退出 | 按进程组/Job Object 回收并记录原因 |

来源：§8.6 / TABLE 36。

VAS：

```text
R_i = 0.25·F_i + 0.20·N_i + 0.20·G_i + 0.20·I_i + 0.15·A_i
Utility_i = R_i × CoverageBenefit_i
Priority_i = Utility_i / max(EstimatedCost_i, ε)
maximize Σ Utility_i·x_i   subject to Σ Cost_i·x_i ≤ Budget
x_i = 1 for mandatory verification nodes
```

F 为历史失败风险（Beta-Binomial 平滑）；N 为输入/配置新颖度；G 为证据缺口；I 为下游/报告影响；A 为异常信号。强制集合至少包括最终报告节点、报告指标来源节点、证据完整性异常节点和安全关键节点；强制节点不得被预算优化排除。节点少时用动态规划求精确解；节点多时可用贪心近似，并报告相对小规模最优解的差距。

来源：§8.7 / P0222–P0229。

四种验证预算策略：随机、固定拓扑序、报告优先、风险优先；用于同预算对照。来源：§8.8 / TABLE 37。

## 10. 数据流

### 10.1 任务流

```text
用户/Harness
  → API/Adapter
  → Planner
  → DAG Builder
  → Scheduler
  → StateMachine
  → Executor（内置模板）
  → 产物与运行事件
```

### 10.2 证据流

```text
Agent 声明(E0) / 工具调用(E1) / Executor 观测(E2)
  → Collector（单写者、event_seq、哈希链）
  → Gate
  → Verifier（L1/L2/L3、独立重执行）
  → VerificationReport
  → VERIFIED 才签发 CompletionCertificate
  → Evidence Bundle
  → 第三方离线复核
```

### 10.3 恢复流

```text
节点失败
  → 错误签名
  → 受影响子图
  → Recovery Proposal
  → Scheduler 校验/审批
  → DC/SPA 条件检查
  → 必须重跑节点 + 可合法省略节点
  → 重新验证
```

来源：§5.3 / P0099–P0113。

## 11. 部署边界与资源预算

### 11.1 第一版边界

- Windows 11 单机；16GB 内存；CPU-only；默认并发 2；轻量数据；远端模型或无模型模式。
- 不部署本地大模型；不强制 Docker；不默认开放网络；不执行任意用户代码。
- 受控子进程不等于安全沙箱；开放外部代码时必须升级容器/microVM、只读挂载和网络出口控制。

来源：§4.1 / P0074；§5.4 / P0116；§5.6 / P0122；§17.1 / P0427。

### 11.2 进程与初始资源预算（设计值，不是实测）

| 进程 | 职责/方式 | 初始资源约束 |
|---|---|---|
| API + Orchestrator | REST、任务、DAG、调度和状态机 | 约 1.0–1.5GB；状态单入口 |
| Agent Gateway | 组织六角色调用、模型和工具权限 | 逻辑角色共享模型服务，不启动六个大模型常驻进程 |
| Executor ×2 | 白名单模板，独立子进程/工作目录 | 每 worker 约 0.6–1.2GB；默认并发 2 |
| Collector | 追加写 E0/E1/E2，分配 event_seq | 约 0.1–0.2GB；队列积压告警 |
| Verifier | L1/L2/L3、独立重执行、报告和签名 | 约 0.4–1.0GB；新目录、不共享 Executor 工作区 |
| Streamlit | 工作台 | 约 0.3–0.6GB |
| SQLite WAL/日志 | 状态、审计和证据元数据 | 约 0.2–0.5GB；容量实测 |
| 可选本地 LLM | 自然语言理解/解释 | 非核心依赖，单独核算内存 |

来源：§5.4 / TABLE 22。

> 以上是**设计预算**，不是硬件承诺。16GB 单机默认无 GPU、并发 2；每轮测试必须记录进程树 RSS、CPU、磁盘与峰值时间。并发 2 未实测前不得宣称达成。

## 12. Domain Pack 与技术选型

### 12.1 Domain Pack 钩子

| 钩子 | 职责 | 约束 |
|---|---|---|
| `profile_data` | 数据画像：字段、缺失、分布、标签、分组/时间字段 | 只读数据，结果由 Collector 记录 |
| `required_checks` | 声明领域必检项与规则版本 | 规则可机器判定且有测试 |
| `tool_contracts` | 白名单工具、参数 Schema、超时和资源限制 | 禁止任意 shell/Python 入口 |
| `knowledge_seeds` | 领域规范、工具说明、故障案例 | 来源、许可、版本和 hash 齐全 |
| `render_report` | 渲染领域报告 | 只展示 Verifier 结果，不修改判定 |

来源：§5.7 / TABLE 24。

### 12.2 技术选型（策划书建议，不是冻结依赖）

| 领域 | 建议技术 | 自研边界 |
|---|---|---|
| API/模型 | Python 3.11、FastAPI、Pydantic v2 | 自研任务/证据/报告/凭证 Schema |
| 持久化/DAG | SQLite WAL、NetworkX | 自研状态机、失效传播、剪枝判定 |
| 实验执行 | scikit-learn、pandas、Python 子进程 | 只运行内置模板 |
| 界面/检索 | Streamlit、FTS5/BM25 | 自研工作台、知识绑定与留痕 |
| 密码学 | hashlib、cryptography、Ed25519、JCS、RFC 9162 Merkle | 复用标准算法，自研证据协议与签名载荷 |
| Harness | DeepSeek Harness Cordis 插件首适配 | 不替换 Harness 运行时 |

来源：§5.5 / TABLE 23；§15.4 / TABLE 58。

`[现状]` 以上依赖已在 WP-01 锁定：`.venv` 使用 Python 3.11.16（64 位），`requirements.lock` 锁定 58 个包；实际版本与偏差见 `docs/verification/t0/wp-01/`。这表示依赖基线已建立，不表示架构各层已实现。

## 13. 当前实现状态与 G0 缺口

### 13.1 当前状态（`[现状]`）

| 项 | 状态 |
|---|---|
| 业务代码 | 部分实现：Pydantic 契约模型 + `POST/GET /api/v1/tasks`；其余未实现 |
| 契约/Schema | 5 份冻结 JSON Schema v1.0 + 72 个正反例 |
| StateMachine / DB / 审计 | 未实现；P2 设计件已验收（2026-11-12），实现未开始 |
| Executor / Collector / Gate / Verifier | 未实现；P3–P5 设计件已验收（2026-11-12） |
| 密码学 / 离线验签 | 未实现；P6 设计件已验收（2026-11-12） |
| 前端 | 未实现 |
| T0 | 进行中 |
| G0–G7 | G0 `PASS`；G1–G7 `NOT_STARTED` |

### 13.2 G0 冻结时的缺口（历史清单，已由 G0 文档包处置）

- Task / Node / Evidence / Report / Certificate 的完整 JSON Schema；
- REST API 路径、请求/响应字段与错误码表；
- 数据库表结构、索引、迁移策略；
- `gates.yaml`、`limits.yaml`、`security.yaml` 等配置的最终字段；
- 规则版本命名与哈希口径；
- 信任锚、密钥轮换与撤销的具体实现；
- 进程/目录隔离与权限测试的具体实现；
- 并发 2、16GB 内存下的资源验收口径；
- ~~**策划书基线版本（`BLK-002`）**~~（已于 2026-11-08 由用户决议：内部 v4.3.0 为内容基线，v4.3.1 仅为文件名标签；不再列为 G0 缺口）。

> 上述清单是 G0 冻结前的历史缺口记录，不代表当前仍未冻结。G0 已于 2026-11-10 `PASS`；当前实现状态见 `docs/state/project_state.json`。

来源：§7.2、§7.6、§15.3、附录 D/E/F；`docs/memory/architecture-decisions.md` §7。

## 14. 待确认与建议

### 14.1 待用户确认

1. ~~`BLK-002`：以内部 v4.3.0 还是文件名 v4.3.1 为基线；是否存在真正的 v4.3.1 内容。~~ **已决（2026-11-08）**：内部 v4.3.0 为内容基线，v4.3.1 仅为文件名标签。
2. G0 冻结时的 3 项裁决已由 G0 文档包关闭；历史记录见 [`state/G0_DECISION_LIST.md`](state/G0_DECISION_LIST.md)。
3. 是否采用策划书建议的技术栈与进程预算。
4. 并发 2 的最终验收口径。

### 14.2 工程建议（未冻结）

- `[建议]` 先冻结 contracts，再写 StateMachine；不要先做前端或六个 Agent（与 §15.5 开发顺序一致）。
- `[建议]` StateMachine 的数据库写权限与 API 进程分离；审计日志与状态表同事务写入。
- `[建议]` Executor 与 Verifier 使用不同 OS 用户/工作目录/进程树；验证器只读挂载原始数据。
- `[建议]` 哈希链、Merkle、JCS、Ed25519 先做标准测试向量，再接业务；不要自创编码。
- `[建议]` Gate 输出结构化 `GAP`，不要用自由文本解释代替缺口码。
- `[建议]` 任何“实时演示”与“预录/预生成”必须显式区分；不得把预录画面说成实时执行。

这些建议不改变策划书的核心目标与不可协商约束；如与 G0 冻结决策冲突，以冻结契约为准。

## 15. 来源索引

| 主题 | 章节/锚点 |
|---|---|
| 定位与判定立场 | §1.1 / P0026–P0027 |
| 四类面 | 摘要 / P0017 |
| 五条架构原则 | §5.1 / TABLE 20 |
| 六层架构 | §5.2 / TABLE 21 |
| 数据流 | §5.3 / P0099–P0113 |
| 资源预算 | §5.4 / TABLE 22 |
| 技术选型 | §5.5 / TABLE 23；§15.4 / TABLE 58 |
| 四类状态机 | §6.2 / TABLE 26 |
| 消息协议 | §6.3 / TABLE 27 |
| REST API | §6.4 / TABLE 28 |
| E0–E3 | §7.1 / TABLE 31 |
| Gate | §7.2 / P0159–P0168 |
| 哈希链/Merkle | §7.3 / P0170 |
| 报告/凭证 | §7.4 / TABLE 32 |
| JCS/Ed25519 | §7.5 / P0173–P0178 |
| 密钥生命周期 | §7.6 / TABLE 33 |
| 四类决策组件 | §8.1 / P0190 |
| DC | §8.2 / P0192、TABLE 34 |
| SPA | §8.3 / P0195–P0200 |
| 定向恢复 | §8.4 / P0201–P0214 |
| Scheduler/Governor/VAS | §8.5–8.8 / P0216–P0230 |
| L1/L2/L3 | §9.1 / TABLE 38 |
| 泄漏五规则 | §9.2 / TABLE 39 |
| L3 步骤 | §9.3 / P0241–P0245 |
| Evidence Bundle | §9.5 / P0249–P0251 |
| 六角色/权限 | §10.1–10.2 / TABLE 40、41 |
| T0/T1/T2 | §15.2 / TABLE 56 |
| G0–G7 | §15.3 / TABLE 57 |
| 开发顺序 | §15.5 / P0386–P0395 |
| 仓库结构建议 | §15.6 / P0397–P0406 |
| 安全边界 | §17.1 / P0427 |
| 最终验收 | §18.1 / P0446–P0454 |
| 状态迁移/不变量 | 附录 F / TABLE 70、71 |
| T0 清单 | 附录 J / TABLE 78 |

## 16. 相关文件

- [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md)
- [`SECURITY_POLICY.md`](SECURITY_POLICY.md)
- [`DEVELOPMENT_WORKFLOW.md`](DEVELOPMENT_WORKFLOW.md)
- [`GLOSSARY.md`](GLOSSARY.md)
- [`state/runtime_states.md`](state/runtime_states.md)
- [`memory/architecture-decisions.md`](memory/architecture-decisions.md)
- [`reference/SOURCE_REGISTER.md`](reference/SOURCE_REGISTER.md)
- [`reference/CONFLICT_REPORT.md`](reference/CONFLICT_REPORT.md)
