# 04 架构与信任边界（G0 冻结 v1.0）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v0.2（候选）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ④ v1.0（G0 冻结）**；**不是 G0 门禁 PASS，不是 T0 开发批准**。
> 日期：2026-11-10（Asia/Shanghai）；候选期内容更新于 2026-11-09。
> 候选期 v0.2 变更：只同步已关闭 OQ（`OQ-ARCH-1/2` → 已决）与基线版本引用；**架构分层、组件边界、信任边界均未改**。
> 基线：策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）；术语按 [01_BASELINE_AND_TERMS.md](../G0/01_BASELINE_AND_TERMS.md) v1.0；需求按 [02_REQUIREMENT_TRACEABILITY.md](../PRD/02_REQUIREMENT_TRACEABILITY.md) v1.0。
> 标注：`【策划书】` 原文明确；`【用户决议】` 2026-11-08/09 书面裁决；`【工程建议】` 未冻结；`【OPEN QUESTION】` 原文未定义。
> 边界：本文只写架构与信任边界，不写字段级 Schema（见 ⑤）、不写 API/DB 细节（见 ⑥）、不写测试矩阵（见 ⑦）。不提前设计超出策划书的复杂架构。

## 1. 架构立场

### 1.1 核心判定立场

【策划书】平台把 Agent 的自然语言声明视为**低等级输入**，不直接据此改变任务状态。任务是否完成由 StateMachine 根据 Gate 与独立 Verifier 的结构化结果决定（§1.1 / P0027；§3.1 / P0058；§5.1 / TABLE 20）。

【策划书】五条不可协商原则（§5.1 / TABLE 20）：

| 原则 | 设计要求 | 代码保证方向 |
|---|---|---|
| 写入者隔离 | LLM Agent 无状态库、证据目录与私钥写权限 | Agent 只经 Tool Gateway；权限拒绝测试 |
| 状态单入口 | 节点状态只能由 `StateMachine.transition()` 改变 | 无公开 setter；每次迁移写 `audit_log` |
| 执行与判定分离 | Executor 只执行；Collector 只记录；Verifier 才判定/签发 | 独立进程、独立工作目录和文件权限 |
| 证据与声明分离 | E0 声明不能推动状态 | Gate 只读取结构化证据和规则 |
| 外部可复核 | 证据包离开数据库和模型仍可验签 | `verify_bundle.py` 离线运行，正负例齐全 |

### 1.2 四类“面”

【策划书】摘要 / P0017；§3.4 / TABLE 16；§10.2 / TABLE 41：

| 面 | 组件 | 不做什么 |
|---|---|---|
| **Agent 决策面** | 六个逻辑角色、Agent Gateway | 不写状态/证据/报告/凭证/私钥；不执行任意代码 |
| **确定性控制面** | API、DAG、Scheduler、StateMachine、Recovery、Governor、VAS、Gate | 不执行实验；不持私钥；不凭自然语言裁决成功 |
| **受控执行面** | Tool Registry、内置模板 Executor、Workspace、SplitService、资源限制 | 不裁决成功；不写证据库 |
| **独立证据/验证面** | Collector、Evidence Store、Verifier、Certificate、KB、Bench | 不补造证据；不复用 Executor 进程内状态作为独立证据 |

【用户决议】T0 只实现“确定性控制面（不含 Scheduler/Governor/VAS）+ 受控执行面 + 独立证据/验证面”；Agent 决策面在 T0 不存在。

### 1.3 T0 的架构子集

| 面 | T0 是否实现 | 说明 |
|---|---|---|
| Agent 决策面 | **否** | 六角色、消息协议、Tool Gateway 属 T1 |
| 确定性控制面 | **部分** | API、DAG Builder（静态）、StateMachine、Gate、WP-R 失效传播；**无** Scheduler/Governor/VAS |
| 受控执行面 | **是** | Tool Registry（内置模板白名单）、Executor、Workspace、SplitService、资源限制 |
| 独立证据/验证面 | **是** | Collector、Evidence Store、Verifier L1/L2/L3、Certificate、verify_bundle；**无** KB/Bench |

## 2. 六层架构（架构层 L1–L6）

【策划书】§5.2 / TABLE 21：

