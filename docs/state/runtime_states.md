# runtime_states.md — ResearchFlow 运行时状态对照

> 更新时间：2026-11-12
> 核验状态：已按 G0 冻结契约核对。Task / Node / Evidence 状态机、Recovery 边界与不变量取自 `docs/design/05_CONTRACTS_AND_STATES.md` §9–§10；Node 的 `INVALIDATED` 由 [`ADR-001`](../ADR/ADR-001-invalidated-node-state.md) 增加（Node 10 个状态）。规范性以 `docs/design/05_CONTRACTS_AND_STATES.md`、`contracts/` 与 ADR 为准。
> 重要边界：本文件描述 ResearchFlow **运行时**状态，不是研发看板状态。研发看板状态见 `docs/state/project_state.json`，只允许 `BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED`。

当前状态以 docs/state/project_state.json 为准。

## 1. 为什么必须分开

两套状态回答不同问题：

| 维度 | 研发看板状态 | 运行时状态 |
|---|---|---|
| 描述对象 | 研发任务、交付物、阶段工作 | ResearchFlow 运行中的 Task / Node / Report / Certificate |
| 存储位置 | `docs/state/project_state.json` | 运行时数据库 / StateMachine / 审计日志（尚未实现） |
| 谁可修改 | 研发流程（人工或经批准的 Agent） | 仅 `StateMachine`（Report/Certificate 由 Verifier 按规则签发） |
| 典型值 | `BACKLOG`、`IN_PROGRESS`、`DONE` | `CREATED`、`RUNNING`、`VERIFYING`、`VERIFIED` |
| 当前状态 | 已建立 | 仅文档对照，尚无运行时实现 |

禁止：

- 把 `DONE` 当成运行时 Task 的 `COMPLETED`；
- 把运行时 `VERIFYING` 写进研发看板；
- 用研发看板的 `BLOCKED` 替代运行时 Task/Node 的 `BLOCKED`；
- 为了“统一”而合并、改名或删减任一状态集合。

## 2. Task 状态（9 个）

