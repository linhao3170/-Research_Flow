# runtime_states.md — ResearchFlow 运行时状态对照

> 更新时间：2026-11-08
> 核验状态：部分核验。Task / Node 状态名称与迁移表已从策划书**内部 v4.3.0**（文件名标签 v4.3.1；`BLK-002` 已关闭）附录 F（状态迁移表、核心不变量表）抽取，并与用户阶段 4 指令核对；**详细契约尚未在 G0 冻结**，冻结时需逐条确认。
> 重要边界：本文件描述的是 ResearchFlow **运行时**状态，不是研发看板状态。研发看板状态见 `docs/state/project_state.json`，只允许 `BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED`。

## 1. 为什么必须分开

两套状态回答不同问题：

| 维度 | 研发看板状态 | 运行时状态 |
|---|---|---|
| 描述对象 | 研发任务、交付物、阶段工作 | ResearchFlow 运行中的 Task / Node / Report / Certificate |
| 存储位置 | `docs/state/project_state.json` | 运行时数据库 / StateMachine / 审计日志（尚未实现） |
| 谁可修改 | 研发流程（人工或经批准的 Agent） | 仅 `StateMachine`（Report/Certificate 由 Verifier 按规则签发） |
| 典型值 | `BACKLOG`、`IN_PROGRESS`、`DONE` | `CREATED`、`RUNNING`、`VERIFYING`、`VERIFIED` |
| 当前状态 | 已建立（阶段 4） | 仅文档对照，尚无实现 |

禁止：

- 把 `DONE` 当成运行时 Task 的 `COMPLETED`；
- 把运行时 `VERIFYING` 写进研发看板；
- 用研发看板的 `BLOCKED` 替代运行时 Task/Node 的 `BLOCKED`；
- 为了“统一”而合并、改名或删减任一状态集合。

## 2. Task 状态（9 个）

`CREATED`、`PLANNING`、`READY`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED`。

允许迁移（策划书附录 F 状态迁移表）：

| 当前状态 | 允许的下一状态 | 禁止 / 特殊条件 |
|---|---|---|
| `CREATED` | `PLANNING` / `CANCELLED` | 创建后不能直接 `COMPLETED` |
| `PLANNING` | `READY` / `BLOCKED` / `FAILED` | DAG 必须通过校验 |
| `READY` | `RUNNING` / `CANCELLED` | 至少一个节点 `READY` |
| `RUNNING` | `VERIFYING` / `FAILED` / `BLOCKED` | 执行未结束不能验证最终完成 |
| `VERIFYING` | `COMPLETED` / `FAILED` / `BLOCKED` | `COMPLETED` 需报告 `VERIFIED` 和凭证 |

未在表中列出的迁移一律拒绝，除非后续冻结契约明确允许。`COMPLETED` 不是“执行结束”的同义词，必须同时满足报告与凭证条件。

## 3. Node 状态（9 个）

`PLANNED`、`READY`、`RUNNING`、`VERIFYING`、`VERIFIED`、`FAILED`、`BLOCKED`、`DIAGNOSING`、`RECOVERING`。

允许迁移（策划书附录 F 状态迁移表）：

| 当前状态 | 允许的下一状态 | 禁止 / 特殊条件 |
|---|---|---|
| `PLANNED` | `READY` / `BLOCKED` | 依赖未满足不能 `READY` |
| `READY` | `RUNNING` / `BLOCKED` | 资源 / 权限检查通过 |
| `RUNNING` | `VERIFYING` / `FAILED` | 必须有 attempt 结束事件 |
| `VERIFYING` | `VERIFIED` / `FAILED` / `BLOCKED` | Gate 与 Verifier 判定 |
| `FAILED` | `DIAGNOSING` / `BLOCKED` | 恢复次数未超限 |
| `DIAGNOSING` | `RECOVERING` / `BLOCKED` | 根因 / 计划结构有效 |
| `RECOVERING` | `READY` / `BLOCKED` | 恢复计划执行完并复核 |

未在表中列出的迁移一律拒绝，除非后续冻结契约明确允许。

## 4. Report / Certificate 状态

| 对象 | 允许状态 | 约束 |
|---|---|---|
| `VerificationReport` | `VERIFIED`、`PARTIAL`、`FAILED`、`BLOCKED` | 由独立 Verifier 签发；四态 |
| `CompletionCertificate` | 仅 `VERIFIED` | 只能由 `VERIFIED` 报告生成；`PARTIAL` 映射为节点 `BLOCKED`，不能签发凭证 |

## 5. 核心不变量（策划书附录 F 核心不变量表）

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

## 6. 事件顺序与恢复不变量（附录 F.1）

- `event_seq` 由 Collector 单调分配；并发事件先进入单写队列。
- 同一 `event_id` 重复投递只产生一次逻辑记录；原始投递次数可另记 `ingestion_log`。
- 状态迁移事件必须包含 `previous_state`、`next_state`、`actor`、`reason_code`、`rule_version`、`correlation_id`。
- 状态迁移失败也写 `audit_log`；失败不等于证据记录成功。
- 任务一旦签发凭证，后续发现撤销条件必须生成 `revocation event`，不得静默修改旧凭证。
- 系统重启后先校验数据库、证据链和未完成 attempt，再恢复调度；不得默认把 `RUNNING` 改成 `COMPLETED`。

## 7. 实现状态

- 运行时 StateMachine：**尚未实现**。
- 运行时数据库 / 审计日志：**尚未实现**。
- 本文件不是代码，也不是冻结契约；它只是阶段 4 建立的对照索引，用于防止研发看板与运行时状态混淆。
- 任何实现必须等待 G0 规格冻结与 T0 启动批准。

## 8. 相关文件

- [`AGENTS.md`](../../AGENTS.md)
- [`docs/state/project_state.json`](project_state.json)
- [`docs/memory/architecture-decisions.md`](../memory/architecture-decisions.md)
- [`docs/memory/references.md`](../memory/references.md)