| 层 | 名称 | 职责 | 边界 | T0 范围 |
|---|---|---|---|---|
| **L1** | 交互层 | 任务输入、DAG、证据中心、报告、基准看板 | 不直接修改状态/证据 | 最小工作台：任务、DAG、证据、报告四视图；无基准看板 |
| **L2** | 接入层 | REST、Harness Adapter、认证、幂等、事件标准化 | Harness 轨迹默认 E1，不自动等于 E2 | 本地 REST + 幂等；**无** Harness Adapter |
| **L3** | 编排控制层 | Planner Router、DAG、Scheduler、StateMachine、Recovery、Governor、VAS、Gate | 不执行实验、不持私钥 | DAG Builder（静态）、StateMachine、Gate、WP-R；**无** Planner Router/Scheduler/Governor/VAS/完整 Recovery |
| **L4** | Agent 决策层 | 六逻辑角色 | 只提交结构化请求，不自由聊天 | **不实现** |
| **L5** | 执行层 | Tool Registry、内置模板 Executor、Workspace、SplitService、资源限制 | 不裁决成功 | 全部实现，仅内置表格 ML 模板 |
| **L6** | 证据/验证/知识层 | Collector、Evidence Store、Verifier、Certificate、KB、Bench | 按进程/权限分离写入 | Collector/Store/Verifier/Certificate/verify_bundle；**无** KB/Bench |

命名警告：架构层 `L3`（编排控制层）不是验证级 `L3`（独立重执行）。本文写“架构层 L3”或“验证级 L3”时必须带限定语；详见 01 §4.4。

## 3. 模块职责与边界

### 3.1 职责表

| 模块 | 层 | 职责 | 输入 | 输出 | 依赖 | 禁止行为 | 单写者 | 阶段 |
|---|---|---|---|---|---|---|---|---|
| API | L2 | 接收任务、查询状态/证据/报告、触发验证 | REST 请求、TaskSpec | 响应、错误码 | Contracts、StateMachine | 不直接改状态；不写证据 | 否（只转发） | T0 |
| Contract Registry | L2 | 加载/校验契约版本与 Schema | `contracts/` | 校验结果、版本号 | 无 | 不执行实验；不裁决 | 否 | T0 |
| DAG Builder | L3 | 静态建图与校验（节点/边、拓扑、环、孤立节点、重复边、缺失依赖、图版本） | TaskSpec、节点/边声明 | 校验通过的图、`graph_version`、拓扑序 | Contracts | 不做运行时调度；不改图 | 否（图由持久层保存） | T0 |
| StateMachine | L3 | 运行时 Task/Node 状态迁移唯一入口 | 迁移请求（previous/next、actor、reason_code、rule_version、correlation_id） | 新状态 + `audit_log` | DB、Contracts | 不执行实验；不裁决证据 | **是**（状态 + audit） | T0 |
| Invalidation / WP-R | L3 | 失效传播、恢复计划生成与冻结、保守重跑编排 | 上游变化、DAG、证据、attempt | 失效记录、恢复计划、重跑请求 | DAG、StateMachine、Collector | 不做 DC/SPA；不自动诊断；不改写已冻结计划 | 否（经 StateMachine 写状态） | T0（`WP-R`） |
| Gate | L3 | 按 `RequiredChecks` 生成覆盖矩阵、校验链/哈希/版本/冲突/等级/L3 | 证据集、规则版本 | coverage matrix、`GAP`/PASS | Collector、Contracts | 不执行实验；不签凭证；不修改证据 | 否（只读） | T0 |
| Tool Registry | L5 | 白名单模板注册与查找 | 模板清单 | 模板句柄/拒绝 | Contracts | 不接受任意代码路径 | 否 | T0 |
| Executor | L5 | 在独立工作目录/子进程执行内置模板，记录退出码、产物哈希、资源峰值 | 模板 + 参数 + workspace | 执行事件、产物 | Tool Registry、资源限制 | 不裁决成功；不写证据库；不持私钥 | 否（执行事件交 Collector） | T0 |
| Workspace / SplitService | L5 | 每 attempt 独立目录；数据划分清单生成 | 数据引用、参数 | 工作目录、Split Manifest | 资源限制 | 不复用他人目录；不越界读取 | 否 | T0 |
| Collector | L6 | E0/E1/E2 受控记录；`event_seq` 单调；哈希链 | 执行/工具/声明事件 | EvidenceRecord、链哈希 | Evidence Store、DB | 不补造证据；不改写历史 | **是**（证据库 + 序号） | T0 |
| Evidence Store | L6 | 证据追加存储与查询 | EvidenceRecord | 证据记录/查询结果 | DB | 不删除/不原位覆盖 | **是**（由 Collector 写） | T0 |
| Verifier | L6 | 独立执行 L1/L2/L3，产生 E3，签发报告/凭证 | 证据包、原始数据、配置、Split Manifest | `VerificationReport`、`CompletionCertificate`、E3 | Evidence Store、签名 | 不复用 Executor 进程内状态；不写状态；不伪造重跑 | **是**（报告/证书/E3） | T0 |
| Signing / Key Mgmt | L6 | Ed25519 签名、验签、`key_id`/指纹管理 | 签名载荷、私钥句柄 | 签名、指纹 | 无 | 私钥不进 Git/日志/证据包/前端 | **是**（密钥操作） | T0 |
| Bundle Exporter | L6 | 导出 Evidence Bundle | 证据、报告、证书、证明 | 包目录 | 上述全部 | 不改判定；不内嵌私钥 | 否 | T0 |
| `verify_bundle.py` | 独立工具 | 离线验签真包/负例 | 包目录、外部信任锚 | 验签结果 | 仅标准库/密码学库 | 不连数据库；不连模型；不信包内公钥 | 不适用 | T0 |
| 最小工作台 | L1 | 任务、DAG、证据、报告四视图 | API | 页面 | API | 不直接改状态/证据 | 否 | T0 |
| Harness Adapter | L2 | Harness 事件映射 | Harness 事件 | 标准化事件 | 契约 | 轨迹默认 E1 | 否 | T2 |
| Planner/Scheduler/Governor/VAS/Recovery Agent | L3/L4 | 动态规划、调度、资源、验证预算、完整恢复 | — | — | — | — | — | T1/T2 |
| KB / Bench | L6 | 知识治理、基准与统计 | — | — | — | — | — | T1/T2 |