`CREATED`、`PLANNING`、`READY`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED`。

允许迁移（05 §9.2）：

| 当前状态 | 允许的下一状态 | 禁止 / 特殊条件 |
|---|---|---|
| `CREATED` | `PLANNING` / `CANCELLED` | 创建后不能直接 `COMPLETED` |
| `PLANNING` | `READY` / `BLOCKED` / `FAILED` | DAG 必须通过校验 |
| `READY` | `RUNNING` / `CANCELLED` | 至少一个节点 `READY` |
| `RUNNING` | `VERIFYING` / `FAILED` / `BLOCKED` | 执行未结束不能验证最终完成 |
| `VERIFYING` | `COMPLETED` / `FAILED` / `BLOCKED` | `COMPLETED` 需报告 `VERIFIED` 和凭证 |

未在表中列出的迁移一律拒绝，除非后续冻结契约明确允许。`COMPLETED` 不是“执行结束”的同义词，必须同时满足报告与凭证条件。

## 3. Node 状态（10 个）

`PLANNED`、`READY`、`RUNNING`、`VERIFYING`、`VERIFIED`、`FAILED`、`BLOCKED`、`DIAGNOSING`、`RECOVERING`、`INVALIDATED`。

> 策划书附录 F 的 Node 为 9 个状态；`ADR-001` 增加 `INVALIDATED` 后为 10 个。以 `ADR-001` 与 05 §9.3 为准。

允许迁移（05 §9.3）：

| 当前状态 | 允许的下一状态 | 禁止 / 特殊条件 |
|---|---|---|
| `PLANNED` | `READY` / `BLOCKED` | 依赖未满足不能 `READY` |
| `READY` | `RUNNING` / `BLOCKED` | 资源 / 权限检查通过 |
| `RUNNING` | `VERIFYING` / `FAILED` | 必须有 attempt 结束事件 |
| `VERIFYING` | `VERIFIED` / `FAILED` / `BLOCKED` | Gate 与 Verifier 判定 |
| `FAILED` | `DIAGNOSING` / `BLOCKED` | 恢复次数未超限 |
| `DIAGNOSING` | `RECOVERING` / `BLOCKED` | 根因 / 计划结构有效 |
| `RECOVERING` | `READY` / `BLOCKED` | 恢复计划执行完并复核 |
| `VERIFIED` | `INVALIDATED` | 上游输入 / 前驱 / 图版本 / 规则版本变化；证据判定 stale；写失效记录，不删除证据 |
| `INVALIDATED` | `READY` | 计划文件存在、`plan_hash` 一致、冻结早于重跑（三条件全部满足） |

未授权迁移（一律拒绝，需新 ADR）：`VERIFIED → READY`（跳过 `INVALIDATED`）、`INVALIDATED → VERIFYING/VERIFIED/FAILED`、任何状态直接回 `PLANNED`、Task 级 `COMPLETED` 后的失效（T1）。

## 4. Evidence / Report / Certificate 状态

### 4.1 Evidence 状态机（05 §9.4）

| 当前状态 | 允许的下一状态 | 约束 |
|---|---|---|
| `RECEIVED` | `VALIDATED` / `INVALID` | 写入后先进入 `RECEIVED` |
| `VALIDATED` | `APPENDED` / `CONFLICT` | 链 / 哈希 / 等级校验通过 |
| `APPENDED` | —（终态） | 只追加；不修改 |
| `INVALID` / `CONFLICT` | —（终态，保留） | 无效记录保留并标注 |

### 4.2 签发对象状态

| 对象 | 允许状态 | 约束 |
|---|---|---|
| `VerificationReport` | `VERIFIED`、`PARTIAL`、`FAILED`、`BLOCKED` | 由独立 Verifier 签发；四态 |
| `CompletionCertificate` | 仅 `VERIFIED` | 只能由 `VERIFIED` 报告生成；`PARTIAL` 映射为节点 `BLOCKED`，不能签发凭证 |

## 5. Recovery 状态机（仅 T1；T0 不复用）

T0 不复用完整 Recovery 状态机：没有 `PROPOSED`/`APPROVED`，没有 Agent 提案，没有人工审批环节。T0 只用 `evidence_invalidations`、内容寻址的冻结计划文件与 `INVALIDATED → READY` 守卫表达“恢复”（05 §9.5）。

| 当前状态 | 允许的下一状态 | 约束 |
|---|---|---|
| `PROPOSED` | `VALIDATED` / `ESCALATED` | Recovery Agent 只提案 |
| `VALIDATED` | `APPROVED` / `ESCALATED` | 计划结构有效 |
| `APPROVED` | `EXECUTING` | 调度器 / 人工批准 |
| `EXECUTING` | `RECHECKED` / `ESCALATED` | 计划不得中途改写 |
| `RECHECKED` | `CLOSED` / `ESCALATED` | 复核完成 |

完整 Recovery 与 G4 均属 T1；T0 不得把这些状态值写入代码或数据库枚举。

## 6. 核心不变量（05 §10）

| 编号 | 不变量 | 校验点 |
|---|---|---|
| I-01 | Agent 不能直接写 Task/Node 状态 | 权限矩阵 + 权限测试 |
| I-02 | E0/E1 不能单独满足执行类必检项 | Gate |
| I-03 | Verifier 与 Executor 工作目录分离 | 目录 / 进程检查 |
| I-04 | 报告指标来源节点必须达到规定 L3 覆盖 | Gate + Report |
| I-05 | 无有效 DC 的节点不能被 SPA 跳过 | T2 的 SPA 检查（T0 不适用） |
| I-06 | 签名载荷包含规则版本、证据根和状态（`schema_version` 见 I-13） | 签名 / 验签 |
| I-07 | 非 `VERIFIED` 报告不产生 `CompletionCertificate` | 签发入口 |
| I-08 | 离线验签使用外部可信指纹，不信任证书自带公钥 | `verify_bundle.py` |
| I-09 | `INVALIDATED` 只从 `VERIFIED` 进入，且只能回 `READY` | StateMachine（B1 / ADR-001） |
| I-10 | stale 证据不得满足必检项；证据不删除 | Gate + Evidence Store（B1 / 决议 4） |
| I-11 | 失效 / 恢复控制事件不是证据：只写 `audit_log` + `evidence_invalidations`，不占用 E0–E3 | StateMachine / Collector（决议 4） |
| I-12 | `INVALIDATED → READY` 必须同时满足计划存在、`plan_hash` 一致、先冻结后重跑 | StateMachine（决议 5） |
| I-13 | 报告与证书签名载荷必须含 `schema_version`；验签方拒绝未知 `MAJOR` | Signing / Verifier（决议 2） |
| I-14 | 失败迁移的 `DENIED` 审计在状态回滚后仍存在；二次失败降级结构化 stderr 并计测试缺口 | StateMachine（决议 7） |

## 7. 事件顺序与恢复不变量（附录 F.1）

- `event_seq` 由 Collector 单调分配；并发事件先进入单写队列。
- 同一 `event_id` 重复投递只产生一次逻辑记录；原始投递次数可另记 `ingestion_log`。
- 状态迁移事件必须包含 `previous_state`、`next_state`、`actor`、`reason_code`、`rule_version`、`correlation_id`。
- 状态迁移失败也写 `audit_log`；失败不等于证据记录成功。
- 任务一旦签发凭证，后续发现撤销条件必须生成 `revocation event`，不得静默修改旧凭证。
- 系统重启后先校验数据库、证据链和未完成 attempt，再恢复调度；不得默认把 `RUNNING` 改成 `COMPLETED`。

## 8. 实现状态

- G0 规格冻结已由用户于 2026-11-10 宣布通过；Task / Node / Evidence 状态机与不变量已冻结，见 05 §9–§10。
- 运行时 `StateMachine`、SQLite 与 `audit_log`：尚未实现；WP-03 尚未启动，P2 伪代码为 `IN_REVIEW`。
- `researchflow/contracts` 的 Pydantic 模型与 `POST/GET /api/v1/tasks` 已部分实现；API 返回的 `state` 来自临时内存注册表，不是状态机。
- 本文件不是代码，也不是冻结契约；它是对照索引。任何实现必须先经 StateMachine 单入口，并以 WP-03 的批准范围与 05 的迁移表为准。

## 9. 相关文件

- [`AGENTS.md`](../../AGENTS.md)
- [`docs/design/05_CONTRACTS_AND_STATES.md`](../design/05_CONTRACTS_AND_STATES.md)
- [`docs/state/project_state.json`](project_state.json)
- [`docs/memory/architecture-decisions.md`](../memory/architecture-decisions.md)
- [`docs/ADR/ADR-001-invalidated-node-state.md`](../ADR/ADR-001-invalidated-node-state.md)
- [`docs/memory/references.md`](../memory/references.md)