### 3.2 依赖方向

【工程建议】依赖只允许向下或同层只读，禁止反向：

```text
L1 交互 → L2 接入 → L3 编排控制 → L5 执行
                        ↘ L6 证据/验证
L4 Agent（T1）→ 只经 Tool Gateway 调 L5，只读 L6
```

约束：

1. L5 不调用 L3；执行结果只能作为事件交给 Collector。
2. L6 的 Verifier 不调用 L5 的 Executor，而是自建独立进程执行重跑。
3. L3 的 Gate 只读 L6 证据，不写证据。
4. L1 只调用 L2 API，不直连数据库。

## 4. 信任边界

### 4.1 威胁模型（T0 相关）

【策划书】§3.4 / TABLE 16：

| 主体 | 信任假设 | 允许/禁止边界 |
|---|---|---|
| LLM Agent | 可能出错或不诚实 | 可提计划/请求/解释；不可写状态、证据、报告或私钥（T1 才存在） |
| StateMachine | 可信计算基组件 | 唯一状态迁移入口；不执行实验、不签凭证 |
| Executor | 运行审核过的内置模板 | 只执行；不裁决成功、不持私钥 |
| Collector | 可信记录服务，单写者追加写 | 采集 E0/E1/E2；不根据自述补造证据 |
| Verifier | 独立于 Executor 的验证进程 | L1/L2/L3、写 E3、签发报告/凭证 |
| 本机 root/主机完全失陷 | 不在 MVP 可防御范围 | 不宣称抵御同时控制主机、数据库、密钥和锚定位置的攻击者 |

### 4.2 五个核心组件的信任边界

| 组件 | 信任级别 | 可信输入 | 必须拒绝的输入 | 边界实现（T0） |
|---|---|---|---|---|
| **StateMachine** | 可信计算基 | 已校验的迁移请求（含 actor/reason/rule_version/correlation_id） | 任何旁路写、过期 previous_state、非法迁移 | 唯一写入口；无公开 setter；DB 写权限只授予它；成功/失败都写 `audit_log` |
| **Executor** | 受控但不可信其结论 | 白名单模板 ID、已校验参数 | 未注册模板、任意代码/脚本路径、越界路径、运行期安装依赖 | 独立子进程 + 独立工作目录 + 资源上限 + 进程树回收；只产出事件与产物 |
| **Collector** | 可信记录者 | 真实执行事件、工具调用、Agent 声明（标记 E0） | 自述补造的“执行证据”、重复 `event_id`、乱序/缺口 | 单写者；`event_seq` 单调；追加写；链哈希；队列积压告警 |
| **Gate** | 规则评估器 | 证据集、`RequiredChecks`、`rule_version` | 缺必检项、哈希不符、版本不匹配、未解释冲突、stale 证据 | 只读；结构化 `GAP`；不写证据、不签凭证 |
| **Verifier** | 独立验证与签发者 | 证据包、原始数据、配置、Split Manifest、私钥句柄 | 复用 Executor 进程内状态、旧产物、假 L3、非 `VERIFIED` 却要求签发 | 独立进程 + 新目录 + 只读原始数据；L3 真实重训/推理；签发前校验六项条件 |

### 4.3 单写者权限矩阵

图例：`W` = 唯一写者；`A` = 追加写；`R` = 只读；`—` = 禁止。

| 对象 | StateMachine | Executor | Collector | Gate | Verifier | API | Agent（T1） | 人工/工具 |
|---|---|---|---|---|---|---|---|---|
| Task/Node 状态 | **W** | — | — | — | — | — | — | — |
| `audit_log` | **W**（同事务） | — | — | — | — | — | — | — |
| EvidenceRecord（E0/E1/E2） | — | — | **W**（追加） | R | R | R | — | — |
| EvidenceRecord（E3） | — | — | — | R | **W**（追加） | R | — | — |
| VerificationReport | — | — | — | R | **W** | R | — | — |
| CompletionCertificate | — | — | — | — | **W**（仅 `VERIFIED`） | R | — | — |
| 私钥 | — | — | — | — | **W**（经 Key Mgmt） | — | — | 受控工具 |
| 公钥/信任锚指纹 | — | — | — | — | R | R | — | **W**（受控流程） |
| DAG/图版本 | **W**（经审批的图变更；T0 只建图） | — | — | — | — | — | 提案（T1） | 审批 |
| 恢复计划（WP-R） | **W**（冻结时写入并通过状态迁移） | — | — | — | — | 触发 | — | — |
| Evidence Bundle | — | — | — | — | **W**（导出） | — | — | 只读复制 |

规则：

1. 任何组件不得同时拥有“执行”和“判定/签发”权限。
2. Collector 与 Verifier 都写证据库，但只写各自等级；任何一方不得改写另一方记录。
3. API 永远不是任何对象的写者，只做校验与转发。
4. Agent（T1）在任何对象上都没有 `W`/`A`。

### 4.4 进程与目录隔离（T0）

【策划书】§5.4 / TABLE 22；§9.3；`AGENTS.md` §4：

| 隔离项 | T0 要求 |
|---|---|
| Executor 与 Verifier | 不同工作目录、不同进程；Verifier 不读 Executor 进程内状态 |
| 每 attempt | 独立工作目录；不得复用历史目录 |
| L3 重执行 | 新目录、独立进程、只读原始数据；禁止读取原运行 metrics/predictions/模型 |
| 私钥 | 受限目录/ACL；Agent/Executor 读取失败 |
| 证据目录 | 只由 Collector/Verifier 追加；其他进程只读 |
| 网络 | 默认关闭；无外部请求 |

【工程建议】T0 用同机不同进程 + 目录权限实现隔离；受控子进程**不等于**安全沙箱，不得宣称抵御本机 root（§17.1 / P0427）。

## 5. 数据流与判定链

### 5.1 任务流（T0）

```text
用户/工作台
  → API（校验 TaskSpec）
  → DAG Builder（静态校验，产出 graph_version）
  → StateMachine（CREATED→PLANNING→READY→RUNNING）
  → Executor（内置模板，独立目录/子进程）
  → 执行事件与产物
```

【策划书】§5.3 / P0099–P0113。

### 5.2 证据与判定链（T0）

```text
执行事件(E2) / 工具调用(E1) / Agent 声明(E0)
  → Collector（单写者、event_seq、哈希链）
  → Gate（覆盖矩阵、链/哈希/版本/冲突/E2-E3/L3、stale 拒绝）
  → Verifier（L1/L2/L3，产生 E3）
  → VerificationReport = VERIFIED / PARTIAL / FAILED / BLOCKED
  → 仅 VERIFIED 签发 CompletionCertificate
  → Evidence Bundle
  → 独立环境离线验签（外部信任锚）
```

### 5.3 失效传播与最小恢复流（WP-R，T0）

```text
上游变化（输入/参数/代码/环境/规则）
  → 计算受影响后代
  → StateMachine: VERIFIED → INVALIDATED
  → 生成恢复计划（冻结，含计划哈希）
  → StateMachine: INVALIDATED → READY
  → 受影响后代保守重跑（不签 DC、不做 SPA）
  → 重新采证 → Gate（stale 证据被拒）→ Verifier
```

【用户决议 B1】不做 DC/SPA、不做动态调度、不做 Recovery Agent、不做自动诊断；Task 级 `COMPLETED` 之后的撤销属 T1。

## 6. 不提前设计的部分

| 不做 | 原因 | 归属 |
|---|---|---|
| Scheduler/Governor/VAS 的评分与阈值 | 属动态调度，T1/T2 | T1/T2 |
| DC/SPA 的资格判定与剪枝 | 依赖 T1 完整 Recovery 与调度 | T2 |
| 六角色消息总线与 Tool Gateway 实现 | T0 无 Agent | T1 |
| 知识库/FOL/Bench 的存储与检索 | T0 不需要 | T1 |
| Harness 事件标准化与状态回传 | T0 不接 Adapter | T2 |
| 多租户、分布式、容器化 | 第一版明确不做 | 不做 |
| 超出附录 D 的契约字段 | 不得凭空补字段 | OQ |

【工程建议】T0 的“最小工作台”只做任务/DAG/证据/报告四视图，不引入六页工作台的信息架构；避免为 T1 预埋未验证的抽象。

## 7. 架构相关未决项

| 编号 | 问题 | 状态 / 去向 |
|---|---|---|
| `OQ-ARCH-1` | `RecoveryPlan` 是内部产物还是公开契约（影响架构中的模块边界） | **已关闭**（决议 3 / `ADR-004`）：T0 内部不可变产物，内容寻址文件，不签名、不对外 |
| `OQ-ARCH-2` | 失效/恢复控制事件写 `audit_log` 还是也写 E1/E2 | **已关闭**（决议 4 / `ADR-004`）：只写 `audit_log` + `evidence_invalidations`，不占 E0–E3 |
| `OQ-ARCH-3` | 最小工作台四视图的接口范围（是否暴露证据分页/报告下载） | 开放；⑥/⑦（`ADR-007` PROPOSED） |
| `OQ-ARCH-4` | T0 的 API 进程与 StateMachine 是否同进程 | 开放；⑥ |
| `OQ-ARCH-5` | 私钥存储的具体形态（文件 + ACL vs 系统密钥存储） | 开放；⑥/⑧ |

## 8. 依据锚点

| 主题 | 锚点 |
|---|---|
| 判定立场 | §1.1 / P0027；§3.1 / P0058 |
| 五条原则 | §5.1 / TABLE 20 |
| 四类面 | 摘要 / P0017；§3.4 / TABLE 16 |
| 六层架构 | §5.2 / TABLE 21 |
| 数据流 | §5.3 / P0099–P0113 |
| 进程与资源 | §5.4 / TABLE 22 |
| Domain Pack 钩子 | §5.7 / TABLE 24 |
| 消息协议 | §6.3 / TABLE 27（T1） |
| REST | §6.4 / TABLE 28 |
| 工作台 | §6.5 / TABLE 29 |
| E0–E3 | §7.1 / TABLE 31 |
| Gate | §7.2 / P0159–P0168 |
| 状态机 | §6.2 / TABLE 26；附录 F / TABLE 70–71 |
| L1–L3 | §9.1–9.4 / TABLE 38–39 |
| 安全边界 | §17.1 / P0427 |
| 测试分层 | §6.7 / TABLE 30 |

---

**标记：本文件是 G0 文档 ④ v1.0（G0 冻结），不是 G0 门禁 PASS。** 文档已按用户 2026-11-10 指令冻结；G0 是否 PASS 由用户宣布；未建 `.venv`、未写业务代码。